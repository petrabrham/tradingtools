import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import pandas as pd

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.trading212_api import ArchivedCSV
from tradingtools.trading212_sync import Trading212Connection, Trading212Sync, load_connection, save_connection


class TestTrading212Sync(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "history.db"
        logger = patch("tradingtools.db.dbmanager.setup_logger", return_value=Mock())
        logger.start()
        self.addCleanup(logger.stop)
        self.database = DatabaseManager()
        self.database.create_database(str(self.path))
        self.addCleanup(self.database.close)
        self.binding = Trading212Connection("demo", 123, str(self.directory / "archive"), 2020)
        save_connection(self.database, self.binding)
        rate = patch.object(DatabaseManager, "get_exchange_rate", return_value=2.0)
        self.rate = rate.start()
        self.addCleanup(rate.stop)
        self.api = Mock()
        self.api.verify_account.return_value = 123
        self.factory = Mock(return_value=self.api)
        self.archived = []
        self.published = []
        self.api.get_archived_csvs.side_effect = lambda *a, **kw: self.deliver(self.archived, kw["on_report"])
        self.api.sync_yearly_csv.side_effect = lambda *a, **kw: self.deliver(self.published, kw["on_report"])

    @property
    def conn(self):
        assert self.database.conn is not None
        return self.database.conn

    @staticmethod
    def deliver(reports, callback):
        for report in reports:
            callback(report)
        return [report.path for report in reports]

    @staticmethod
    def row(identifier, total=2, year=2020):
        return {
            "Action": "Interest on cash", "Time (UTC)": f"{year}-06-01 12:00:00+00:00",
            "ID": identifier, "Total": total, "Currency (Total)": "USD", "Notes": "Interest on cash",
        }

    def report(self, year, rows):
        path = self.directory / f"{year}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return ArchivedCSV(year, path, hashlib.sha256(path.read_bytes()).hexdigest(), year, True)

    @staticmethod
    def key(report):
        return f"trading212.import.{report.year}.{report.sha256}"

    def run_sync(self, **kwargs):
        return Trading212Sync(str(self.path), self.binding, api_factory=self.factory, **kwargs).run()

    def test_connection_roundtrip_rejects_rebinding_and_malformed_settings_without_schema_change(self):
        self.assertEqual(load_connection(self.database), self.binding)
        self.assertEqual(self.database.get_db_version(), 2)
        with self.assertRaisesRegex(ValueError, "already bound"):
            save_connection(self.database, Trading212Connection("live", 123, self.binding.archive_directory, 2020))
        with self.assertRaisesRegex(ValueError, "already bound"):
            save_connection(self.database, Trading212Connection("demo", 456, self.binding.archive_directory, 2020))
        for changes in ({"account_id": True}, {"first_year": True}, {"archive_directory": ""},
                        {"version": True}, {"timezone": "UTC"}, {"environment": "invalid"}):
            with self.subTest(changes=changes):
                save_connection(self.database, self.binding)
                data = json.loads(self.database.get_setting("trading212.connection"))
                data.update(changes)
                self.database.set_setting("trading212.connection", json.dumps(data))
                with self.assertRaises(ValueError):
                    load_connection(self.database)
                self.database.set_setting("trading212.connection", "")

    def test_success_skip_unchanged_and_explicit_refresh_reimports_same_hash(self):
        report = self.report(2020, [self.row("one")])
        self.archived = [report]
        self.published = [report]
        first = self.run_sync()
        self.assertEqual(first.status, "complete")
        self.assertEqual(len(first.reports), 1)
        self.assertEqual(first.reports[0].counts["interest"], 1)
        self.assertIn("interest: 1 / 1", first.summary())
        state = json.loads(self.database.get_setting(self.key(report)))
        self.assertEqual(state["status"], "complete")
        self.assertIn("attempted_at", state)
        self.assertIn("completed_at", state)
        self.rate.reset_mock()
        second = self.run_sync()
        self.assertEqual(second.reports[0].status, "already imported")
        self.assertEqual(second.reports[0].counts, {})
        refreshed = self.run_sync(refresh_years=(2020,))
        self.assertEqual(refreshed.reports[0].status, "complete")
        self.assertEqual(refreshed.reports[0].counts["duplicates"], 1)
        self.assertEqual(refreshed.reports[0].counts["interest"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)
        self.rate.assert_not_called()

    def test_finalization_updates_archive_coverage_without_reimporting_identical_bytes(self):
        report = self.report(2020, [self.row("one")])
        self.archived = [replace(report, complete=False)]
        self.published = [report]
        result = self.run_sync()
        self.assertTrue(result.reports[0].report.complete)
        self.assertIn("full year", result.summary())
        self.assertEqual(self.rate.call_count, 1)
        result = self.run_sync()
        self.assertTrue(result.reports[0].report.complete)
        self.assertEqual(result.reports[0].status, "already imported")

    def test_conflict_retains_original_values_and_continues_next_year_in_memory_only(self):
        original = self.row("same", 2)
        self.database.import_dataframe(pd.DataFrame([original]))
        self.rate.reset_mock()
        self.archived = [
            self.report(2020, [self.row("same", 3)]),
            self.report(2021, [self.row("new", 4, 2021)]),
        ]
        result = self.run_sync()
        self.assertEqual(result.status, "partial")
        self.assertEqual([report.status for report in result.reports], ["partial", "complete"])
        self.assertEqual(len(result.comparisons), 1)
        comparison = result.comparisons[0]
        self.assertEqual((comparison.year, comparison.row), (2020, 1))
        self.assertEqual(comparison.incoming["Total"], 3)
        self.assertEqual(comparison.source["Total"], 3)
        self.assertEqual(comparison.candidates[0].source["Total"], 2)
        self.assertEqual(comparison.candidates[0].stored["total_czk"], 4)
        self.assertEqual(self.conn.execute("SELECT total_czk FROM interests ORDER BY id").fetchall(), [(4.0,), (8.0,)])
        self.assertEqual(self.rate.call_count, 1)

    def test_time_normalization_is_reported_with_backup_and_not_as_conflict(self):
        incoming = self.row("normalize")
        original = {key: value for key, value in incoming.items() if key != "Time (UTC)"}
        original["Time"] = incoming["Time (UTC)"][:-6]
        self.database.import_dataframe(pd.DataFrame([original]))
        before = self.conn.execute("SELECT * FROM interests").fetchall()
        self.archived = [self.report(2020, [incoming])]
        self.rate.reset_mock()
        result = self.run_sync()
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.comparisons, [])
        item = result.reports[0]
        self.assertEqual((item.time_normalized, item.counts["duplicates"], item.conflicts), (1, 1, 0))
        self.assertIn("normalized times: 1", result.summary())
        self.assertIn(str(item.time_backup), result.summary())
        backup = sqlite3.connect(item.time_backup)
        try:
            self.assertEqual(backup.execute("SELECT * FROM interests").fetchall(), before)
        finally:
            backup.close()
        self.assertEqual(json.loads(self.database.get_setting(self.key(item.report)))["time_normalized"], 1)
        self.published = self.archived
        retried = self.run_sync(refresh_years=(2020,)).reports[0]
        self.assertEqual((retried.time_normalized, retried.counts["duplicates"]), (0, 1))
        self.assertIsNone(retried.time_backup)
        self.rate.assert_not_called()
        settings = self.conn.execute("SELECT value FROM settings WHERE key LIKE 'trading212.import.%'").fetchall()
        for (text,) in settings:
            state = json.loads(text)
            self.assertNotIn("same", text)
            self.assertNotIn("candidate", text)
            self.assertNotIn("Total", text)
            self.assertNotIn("errors", state)
        self.assertEqual(self.database.get_db_version(), 2)

    def test_restart_retries_running_partial_cancelled_and_failed_revisions(self):
        for year, status in enumerate(("running", "partial", "cancelled", "failed"), start=2020):
            report = self.report(year, [self.row(f"id-{year}", year=year)])
            self.archived.append(report)
            self.database.set_setting(self.key(report), json.dumps({"version": 1, "status": status}))
        result = self.run_sync()
        self.assertEqual(result.status, "complete")
        self.assertEqual([report.counts["interest"] for report in result.reports], [1, 1, 1, 1])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 4)

    def test_root_cancellation_after_publication_keeps_archive_and_completed_import(self):
        report = self.report(2020, [self.row("one")])
        self.published = [report]
        cancel = Event()

        def publish(*args, **kwargs):
            kwargs["on_report"](report)
            cancel.set()
            raise InterruptedError("Cancelled after publication")

        self.api.sync_yearly_csv.side_effect = publish
        result = self.run_sync(cancel_event=cancel)
        self.assertEqual(result.status, "cancelled")
        self.assertTrue(report.path.exists())
        self.assertEqual(json.loads(self.database.get_setting(self.key(report)))["status"], "complete")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)
        self.archived = [report]
        self.api.sync_yearly_csv.side_effect = lambda *a, **kw: []
        self.assertEqual(self.run_sync().reports[0].status, "already imported")

    def test_fatal_database_failure_stops_and_records_incomplete_not_false_success(self):
        report = self.report(2020, [self.row("one"), self.row("two")])
        self.archived = [report]
        original = DatabaseManager._import_csv_row
        error = sqlite3.OperationalError("Synthetic disk full")
        error.sqlite_errorcode = sqlite3.SQLITE_FULL

        def fail_second(database, row, category, **kwargs):
            if row["ID"] == "two":
                raise error
            return original(database, row, category, **kwargs)

        with patch.object(DatabaseManager, "_import_csv_row", new=fail_second):
            result = self.run_sync()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reports[0].status, "failed")
        self.assertIn("counts unavailable", result.summary())
        self.assertIn("Synthetic disk full", result.error)
        self.api.sync_yearly_csv.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)
        self.assertEqual(json.loads(self.database.get_setting(self.key(report)))["status"], "failed")
        self.assertTrue(report.path.exists())
        retry = self.run_sync()
        self.assertEqual(retry.status, "complete")
        self.assertEqual(retry.reports[0].counts["duplicates"], 1)
        self.assertEqual(retry.reports[0].counts["interest"], 1)

    def test_wrong_account_and_archive_errors_stop_before_import_or_new_exports(self):
        self.api.verify_account.return_value = 456
        result = self.run_sync()
        self.assertEqual(result.status, "failed")
        self.assertIn("account does not match", result.error)
        self.api.get_archived_csvs.assert_not_called()
        self.api.verify_account.return_value = 123
        self.api.get_archived_csvs.side_effect = RuntimeError("Archive hash mismatch")
        result = self.run_sync()
        self.assertEqual(result.status, "failed")
        self.assertIn("Archive hash mismatch", result.error)
        self.api.sync_yearly_csv.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 0)

    def test_unknown_actions_are_partial_and_reported_separately_from_intentional_skips(self):
        self.published = [self.report(2020, [
            {**self.row("unknown"), "Action": "Synthetic unsupported"},
            {**self.row("deposit"), "Action": "Deposit"},
        ])]
        result = self.run_sync()
        self.assertEqual(result.status, "partial")
        self.assertIn("Unsupported: Synthetic unsupported: 1", result.summary())
        self.assertIn("Intentionally skipped: Deposit: 1", result.summary())
        self.assertEqual(result.comparisons, [])

    def test_missing_rates_explain_partial_import_and_retry_uses_the_retained_csv(self):
        self.archived = [self.report(2020, [self.row("one")])]
        self.rate.side_effect = ValueError("Missing annual USD exchange rate for 2020")
        result = self.run_sync()
        self.assertEqual(result.status, "partial")
        self.assertIn("Missing annual USD exchange rate for 2020", result.summary())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 0)
        self.rate.side_effect = None
        self.assertEqual(self.run_sync().status, "complete")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)

    def test_failure_to_persist_completion_is_fatal_but_committed_rows_are_safe_to_retry(self):
        report = self.report(2020, [self.row("one")])
        self.archived = [report]
        original = DatabaseManager.set_setting

        def fail_complete(database, key, value, description=""):
            if key.startswith("trading212.import.") and json.loads(value)["status"] == "complete":
                raise sqlite3.OperationalError("Synthetic import status write failure")
            return original(database, key, value, description)

        with patch.object(DatabaseManager, "set_setting", new=fail_complete):
            result = self.run_sync()
        self.assertEqual(result.status, "failed")
        self.assertIn("Synthetic import status write failure", result.error)
        self.api.sync_yearly_csv.assert_not_called()
        self.assertEqual(json.loads(self.database.get_setting(self.key(report)))["status"], "failed")
        retry = self.run_sync()
        self.assertEqual(retry.status, "complete")
        self.assertEqual(retry.reports[0].counts["duplicates"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
