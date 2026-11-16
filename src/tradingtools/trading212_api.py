"""Trading 212 account access and Windows Credential Manager integration."""

import base64
import http.client
import json
import logging
import math
import ssl
import sys
from typing import Literal, NoReturn

import keyring
from keyring.backends import Windows
from keyring.errors import KeyringError

if sys.platform == "win32":
    from win32ctypes.pywin32 import pywintypes, win32cred


class Trading212API:
    """Manage credentials and verify an account without changing its portfolio."""

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

    def _verify_credentials(self, api_key: str, api_secret: str) -> int:
        self._validate_credentials(api_key, api_secret)
        authorization = base64.b64encode(
            f"{api_key}:{api_secret}".encode("utf-8")
        ).decode("ascii")
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(
                f"{self._environment}.trading212.com",
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
            connection.request(
                "GET",
                "/api/v0/equity/account/summary",
                headers={
                    "Authorization": f"Basic {authorization}",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                messages = {
                    401: "Trading212 rejected the API Key or Secret.",
                    403: "Trading212 account data permission is missing.",
                    429: "Trading212 account request rate limit reached. Try again later.",
                }
                if 300 <= response.status < 400:
                    self._fail("Trading212 API redirects are not permitted.")
                self._fail(messages.get(
                    response.status,
                    f"Trading212 account verification failed (HTTP {response.status}).",
                ))
            content = response.read(64 * 1024 + 1)
            if len(content) > 64 * 1024:
                self._fail("Trading212 account response exceeded the size limit.")
        except (OSError, http.client.HTTPException):
            self._fail("Could not securely connect to the Trading212 account API.")
        finally:
            if connection is not None:
                connection.close()

        try:
            summary: object = json.loads(content)
        except (json.JSONDecodeError, UnicodeError):
            self._fail("Trading212 returned invalid account JSON.")
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

    def verify_account(self) -> int:
        """Verify that the stored credentials still match the connected account."""
        return self._verify_credentials(*self.load_credentials())

    def delete_credentials(self) -> None:
        """Remove local credentials; this does not revoke the key at Trading 212."""
        target = self._credential_target()
        backend = self._credential_backend()
        try:
            backend.delete_password(target, str(self._account_id))
        except (KeyringError, pywintypes.error, OSError):
            self._fail("Could not remove credentials from Windows Credential Manager.")
