import base64
import hashlib
import json
import logging
import os
import ssl
import sys
import tempfile
import traceback
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

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
        self.clock = 0.0
        self.stack.enter_context(patch("tradingtools.trading212_api.time.monotonic", side_effect=lambda: self.clock))
        self.stack.enter_context(patch("tradingtools.trading212_api.time.time", side_effect=lambda: 1_000_000_000 + self.clock))
        self.stack.enter_context(patch("tradingtools.trading212_api.time.sleep", side_effect=self.advance))
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
        self.response = Mock(status=200, length=None)
        self.response.read.return_value = b'{"id": 123, "currency": "CZK"}'
        self.connection = Mock()
        self.connection.getresponse.side_effect = self.response_for_request
        self.response.read1.side_effect = self.read_response
        self.connect = self.stack.enter_context(patch(
            "tradingtools.trading212_api.http.client.HTTPSConnection",
            return_value=self.connection,
        ))
        self.logger = logging.getLogger("trading_tools.test_trading212")
        self.api = Trading212API(logger=self.logger)
        self.key = "test-key"
        self.secret = "test-secret"

    def advance(self, duration):
        self.clock += duration

    def response_for_request(self):
        self.read_offset = 0
        return self.response

    def read_response(self, amount):
        body = self.response.read.return_value
        chunk = body[self.read_offset:self.read_offset + amount]
        self.read_offset += len(chunk)
        return chunk

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

    def test_verify_entered_pair_does_not_store_and_cancelled_save_does_not_overwrite(self):
        self.api.save_credentials(self.key, self.secret)
        original = dict(self.storage)
        self.write.reset_mock()
        self.assertEqual(self.api.verify_credentials("replacement-key", "replacement-secret"), 123)
        self.write.assert_not_called()
        self.assertEqual(self.storage, original)
        cancel = Event()
        with patch.object(self.api, "verify_credentials", side_effect=lambda *a, **kw: (cancel.set() or 123)):
            with self.assertRaises(InterruptedError):
                self.api.save_credentials("replacement-key", "replacement-secret", cancel_event=cancel)
        self.write.assert_not_called()
        self.assertEqual(self.storage, original)

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
        self.response.read1.assert_not_called()
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


class _CSVReportFixture(unittest.TestCase):
    CSV = (
        b"\xef\xbb\xbfAction,Time (UTC),ID,Total,Currency (Total)\r\n"
        b"Interest on cash,2024-01-01 12:00:00+00:00,cash-1,1.23,CZK\r\n"
    )
    HOST = "reports.s3.eu-west-1.amazonaws.com"
    URL = "https://reports.s3.eu-west-1.amazonaws.com/history.csv?token=signed-test-token"

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.clock = 0.0
        self.stack.enter_context(patch("tradingtools.trading212_api.time.monotonic", side_effect=lambda: self.clock))
        self.stack.enter_context(patch("tradingtools.trading212_api.time.time", side_effect=lambda: 1_000_000_000 + self.clock))
        self.stack.enter_context(patch("tradingtools.trading212_api.time.sleep", side_effect=self.advance))
        self.logger = logging.getLogger("trading_tools.test_reports")
        self.api = Trading212API(account_id=123, logger=self.logger)
        self.load = self.stack.enter_context(patch.object(
            self.api, "load_credentials", return_value=("test-key", "test-secret"),
        ))
        self.responses = []
        self.requests = []
        self.stack.enter_context(patch(
            "tradingtools.trading212_api.http.client.HTTPSConnection",
            side_effect=self.connect,
        ))
        self.start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    def advance(self, duration):
        self.clock += duration

    def queue(self, method, path, data, *, status=200, host="live.trading212.com",
              headers=None, error=None, on_read=None, on_request=None):
        self.responses.append({
            "method": method, "path": path, "host": host, "status": status,
            "body": data if isinstance(data, bytes) else json.dumps(data).encode(),
            "headers": headers or {}, "error": error, "on_read": on_read,
            "on_request": on_request,
        })

    def connect(self, host, **kwargs):
        connection = Mock()
        response = Mock()
        spec = {}
        offset = 0

        def request(method, path, body=None, headers=None):
            nonlocal spec
            self.assertTrue(self.responses, "Unexpected HTTP request")
            spec = self.responses.pop(0)
            self.assertEqual((host, method, path), (spec["host"], spec["method"], spec["path"]))
            self.requests.append({
                "host": host, "method": method, "path": path, "body": body,
                "headers": headers, "time": self.clock, "timeout": kwargs["timeout"],
            })
            if spec["on_request"] is not None:
                spec["on_request"]()
            if spec["error"] is not None:
                raise spec["error"]
            response.status = spec["status"]
            length = spec["headers"].get("Content-Length")
            response.length = int(length) if isinstance(length, str) and length.isdigit() else None
            response.getheader.side_effect = lambda name: spec["headers"].get(name)

        def read(amount):
            nonlocal offset
            chunk = spec["body"][offset:offset + amount]
            offset += len(chunk)
            if response.length is not None:
                response.length -= len(chunk)
            if spec["on_read"] is not None:
                spec["on_read"]()
            return chunk

        connection.request.side_effect = request
        connection.getresponse.return_value = response
        response.read.side_effect = read
        response.read1.side_effect = read
        return connection

    def account(self):
        self.queue("GET", "/api/v0/equity/account/summary", {"id": 123})

    def report(self, status="Finished", report_id=77, link=None):
        return {
            "reportId": report_id, "status": status,
            "timeFrom": "2024-01-01T00:00:00Z",
            "timeTo": "2024-12-31T23:59:59Z",
            "dataIncluded": {
                "includeOrders": True, "includeDividends": True,
                "includeInterest": True, "includeTransactions": True,
            },
            "downloadLink": self.URL if link is None else link,
        }

    def ready_to_download(self, *, link=None):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report(link=link)])

    def assert_safe_failure(self, operation, pattern):
        with self.assertLogs(self.logger, level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, pattern) as raised:
                operation()
        output = "\n".join(logs.output) + "".join(traceback.format_exception(raised.exception))
        for sensitive in ("test-key", "test-secret", "signed-test-token"):
            self.assertNotIn(sensitive, output)
        return raised.exception

    def assert_no_files(self):
        self.assertEqual(list(self.directory.iterdir()), [])


class TestTrading212CSVReports(_CSVReportFixture):
    def test_finished_report_uses_broker_millisecond_precision_without_changing_request(self):
        end = self.end.replace(microsecond=999999)
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, {"reportId": 77})
        self.api.request_csv_report(self.start, end)
        self.assertEqual(json.loads(self.requests[-1]["body"])["timeTo"], "2024-12-31T23:59:59.999999Z")
        report = self.report()
        report.update(timeFrom="2024-01-01T00:00:00.000Z", timeTo="2024-12-31T23:59:59.999Z")
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [report])
        self.assertEqual(self.api.wait_for_csv_report(77), self.URL)
        self.assertEqual(sum(request["method"] == "POST" for request in self.requests), 1)

    def test_millisecond_precision_does_not_accept_other_milliseconds_or_precise_mismatches(self):
        payload = {
            "timeFrom": "2024-01-01T00:00:00Z", "timeTo": "2024-12-31T23:59:59.999999Z",
            "dataIncluded": self.api._history_content(),
        }
        for end in ("2024-12-31T23:59:59.998Z", "2024-12-31T23:59:59.999998Z", "2025-01-01T00:00:00Z"):
            with self.subTest(end=end):
                report = self.report()
                report["timeTo"] = end
                self.assertFalse(self.api._report_matches(report, payload))

    def test_lost_post_response_recovers_millisecond_metadata_without_reposting(self):
        report = self.report()
        report["timeTo"] = "2024-12-31T23:59:59.999Z"
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, None, error=TimeoutError("synthetic transport failure"))
        self.queue("GET", self.api._EXPORT_PATH, [report])
        self.assertEqual(self.api.request_csv_report(self.start, self.end.replace(microsecond=999999)), 77)
        self.assertEqual(sum(request["method"] == "POST" for request in self.requests), 1)

    def test_request_wait_and_download_preserve_original_csv_without_credentials(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", {"reportId": 77})
        self.assertEqual(self.api.request_csv_report(self.start, self.end), 77)
        payload = json.loads(self.requests[-1]["body"])
        self.assertEqual(payload["timeFrom"], "2024-01-01T00:00:00Z")
        self.assertEqual(payload["timeTo"], "2024-12-31T23:59:59Z")
        self.assertTrue(all(payload["dataIncluded"].values()))
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", self.CSV,
                   host=self.HOST, headers={"Content-Length": str(len(self.CSV))})
        destination = self.directory / "report.csv"
        self.assertEqual(self.api.download_csv_report(77, destination), destination)
        self.assertEqual(destination.read_bytes(), self.CSV)
        self.assertEqual(list(self.directory.iterdir()), [destination])
        downloaded = self.requests[-1]
        self.assertNotIn("Authorization", downloaded["headers"])
        self.assertEqual(downloaded["method"], "GET")
        polls = [r for r in self.requests if r["path"] == "/api/v0/equity/history/exports" and r["method"] == "GET"]
        self.assertGreaterEqual(polls[1]["time"] - polls[0]["time"], 60)

    def test_wait_handles_all_pending_states_with_minute_polling_and_timeout(self):
        self.account()
        for state in ("Queued", "Processing", "Running", "Finished"):
            self.queue("GET", "/api/v0/equity/history/exports", [self.report(state)])
        self.assertEqual(self.api.wait_for_csv_report(77), self.URL)
        polls = [r["time"] for r in self.requests if r["path"] == "/api/v0/equity/history/exports"]
        self.assertTrue(all(right - left >= 60 for left, right in zip(polls, polls[1:])))
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report("Processing")])
        with self.assertLogs(self.logger, level="ERROR"):
            with self.assertRaises(TimeoutError):
                self.api.wait_for_csv_report(77, wait_timeout=30)

    def test_deadline_is_checked_between_incoming_response_chunks(self):
        self.queue("GET", "/api/v0/equity/account/summary", {"id": 123},
                   on_read=lambda: self.advance(11))
        with self.assertLogs(self.logger, level="ERROR"):
            with self.assertRaises(TimeoutError):
                self.api.list_csv_reports(wait_timeout=10)
        self.assertEqual(len(self.requests), 1)
        self.assertLessEqual(self.requests[0]["timeout"], 10)

    def test_truncated_json_transport_is_retried_instead_of_accepted(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [],
                   headers={"Content-Length": "100"})
        self.queue("GET", "/api/v0/equity/history/exports", [],
                   headers={"Content-Length": "2"})
        self.assertEqual(self.api.list_csv_reports(), [])
        self.assertEqual(len(self.requests), 3)
        self.assertGreaterEqual(self.requests[-1]["time"] - self.requests[-2]["time"], 60)

    def test_terminal_unknown_and_malformed_report_responses_fail(self):
        cases = [
            [self.report("Failed")], [self.report("Canceled")], [self.report("Unexpected")],
            {"items": []}, [{"reportId": True}], [self.report(), self.report()], b"test-secret",
        ]
        for data in cases:
            with self.subTest(data_type=type(data).__name__):
                self.account()
                self.queue("GET", "/api/v0/equity/history/exports", data)
                self.assert_safe_failure(lambda: self.api.wait_for_csv_report(77), "Trading212")

    def test_rate_limits_use_reset_and_retry_after_headers(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", None, status=429,
                   headers={"x-ratelimit-reset": "1000000090", "x-ratelimit-remaining": "0"})
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.assertEqual(self.api.list_csv_reports(), [])
        self.assertEqual(self.requests[-1]["time"], 90)
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", None, status=503,
                   headers={"Retry-After": "120"})
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.assertEqual(self.api.list_csv_reports(), [])
        self.assertEqual(self.requests[-1]["time"], 270)
        self.account()
        for _ in range(3):
            self.queue("GET", "/api/v0/equity/history/exports", None, status=503)
        before = len(self.requests)
        self.assert_safe_failure(self.api.list_csv_reports, "HTTP 503")
        polls = [r["time"] for r in self.requests[before:] if r["path"] == "/api/v0/equity/history/exports"]
        self.assertEqual(len(polls), 3)
        self.assertTrue(all(b - a >= 60 for a, b in zip(polls, polls[1:])))

    def test_rejected_post_is_not_retried_and_429_retries_are_bounded(self):
        for status in (400, 401, 403, 302, 429):
            with self.subTest(status=status):
                self.account()
                self.queue("GET", "/api/v0/equity/history/exports", [])
                for _ in range(3 if status == 429 else 1):
                    self.queue("POST", "/api/v0/equity/history/exports", None, status=status)
                before = len(self.requests)
                self.assert_safe_failure(
                    lambda: self.api.request_csv_report(self.start, self.end), "Trading212",
                )
                posts = [r["time"] for r in self.requests[before:] if r["method"] == "POST"]
                self.assertEqual(len(posts), 3 if status == 429 else 1)
                self.assertTrue(all(b - a >= 30 for a, b in zip(posts, posts[1:])))

    def test_lost_post_response_recovers_only_new_exact_report_without_reposting(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report(report_id=76)])
        self.queue("POST", "/api/v0/equity/history/exports", None, error=TimeoutError("test-secret"))
        self.queue("GET", "/api/v0/equity/history/exports",
                   [self.report(report_id=76), self.report(report_id=77)])
        self.assertEqual(self.api.request_csv_report(self.start, self.end), 77)
        self.assertEqual(sum(r["method"] == "POST" for r in self.requests), 1)

    def test_uncertain_creation_rechecks_on_same_instance_without_another_post(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", None, status=408)
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.assert_safe_failure(
            lambda: self.api.request_csv_report(self.start, self.end), "outcome is uncertain",
        )
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report()])
        self.assertEqual(self.api.request_csv_report(self.start, self.end), 77)
        self.assertEqual(sum(r["method"] == "POST" for r in self.requests), 1)

    def test_ambiguous_recovery_and_mismatched_finished_content_are_not_accepted(self):
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", None, status=500)
        self.queue("GET", "/api/v0/equity/history/exports", [self.report(), self.report(report_id=78)])
        self.assert_safe_failure(
            lambda: self.api.request_csv_report(self.start, self.end), "outcome is uncertain",
        )
        self.assertEqual(sum(r["method"] == "POST" for r in self.requests), 1)
        self.api = Trading212API(account_id=123, logger=self.logger)
        self.stack.enter_context(patch.object(self.api, "load_credentials", return_value=("test-key", "test-secret")))
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", {"reportId": 77})
        self.api.request_csv_report(self.start, self.end)
        wrong = self.report()
        wrong["timeFrom"] = "2024-02-01T00:00:00Z"
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [wrong])
        self.assert_safe_failure(lambda: self.api.wait_for_csv_report(77), "does not match")

    def test_cancellation_before_work_and_during_wait_does_not_send_extra_requests(self):
        event = Event()
        event.set()
        with self.assertRaises(InterruptedError):
            self.api.request_csv_report(self.start, self.end, cancel_event=event)
        self.load.assert_not_called()
        cancelled = [False]
        token = Mock(spec=Event)
        token.is_set.side_effect = lambda: cancelled[0]
        token.wait.side_effect = lambda duration: cancelled.__setitem__(0, True)
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report("Processing")])
        with self.assertRaises(InterruptedError):
            self.api.wait_for_csv_report(77, cancel_event=token)
        self.assertEqual(len(self.requests), 2)

    def test_cancelled_post_response_can_be_recovered_without_reposting(self):
        event = Event()
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", {"reportId": 77}, on_read=event.set)
        with self.assertRaises(InterruptedError):
            self.api.request_csv_report(self.start, self.end, cancel_event=event)
        event.clear()
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [self.report()])
        self.assertEqual(self.api.request_csv_report(self.start, self.end), 77)
        self.assertEqual(sum(r["method"] == "POST" for r in self.requests), 1)

    def test_cancelled_post_rate_wait_does_not_leave_an_unsent_uncertain_request(self):
        cancelled = [False]
        token = Mock(spec=Event)
        token.is_set.side_effect = lambda: cancelled[0]
        token.wait.side_effect = lambda _duration: cancelled.__setitem__(0, True)
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", None, status=429)
        with self.assertRaises(InterruptedError):
            self.api.request_csv_report(self.start, self.end, cancel_event=token)
        self.account()
        self.queue("GET", "/api/v0/equity/history/exports", [])
        self.queue("POST", "/api/v0/equity/history/exports", {"reportId": 77})
        self.assertEqual(self.api.request_csv_report(self.start, self.end), 77)
        self.assertEqual(sum(r["method"] == "POST" for r in self.requests), 2)

    def test_cancelled_transfer_preserves_cancellation_and_removes_temporary_file(self):
        event = Event()
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", self.CSV,
                   host=self.HOST, on_read=event.set)
        with self.assertRaises(InterruptedError):
            self.api.download_csv_report(77, self.directory / "report.csv", cancel_event=event)
        self.assertEqual(sum(r["host"] == self.HOST for r in self.requests), 1)
        self.assert_no_files()

    def test_download_retries_incomplete_transfer_and_keeps_no_partial_output(self):
        self.ready_to_download()
        for _ in range(3):
            self.queue("GET", "/history.csv?token=signed-test-token", self.CSV,
                       host=self.HOST, headers={"Content-Length": str(len(self.CSV) + 1)})
        self.assert_safe_failure(
            lambda: self.api.download_csv_report(77, self.directory / "report.csv"),
            "complete Trading212 CSV",
        )
        self.assertEqual(sum(r["host"] == self.HOST for r in self.requests), 3)
        self.assert_no_files()

    def test_empty_report_and_exact_size_boundary_are_valid_csv(self):
        content = self.CSV.split(b"\r\n")[0] + b"\r\n"
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", content, host=self.HOST)
        destination = self.directory / "empty.csv"
        with patch.object(self.api, "_MAX_CSV_BYTES", len(content)):
            self.api.download_csv_report(77, destination)
        self.assertEqual(destination.read_bytes(), content)

    def test_invalid_csv_or_size_limit_never_publishes_a_file(self):
        for content in (
            b"<html>test-secret</html>", b"", b"Action,Time (UTC),ID,Total,Currency (Total)\n"
            b'Interest on cash,"unterminated,cash-1,1,CZK',
        ):
            with self.subTest(length=len(content)):
                self.ready_to_download()
                self.queue("GET", "/history.csv?token=signed-test-token", content, host=self.HOST)
                self.assert_safe_failure(
                    lambda: self.api.download_csv_report(77, self.directory / "report.csv"),
                    "CSV|report",
                )
                self.assert_no_files()
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", self.CSV, host=self.HOST)
        with patch.object(self.api, "_MAX_CSV_BYTES", len(self.CSV) - 1):
            self.assert_safe_failure(
                lambda: self.api.download_csv_report(77, self.directory / "report.csv"), "size limit",
            )
        self.assert_no_files()

    def test_download_redirects_are_checked_and_never_receive_authorization(self):
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", b"", host=self.HOST,
                   status=302, headers={"Location": "/final.csv"})
        self.queue("GET", "/final.csv", self.CSV, host=self.HOST)
        destination = self.directory / "report.csv"
        self.api.download_csv_report(77, destination)
        for request in self.requests:
            if request["host"] == self.HOST:
                self.assertNotIn("Authorization", request["headers"])
        for link in (
            "http://reports.s3.eu-west-1.amazonaws.com/report.csv",
            "https://127.0.0.1/report.csv", "https://evil.example/report.csv",
            "https://live.trading212.com.evil.example/report.csv",
            "https://user:test-secret@live.trading212.com/report.csv",
        ):
            with self.subTest(link_type=link.split(":")[0]):
                self.ready_to_download(link=link)
                self.assert_safe_failure(
                    lambda: self.api.download_csv_report(77, self.directory / "unsafe.csv"),
                    "approved HTTPS",
                )
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", b"", host=self.HOST,
                   status=302, headers={"Location": "https://evil.example/?token=signed-test-token"})
        self.assert_safe_failure(
            lambda: self.api.download_csv_report(77, self.directory / "unsafe.csv"),
            "approved HTTPS",
        )
        self.assertFalse((self.directory / "unsafe.csv").exists())
        self.assertFalse(list(self.directory.glob("*.part")))
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", b"", host=self.HOST,
                   status=302, headers={"Location": "/loop.csv"})
        for _ in range(3):
            self.queue("GET", "/loop.csv", b"", host=self.HOST,
                       status=302, headers={"Location": "/loop.csv"})
        before = len(self.requests)
        self.assert_safe_failure(
            lambda: self.api.download_csv_report(77, self.directory / "unsafe.csv"),
            "excessive redirects",
        )
        self.assertEqual(sum(r["host"] == self.HOST for r in self.requests[before:]), 4)
        self.assertFalse((self.directory / "unsafe.csv").exists())
        self.assertFalse(list(self.directory.glob("*.part")))

    def test_existing_destination_and_disk_errors_are_explicit_and_preserve_files(self):
        destination = self.directory / "report.csv"
        destination.write_bytes(b"original")
        self.assert_safe_failure(lambda: self.api.download_csv_report(77, destination), "already exists")
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertFalse(self.requests)
        self.ready_to_download()
        with patch("tradingtools.trading212_api.tempfile.mkstemp", side_effect=PermissionError("test-secret")):
            self.assert_safe_failure(
                lambda: self.api.download_csv_report(77, self.directory / "new.csv"), "publish",
            )
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.directory.iterdir()), [destination])

    def test_temporary_file_write_error_is_not_retried_as_a_network_failure(self):
        self.ready_to_download()
        self.queue("GET", "/history.csv?token=signed-test-token", self.CSV, host=self.HOST)
        original_open = Path.open

        def fail_write(path, *args, **kwargs):
            if args and args[0] == "wb":
                raise PermissionError("test-secret")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", new=fail_write):
            self.assert_safe_failure(
                lambda: self.api.download_csv_report(77, self.directory / "report.csv"),
                "write the temporary",
            )
        self.assertEqual(sum(r["host"] == self.HOST for r in self.requests), 1)
        self.assert_no_files()

    def test_invalid_intervals_ids_and_unapproved_operations_never_send_requests(self):
        with self.assertRaises(ValueError):
            self.api.request_csv_report(self.end, self.start)
        with self.assertRaises(ValueError):
            self.api.request_csv_report(datetime(2024, 1, 1), self.end)
        with self.assertRaises(ValueError):
            self.api.wait_for_csv_report(True)
        with self.assertRaises(ValueError):
            self.api.wait_for_csv_report(77, wait_timeout=float("inf"))
        for method, path in (
            ("DELETE", "/api/v0/equity/orders/77"),
            ("POST", "/api/v0/equity/account/summary"),
        ):
            with self.subTest(method=method):
                with self.assertRaises(ValueError):
                    self.api._api_exchange(method, path)
        self.assertFalse(self.requests)


@unittest.skipUnless(sys.platform == "win32", "Windows archive file locking required")
class TestTrading212AnnualArchive(_CSVReportFixture):
    NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)
    ZONE = ZoneInfo("Europe/Prague")
    HEADER = b"\xef\xbb\xbfAction,Time (UTC),ID,Total,Currency (Total)\r\n"

    @property
    def root(self):
        return self.directory.resolve() / "Trading212" / "live" / "123"

    def metadata(self):
        return json.loads((self.root / "archive.json").read_text(encoding="utf-8"))

    def annual_report(self, year, now, report_id=77):
        report = self.report(report_id=report_id)
        start = datetime(year, 1, 1, tzinfo=self.ZONE).astimezone(timezone.utc)
        end = (
            datetime(year + 1, 1, 1, tzinfo=self.ZONE).astimezone(timezone.utc)
            - timedelta(microseconds=1)
            if year < now.astimezone(self.ZONE).year else now.astimezone(timezone.utc)
        )
        report.update(timeFrom=start.isoformat().replace("+00:00", "Z"),
                      timeTo=end.isoformat().replace("+00:00", "Z"))
        return report

    def annual_csv(self, year, *, amount="1.23", timestamp=None):
        if timestamp is None:
            timestamp = datetime(year, 1, 1, tzinfo=self.ZONE).astimezone(timezone.utc).isoformat(" ")
        return self.HEADER + f"Interest on cash,{timestamp},cash-1,{amount},CZK\r\n".encode()

    def queue_download(self, report, content, *, on_read=None):
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [report])
        self.queue("GET", "/history.csv?token=signed-test-token", content, host=self.HOST,
                   headers={"Content-Length": str(len(content))}, on_read=on_read)

    def queue_year(self, year, now, report_id, content=None, *, on_post=None, on_read=None):
        report = self.annual_report(year, now, report_id)
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, {"reportId": report_id}, on_request=on_post)
        self.queue_download(report, self.annual_csv(year) if content is None else content, on_read=on_read)
        return report

    def restart(self):
        self.api = Trading212API(account_id=123, logger=self.logger)
        self.load = self.stack.enter_context(patch.object(
            self.api, "load_credentials", return_value=("test-key", "test-secret"),
        ))

    def posts(self):
        return [request for request in self.requests if request["method"] == "POST"]

    def test_first_run_leap_year_prague_boundaries_and_original_bytes(self):
        content = self.annual_csv(2024, timestamp="2024-02-29 12:00:00+00:00")
        content += b"Dividend adjustment,2024-12-31 22:59:59.999999+00:00,adjustment-1,0.02,CZK\r\n"
        self.queue_year(2024, self.NOW, 77, content)
        self.queue_year(2025, self.NOW, 78)
        paths = self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW)
        self.assertEqual([path.parent.name for path in paths], ["2024", "2025"])
        self.assertEqual(paths[0].read_bytes(), content)
        payload = json.loads(self.posts()[0]["body"])
        self.assertEqual(payload["timeFrom"], "2023-12-31T23:00:00Z")
        self.assertEqual(payload["timeTo"], "2024-12-31T22:59:59.999999Z")
        self.assertTrue(all(payload["dataIncluded"].values()))
        state = self.metadata()
        self.assertEqual(state["timezone"], "Europe/Prague")
        self.assertEqual([entry["complete"] for entry in state["reports"]], [True, False])
        self.assertEqual(state["reports"][0]["sha256"], hashlib.sha256(content).hexdigest())
        serialized = json.dumps(state)
        for secret in ("test-key", "test-secret", "signed-test-token", "downloadLink", "Authorization"):
            self.assertNotIn(secret, serialized)
        self.assertFalse(list(self.root.glob("*/*.part")))
        polls = [request["time"] for request in self.requests
                 if request["method"] == "GET" and request["path"] == self.api._EXPORT_PATH]
        self.assertTrue(all(right - left >= 60 for left, right in zip(polls, polls[1:])))
        self.load.reset_mock()
        self.assertEqual(self.api.get_archived_csvs(self.directory), paths)
        self.load.assert_not_called()

    def test_report_callback_runs_after_durable_publication_and_failure_never_reposts(self):
        self.queue_year(2024, self.NOW, 77)
        self.queue_year(2025, self.NOW, 78)
        notifications = []

        def imported(report):
            notifications.append(report)
            self.assertTrue(report.path.exists())
            state = self.metadata()
            self.assertIsNone(state["pending"])
            self.assertEqual(state["recommended"][str(report.year)], report.report_id)
            self.assertEqual(hashlib.sha256(report.path.read_bytes()).hexdigest(), report.sha256)
            raise RuntimeError("Synthetic database failure")

        with self.assertRaisesRegex(RuntimeError, "Synthetic database failure"):
            self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW, on_report=imported)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual([report.year for report in notifications], [2024])
        self.assertIsNone(self.api._archive_state)
        self.restart()
        descriptors = []
        self.api.get_archived_csvs(self.directory, on_report=descriptors.append)
        self.assertEqual(descriptors, notifications)
        self.load.assert_not_called()
        self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW, on_report=descriptors.append)
        self.assertEqual(len(self.posts()), 2)
        self.assertEqual([report.year for report in descriptors], [2024, 2024, 2025])
        self.assertFalse(self.responses)

    def test_missing_year_normal_refresh_identical_bytes_and_changed_old_revision(self):
        self.queue_year(2024, self.NOW, 77)
        self.queue_year(2025, self.NOW, 78)
        original = self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW)
        later = self.NOW + timedelta(days=1)
        self.queue_year(2023, later, 79)
        self.queue_year(2025, later, 80)
        paths = self.api.sync_yearly_csv(self.directory, 2023, as_of=later)
        self.assertEqual(paths[1:], original)
        self.assertEqual(len(list(self.root.glob("*/*.csv"))), 3)
        self.queue_year(2023, later, 81, self.annual_csv(2023, amount="2.34"))
        self.queue_year(2025, later, 82)
        refreshed = self.api.sync_yearly_csv(self.directory, 2023, as_of=later, refresh_years=(2023,))
        self.assertNotEqual(refreshed[0], paths[0])
        self.assertTrue(paths[0].exists())
        self.assertEqual(refreshed[1:], original)
        self.assertEqual(len(list(self.root.glob("*/*.csv"))), 4)
        self.assertEqual(self.metadata()["recommended"], {"2023": 81, "2024": 77, "2025": 82})
        with patch.object(self.api, "_validate_archive_csv", wraps=self.api._validate_archive_csv) as validate:
            self.assertEqual(self.api.get_archived_csvs(self.directory), refreshed)
        self.assertEqual(validate.call_count, 4)
        self.assertFalse(self.responses)

    def test_rollover_uses_local_year_finalizes_partial_and_has_seven_day_overlap(self):
        before = datetime(2024, 12, 31, 22, 30, tzinfo=timezone.utc)
        self.queue_year(2024, before, 77)
        original = self.api.sync_yearly_csv(self.directory, 2024, as_of=before)[0]
        after = datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc)
        self.queue_year(2024, after, 78)
        self.queue_year(2025, after, 79)
        paths = self.api.sync_yearly_csv(self.directory, 2024, as_of=after)
        self.assertEqual(paths[0], original)
        self.assertTrue(self.api._recommended_reports(self.metadata())[2024]["complete"])
        inside = datetime(2025, 1, 7, 22, 59, 59, tzinfo=timezone.utc)
        self.queue_year(2024, inside, 80)
        self.queue_year(2025, inside, 81)
        self.api.sync_yearly_csv(self.directory, 2024, as_of=inside)
        outside = datetime(2025, 1, 7, 23, tzinfo=timezone.utc)
        self.queue_year(2025, outside, 82)
        self.api.sync_yearly_csv(self.directory, 2024, as_of=outside)
        self.assertEqual(len(self.posts()), 6)
        self.assertEqual(len(list(self.root.glob("*/*.csv"))), 2)
        self.assertFalse(self.responses)

    def test_empty_report_valid_but_out_of_range_or_naive_timestamps_never_publish(self):
        self.queue_year(2025, self.NOW, 77, self.HEADER)
        paths = self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(paths[0].read_bytes(), self.HEADER)
        for timestamp in ("2024-12-31 22:59:59+00:00", "2025-01-01 00:00:00"):
            with self.subTest(timestamp=timestamp):
                report_id = 78 + len(self.posts())
                self.queue_year(2025, self.NOW, report_id, self.annual_csv(2025, timestamp=timestamp))
                self.assert_safe_failure(
                    lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "timestamps",
                )
                self.assertEqual(len(list(self.root.glob("*/*.csv"))), 1)
                self.assertFalse(list(self.root.glob("*/*.part")))
                self.root.joinpath("archive.json").write_text(
                    json.dumps({**self.metadata(), "pending": None}), encoding="utf-8",
                )

    def test_tampered_hash_identity_schema_coverage_and_paths_fail_before_network(self):
        self.queue_year(2025, self.NOW, 77)
        path = self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)[0]
        original = self.metadata()
        for field, value in (("account_id", 124), ("environment", "demo"), ("timezone", "UTC"),
                             ("version", 2), ("api_secret", "test-secret")):
            with self.subTest(field=field):
                changed = {**original, field: value}
                (self.root / "archive.json").write_text(json.dumps(changed), encoding="utf-8")
                self.assert_safe_failure(lambda: self.api.get_archived_csvs(self.directory), "invalid")
        for field, value in (("complete", True), ("file", "..\\outside.csv"),
                             ("file", "C:\\outside.csv"), ("sha256", "0" * 64)):
            with self.subTest(field=field, value=value):
                changed = json.loads(json.dumps(original))
                changed["reports"][0][field] = value
                (self.root / "archive.json").write_text(json.dumps(changed), encoding="utf-8")
                self.assert_safe_failure(lambda: self.api.get_archived_csvs(self.directory),
                                         "invalid|unsafe|SHA-256")
        (self.root / "archive.json").write_text(json.dumps(original), encoding="utf-8")
        path.write_bytes(self.annual_csv(2025, amount="9.99"))
        self.assert_safe_failure(lambda: self.api.get_archived_csvs(self.directory), "SHA-256")
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(self.responses)

    def test_crash_after_csv_or_validated_partial_is_recovered_offline(self):
        self.queue_year(2025, self.NOW, 77)
        with patch.object(self.api, "_finish_archive_report", side_effect=OSError("test-secret")):
            self.assert_safe_failure(
                lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "archive",
            )
        pending = self.metadata()["pending"]
        final = self.root / pending["file"]
        self.assertTrue(final.exists())
        final.rename(self.root / pending["temporary"])
        self.restart()
        paths = self.api.get_archived_csvs(self.directory)
        self.assertEqual(paths, [final])
        self.load.assert_not_called()
        self.assertIsNone(self.metadata()["pending"])
        self.assertFalse(list(self.root.glob("*/*.part")))
        self.assertEqual(len(self.posts()), 1)

    def test_crash_after_publication_before_metadata_recovers_known_report_without_post(self):
        self.queue_year(2025, self.NOW, 77)
        original_replace = os.replace

        def fail_commit(source, destination):
            state = self.api._archive_state
            self.assertIsNotNone(state)
            if state is not None and state["pending"] is None:
                raise OSError("test-secret")
            return original_replace(source, destination)

        with patch("tradingtools.trading212_api.os.replace", side_effect=fail_commit):
            self.assert_safe_failure(
                lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "persist",
            )
        self.assertTrue((self.root / self.metadata()["pending"]["file"]).exists())
        self.assertFalse(list(self.root.glob(".archive-*.tmp")))
        self.restart()
        paths = self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(self.posts()), 1)
        self.load.assert_not_called()

    def test_uncertain_post_checkpoint_survives_restart_and_excludes_old_matching_id(self):
        report = self.annual_report(2025, self.NOW, 77)
        old = {**report, "reportId": 76}
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [old])

        def assert_checkpoint():
            pending = self.metadata()["pending"]
            self.assertEqual(pending["state"], "uncertain")
            self.assertEqual(pending["baselineIds"], [76])
            self.assertIsNone(pending["reportId"])
            self.assertNotIn("signed-test-token", json.dumps(pending))

        self.queue("POST", self.api._EXPORT_PATH, None, error=ConnectionError("test-secret"),
                   on_request=assert_checkpoint)
        self.queue("GET", self.api._EXPORT_PATH, [old])
        self.assert_safe_failure(
            lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "uncertain",
        )
        self.restart()
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [old, report])
        self.queue_download(report, self.annual_csv(2025))
        self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.metadata()["reports"][0]["reportId"], 77)

    def test_unresolved_restart_never_creates_a_second_report(self):
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, None, error=ConnectionError("test-secret"))
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.assert_safe_failure(
            lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "uncertain",
        )
        self.restart()
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.assert_safe_failure(
            lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "uncertain",
        )
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.metadata()["pending"]["state"], "uncertain")

    def test_disk_failure_before_dispatch_is_safe_to_retry_after_restart(self):
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        original_replace = os.replace

        def fail_intent(source, destination):
            state = self.api._archive_state
            self.assertIsNotNone(state)
            pending = None if state is None else state["pending"]
            if pending is not None and pending["state"] == "uncertain":
                raise OSError("test-secret")
            return original_replace(source, destination)

        with patch("tradingtools.trading212_api.os.replace", side_effect=fail_intent):
            self.assert_safe_failure(
                lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "persist",
            )
        self.assertFalse(self.posts())
        self.assertIsNone(self.api._pending_creation)
        self.assertEqual(self.metadata()["pending"]["state"], "prepared")
        self.restart()
        self.queue_year(2025, self.NOW, 77)
        self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(self.posts()), 1)

    def test_cancelled_download_keeps_identity_and_resumes_without_post(self):
        cancelled = Event()
        report = self.queue_year(2025, self.NOW, 77, on_read=cancelled.set)
        with patch.object(cancelled, "wait", side_effect=self.advance):
            with self.assertRaises(InterruptedError):
                self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW, cancel_event=cancelled)
        self.assertEqual(self.metadata()["pending"]["reportId"], 77)
        self.assertFalse(list(self.root.glob("*/*.csv")))
        self.assertFalse(list(self.root.glob("*/*.part")))
        self.restart()
        with self.assertLogs(self.logger, level="WARNING") as logs:
            self.assertEqual(self.api.get_archived_csvs(self.directory), [])
        self.assertIn("only committed CSVs", "".join(logs.output))
        self.load.assert_not_called()
        self.queue_download(report, self.annual_csv(2025))
        self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(self.posts()), 1)

    def test_restart_resumes_existing_microsecond_request_with_millisecond_metadata(self):
        report = self.annual_report(2024, self.NOW, 77)
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, {"reportId": 77})
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [{**report, "timeTo": "2024-12-31T22:59:59.998Z"}])
        self.assert_safe_failure(
            lambda: self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW),
            "does not match",
        )
        self.assertEqual(self.metadata()["pending"]["reportId"], 77)
        self.restart()
        self.queue_download({**report, "timeTo": "2024-12-31T22:59:59.999Z"}, self.annual_csv(2024))
        self.queue_year(2025, self.NOW, 78)
        paths = self.api.sync_yearly_csv(self.directory, 2024, as_of=self.NOW)
        self.assertEqual(len(paths), 2)
        self.assertEqual(len(self.posts()), 2)
        self.assertIsNone(self.metadata()["pending"])

    def test_confirmed_remote_failure_allows_new_report_only_on_next_run(self):
        failed = self.annual_report(2025, self.NOW, 77)
        failed["status"] = "Failed"
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, {"reportId": 77})
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [failed])
        self.assert_safe_failure(
            lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "Failed",
        )
        self.assertEqual(self.metadata()["pending"]["state"], "failed")
        self.restart()
        self.queue_year(2025, self.NOW, 78)
        self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(self.posts()), 2)

    def test_year_deadline_keeps_known_identity_for_the_next_run(self):
        report = self.annual_report(2025, self.NOW, 77)
        self.account()
        self.queue("GET", self.api._EXPORT_PATH, [])
        self.queue("POST", self.api._EXPORT_PATH, {"reportId": 77})
        self.account()
        with self.assertLogs(self.logger, level="ERROR"):
            with self.assertRaises(TimeoutError):
                self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW, wait_timeout=60)
        self.assertEqual(self.clock, 60)
        self.assertEqual(self.metadata()["pending"]["reportId"], 77)
        self.assertFalse(list(self.root.glob("*/*.csv")))
        self.restart()
        self.queue_download(report, self.annual_csv(2025))
        self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW)
        self.assertEqual(len(self.posts()), 1)

    def test_invalid_years_and_concurrent_writer_never_send_requests(self):
        for first, refresh, now in (
            (True, (), self.NOW), (0, (), self.NOW), (1, (), self.NOW), (2026, (), self.NOW),
            (2024, (2023,), self.NOW), (2024, (True,), self.NOW),
            (2024, (), datetime(2025, 1, 1)),
        ):
            with self.subTest(first=first, refresh=refresh):
                with self.assertRaises(ValueError):
                    self.api.sync_yearly_csv(self.directory, first, as_of=now, refresh_years=refresh)
        self.assertFalse(self.requests)
        self.assertFalse(self.root.exists())
        with self.api._lock_archive(self.root):
            self.assert_safe_failure(
                lambda: self.api.sync_yearly_csv(self.directory, 2025, as_of=self.NOW), "in use",
            )
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
