"""Read-only Trading 212 access, CSV reports, and Windows credentials."""

import base64
import csv
import hashlib
import http.client
import json
import logging
import math
import os
import re
import ssl
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Event
from typing import Callable, Generator, Literal, NoReturn, TypedDict, TypeGuard
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import keyring
from keyring.backends import Windows
from keyring.errors import KeyringError

if sys.platform == "win32":
    import msvcrt
    from win32ctypes.pywin32 import pywintypes, win32cred


@dataclass(frozen=True)
class APIProgress:
    phase: str
    year: int | None = None
    wait_seconds: float | None = None


@dataclass(frozen=True)
class ArchivedCSV:
    year: int
    path: Path
    sha256: str
    report_id: int
    complete: bool


class _ArchiveReport(TypedDict):
    year: int
    timeFrom: str
    timeTo: str
    dataIncluded: dict[str, bool]
    complete: bool
    reportId: int
    downloadedAt: str
    file: str
    size: int
    sha256: str


class _ArchivePending(TypedDict):
    year: int
    timeFrom: str
    timeTo: str
    dataIncluded: dict[str, bool]
    complete: bool
    state: Literal["prepared", "uncertain", "waiting", "failed"]
    baselineIds: list[int]
    reportId: int | None
    downloadedAt: str
    file: str | None
    temporary: str | None
    size: int | None
    sha256: str | None


class _ArchiveState(TypedDict):
    version: int
    environment: str
    account_id: int
    timezone: str
    reports: list[_ArchiveReport]
    recommended: dict[str, int]
    pending: _ArchivePending | None


class Trading212API:
    """Manage credentials and export history without changing the portfolio."""

    _ACCOUNT_PATH = "/api/v0/equity/account/summary"
    _EXPORT_PATH = "/api/v0/equity/history/exports"
    _MAX_CSV_BYTES = 100 * 1024 * 1024
    _MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
    _ARCHIVE_TIMEZONE = "Europe/Prague"

    def __init__(
        self,
        environment: Literal["live", "demo"] = "live",
        account_id: int | None = None,
        timeout: float = 30.0,
        logger: logging.Logger | None = None,
        on_progress: Callable[[APIProgress], None] | None = None,
    ) -> None:
        if environment not in ("live", "demo"):
            raise ValueError("Trading212 environment must be 'live' or 'demo'.")
        if account_id is not None and (
            not isinstance(account_id, int)
            or isinstance(account_id, bool)
            or account_id <= 0
        ):
            raise ValueError("Trading212 account ID must be a positive integer.")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Trading212 timeout must be a finite positive number.")
        self._environment: Literal["live", "demo"] = environment
        self._account_id = account_id
        self._timeout = float(timeout)
        self._logger = logger or logging.getLogger("trading_tools.trading212")
        self._on_progress = on_progress
        self._keyring: Windows.WinVaultKeyring | None = None
        self._next_request_at: dict[tuple[str, str], float] = {}
        self._pending_creation: tuple[dict[str, object], set[int]] | None = None
        self._report_requests: dict[int, dict[str, object]] = {}
        self._post_dispatched = False
        self._archive_root: Path | None = None
        self._archive_state: _ArchiveState | None = None

    @property
    def environment(self) -> Literal["live", "demo"]:
        return self._environment

    @property
    def account_id(self) -> int | None:
        return self._account_id

    @classmethod
    def current_archive_year(cls) -> int:
        return datetime.now(ZoneInfo(cls._ARCHIVE_TIMEZONE)).year

    def _emit(self, phase: str, *, year: int | None = None, wait_seconds: float | None = None) -> None:
        if self._on_progress is not None:
            self._on_progress(APIProgress(phase, year, wait_seconds))

    def _notify_archived(self, year: int, callback: Callable[[ArchivedCSV], None] | None) -> None:
        if callback is None:
            return
        if self._archive_state is None or self._archive_root is None:
            raise RuntimeError("No active archive for report notification.")
        report = self._recommended_reports(self._archive_state)[year]
        callback(ArchivedCSV(
            year, self._archive_path(self._archive_root, report["file"], year),
            report["sha256"], report["reportId"], report["complete"],
        ))

    def _fail(self, message: str) -> NoReturn:
        self._logger.error(message)
        raise RuntimeError(message) from None

    def _credential_backend(self) -> Windows.WinVaultKeyring:
        if sys.platform != "win32":
            self._fail("Trading212 credentials require Windows Credential Manager.")
        if self._keyring is None:
            try:
                Windows.WinVaultKeyring.priority
                backend = keyring.get_keyring()
            except (KeyringError, RuntimeError, ImportError, OSError):
                self._fail("Windows Credential Manager could not be initialized.")
            if (
                not isinstance(backend, Windows.WinVaultKeyring)
                or type(backend) is not Windows.WinVaultKeyring
            ):
                self._fail("Trading212 requires the native Windows keyring backend.")
            self._keyring = backend
        return self._keyring

    def _credential_target(self, account_id: int | None = None) -> str:
        account_id = self._account_id if account_id is None else account_id
        if account_id is None:
            self._fail("Connect a Trading212 account before accessing stored credentials.")
        return f"TradingTools:Trading212:{self._environment}:{account_id}"

    @staticmethod
    def _validate_credentials(api_key: str, api_secret: str) -> None:
        if (
            not isinstance(api_key, str)
            or not isinstance(api_secret, str)
            or not api_key
            or not api_secret
            or ":" in api_key
            or any(char.isspace() for char in api_key + api_secret)
        ):
            raise ValueError("API Key and Secret must be non-empty tokens without whitespace.")

    def _verify_credentials(
        self,
        api_key: str,
        api_secret: str,
        cancel_event: Event | None = None,
        deadline: float | None = None,
    ) -> int:
        try:
            status, content, _ = self._api_exchange(
                "GET", self._ACCOUNT_PATH, credentials=(api_key, api_secret),
                cancel_event=cancel_event, deadline=deadline, size_limit=64 * 1024,
            )
        except ConnectionError:
            self._fail("Could not securely connect to the Trading212 account API.")
        if status != 200:
            self._raise_api_status(status, self._ACCOUNT_PATH)
        summary = self._decode_json(content)
        if not isinstance(summary, dict):
            self._fail("Trading212 returned an invalid account response.")
        account_id = summary.get("id")
        if (
            not isinstance(account_id, int)
            or isinstance(account_id, bool)
            or account_id <= 0
        ):
            self._fail("Trading212 returned an invalid account identity.")
        if self._account_id is not None and account_id != self._account_id:
            self._fail("Trading212 credentials belong to a different account.")
        return account_id

    @staticmethod
    def _deadline(wait_timeout: float) -> float:
        if (
            not isinstance(wait_timeout, (int, float))
            or isinstance(wait_timeout, bool)
            or not math.isfinite(wait_timeout)
            or wait_timeout <= 0
        ):
            raise ValueError("Report wait timeout must be a finite positive number.")
        return time.monotonic() + wait_timeout

    def _check_operation(self, cancel_event: Event | None, deadline: float) -> None:
        if cancel_event is not None and cancel_event.is_set():
            self._logger.info("Trading212 operation cancelled.")
            raise InterruptedError("Trading212 operation cancelled.")
        if time.monotonic() >= deadline:
            self._logger.error("Trading212 operation timed out.")
            raise TimeoutError("Trading212 operation timed out.")

    def _pause(self, delay: float, cancel_event: Event | None, deadline: float) -> None:
        self._check_operation(cancel_event, deadline)
        duration = min(max(0.0, delay), max(0.0, deadline - time.monotonic()))
        if duration:
            self._emit("Waiting for API rate limit / retry", wait_seconds=duration)
            if cancel_event is None:
                time.sleep(duration)
            else:
                cancel_event.wait(duration)
        self._check_operation(cancel_event, deadline)

    def _retry_delay(self, headers: dict[str, str], fallback: float) -> float:
        value = headers.get("Retry-After")
        if value is None:
            return fallback
        try:
            try:
                delay = float(value)
            except ValueError:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            if not math.isfinite(delay):
                raise ValueError
            return max(fallback, delay)
        except (ValueError, TypeError, OverflowError):
            self._logger.warning("Invalid Trading212 retry header; using bounded backoff.")
            return fallback

    def _api_exchange(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        credentials: tuple[str, str] | None = None,
        cancel_event: Event | None = None,
        deadline: float | None = None,
        size_limit: int = 1024 * 1024,
    ) -> tuple[int, bytes, dict[str, str]]:
        periods = {
            ("GET", self._ACCOUNT_PATH): 5.0,
            ("GET", self._EXPORT_PATH): 60.0,
            ("POST", self._EXPORT_PATH): 30.0,
        }
        operation = (method, path)
        if operation not in periods or (method == "GET" and payload is not None):
            raise ValueError("Trading212 API operation is not permitted.")
        if method == "POST":
            self._post_dispatched = False
        deadline = self._deadline(600.0) if deadline is None else deadline
        self._pause(
            self._next_request_at.get(operation, 0.0) - time.monotonic(),
            cancel_event, deadline,
        )
        api_key, api_secret = self.load_credentials() if credentials is None else credentials
        self._validate_credentials(api_key, api_secret)
        authorization = base64.b64encode(
            f"{api_key}:{api_secret}".encode("utf-8")
        ).decode("ascii")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Basic {authorization}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        self._next_request_at[operation] = time.monotonic() + periods[operation]
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(
                f"{self._environment}.trading212.com",
                timeout=min(self._timeout, max(0.001, deadline - time.monotonic())),
                context=ssl.create_default_context(),
            )
            if method == "POST":
                self._check_operation(cancel_event, deadline)
                self._checkpoint_creation(uncertain=True)
                self._post_dispatched = True
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            rate_headers = {
                name: value for name in (
                    "Retry-After", "x-ratelimit-reset", "x-ratelimit-remaining",
                ) if isinstance(value := response.getheader(name), str)
            }
            if (
                response.status in (408, 429) or 500 <= response.status < 600
                or rate_headers.get("x-ratelimit-remaining") == "0"
            ):
                delay = self._retry_delay(rate_headers, periods[operation])
                reset = rate_headers.get("x-ratelimit-reset")
                if reset is not None:
                    try:
                        reset_delay = float(reset) - time.time()
                        if not math.isfinite(reset_delay):
                            raise ValueError
                        delay = max(delay, reset_delay)
                    except (ValueError, OverflowError):
                        self._logger.warning("Invalid Trading212 rate-limit reset header.")
                self._next_request_at[operation] = max(
                    self._next_request_at[operation], time.monotonic() + delay,
                )
            content = (
                self._read_api_content(response, size_limit, cancel_event, deadline)
                if response.status == 200 else b""
            )
        except (OSError, http.client.HTTPException):
            self._check_operation(cancel_event, deadline)
            self._logger.warning("Trading212 API connection failed; details withheld.")
            raise ConnectionError("Trading212 API connection failed.") from None
        finally:
            if connection is not None:
                connection.close()
        self._check_operation(cancel_event, deadline)
        return response.status, content, rate_headers

    def _read_api_content(
        self, response: http.client.HTTPResponse, size_limit: int,
        cancel_event: Event | None, deadline: float,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            self._check_operation(cancel_event, deadline)
            chunk = response.read1(min(64 * 1024, size_limit + 1 - total))
            if not chunk:
                if response.length is not None and response.length > 0:
                    raise http.client.IncompleteRead(b"")
                return b"".join(chunks)
            total += len(chunk)
            if total > size_limit:
                self._fail("Trading212 response exceeded the size limit.")
            chunks.append(chunk)

    def _raise_api_status(self, status: int, path: str) -> NoReturn:
        if 300 <= status < 400:
            self._fail("Trading212 API redirects are not permitted.")
        messages = {
            400: "Trading212 rejected the CSV report request.",
            401: "Trading212 rejected the API Key or Secret.",
            403: (
                "Trading212 account data permission is missing."
                if path == self._ACCOUNT_PATH else
                "Trading212 history export permission is missing."
            ),
            429: "Trading212 request rate limit reached. Try again later.",
        }
        self._fail(messages.get(status, f"Trading212 API request failed (HTTP {status})."))

    def _decode_json(self, content: bytes) -> object:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, UnicodeError):
            self._fail("Trading212 returned invalid JSON.")

    def _list_reports(
        self, cancel_event: Event | None, deadline: float,
    ) -> list[dict[str, object]]:
        for attempt in range(3):
            try:
                status, content, _ = self._api_exchange(
                    "GET", self._EXPORT_PATH, cancel_event=cancel_event, deadline=deadline,
                )
            except ConnectionError:
                if attempt == 2:
                    self._fail("Could not retrieve Trading212 CSV reports.")
                self._pause(2 ** attempt, cancel_event, deadline)
                continue
            if status == 200:
                data = self._decode_json(content)
                if not isinstance(data, list):
                    self._fail("Trading212 returned an invalid report list.")
                reports: list[dict[str, object]] = []
                ids: set[int] = set()
                for report in data:
                    if not isinstance(report, dict):
                        self._fail("Trading212 returned an invalid report record.")
                    report_id = report.get("reportId")
                    if (
                        not isinstance(report_id, int) or isinstance(report_id, bool)
                        or report_id <= 0 or report_id in ids
                    ):
                        self._fail("Trading212 returned an invalid or duplicate report ID.")
                    ids.add(report_id)
                    reports.append(report)
                return reports
            if status not in (408, 429) and not 500 <= status < 600:
                self._raise_api_status(status, self._EXPORT_PATH)
            if attempt == 2:
                self._raise_api_status(status, self._EXPORT_PATH)
        self._fail("Could not retrieve Trading212 CSV reports.")

    def verify_credentials(
        self, api_key: str, api_secret: str, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> int:
        """Verify an entered pair without changing the saved credentials."""
        self._validate_credentials(api_key, api_secret)
        self._credential_backend()
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._emit("Verifying account")
        return self._verify_credentials(
            api_key, api_secret, cancel_event=cancel_event, deadline=deadline,
        )

    def save_credentials(
        self, api_key: str, api_secret: str, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> int:
        """Verify and store a key pair, returning the connected account ID."""
        account_id = self.verify_credentials(
            api_key, api_secret, cancel_event=cancel_event, wait_timeout=wait_timeout,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Trading212 operation cancelled before saving credentials.")
        payload = json.dumps({"api_key": api_key, "api_secret": api_secret})
        try:
            # keyring.set_password retains an old-secret backup; overwrite one native record.
            win32cred.CredWrite(
                {
                    "Type": win32cred.CRED_TYPE_GENERIC,
                    "TargetName": self._credential_target(account_id),
                    "UserName": str(account_id),
                    "CredentialBlob": payload,
                    "Comment": "TradingTools Trading212 API credentials",
                    "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
        except (KeyringError, pywintypes.error, OSError, ValueError):
            self._fail("Could not save credentials in Windows Credential Manager.")
        self._account_id = account_id
        return account_id

    def load_credentials(self) -> tuple[str, str]:
        """Read the connected account's key pair from Windows Credential Manager."""
        target = self._credential_target()
        backend = self._credential_backend()
        try:
            payload = backend.get_password(target, str(self._account_id))
        except (KeyringError, pywintypes.error, OSError, UnicodeError):
            self._fail("Could not read credentials from Windows Credential Manager.")
        if payload is None:
            self._fail("No stored credentials for this Trading212 account.")
        if not isinstance(payload, str):
            self._fail("Stored Trading212 credentials are invalid. Replace the key pair.")
        try:
            data: object = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError
            api_key = data.get("api_key")
            api_secret = data.get("api_secret")
            if not isinstance(api_key, str) or not isinstance(api_secret, str):
                raise ValueError
            self._validate_credentials(api_key, api_secret)
        except (ValueError, TypeError, UnicodeError):
            self._fail("Stored Trading212 credentials are invalid. Replace the key pair.")
        return api_key, api_secret

    def verify_account(
        self, cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> int:
        """Verify that the stored credentials still match the connected account."""
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._emit("Verifying account")
        return self._verify_credentials(
            *self.load_credentials(), cancel_event=cancel_event, deadline=deadline,
        )

    def delete_credentials(self) -> None:
        """Remove local credentials; this does not revoke the key at Trading 212."""
        target = self._credential_target()
        backend = self._credential_backend()
        try:
            backend.delete_password(target, str(self._account_id))
        except (KeyringError, pywintypes.error, OSError):
            self._fail("Could not remove credentials from Windows Credential Manager.")

    @staticmethod
    def _utc_time(value: datetime) -> str:
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("CSV report dates must include a time zone.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _history_content() -> dict[str, bool]:
        return {
            "includeOrders": True, "includeDividends": True,
            "includeInterest": True, "includeTransactions": True,
        }

    def _report_matches(self, report: dict[str, object], payload: dict[str, object]) -> bool:
        if report.get("dataIncluded") != payload["dataIncluded"]:
            return False
        for field in ("timeFrom", "timeTo"):
            value = report.get(field)
            if not isinstance(value, str):
                return False
            try:
                normalized = self._utc_time(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError:
                return False
            if normalized != payload[field]:
                return False
        return True

    def _recover_creation(self, cancel_event: Event | None, deadline: float) -> int:
        if self._pending_creation is None:
            self._fail("No uncertain Trading212 report request to recover.")
        payload, existing_ids = self._pending_creation
        matches = [
            report for report in self._list_reports(cancel_event, deadline)
            if report["reportId"] not in existing_ids and self._report_matches(report, payload)
        ]
        if len(matches) != 1:
            self._fail(
                "CSV report creation outcome is uncertain. Retry the same request to "
                "check reports; no POST will be repeated."
            )
        report_id = matches[0]["reportId"]
        if not isinstance(report_id, int):
            self._fail("Trading212 returned an invalid recovered report ID.")
        self._report_requests[report_id] = payload
        self._pending_creation = None
        self._checkpoint_creation(report_id=report_id)
        return report_id

    def request_csv_report(
        self, time_from: datetime, time_to: datetime, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> int:
        """Request all history categories; return an ID for waiting or resuming."""
        self._emit("Requesting CSV report")
        payload: dict[str, object] = {
            "timeFrom": self._utc_time(time_from),
            "timeTo": self._utc_time(time_to),
            "dataIncluded": self._history_content(),
        }
        if time_from > time_to:
            raise ValueError("CSV report start must not be after its end.")
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._verify_credentials(
            *self.load_credentials(), cancel_event=cancel_event, deadline=deadline,
        )
        if self._pending_creation is not None:
            if payload != self._pending_creation[0]:
                self._fail("Resolve the uncertain CSV report request before starting another.")
            return self._recover_creation(cancel_event, deadline)
        previous_ids = {report["reportId"] for report in self._list_reports(cancel_event, deadline)}
        existing_ids = {value for value in previous_ids if isinstance(value, int)}
        self._pending_creation = payload, existing_ids
        self._post_dispatched = False
        try:
            self._checkpoint_creation()
            for attempt in range(3):
                try:
                    status, content, _ = self._api_exchange(
                        "POST", self._EXPORT_PATH, payload,
                        cancel_event=cancel_event, deadline=deadline,
                    )
                except ConnectionError:
                    if not self._post_dispatched:
                        self._pending_creation = None
                        self._fail("Could not connect to create a Trading212 CSV report.")
                    return self._recover_creation(cancel_event, deadline)
                if status == 200:
                    try:
                        data: object = json.loads(content)
                    except (json.JSONDecodeError, UnicodeError):
                        return self._recover_creation(cancel_event, deadline)
                    report_id = data.get("reportId") if isinstance(data, dict) else None
                    if (
                        not isinstance(report_id, int) or isinstance(report_id, bool)
                        or report_id <= 0
                    ):
                        return self._recover_creation(cancel_event, deadline)
                    self._report_requests[report_id] = payload
                    self._pending_creation = None
                    self._checkpoint_creation(report_id=report_id)
                    return report_id
                if status == 408 or 500 <= status < 600:
                    return self._recover_creation(cancel_event, deadline)
                if status != 429 or attempt == 2:
                    self._pending_creation = None
                    self._checkpoint_creation()
                    self._raise_api_status(status, self._EXPORT_PATH)
                self._post_dispatched = False
                self._checkpoint_creation()
        finally:
            if not self._post_dispatched:
                self._pending_creation = None
                self._checkpoint_creation()
        self._fail("Could not request a Trading212 CSV report.")

    def list_csv_reports(
        self, *, cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> list[dict[str, object]]:
        """List reports without creating an export or repeating an uncertain POST."""
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._verify_credentials(
            *self.load_credentials(), cancel_event=cancel_event, deadline=deadline,
        )
        return self._list_reports(cancel_event, deadline)

    def _wait_for_report(
        self, report_id: int, cancel_event: Event | None, deadline: float,
    ) -> str:
        while True:
            self._emit("Waiting for CSV report")
            reports = self._list_reports(cancel_event, deadline)
            report = next((item for item in reports if item["reportId"] == report_id), None)
            if report is None:
                self._logger.info("Trading212 report is not listed yet.")
                continue
            status = report.get("status")
            if status == "Finished":
                expected = self._report_requests.get(report_id)
                if expected is not None and not self._report_matches(report, expected):
                    self._fail("Trading212 report does not match the requested content or interval.")
                link = report.get("downloadLink")
                if not isinstance(link, str) or not link:
                    self._fail("Finished Trading212 report has no download link.")
                self._download_target(link)
                return link
            if status in ("Failed", "Canceled"):
                if (
                    self._archive_state is not None
                    and (pending := self._archive_state["pending"]) is not None
                    and pending["reportId"] == report_id
                ):
                    pending["state"] = "failed"
                    self._save_archive()
                self._fail(f"Trading212 report generation ended with {status}.")
            if status not in ("Queued", "Processing", "Running"):
                self._fail("Trading212 returned an unknown report status.")
            self._logger.info("Waiting for Trading212 CSV report (%s).", status)

    def wait_for_csv_report(
        self, report_id: int, *, cancel_event: Event | None = None,
        wait_timeout: float = 600.0,
    ) -> str:
        """Wait for a known report ID and return its sensitive download URL."""
        self._validate_report_id(report_id)
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._verify_credentials(
            *self.load_credentials(), cancel_event=cancel_event, deadline=deadline,
        )
        return self._wait_for_report(report_id, cancel_event, deadline)

    @staticmethod
    def _validate_report_id(report_id: int) -> None:
        if not isinstance(report_id, int) or isinstance(report_id, bool) or report_id <= 0:
            raise ValueError("CSV report ID must be a positive integer.")

    def _download_target(self, url: str) -> tuple[str, str]:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower()
            allowed = any(
                host == domain or host.endswith("." + domain)
                for domain in ("trading212.com", "amazonaws.com")
            )
            if (
                parsed.scheme != "https" or not allowed
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment
                or any(char.isspace() or ord(char) < 32 for char in url)
            ):
                raise ValueError
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            return host, target
        except ValueError:
            self._fail("Trading212 report download requires an approved HTTPS destination.")

    def _download_to_file(
        self, url: str, path: Path, cancel_event: Event | None, deadline: float,
    ) -> None:
        for attempt in range(3):
            current_url = url
            retry_delay = float(2 ** attempt)
            for redirect in range(4):
                self._check_operation(cancel_event, deadline)
                host, target = self._download_target(current_url)
                connection: http.client.HTTPSConnection | None = None
                try:
                    connection = http.client.HTTPSConnection(
                        host, timeout=min(self._timeout, max(0.001, deadline - time.monotonic())),
                        context=ssl.create_default_context(),
                    )
                    connection.request("GET", target, headers={"Accept": "text/csv,*/*"})
                    response = connection.getresponse()
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader("Location")
                        if redirect == 3 or not isinstance(location, str) or not location:
                            self._fail("Trading212 CSV download has invalid or excessive redirects.")
                        current_url = urljoin(current_url, location)
                        self._download_target(current_url)
                        continue
                    if response.status in (408, 429) or 500 <= response.status < 600:
                        retry_after = response.getheader("Retry-After")
                        retry_delay = self._retry_delay(
                            {"Retry-After": retry_after} if isinstance(retry_after, str) else {},
                            retry_delay,
                        )
                        break
                    if response.status != 200:
                        self._fail(f"Trading212 CSV download failed (HTTP {response.status}).")
                    length_header = response.getheader("Content-Length")
                    expected_length = None
                    if isinstance(length_header, str):
                        try:
                            expected_length = int(length_header)
                        except ValueError:
                            self._fail("CSV download returned an invalid content length.")
                        if expected_length < 0 or expected_length > self._MAX_CSV_BYTES:
                            self._fail("CSV download exceeds the size limit.")
                    total = self._write_csv_response(response, path, cancel_event, deadline)
                    if expected_length is not None and total != expected_length:
                        raise http.client.IncompleteRead(b"")
                    return
                except (OSError, http.client.HTTPException):
                    self._check_operation(cancel_event, deadline)
                    self._logger.warning("Trading212 CSV transfer failed; details withheld.")
                    break
                finally:
                    if connection is not None:
                        connection.close()
            if attempt == 2:
                self._fail("Could not download the complete Trading212 CSV report.")
            self._pause(retry_delay, cancel_event, deadline)

    def _write_csv_response(
        self, response: http.client.HTTPResponse, path: Path,
        cancel_event: Event | None, deadline: float,
    ) -> int:
        total = 0
        try:
            with path.open("wb") as file:
                while True:
                    self._check_operation(cancel_event, deadline)
                    try:
                        chunk = response.read1(64 * 1024)
                    except (OSError, http.client.HTTPException):
                        raise ConnectionError("Trading212 CSV transfer failed.") from None
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._MAX_CSV_BYTES:
                        self._fail("CSV download exceeds the size limit.")
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
        except (InterruptedError, TimeoutError, ConnectionError):
            raise
        except OSError:
            self._fail("Could not write the temporary Trading212 CSV file.")
        return total

    def _validate_csv(self, path: Path, cancel_event: Event | None, deadline: float) -> None:
        try:
            with path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file, strict=True)
                fields = reader.fieldnames
                if (
                    not fields or any(not field for field in fields)
                    or len(fields) != len(set(fields))
                    or not {"Action", "ID", "Total", "Currency (Total)"}.issubset(fields)
                    or not ("Time (UTC)" in fields or "Time" in fields)
                ):
                    self._fail("Downloaded report has an unsupported CSV header.")
                time_column = "Time (UTC)" if "Time (UTC)" in fields else "Time"
                for row in reader:
                    self._check_operation(cancel_event, deadline)
                    if None in row or any(value is None for value in row.values()):
                        self._fail("Downloaded CSV row does not match its header.")
                    if not row["Action"]:
                        self._fail("Downloaded CSV row has no transaction action.")
                    datetime.fromisoformat(row[time_column].replace("Z", "+00:00"))
        except (InterruptedError, TimeoutError):
            raise
        except (OSError, UnicodeError, csv.Error, ValueError):
            self._fail("Downloaded Trading212 report is not a valid CSV file.")

    def download_csv_report(
        self, report_id: int, destination: str | Path, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> Path:
        """Wait, download original CSV bytes, validate, and publish a new file."""
        self._validate_report_id(report_id)
        destination = Path(destination)
        if destination.suffix.lower() != ".csv":
            raise ValueError("CSV report destination must have a .csv extension.")
        if destination.exists() or destination.is_symlink():
            self._fail("CSV report destination already exists; choose a new file.")
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        self._verify_credentials(
            *self.load_credentials(), cancel_event=cancel_event, deadline=deadline,
        )
        url = self._wait_for_report(report_id, cancel_event, deadline)
        self._emit("Downloading CSV report")
        temporary: Path | None = None
        try:
            descriptor, filename = tempfile.mkstemp(
                prefix=".trading212-", suffix=".part", dir=destination.parent,
            )
            temporary = Path(filename)
            os.close(descriptor)
            self._checkpoint_download(temporary, cancel_event, deadline, validated=False)
            self._download_to_file(url, temporary, cancel_event, deadline)
            self._validate_csv(temporary, cancel_event, deadline)
            reused = self._checkpoint_download(
                temporary, cancel_event, deadline, validated=True,
            )
            self._check_operation(cancel_event, deadline)
            if reused is not None:
                return reused
            # Windows rename publishes atomically without replacing an existing destination.
            temporary.rename(destination)
            return destination
        except (InterruptedError, TimeoutError):
            raise
        except OSError:
            self._fail("Could not publish the Trading212 CSV file.")
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    self._fail("Could not remove the incomplete Trading212 CSV file.")

    def _year_bounds(self, year: int) -> tuple[datetime, datetime]:
        zone = ZoneInfo(self._ARCHIVE_TIMEZONE)
        try:
            start = datetime(year, 1, 1, tzinfo=zone).astimezone(timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=zone).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise ValueError("Archive year cannot be represented in Prague and UTC time.") from None
        return start, end - timedelta(microseconds=1)

    def _archive_directory(self, directory: str | Path) -> Path:
        if self._account_id is None:
            self._fail("Connect a Trading212 account before accessing its archive.")
        base = Path(directory).expanduser().resolve()
        root = base / "Trading212" / self._environment / str(self._account_id)
        if not root.resolve().is_relative_to(base):
            self._fail("Trading212 archive directory escapes the selected folder.")
        return root

    def _archive_path(
        self, root: Path, relative: str, year: int, *, temporary: bool = False,
    ) -> Path:
        path = Path(relative)
        pattern = (
            r"\.trading212-[a-zA-Z0-9_-]+\.part" if temporary
            else rf"Trading212_{year}_[0-9]{{8}}T[0-9]{{12}}Z_[1-9][0-9]*\.csv"
        )
        if (
            path.is_absolute() or path.drive or len(path.parts) != 2
            or path.parts[0] != str(year) or not re.fullmatch(pattern, path.name)
        ):
            self._fail("Trading212 archive contains an unsafe file path.")
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            self._fail("Trading212 archive file escapes its account directory.")
        return target

    def _valid_archive_record(self, value: object, *, pending: bool) -> bool:
        if not isinstance(value, dict):
            return False
        common = {
            "year", "timeFrom", "timeTo", "dataIncluded", "complete",
            "reportId", "downloadedAt", "file", "size", "sha256",
        }
        if set(value) != common | ({"state", "baselineIds", "temporary"} if pending else set()):
            return False
        year = value["year"]
        if not isinstance(year, int) or isinstance(year, bool) or not 1 <= year < 9999:
            return False
        if type(value["complete"]) is not bool or value["dataIncluded"] != self._history_content():
            return False
        included = value["dataIncluded"]
        if not isinstance(included, dict) or any(type(flag) is not bool for flag in included.values()):
            return False
        try:
            dates = []
            for key in ("timeFrom", "timeTo", "downloadedAt"):
                text = value[key]
                if not isinstance(text, str):
                    return False
                date = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if self._utc_time(date) != text:
                    return False
                dates.append(date)
            start, end = self._year_bounds(year)
            if dates[0] != start or not start <= dates[1] <= end:
                return False
            if value["complete"] and dates[1] != end:
                return False
        except (ValueError, OverflowError):
            return False
        report_id, filename, size, digest = (
            value["reportId"], value["file"], value["size"], value["sha256"],
        )
        if pending:
            if value["state"] not in ("prepared", "uncertain", "waiting", "failed"):
                return False
            ids = value["baselineIds"]
            if (
                not isinstance(ids, list)
                or any(type(item) is not int or item <= 0 for item in ids)
                or len(ids) != len(set(ids))
            ):
                return False
            if value["state"] in ("prepared", "uncertain"):
                if any(item is not None for item in (
                    report_id, filename, size, digest, value["temporary"],
                )):
                    return False
                return True
            if value["temporary"] is not None and not isinstance(value["temporary"], str):
                return False
            if (size is None) != (digest is None):
                return False
        if type(report_id) is not int or report_id <= 0:
            return False
        if filename is not None and not isinstance(filename, str):
            return False
        if not pending and filename is None:
            return False
        if size is None and digest is None and pending:
            return True
        return (
            isinstance(size, int) and not isinstance(size, bool)
            and 0 < size <= self._MAX_CSV_BYTES
            and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
            and isinstance(filename, str)
        )

    def _valid_archive_state(self, value: object) -> TypeGuard[_ArchiveState]:
        if not isinstance(value, dict) or set(value) != {
            "version", "environment", "account_id", "timezone", "reports", "recommended", "pending",
        }:
            return False
        if (
            type(value["version"]) is not int or value["version"] != 1
            or type(value["account_id"]) is not int or value["account_id"] != self._account_id
            or value["environment"] != self._environment
            or value["timezone"] != self._ARCHIVE_TIMEZONE
        ):
            return False
        reports = value["reports"]
        recommended = value["recommended"]
        return (
            isinstance(reports, list)
            and all(self._valid_archive_record(item, pending=False) for item in reports)
            and isinstance(recommended, dict)
            and all(
                isinstance(year, str) and year.isdecimal()
                and type(report_id) is int and report_id > 0
                for year, report_id in recommended.items()
            )
            and (value["pending"] is None or self._valid_archive_record(value["pending"], pending=True))
        )

    def _file_digest(self, path: Path, cancel_event: Event | None, deadline: float) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as file:
                while True:
                    self._check_operation(cancel_event, deadline)
                    chunk = file.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self._MAX_CSV_BYTES:
                        self._fail("Archived Trading212 CSV exceeds the size limit.")
                    digest.update(chunk)
        except (InterruptedError, TimeoutError):
            raise
        except OSError:
            self._fail("Could not read an archived Trading212 CSV file.")
        return size, digest.hexdigest()

    def _validate_archive_csv(
        self, path: Path, record: _ArchiveReport | _ArchivePending,
        cancel_event: Event | None, deadline: float,
    ) -> tuple[datetime | None, datetime | None]:
        self._validate_csv(path, cancel_event, deadline)
        start = datetime.fromisoformat(record["timeFrom"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(record["timeTo"].replace("Z", "+00:00"))
        minimum: datetime | None = None
        maximum: datetime | None = None
        try:
            with path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file, strict=True)
                for row in reader:
                    self._check_operation(cancel_event, deadline)
                    text = row["Time (UTC)"] if "Time (UTC)" in row else row["Time"]
                    date = datetime.fromisoformat(text.replace("Z", "+00:00"))
                    if date.utcoffset() is None or not start <= date <= end:
                        self._fail("Archived CSV timestamps do not match the requested annual interval.")
                    minimum = date if minimum is None else min(minimum, date)
                    maximum = date if maximum is None else max(maximum, date)
        except (InterruptedError, TimeoutError):
            raise
        except (OSError, UnicodeError, csv.Error, ValueError):
            self._fail("Could not validate the archived Trading212 CSV coverage.")
        return minimum, maximum

    def _load_archive(
        self, root: Path, cancel_event: Event | None, deadline: float,
    ) -> _ArchiveState:
        if self._account_id is None:
            self._fail("Connect a Trading212 account before accessing its archive.")
        metadata = root / "archive.json"
        if metadata.is_symlink():
            self._fail("Trading212 archive metadata must not be a symbolic link.")
        if not metadata.exists():
            if root.exists() and any(root.glob("*/*.csv")):
                self._fail("CSV files exist without archive metadata; restore archive.json before syncing.")
            return {
                "version": 1, "environment": self._environment,
                "account_id": self._account_id, "timezone": self._ARCHIVE_TIMEZONE,
                "reports": [], "recommended": {}, "pending": None,
            }
        try:
            if metadata.stat().st_size > self._MAX_ARCHIVE_BYTES:
                self._fail("Trading212 archive metadata exceeds the size limit.")
            with metadata.open(encoding="utf-8") as file:
                data: object = json.load(file)
        except (OSError, UnicodeError, ValueError):
            self._fail("Could not read Trading212 archive metadata.")
        if not self._valid_archive_state(data):
            self._fail("Trading212 archive schema, account, environment, timezone or coverage is invalid.")
        if data["recommended"] != {
            str(year): report["reportId"]
            for year, report in self._recommended_reports(data).items()
        }:
            self._fail("Trading212 archive recommended revisions are inconsistent.")
        ids: set[int] = set()
        checked: dict[Path, tuple[int, str]] = {}
        coverage: dict[Path, tuple[datetime | None, datetime | None]] = {}
        for report in data["reports"]:
            if report["reportId"] in ids:
                self._fail("Trading212 archive contains duplicate report identities.")
            ids.add(report["reportId"])
            path = self._archive_path(root, report["file"], report["year"])
            if path not in checked:
                checked[path] = self._file_digest(path, cancel_event, deadline)
                coverage[path] = self._validate_archive_csv(path, report, cancel_event, deadline)
            if checked[path] != (report["size"], report["sha256"]):
                self._fail("Archived Trading212 CSV size or SHA-256 does not match its metadata.")
            minimum, maximum = coverage[path]
            start = datetime.fromisoformat(report["timeFrom"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(report["timeTo"].replace("Z", "+00:00"))
            if (minimum is not None and minimum < start) or (maximum is not None and maximum > end):
                self._fail("Archived CSV timestamps do not match the requested annual interval.")
        if (pending := data["pending"]) is not None:
            if pending["file"] is not None:
                self._archive_path(root, pending["file"], pending["year"])
            if pending["temporary"] is not None:
                self._archive_path(root, pending["temporary"], pending["year"], temporary=True)
            if pending["reportId"] in ids:
                self._fail("Pending Trading212 report is already recorded in the archive.")
        known = set(checked)
        if pending is not None and pending["file"] is not None:
            known.add(self._archive_path(root, pending["file"], pending["year"]))
        if root.exists() and any(path not in known for path in root.glob("*/*.csv")):
            self._fail("Trading212 archive contains an untracked CSV; do not silently discard it.")
        return data

    @contextmanager
    def _lock_archive(self, root: Path) -> Generator[None, None, None]:
        if sys.platform != "win32":
            self._fail("Trading212 archive synchronization requires Windows file locking.")
        try:
            root.mkdir(parents=True, exist_ok=True)
            lock_path = root / ".archive.lock"
            if lock_path.is_symlink() or lock_path.resolve().parent != root.resolve():
                self._fail("Trading212 archive lock must not be a symbolic link.")
            with lock_path.open("a+b") as lock:
                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._fail("Trading212 archive is in use or could not be locked.")
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        except (InterruptedError, TimeoutError):
            raise
        except OSError:
            self._fail("Could not access or unlock the Trading212 archive.")

    def _save_archive(self) -> None:
        if self._archive_root is None or self._archive_state is None:
            self._fail("No active Trading212 archive to persist.")
        self._archive_state["recommended"] = {
            str(year): report["reportId"]
            for year, report in self._recommended_reports(self._archive_state).items()
        }
        content = json.dumps(self._archive_state, indent=2, sort_keys=True).encode("utf-8")
        if len(content) > self._MAX_ARCHIVE_BYTES:
            self._fail("Trading212 archive metadata exceeds the size limit.")
        temporary: Path | None = None
        try:
            descriptor, filename = tempfile.mkstemp(
                prefix=".archive-", suffix=".tmp", dir=self._archive_root,
            )
            temporary = Path(filename)
            with os.fdopen(descriptor, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._archive_root / "archive.json")
        except OSError:
            self._fail("Could not persist Trading212 archive metadata.")
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    self._fail("Could not remove temporary Trading212 archive metadata.")

    def _checkpoint_creation(self, report_id: int | None = None, *, uncertain: bool = False) -> None:
        if self._archive_state is None:
            return
        pending = self._archive_state["pending"]
        if pending is None:
            self._fail("No annual report intent to persist.")
        if report_id is not None:
            pending["reportId"] = report_id
            pending["state"] = "waiting"
        elif self._pending_creation is not None:
            pending["baselineIds"] = sorted(self._pending_creation[1])
            pending["state"] = "uncertain" if uncertain or self._post_dispatched else "prepared"
        else:
            pending["baselineIds"] = []
            pending["state"] = "prepared"
        self._save_archive()

    def _checkpoint_download(
        self, temporary: Path, cancel_event: Event | None, deadline: float, *, validated: bool,
    ) -> Path | None:
        if self._archive_state is None or self._archive_root is None:
            return None
        pending = self._archive_state["pending"]
        if pending is None or pending["file"] is None:
            self._fail("No annual download destination to persist.")
        pending["temporary"] = str(temporary.relative_to(self._archive_root))
        if validated:
            self._validate_archive_csv(temporary, pending, cancel_event, deadline)
            pending["size"], pending["sha256"] = self._file_digest(temporary, cancel_event, deadline)
            pending["downloadedAt"] = self._utc_time(datetime.now(timezone.utc))
            for old in reversed(self._archive_state["reports"]):
                if (
                    old["year"] == pending["year"]
                    and (old["size"], old["sha256"]) == (pending["size"], pending["sha256"])
                ):
                    pending["file"] = old["file"]
                    self._save_archive()
                    return self._archive_path(self._archive_root, old["file"], old["year"])
        self._save_archive()
        return None

    @staticmethod
    def _archive_payload(pending: _ArchivePending) -> dict[str, object]:
        return {
            "timeFrom": pending["timeFrom"], "timeTo": pending["timeTo"],
            "dataIncluded": pending["dataIncluded"],
        }

    def _finish_archive_report(self, cancel_event: Event | None, deadline: float) -> None:
        if self._archive_state is None or self._archive_root is None:
            self._fail("No active Trading212 archive.")
        pending = self._archive_state["pending"]
        if pending is None or pending["reportId"] is None or pending["file"] is None:
            self._fail("Annual Trading212 report is not ready for publication.")
        path = self._archive_path(self._archive_root, pending["file"], pending["year"])
        self._validate_archive_csv(path, pending, cancel_event, deadline)
        size, digest = self._file_digest(path, cancel_event, deadline)
        if (size, digest) != (pending["size"], pending["sha256"]):
            self._fail("Uncommitted Trading212 CSV does not match its persisted SHA-256.")
        if pending["temporary"] is not None:
            temporary = self._archive_path(
                self._archive_root, pending["temporary"], pending["year"], temporary=True,
            )
            if temporary.exists():
                temporary.unlink()
        self._archive_state["reports"].append({
            "year": pending["year"], "timeFrom": pending["timeFrom"],
            "timeTo": pending["timeTo"], "dataIncluded": pending["dataIncluded"],
            "complete": pending["complete"], "reportId": pending["reportId"],
            "downloadedAt": pending["downloadedAt"], "file": pending["file"],
            "size": size, "sha256": digest,
        })
        self._archive_state["pending"] = None
        self._check_operation(cancel_event, deadline)
        self._save_archive()

    def _resume_archive_report(
        self, cancel_event: Event | None, deadline: float, *, local_only: bool = False,
    ) -> None:
        if self._archive_state is None or self._archive_root is None:
            self._fail("No active Trading212 archive.")
        pending = self._archive_state["pending"]
        if pending is None:
            return
        self._check_operation(cancel_event, deadline)
        if pending["file"] is not None:
            path = self._archive_path(self._archive_root, pending["file"], pending["year"])
            if path.exists():
                self._finish_archive_report(cancel_event, deadline)
                return
        if pending["temporary"] is not None:
            temporary = self._archive_path(
                self._archive_root, pending["temporary"], pending["year"], temporary=True,
            )
            if temporary.exists():
                if pending["sha256"] is not None and pending["file"] is not None:
                    if self._file_digest(temporary, cancel_event, deadline) != (
                        pending["size"], pending["sha256"],
                    ):
                        self._fail("Interrupted Trading212 CSV does not match its persisted SHA-256.")
                    self._validate_archive_csv(temporary, pending, cancel_event, deadline)
                    temporary.rename(self._archive_path(
                        self._archive_root, pending["file"], pending["year"],
                    ))
                    self._finish_archive_report(cancel_event, deadline)
                    return
                if not local_only:
                    temporary.unlink()
        if local_only:
            return
        payload = self._archive_payload(pending)
        if pending["state"] == "uncertain":
            self._pending_creation = payload, set(pending["baselineIds"])
        if pending["state"] == "failed":
            pending.update(
                state="prepared", reportId=None, file=None, temporary=None, size=None, sha256=None,
            )
            self._save_archive()
        if pending["reportId"] is None:
            self._check_operation(cancel_event, deadline)
            self.request_csv_report(
                datetime.fromisoformat(pending["timeFrom"].replace("Z", "+00:00")),
                datetime.fromisoformat(pending["timeTo"].replace("Z", "+00:00")),
                cancel_event=cancel_event, wait_timeout=max(0.001, deadline - time.monotonic()),
            )
        report_id = pending["reportId"]
        if report_id is None:
            self._fail("Trading212 annual report creation returned no identity.")
        self._report_requests[report_id] = payload
        if pending["file"] is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            pending["file"] = str(Path(str(pending["year"])) / f"Trading212_{pending['year']}_{stamp}_{report_id}.csv")
        pending["temporary"], pending["size"], pending["sha256"] = None, None, None
        self._save_archive()
        destination = self._archive_path(self._archive_root, pending["file"], pending["year"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._check_operation(cancel_event, deadline)
        self.download_csv_report(
            report_id, destination, cancel_event=cancel_event,
            wait_timeout=max(0.001, deadline - time.monotonic()),
        )
        self._finish_archive_report(cancel_event, deadline)

    @staticmethod
    def _recommended_reports(state: _ArchiveState) -> dict[int, _ArchiveReport]:
        recommended: dict[int, _ArchiveReport] = {}
        for report in state["reports"]:
            previous = recommended.get(report["year"])
            key = (report["complete"], datetime.fromisoformat(report["timeTo"].replace("Z", "+00:00")))
            if previous is None or key >= (
                previous["complete"], datetime.fromisoformat(previous["timeTo"].replace("Z", "+00:00")),
            ):
                recommended[report["year"]] = report
        return recommended

    def get_archived_csvs(
        self, archive_directory: str | Path, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
        on_report: Callable[[ArchivedCSV], None] | None = None,
    ) -> list[Path]:
        """Verify committed CSVs and recover validated local downloads, without API calls."""
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        root = self._archive_directory(archive_directory)
        if self._archive_state is not None:
            self._fail("Trading212 archive synchronization is already active on this instance.")
        if not root.exists():
            return []
        with self._lock_archive(root):
            state = self._load_archive(root, cancel_event, deadline)
            self._archive_root, self._archive_state = root, state
            try:
                self._resume_archive_report(cancel_event, deadline, local_only=True)
                if state["pending"] is not None:
                    self._logger.warning(
                        "Trading212 archive has an unfinished report; returning only committed CSVs."
                    )
                recommended = self._recommended_reports(state)
                for year in sorted(recommended):
                    self._notify_archived(year, on_report)
                return [
                    self._archive_path(root, recommended[year]["file"], year)
                    for year in sorted(recommended)
                ]
            finally:
                self._archive_root, self._archive_state = None, None

    def sync_yearly_csv(
        self, archive_directory: str | Path, first_year: int, *,
        refresh_years: tuple[int, ...] = (), as_of: datetime | None = None,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
        on_report: Callable[[ArchivedCSV], None] | None = None,
    ) -> list[Path]:
        """Archive Prague calendar years; never import into the analytical database."""
        now = datetime.now(timezone.utc) if as_of is None else as_of
        self._utc_time(now)
        current_year = now.astimezone(ZoneInfo(self._ARCHIVE_TIMEZONE)).year
        if (
            type(first_year) is not int or not 1 <= first_year <= current_year < 9999
            or any(type(year) is not int or not first_year <= year <= current_year for year in refresh_years)
        ):
            raise ValueError("Archive years must be integers from the first year through the current year.")
        for year in range(first_year, current_year + 1):
            self._year_bounds(year)
        deadline = self._deadline(wait_timeout)
        self._check_operation(cancel_event, deadline)
        root = self._archive_directory(archive_directory)
        if self._archive_state is not None:
            self._fail("Trading212 archive synchronization is already active on this instance.")
        with self._lock_archive(root):
            state = self._load_archive(root, cancel_event, deadline)
            pending = state["pending"]
            if self._pending_creation is not None and (
                pending is None or pending["state"] != "uncertain"
                or self._pending_creation != (self._archive_payload(pending), set(pending["baselineIds"]))
            ):
                self._fail("Resolve the uncertain standalone CSV request before synchronizing this archive.")
            self._archive_root, self._archive_state = root, state
            try:
                resumed = None if pending is None else (
                    pending["year"], pending["timeFrom"], pending["timeTo"], pending["complete"],
                )
                self._resume_archive_report(cancel_event, self._deadline(wait_timeout))
                recommended = self._recommended_reports(state)
                for year in range(first_year, current_year + 1):
                    self._emit("Preparing archive year", year=year)
                    deadline = self._deadline(wait_timeout)
                    self._check_operation(cancel_event, deadline)
                    start, end = self._year_bounds(year)
                    time_to = end if year < current_year else now
                    if resumed == (
                        year, self._utc_time(start), self._utc_time(time_to), year < current_year,
                    ):
                        self._notify_archived(year, on_report)
                        continue
                    old = recommended.get(year)
                    if (
                        year != current_year and old is not None and old["complete"]
                        and year not in refresh_years and end < now - timedelta(days=7)
                    ):
                        self._notify_archived(year, on_report)
                        continue
                    state["pending"] = {
                        "year": year, "timeFrom": self._utc_time(start),
                        "timeTo": self._utc_time(time_to),
                        "dataIncluded": self._history_content(),
                        "complete": year < current_year, "state": "prepared",
                        "baselineIds": [], "reportId": None,
                        "downloadedAt": self._utc_time(datetime.now(timezone.utc)),
                        "file": None, "temporary": None, "size": None, "sha256": None,
                    }
                    self._save_archive()
                    self._resume_archive_report(cancel_event, deadline)
                    self._emit("Archived CSV report", year=year)
                    self._notify_archived(year, on_report)
                recommended = self._recommended_reports(state)
                return [
                    self._archive_path(root, recommended[year]["file"], year)
                    for year in range(first_year, current_year + 1)
                ]
            finally:
                self._archive_root, self._archive_state = None, None
