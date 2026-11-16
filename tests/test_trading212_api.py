import base64
import json
import logging
import ssl
import sys
import traceback
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from keyring.backends import Windows
from keyring.backends.null import Keyring as NullKeyring
from keyring.errors import PasswordDeleteError

from tradingtools.trading212_api import Trading212API

if sys.platform == "win32":
    from win32ctypes.pywin32 import pywintypes, win32cred


@unittest.skipUnless(sys.platform == "win32", "Native Windows credential backend required")
class TestTrading212API(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("tradingtools.trading212_api.sys.platform", "win32"))
        self.storage = {}
        self.backend = Windows.WinVaultKeyring()
        self.select_backend = self.stack.enter_context(patch(
            "tradingtools.trading212_api.keyring.get_keyring",
            return_value=self.backend,
        ))
        self.stack.enter_context(patch.object(
            self.backend, "get_password",
            side_effect=lambda service, username: self.storage.get((service, username)),
        ))
        self.stack.enter_context(patch.object(
            self.backend, "delete_password", side_effect=self.delete_password,
        ))
        self.write = self.stack.enter_context(patch(
            "tradingtools.trading212_api.win32cred.CredWrite",
            side_effect=self.write_credential,
        ))
        self.response = Mock(status=200)
        self.response.read.return_value = b'{"id": 123, "currency": "CZK"}'
        self.connection = Mock()
        self.connection.getresponse.return_value = self.response
        self.connect = self.stack.enter_context(patch(
            "tradingtools.trading212_api.http.client.HTTPSConnection",
            return_value=self.connection,
        ))
        self.logger = logging.getLogger("trading_tools.test_trading212")
        self.api = Trading212API(logger=self.logger)
        self.key = "test-key"
        self.secret = "test-secret"

    def write_credential(self, credential, _flags):
        self.storage[(credential["TargetName"], credential["UserName"])] = (
            credential["CredentialBlob"]
        )

    def delete_password(self, service, username):
        if (service, username) not in self.storage:
            raise PasswordDeleteError(service)
        del self.storage[(service, username)]

    def assert_safe_failure(self, operation, message):
        with self.assertLogs(self.logger, level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, message) as raised:
                operation()
        output = "\n".join(logs.output) + "".join(
            traceback.format_exception(raised.exception)
        )
        self.assertNotIn(self.key, output)
        self.assertNotIn(self.secret, output)
        return raised.exception

    def test_save_reload_verify_and_delete_with_one_native_record(self):
        self.assertEqual(self.api.save_credentials(self.key, self.secret), 123)
        request = self.connection.request.call_args
        self.assertEqual(request.args, ("GET", "/api/v0/equity/account/summary"))
        headers = request.kwargs["headers"]
        self.assertEqual(
            base64.b64decode(headers["Authorization"].removeprefix("Basic ")).decode(),
            f"{self.key}:{self.secret}",
        )
        self.assertEqual(self.connect.call_args.args, ("live.trading212.com",))
        context = self.connect.call_args.kwargs["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(self.connect.call_args.kwargs["timeout"], 30)
        self.connection.close.assert_called_once()

        credential, flags = self.write.call_args.args
        self.assertEqual(flags, 0)
        self.assertEqual(credential["Persist"], win32cred.CRED_PERSIST_LOCAL_MACHINE)
        self.assertEqual(json.loads(credential["CredentialBlob"]), {
            "api_key": self.key, "api_secret": self.secret,
        })
        reloaded = Trading212API(account_id=123, logger=self.logger)
        self.assertEqual(reloaded.load_credentials(), (self.key, self.secret))
        self.assertEqual(reloaded.verify_account(), 123)
        reloaded.delete_credentials()
        self.assertFalse(self.storage)
        self.assert_safe_failure(reloaded.load_credentials, "No stored credentials")

    def test_account_and_environment_are_isolated_and_update_keeps_one_record(self):
        self.api.save_credentials(self.key, self.secret)
        demo = Trading212API("demo", logger=self.logger)
        demo.save_credentials("demo-key", "demo-secret")
        self.response.read.return_value = b'{"id": 456}'
        other = Trading212API(logger=self.logger)
        other.save_credentials("other-key", "other-secret")
        self.response.read.return_value = b'{"id": 123}'
        self.api.save_credentials("replacement-key", "replacement-secret")
        self.assertEqual(len(self.storage), 3)
        self.assertEqual(self.api.load_credentials(), ("replacement-key", "replacement-secret"))
        self.assertEqual(demo.load_credentials(), ("demo-key", "demo-secret"))
        self.assertEqual(other.load_credentials(), ("other-key", "other-secret"))
        self.api.delete_credentials()
        self.assertEqual(len(self.storage), 2)

    def test_failed_verification_or_write_preserves_original_pair(self):
        self.api.save_credentials(self.key, self.secret)
        original = dict(self.storage)
        for failure in ("rejected", "other-account", "native-write"):
            with self.subTest(failure=failure):
                self.response.status = 401 if failure == "rejected" else 200
                self.response.read.return_value = (
                    b'{"id": 456}' if failure == "other-account" else b'{"id": 123}'
                )
                self.write.side_effect = (
                    pywintypes.error(5, "CredWrite", self.secret)
                    if failure == "native-write" else self.write_credential
                )
                self.assert_safe_failure(
                    lambda: self.api.save_credentials("new-key", "new-secret"),
                    "rejected|different account|Could not save",
                )
                self.assertEqual(self.storage, original)
                self.assertEqual(self.api.load_credentials(), (self.key, self.secret))

    def test_non_native_or_unavailable_backend_blocks_network_and_storage(self):
        for backend in (NullKeyring(), Mock(spec=Windows.WinVaultKeyring)):
            with self.subTest(backend=type(backend).__name__):
                self.select_backend.return_value = backend
                self.assert_safe_failure(
                    lambda: self.api.save_credentials(self.key, self.secret),
                    "native Windows",
                )
        self.select_backend.side_effect = RuntimeError(self.secret)
        self.assert_safe_failure(
            lambda: self.api.save_credentials(self.key, self.secret),
            "could not be initialized",
        )
        self.connect.assert_not_called()
        self.write.assert_not_called()
        with patch("tradingtools.trading212_api.sys.platform", "linux"):
            self.assert_safe_failure(
                lambda: self.api.save_credentials(self.key, self.secret),
                "require Windows",
            )

    def test_http_failures_do_not_save_or_expose_response_body(self):
        for status in (401, 403, 429, 302, 500):
            with self.subTest(status=status):
                self.response.status = status
                self.response.read.return_value = self.secret.encode()
                self.assert_safe_failure(
                    lambda: self.api.save_credentials(self.key, self.secret),
                    "Trading212",
                )
        self.response.read.assert_not_called()
        self.write.assert_not_called()
        self.assertIsNone(self.api.account_id)

    def test_connection_errors_and_invalid_identity_are_sanitized(self):
        self.connection.request.side_effect = OSError(self.secret)
        self.assert_safe_failure(
            lambda: self.api.save_credentials(self.key, self.secret), "securely connect",
        )
        self.connection.request.side_effect = None
        for payload in (
            self.secret.encode(), b'[]', b'{}', b'{"id":true}',
            b'{"id":0}', b'{"id":"123"}', b'x' * (64 * 1024 + 1),
        ):
            with self.subTest(payload_size=len(payload)):
                self.response.read.return_value = payload
                self.assert_safe_failure(
                    lambda: self.api.save_credentials(self.key, self.secret),
                    "invalid|size limit",
                )
        self.write.assert_not_called()

    def test_missing_corrupt_or_unreadable_credentials_fail_explicitly(self):
        api = Trading212API(account_id=123, logger=self.logger)
        self.assert_safe_failure(api.load_credentials, "No stored credentials")
        target = ("TradingTools:Trading212:live:123", "123")
        for payload in (
            self.secret, "[]", '{"api_key":123}',
            '{"api_key":"test-key","api_secret":""}',
        ):
            with self.subTest(payload=payload[:10]):
                self.storage[target] = payload
                self.assert_safe_failure(api.load_credentials, "Stored Trading212")
        with patch.object(self.backend, "get_password", side_effect=OSError(self.secret)):
            self.assert_safe_failure(api.load_credentials, "Could not read")
        with patch.object(self.backend, "delete_password", side_effect=OSError(self.secret)):
            self.assert_safe_failure(api.delete_credentials, "Could not remove")
        self.connect.assert_not_called()
        self.write.assert_not_called()

    def test_invalid_inputs_never_reach_network_or_storage(self):
        for key, secret in (("", self.secret), (self.key, ""), ("bad:key", self.secret),
                            (self.key, "secret\n"), (" key", self.secret)):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.api.save_credentials(key, secret)
        self.assert_safe_failure(self.api.load_credentials, "Connect a Trading212")
        self.connect.assert_not_called()
        self.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
