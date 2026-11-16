"""Read-only Trading 212 access, CSV reports, and Windows credentials."""

import base64
import csv
import http.client
import json
import logging
import math
import os
import ssl
import sys
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Event
from typing import Literal, NoReturn
from urllib.parse import urljoin, urlsplit

import keyring
from keyring.backends import Windows
from keyring.errors import KeyringError

if sys.platform == "win32":
    from win32ctypes.pywin32 import pywintypes, win32cred


class Trading212API:
    """Manage credentials and export history without changing the portfolio."""

    _ACCOUNT_PATH = "/api/v0/equity/account/summary"
    _EXPORT_PATH = "/api/v0/equity/history/exports"
    _MAX_CSV_BYTES = 100 * 1024 * 1024

    def __init__(
        self,
        environment: Literal["live", "demo"] = "live",
        account_id: int | None = None,
        timeout: float = 30.0,
        logger: logging.Logger | None = None,
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
        self._keyring: Windows.WinVaultKeyring | None = None
        self._next_request_at: dict[tuple[str, str], float] = {}
        self._pending_creation: tuple[dict[str, object], set[int]] | None = None
        self._report_requests: dict[int, dict[str, object]] = {}
        self._post_dispatched = False

    @property
    def environment(self) -> Literal["live", "demo"]:
        return self._environment

    @property
    def account_id(self) -> int | None:
        return self._account_id

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

    def save_credentials(self, api_key: str, api_secret: str) -> int:
        """Verify and store a key pair, returning the connected account ID."""
        self._validate_credentials(api_key, api_secret)
        self._credential_backend()
        account_id = self._verify_credentials(api_key, api_secret)
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
        return report_id

    def request_csv_report(
        self, time_from: datetime, time_to: datetime, *,
        cancel_event: Event | None = None, wait_timeout: float = 600.0,
    ) -> int:
        """Request all history categories; return an ID for waiting or resuming."""
        payload: dict[str, object] = {
            "timeFrom": self._utc_time(time_from),
            "timeTo": self._utc_time(time_to),
            "dataIncluded": {
                "includeOrders": True, "includeDividends": True,
                "includeInterest": True, "includeTransactions": True,
            },
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
                    return report_id
                if status == 408 or 500 <= status < 600:
                    return self._recover_creation(cancel_event, deadline)
                if status != 429 or attempt == 2:
                    self._pending_creation = None
                    self._raise_api_status(status, self._EXPORT_PATH)
        finally:
            if not self._post_dispatched:
                self._pending_creation = None
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
        temporary: Path | None = None
        try:
            descriptor, filename = tempfile.mkstemp(
                prefix=".trading212-", suffix=".part", dir=destination.parent,
            )
            temporary = Path(filename)
            os.close(descriptor)
            self._download_to_file(url, temporary, cancel_event, deadline)
            self._validate_csv(temporary, cancel_event, deadline)
            self._check_operation(cancel_event, deadline)
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
