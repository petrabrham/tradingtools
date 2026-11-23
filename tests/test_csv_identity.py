import logging
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.db.import_identity import ImportIdentity
from tradingtools.db.repositories.dividends import DividendsRepository
from tradingtools.db.repositories.fees import FeesRepository
from tradingtools.import_diagnostics import build_comparisons


class PragueDateTime(datetime):
    local_zone = ZoneInfo("Europe/Prague")

    def timestamp(self):
        if self.tzinfo is None:
            return datetime.timestamp(self.replace(tzinfo=self.local_zone))
        return super().timestamp()

    @classmethod
    def fromtimestamp(cls, timestamp, tz=None):
        value = super().fromtimestamp(timestamp, cls.local_zone if tz is None else tz)
        return value.replace(tzinfo=None) if tz is None else value


class TestCSVIdentity(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "history.db"
        self.logger = logging.getLogger("trading_tools.test_identity")
        logger_patch = patch("tradingtools.db.dbmanager.setup_logger", return_value=self.logger)
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        self.db = DatabaseManager()
        self.addCleanup(self.db.close)
        self.db.create_database(str(self.path))
        rate_patch = patch.object(self.db, "get_exchange_rate", return_value=2.0)
        self.rate = rate_patch.start()
        self.addCleanup(rate_patch.stop)
        for module in ("dbmanager", "import_identity", "repositories.pairings"):
            clock = patch(f"tradingtools.db.{module}.datetime", PragueDateTime)
            clock.start()
            self.addCleanup(clock.stop)

    @property
    def conn(self) -> sqlite3.Connection:
        connection = self.db.conn
        assert connection is not None
        return connection

    @staticmethod
    def row(action="Dividend (Dividend)", **values):
        return {
            "Action": action, "Time": "2024-06-01 12:00:00",
            "ID": "", "ISIN": "US0000000001", "Ticker": "TEST", "Name": "Synthetic",
            "No. of shares": 2, "Price / share": 1, "Currency (Price / share)": "USD",
            "Total": 2, "Currency (Total)": "USD",
            "Withholding tax": 0.1, "Currency (Withholding tax)": "USD",
            "Notes": "Interest on cash", **values,
        }

    def utc(self, row):
        converted = {key: value for key, value in row.items() if key != "Time"}
        converted["Time (UTC)"] = row["Time"] + "+00:00"
        return converted

    def seed_legacy(self, row, zone="Europe/Prague"):
        category = self.db._csv_category(row["Action"])
        timestamp = int(datetime.fromisoformat(row["Time"]).replace(tzinfo=ZoneInfo(zone)).timestamp())
        if category != "interest":
            self.db.get_or_create_securities_id(row["ISIN"], row["Ticker"], row["Name"])
        values = self.db._legacy_csv_values(pd.Series(row), category, timestamp, zone)
        if category in ("buy", "sell"):
            values["remaining_quantity"] = values["number_of_shares"]
        keys = list(values)
        table = ImportIdentity.TABLES[category]
        cursor = self.conn.execute(
            f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
            tuple(values[key] for key in keys),
        )
        self.conn.commit()
        return cursor.lastrowid

    def downgrade(self):
        self.conn.execute("DROP TABLE csv_identities")
        self.conn.execute("DROP TABLE fees")
        old_sql = DividendsRepository.TABLE_SQL.replace(
            "FOREIGN KEY", "UNIQUE(timestamp,isin_id), FOREIGN KEY",
        )
        self.conn.execute(old_sql.format(table="dividends_v1"))
        self.conn.execute("INSERT INTO dividends_v1 SELECT * FROM dividends")
        self.conn.execute("DROP TABLE dividends")
        self.conn.execute("ALTER TABLE dividends_v1 RENAME TO dividends")
        self.conn.execute("UPDATE versions SET version=1")
        self.conn.commit()
        self.db.close()

    def import_rows(self, rows):
        return self.db.import_dataframe(pd.DataFrame(rows))

    def test_comparison_keeps_all_ambiguous_legacy_candidates_without_rate_or_database_writes(self):
        row = self.row()
        ids = [self.seed_legacy(row), self.seed_legacy(row)]
        frame = pd.DataFrame([row])
        result = self.db.import_dataframe(frame)
        before = list(self.conn.iterdump())
        self.rate.reset_mock()
        comparisons = build_comparisons(self.db, frame, result, "synthetic.csv", 2024)
        self.assertEqual(len(comparisons), 1)
        comparison = comparisons[0]
        self.assertEqual({candidate.record_id for candidate in comparison.candidates}, set(ids))
        self.assertIsNotNone(comparison.expected)
        self.assertEqual(comparison.expected["net_czk"], comparison.candidates[0].stored["net_czk"])
        self.assertEqual(comparison.incoming["Currency (Total)"], "USD")
        self.assertIsNone(comparison.candidates[0].source)
        self.rate.assert_not_called()
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_comparison_shows_local_edit_against_recorded_snapshot_without_guessing_import_values(self):
        row = self.row("Interest on cash", ID="edited")
        frame = pd.DataFrame([row])
        self.db.import_dataframe(frame)
        self.conn.execute("UPDATE interests SET total_czk=999")
        self.conn.commit()
        result = self.db.import_dataframe(frame)
        self.rate.reset_mock()
        comparison = build_comparisons(self.db, frame, result, "synthetic.csv")[0]
        self.assertEqual(comparison.code, "local_edit")
        self.assertEqual(comparison.candidates[0].stored["total_czk"], 999)
        self.assertEqual(comparison.candidates[0].recorded["total_czk"], 4)
        self.assertIsNone(comparison.expected)
        self.rate.assert_not_called()

    def test_comparison_does_not_choose_first_of_multiple_tracked_anonymous_candidates(self):
        self.import_rows([self.row(ID="first"), self.row(ID="second", Total=3)])
        frame = pd.DataFrame([self.row(Total=4)])
        result = self.db.import_dataframe(frame)
        comparison = build_comparisons(self.db, frame, result, "synthetic.csv")[0]
        self.assertEqual(comparison.code, "ambiguous")
        self.assertEqual(len(comparison.candidates), 2)
        self.assertEqual({candidate.source["Total"] for candidate in comparison.candidates}, {2, 3})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 2)

    def test_migration_backs_up_preserves_ids_times_amounts_pairings_and_sequence(self):
        self.seed_legacy(self.row())
        buy = self.seed_legacy(self.row("Market buy", ID="buy"))
        sell = self.seed_legacy(self.row("Market sell", ID="sell"))
        self.conn.execute(
            "INSERT INTO pairings(sale_trade_id,purchase_trade_id,quantity,method,locked,locked_reason) "
            "VALUES(?,?,1,'Manual',1,'Synthetic locked pairing')", (sell, buy),
        )
        self.conn.commit()
        before = {table: self.conn.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("trades", "dividends", "pairings")}
        self.downgrade()
        legacy = sqlite3.connect(self.path)
        try:
            legacy.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='dividends'")
            legacy.execute("CREATE INDEX custom_dividend_currency ON dividends(currency_of_price)")
            legacy.commit()
        finally:
            legacy.close()
        self.db.open_database(str(self.path))
        self.assertEqual(self.db.get_db_version(), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0], 0)
        for table, rows in before.items():
            self.assertEqual(self.conn.execute(f"SELECT * FROM {table}").fetchall(), rows)
        backups = list(self.directory.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(backups[0])
        try:
            self.assertEqual(backup.execute("SELECT MAX(version) FROM versions").fetchone()[0], 1)
            self.assertEqual(backup.execute("SELECT * FROM dividends").fetchall(), before["dividends"])
        finally:
            backup.close()
        self.assertFalse(self.conn.execute("PRAGMA foreign_key_check").fetchall())
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='custom_dividend_currency'"
        ).fetchone())
        self.assertEqual(self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name='dividends'").fetchone()[0], 100)
        self.db.open_database(str(self.path))
        self.assertEqual(len(list(self.directory.glob("*.bak"))), 1)

    def test_create_existing_file_migrates_or_reopens_without_resetting_settings(self):
        self.seed_legacy(self.row())
        self.db.set_setting("exchange_rate_mode", "annual", "Synthetic setting")
        before = self.conn.execute("SELECT * FROM dividends").fetchall()
        self.downgrade()
        self.db.create_database(str(self.path))
        self.assertEqual(self.db.get_db_version(), 2)
        self.assertTrue(self.db.use_annual_rates)
        self.db.create_database(str(self.path))
        self.assertEqual(self.conn.execute("SELECT * FROM dividends").fetchall(), before)
        self.assertEqual(len(list(self.directory.glob("*.bak"))), 1)

    def test_custom_trigger_refuses_migration_without_modifying_legacy_database(self):
        self.downgrade()
        legacy = sqlite3.connect(self.path)
        try:
            legacy.execute(
                "CREATE TRIGGER custom_dividend_trigger AFTER INSERT ON dividends BEGIN SELECT 1; END"
            )
            legacy.commit()
        finally:
            legacy.close()
        with self.assertLogs(self.logger, level="ERROR"), self.assertRaisesRegex(RuntimeError, "triggers"):
            self.db.open_database(str(self.path))
        self.assertIsNone(self.db.conn)
        self.assertFalse(list(self.directory.glob("*.bak")))

    def test_migration_disk_failure_and_sql_failure_leave_v1_intact(self):
        self.seed_legacy(self.row())
        self.downgrade()
        with (
            patch.object(self.db, "_backup_before_identity_migration", side_effect=PermissionError("read-only")),
            self.assertLogs(self.logger, level="ERROR"),
            self.assertRaises(PermissionError),
        ):
            self.db.open_database(str(self.path))
        self.assertIsNone(self.db.conn)
        with (
            patch.object(ImportIdentity, "SCHEMA", "INVALID SQL"),
            self.assertLogs(self.logger, level="ERROR"),
            self.assertRaises(sqlite3.Error),
        ):
            self.db.open_database(str(self.path))
        original = sqlite3.connect(self.path)
        try:
            self.assertEqual(original.execute("SELECT MAX(version) FROM versions").fetchone()[0], 1)
            self.assertEqual(original.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)
            self.assertIn("UNIQUE", original.execute(
                "SELECT sql FROM sqlite_master WHERE name='dividends'"
            ).fetchone()[0])
        finally:
            original.close()
        self.assertEqual(len(list(self.directory.glob("*.bak"))), 1)

    def test_distinct_same_time_broker_ids_are_retained_and_repeat_safely(self):
        rows = [self.utc(self.row(ID="div-1")), self.utc(self.row(ID="div-2"))]
        first = self.import_rows(rows)
        self.assertEqual(first["added"]["dividend"], 2)
        second = self.import_rows(rows)
        self.assertEqual(second["duplicates"]["dividend"], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 2)

    def test_same_id_changed_financial_content_is_conflict_for_all_categories(self):
        for action in ("Market buy", "Market sell", "Interest on cash", "Dividend (Dividend)", "ADR Fee"):
            with self.subTest(action=action):
                row = self.utc(self.row(action, ID=action))
                self.assertEqual(sum(self.import_rows([row])["added"].values()), 1)
                self.rate.reset_mock()
                with self.assertLogs(self.logger, level="ERROR"):
                    result = self.import_rows([{**row, "Total": 999}])
                self.assertEqual(len(result["conflicts"]), 1)
                self.assertEqual(sum(result["duplicates"].values()), 0)
                self.assertEqual(result["status"], "partial")
                self.rate.assert_not_called()

    def test_no_id_repeats_are_duplicates_but_indistinguishable_input_rows_are_conflicts(self):
        row = self.utc(self.row())
        self.assertEqual(self.import_rows([row])["added"]["dividend"], 1)
        self.assertEqual(self.import_rows([row])["duplicates"]["dividend"], 1)
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([row, row])
        self.assertEqual(len(result["conflicts"]), 2)
        with self.assertLogs(self.logger, level="ERROR"):
            changed = self.import_rows([{**row, "Total": 4}])
        self.assertEqual(len(changed["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)

    def test_mixed_id_and_no_id_indistinguishable_rows_are_not_silently_merged(self):
        row = self.utc(self.row())
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([row, {**row, "ID": "has-id"}])
        self.assertEqual(len(result["conflicts"]), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 0)

    def test_no_id_cannot_choose_between_two_identical_identified_dividends(self):
        row = self.utc(self.row())
        self.import_rows([{**row, "ID": "one"}, {**row, "ID": "two"}])
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([row])
        self.assertEqual(len(result["conflicts"]), 1)

    def test_original_csv_links_winter_and_summer_without_moving_old_records(self):
        for text in ("2024-01-15 12:00:00", "2024-07-15 12:00:00"):
            with self.subTest(text=text):
                old = self.row(Time=text)
                local_id = self.seed_legacy(old)
                before = self.conn.execute("SELECT * FROM dividends WHERE id=?", (local_id,)).fetchone()
                with self.assertLogs(self.logger, level="ERROR"):
                    blocked = self.import_rows([self.utc(old)])
                self.assertEqual(len(blocked["conflicts"]), 1)
                linked = self.db.reconcile_legacy_dataframe(
                    pd.DataFrame([old]), source_timezone="UTC", imported_timezone="Europe/Prague",
                )
                self.assertEqual(linked["linked"], 1)
                self.assertEqual(linked["status"], "complete")
                self.assertEqual(self.import_rows([self.utc(old)])["duplicates"]["dividend"], 1)
                self.assertEqual(self.import_rows([old])["duplicates"]["dividend"], 1)
                self.assertEqual(self.conn.execute("SELECT * FROM dividends WHERE id=?", (local_id,)).fetchone(), before)
                repeated = self.db.reconcile_legacy_dataframe(
                    pd.DataFrame([old]), source_timezone="UTC", imported_timezone="Europe/Prague",
                )
                self.assertEqual(repeated["linked"], 1)

    def test_known_naive_sources_are_normalized_and_both_formats_remain_duplicates(self):
        old = self.row()
        timestamp = int(datetime.fromisoformat(old["Time"]).replace(tzinfo=ZoneInfo("Europe/Prague")).timestamp())
        with patch.object(DatabaseManager, "timestr_to_timestamp", return_value=timestamp):
            self.import_rows([old])
        result = self.import_rows([self.utc(old)])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["time_normalized"], 1)
        self.assertEqual(result["duplicates"]["dividend"], 1)
        self.assertEqual(self.conn.execute("SELECT timestamp FROM dividends").fetchone()[0],
                         int(datetime.fromisoformat(self.utc(old)["Time (UTC)"]).timestamp()))
        backup = sqlite3.connect(result["time_backup"])
        try:
            self.assertEqual(backup.execute("SELECT timestamp FROM dividends").fetchone()[0], timestamp)
        finally:
            backup.close()
        self.assertEqual(self.import_rows([self.utc(old)])["duplicates"]["dividend"], 1)
        self.assertEqual(self.import_rows([old])["duplicates"]["dividend"], 1)

    def test_normalization_preserves_values_and_backs_up_once_for_winter_and_summer(self):
        rows = [self.row(action, Time=text, ID=f"{action}-{text}", **{
                    "Currency conversion fee": 0.3, "Currency (Currency conversion fee)": "USD",
                })
                for text in ("2024-01-15 12:00:00", "2024-07-15 12:00:00")
                for action in ("Market buy", "Market sell", "Interest on cash", "Dividend (Dividend)", "ADR Fee")]
        self.import_rows(rows)
        before = {table: self.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                  for table in ("trades", "interests", "dividends", "fees")}
        sources = self.conn.execute("SELECT category,record_id,source FROM csv_identities").fetchall()
        self.rate.reset_mock()
        result = self.import_rows([self.utc(row) for row in rows])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["time_normalized"], len(rows))
        self.assertEqual(sum(result["duplicates"].values()), len(rows))
        self.assertEqual(sum(result["added"].values()), 0)
        self.assertEqual(len(list(self.directory.glob("*.pre-time-normalization-*.bak"))), 1)
        self.rate.assert_not_called()
        backup = sqlite3.connect(result["time_backup"])
        try:
            for table, records in before.items():
                self.assertEqual(backup.execute(f"SELECT * FROM {table} ORDER BY id").fetchall(), records)
                after = self.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                for old, new in zip(records, after):
                    delta = 3600 if datetime.fromtimestamp(old[1], ZoneInfo("Europe/Prague")).month == 1 else 7200
                    self.assertEqual(new, (old[0], old[1] + delta, *old[2:]))
        finally:
            backup.close()
        self.assertEqual(self.conn.execute(
            "SELECT category,record_id,legacy_source FROM csv_identities"
        ).fetchall(), sources)
        for retry in (rows, [self.utc(row) for row in rows]):
            repeated = self.import_rows(retry)
            self.assertEqual(repeated["time_normalized"], 0)
            self.assertEqual(sum(repeated["duplicates"].values()), len(rows))
            self.assertNotIn("time_backup", repeated)

    def test_anonymous_time_normalization_needs_one_exact_source_candidate(self):
        old = self.row()
        self.import_rows([{**old, "ID": "one"}, {**old, "ID": "two"}])
        before = list(self.conn.iterdump())
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(old)])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["time_normalized"], 0)
        self.assertEqual(list(self.conn.iterdump()), before)
        self.assertNotIn("time_backup", result)

    def test_no_id_fee_normalizes_and_repeated_no_id_groups_do_not(self):
        old = {key: value for key, value in self.fee_row(ISIN=None).items() if key != "Time (UTC)"}
        old["Time"] = "2024-06-01 12:00:00"
        self.import_rows([old])
        with self.assertLogs(self.logger, level="ERROR"):
            ambiguous = self.import_rows([self.utc(old), self.utc(old)])
        self.assertEqual(ambiguous["time_normalized"], 0)
        self.assertEqual(len(ambiguous["conflicts"]), 2)
        normalized = self.import_rows([self.utc(old)])
        self.assertEqual(normalized["time_normalized"], 1)
        self.assertEqual(self.import_rows([old])["duplicates"]["fee"], 1)

    def test_time_normalization_rejects_other_source_changes_and_local_edits(self):
        old = self.row("Market buy", ID="buy")
        self.import_rows([old])
        before = list(self.conn.iterdump())
        for changes in ({"Total": 99}, {"ISIN": "US0000000002"}, {"No. of shares": 99},
                        {"Action": "Market sell"}, {"Time (UTC)": "2024-06-01 12:00:01+00:00"},
                        {"Currency conversion fee": 1, "Currency (Currency conversion fee)": "USD"}):
            with self.subTest(changes=changes), self.assertLogs(self.logger, level="ERROR"):
                result = self.import_rows([{**self.utc(old), **changes}])
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertEqual(result["time_normalized"], 0)
            self.assertEqual(list(self.conn.iterdump()), before)
            self.assertNotIn("time_backup", result)
        self.conn.execute("UPDATE trades SET total_czk=999")
        self.conn.commit()
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(old)])
        self.assertEqual(result["conflicts"][0]["code"], "local_edit")
        self.assertEqual(self.conn.execute("SELECT total_czk FROM trades").fetchone()[0], 999)

    def test_time_normalization_rejects_date_year_and_dst_boundaries(self):
        for index, text in enumerate(("2024-06-01 23:30:00", "2024-01-01 00:30:00",
                                      "2024-03-31 02:30:00", "2024-10-27 02:30:00")):
            with self.subTest(time=text):
                old = self.row("Interest on cash", Time=text, ID=f"unsafe-{index}")
                self.import_rows([old])
                before = list(self.conn.iterdump())
                with self.assertLogs(self.logger, level="ERROR"):
                    result = self.import_rows([self.utc(old)])
                self.assertEqual(len(result["conflicts"]), 1)
                self.assertEqual(result["time_normalized"], 0)
                self.assertEqual(list(self.conn.iterdump()), before)
                self.assertNotIn("time_backup", result)

    def test_time_normalization_does_not_guess_original_machine_timezone(self):
        old = self.row("Interest on cash", ID="moved")
        self.import_rows([old])
        before = list(self.conn.iterdump())
        with (patch.object(PragueDateTime, "local_zone", ZoneInfo("America/New_York")),
              self.assertLogs(self.logger, level="ERROR")):
            result = self.import_rows([self.utc(old)])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(list(self.conn.iterdump()), before)
        self.assertNotIn("time_backup", result)

    def test_time_backup_failure_prevents_all_repairs(self):
        old = self.row("Interest on cash", ID="backup")
        self.import_rows([old])
        before = list(self.conn.iterdump())
        failures = (
            patch.object(self.db, "_backup_database", side_effect=PermissionError("Synthetic backup failure")),
            patch("tradingtools.db.dbmanager.sqlite3.connect",
                  side_effect=sqlite3.OperationalError("Synthetic backup database failure")),
        )
        for failure in failures:
            with failure, self.assertRaisesRegex(RuntimeError, "without a verified database backup"):
                self.import_rows([self.utc(old)])
        self.assertEqual(list(self.conn.iterdump()), before)
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(list(self.directory.glob("*.bak")), [])

    def test_time_identity_write_failure_rolls_back_timestamp_and_keeps_backup(self):
        old = self.row("Interest on cash", ID="rollback")
        self.import_rows([old])
        self.conn.execute(
            "CREATE TRIGGER reject_time_identity BEFORE UPDATE OF source ON csv_identities "
            "BEGIN SELECT RAISE(ABORT,'Synthetic identity failure'); END"
        )
        self.conn.commit()
        before = list(self.conn.iterdump())
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(old)])
        self.assertEqual(result["failed"]["interest"], 1)
        self.assertEqual(result["time_normalized"], 0)
        self.assertEqual(list(self.conn.iterdump()), before)
        self.assertTrue(Path(result["time_backup"]).is_file())

    def test_time_repair_counts_and_backup_survive_cancellation_and_retry(self):
        rows = [self.row("Interest on cash", ID=f"cancel-{index}") for index in range(3)]
        self.import_rows(rows)
        cancel = Event()
        batches = self.db.import_dataframe_batches(pd.DataFrame([self.utc(row) for row in rows]),
                                                   batch_size=1, cancel_event=cancel)
        first = next(batches)
        cancel.set()
        final = next(batches)
        self.assertEqual((final["status"], final["processed"], final["time_normalized"]),
                         ("cancelled", 1, 1))
        self.assertEqual(final["time_backup"], first["time_backup"])
        retried = self.import_rows([self.utc(row) for row in rows])
        self.assertEqual((retried["status"], retried["time_normalized"]), ("complete", 2))
        self.assertEqual(retried["duplicates"]["interest"], 3)

    def test_partial_import_counts_only_successfully_normalized_rows(self):
        rows = [self.row("Interest on cash", ID=identifier) for identifier in ("normalize", "changed")]
        self.import_rows(rows)
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(rows[0]), {**self.utc(rows[1]), "Total": 99}])
        self.assertEqual((result["status"], result["processed"], result["time_normalized"]),
                         ("partial", 2, 1))
        self.assertEqual(result["duplicates"]["interest"], 1)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertTrue(Path(result["time_backup"]).is_file())

    def test_time_repair_keeps_locked_pairing_and_remaining_quantities(self):
        buy = self.row("Market buy", Time="2020-06-01 12:00:00", ID="paired-buy")
        sell = self.utc(self.row("Market sell", Time="2024-07-01 16:00:00", ID="paired-sell"))
        self.import_rows([buy, sell])
        self.conn.execute(
            "INSERT INTO pairings(purchase_trade_id,sale_trade_id,quantity,method,locked,locked_reason,"
            "holding_period_days,time_test_qualified) "
            "VALUES(1,2,1,'Manual',1,'Keep unchanged',1491,1)"
        )
        self.conn.execute("UPDATE trades SET remaining_quantity=0")
        self.conn.commit()
        pairings = self.conn.execute("SELECT * FROM pairings").fetchall()
        trades = self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
        result = self.import_rows([self.utc(buy)])
        self.assertEqual(result["time_normalized"], 1)
        self.assertEqual(self.conn.execute("SELECT * FROM pairings").fetchall(), pairings)
        after = self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
        self.assertEqual(after[0], (trades[0][0], trades[0][1] + 7200, *trades[0][2:]))
        self.assertEqual(after[1], trades[1])

    def seed_pair_with_holding_day_change(self, category="buy"):
        buy_time = "2024-09-20 12:00:00" if category == "buy" else "2024-06-01 12:00:00"
        buy = self.row("Market buy", Time=buy_time, ID=f"day-buy-{category}")
        sell_time = "2024-11-07 11:00:00" if category == "buy" else "2024-06-02 13:00:00"
        sell = self.row("Market sell", Time=sell_time, ID=f"day-sell-{category}")
        self.import_rows([buy if category == "buy" else self.utc(buy),
                          sell if category == "sell" else self.utc(sell)])
        buy_id, buy_timestamp = self.conn.execute(
            "SELECT id,timestamp FROM trades WHERE id_string=?", (buy["ID"],),
        ).fetchone()
        sell_id, sell_timestamp = self.conn.execute(
            "SELECT id,timestamp FROM trades WHERE id_string=?", (sell["ID"],),
        ).fetchone()
        cursor = self.conn.execute(
            "INSERT INTO pairings(purchase_trade_id,sale_trade_id,quantity,method,locked,locked_reason,"
            "holding_period_days,time_test_qualified,notes) VALUES(?,?,1,'Manual',1,'Keep lock',?,0,'Keep note')",
            (buy_id, sell_id, (sell_timestamp - buy_timestamp) // 86400),
        )
        self.conn.execute("UPDATE trades SET remaining_quantity=0")
        self.conn.commit()
        return buy if category == "buy" else sell, cursor.lastrowid

    def test_time_repair_refreshes_only_derived_days_for_locked_buy_and_sell_pairs(self):
        for category, day_change in (("buy", -1), ("sell", 1)):
            with self.subTest(category=category):
                row, pair_id = self.seed_pair_with_holding_day_change(category)
                before_trades = self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
                cursor = self.conn.execute("SELECT * FROM pairings ORDER BY id")
                day_index = [column[0] for column in cursor.description].index("holding_period_days")
                before_pairs = cursor.fetchall()
                record_id = self.conn.execute(
                    "SELECT id FROM trades WHERE id_string=?", (row["ID"],),
                ).fetchone()[0]
                result = self.import_rows([self.utc(row)])
                self.assertEqual((result["status"], result["time_normalized"]), ("complete", 1))
                expected_pairs = [
                    (*pair[:day_index], pair[day_index] + day_change, *pair[day_index + 1:])
                    if pair[0] == pair_id else pair for pair in before_pairs
                ]
                self.assertEqual(self.conn.execute("SELECT * FROM pairings ORDER BY id").fetchall(),
                                 expected_pairs)
                expected_timestamp = int(datetime.fromisoformat(self.utc(row)["Time (UTC)"]).timestamp())
                expected_trades = [
                    (trade[0], expected_timestamp, *trade[2:]) if trade[0] == record_id else trade
                    for trade in before_trades
                ]
                self.assertEqual(self.conn.execute("SELECT * FROM trades ORDER BY id").fetchall(),
                                 expected_trades)
                backup = sqlite3.connect(result["time_backup"])
                try:
                    self.assertEqual(backup.execute("SELECT * FROM trades ORDER BY id").fetchall(),
                                     before_trades)
                    self.assertEqual(backup.execute("SELECT * FROM pairings ORDER BY id").fetchall(),
                                     before_pairs)
                finally:
                    backup.close()
                for retry in (row, self.utc(row)):
                    repeated = self.import_rows([retry])
                    self.assertEqual(repeated["time_normalized"], 0)
                    self.assertEqual(repeated["duplicates"][category], 1)
                    self.assertEqual(self.conn.execute("SELECT * FROM pairings ORDER BY id").fetchall(),
                                     expected_pairs)

    def test_time_repair_does_not_replace_inconsistent_or_unset_pairing_days(self):
        row, pair_id = self.seed_pair_with_holding_day_change()
        self.conn.execute("UPDATE pairings SET holding_period_days=999 WHERE id=?", (pair_id,))
        self.conn.commit()
        before = list(self.conn.iterdump())
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(row)])
        self.assertEqual(result["conflicts"][0]["code"], "time_pairing")
        self.assertEqual(list(self.conn.iterdump()), before)
        self.assertNotIn("time_backup", result)
        self.conn.execute("UPDATE pairings SET holding_period_days=NULL WHERE id=?", (pair_id,))
        self.conn.commit()
        result = self.import_rows([self.utc(row)])
        self.assertEqual(result["time_normalized"], 1)
        self.assertIsNone(self.conn.execute(
            "SELECT holding_period_days FROM pairings WHERE id=?", (pair_id,),
        ).fetchone()[0])

    def test_pairing_day_refresh_waits_for_backup_and_rolls_back_with_identity(self):
        row, _ = self.seed_pair_with_holding_day_change()
        before = list(self.conn.iterdump())
        with (patch.object(self.db, "_backup_database", side_effect=PermissionError("Synthetic backup failure")),
              self.assertRaisesRegex(RuntimeError, "without a verified database backup")):
            self.import_rows([self.utc(row)])
        self.assertEqual(list(self.conn.iterdump()), before)
        self.conn.execute(
            "CREATE TRIGGER reject_paired_time_identity BEFORE UPDATE OF source ON csv_identities "
            "BEGIN SELECT RAISE(ABORT,'Synthetic identity failure'); END"
        )
        self.conn.commit()
        before = list(self.conn.iterdump())
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([self.utc(row)])
        self.assertEqual(result["failed"]["buy"], 1)
        self.assertEqual(result["time_normalized"], 0)
        self.assertTrue(Path(result["time_backup"]).is_file())
        self.assertEqual(list(self.conn.iterdump()), before)

    def test_time_repair_blocks_pairing_chronology_and_time_test_changes(self):
        for index, (buy_time, sell_time) in enumerate((
            ("2024-06-01 12:00:00", "2024-06-01 11:00:00"),
            ("2020-03-28 12:00:00", "2023-03-28 10:30:00"),
        )):
            with self.subTest(buy=buy_time, sell=sell_time):
                buy = self.row("Market buy", Time=buy_time, ID=f"unsafe-buy-{index}")
                sell = self.utc(self.row("Market sell", Time=sell_time, ID=f"unsafe-sell-{index}"))
                self.import_rows([buy, sell])
                buy_id, sell_id = self.conn.execute("SELECT id FROM trades ORDER BY id DESC LIMIT 2").fetchall()[::-1]
                self.conn.execute(
                    "INSERT INTO pairings(purchase_trade_id,sale_trade_id,quantity,method,locked) "
                    "VALUES(?,?,1,'Manual',1)", (buy_id[0], sell_id[0]),
                )
                self.conn.commit()
                before = list(self.conn.iterdump())
                with (patch("tradingtools.db.repositories.pairings.get_time_test_holding_period_years",
                            return_value=3), self.assertLogs(self.logger, level="ERROR")):
                    result = self.import_rows([self.utc(buy)])
                self.assertEqual(result["time_normalized"], 0)
                self.assertEqual(result["conflicts"][0]["code"], "time_pairing")
                self.assertEqual(list(self.conn.iterdump()), before)
                self.assertNotIn("time_backup", result)

    def test_reconciled_trade_interest_and_locked_pairing_survive_both_csv_formats(self):
        rows = [self.row(action, ID=action) for action in
                ("Market buy", "Market sell", "Interest on cash")]
        buy, sell, _ = [self.seed_legacy(row) for row in rows]
        self.conn.execute(
            "INSERT INTO pairings(sale_trade_id,purchase_trade_id,quantity,method,locked,locked_reason) "
            "VALUES(?,?,1,'Manual',1,'Keep pairing')", (sell, buy),
        )
        self.conn.execute("UPDATE trades SET remaining_quantity=0 WHERE id=?", (buy,))
        self.conn.commit()
        before = {table: self.conn.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("trades", "interests", "pairings")}
        result = self.db.reconcile_legacy_dataframe(
            pd.DataFrame(rows), source_timezone="UTC", imported_timezone="Europe/Prague",
        )
        self.assertEqual(result["linked"], 3)
        for batch in (rows, [self.utc(row) for row in rows]):
            imported = self.import_rows(batch)
            self.assertEqual(sum(imported["duplicates"].values()), 3)
            self.assertEqual(imported["status"], "complete")
        for table, records in before.items():
            self.assertEqual(self.conn.execute(f"SELECT * FROM {table}").fetchall(), records)

    def test_reconciliation_rejects_changed_rates_and_indistinguishable_legacy_rows(self):
        row = self.row()
        self.seed_legacy(row)
        before = self.conn.execute("SELECT * FROM dividends").fetchall()
        with patch.object(self.db, "get_exchange_rate", return_value=3), self.assertLogs(self.logger, level="ERROR"):
            result = self.db.reconcile_legacy_dataframe(
                pd.DataFrame([row]), source_timezone="UTC", imported_timezone="Europe/Prague",
            )
        self.assertEqual(len(result["conflicts"]), 1)
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.reconcile_legacy_dataframe(
                pd.DataFrame([row, row]), source_timezone="UTC", imported_timezone="Europe/Prague",
            )
        self.assertEqual(len(result["conflicts"]), 2)
        self.assertEqual(result["linked"], 0)
        self.assertEqual(self.conn.execute("SELECT * FROM dividends").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)

    def test_display_name_and_export_fx_precision_do_not_change_source_identity(self):
        row = self.utc(self.row(ID="div"))
        self.import_rows([row])
        result = self.import_rows([{**row, "Name": "Renamed", "Ticker": "NEW", "Exchange rate": 1.234567}])
        self.assertEqual(result["duplicates"]["dividend"], 1)

    def test_wrong_original_and_ambiguous_dst_are_conflicts_without_history_changes(self):
        old = self.row()
        self.seed_legacy(old)
        before = self.conn.execute("SELECT * FROM dividends").fetchall()
        for row in ({**old, "Total": 99}, {**old, "Time": "2024-10-27 02:30:00"},
                    {**old, "Time": "2024-03-31 02:30:00"}):
            with self.subTest(time=row["Time"]), self.assertLogs(self.logger, level="ERROR"):
                result = self.db.reconcile_legacy_dataframe(
                    pd.DataFrame([row]), source_timezone="UTC", imported_timezone="Europe/Prague",
                )
            self.assertEqual(result["linked"], 0)
            self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT * FROM dividends").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)

    def test_local_edit_is_not_overwritten_and_source_write_failure_rolls_back_insert(self):
        row = self.utc(self.row(ID="div-1"))
        self.import_rows([row])
        self.conn.execute("UPDATE dividends SET net_czk=123")
        self.conn.commit()
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([row])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT net_czk FROM dividends").fetchone()[0], 123)
        with (
            patch.object(ImportIdentity, "remember", side_effect=sqlite3.OperationalError("disk error")),
            self.assertLogs(self.logger, level="ERROR"),
        ):
            result = self.import_rows([
                self.utc(self.row("Interest on cash", ID="new")),
                self.utc(self.row(ID="new-div", ISIN="US0000000002")),
            ])
        self.assertEqual(result["failed"]["interest"], 1)
        self.assertEqual(result["failed"]["dividend"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM securities").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)

    def test_optional_broker_id_can_be_attached_only_to_unique_unchanged_source(self):
        row = self.utc(self.row())
        self.import_rows([row])
        result = self.import_rows([{**row, "ID": "newly-provided"}])
        self.assertEqual(result["duplicates"]["dividend"], 1)
        self.assertEqual(self.conn.execute("SELECT broker_id FROM csv_identities").fetchone()[0], "newly-provided")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)

    @staticmethod
    def fee_row(**values):
        return {
            "Action": "ADR Fee", "Time (UTC)": "2024-06-01 12:00:00+00:00",
            "ISIN": "US0000000001", "Total": -2, "Currency (Total)": "USD",
            "Total (Account CCY)": -999, **values,
        }

    def test_fee_migration_failure_rolls_back_dividend_and_identity_changes(self):
        self.seed_legacy(self.row())
        self.downgrade()
        with (
            patch.object(FeesRepository, "TABLE_SQL", "INVALID SQL"),
            self.assertLogs(self.logger, level="ERROR"), self.assertRaises(sqlite3.Error),
        ):
            self.db.open_database(str(self.path))
        original = sqlite3.connect(self.path)
        try:
            self.assertEqual(original.execute("SELECT MAX(version) FROM versions").fetchone()[0], 1)
            self.assertEqual(original.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 1)
            self.assertIn("UNIQUE", original.execute(
                "SELECT sql FROM sqlite_master WHERE name='dividends'"
            ).fetchone()[0])
            self.assertFalse(original.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('fees','csv_identities')"
            ).fetchall())
        finally:
            original.close()
        self.assertEqual(len(list(self.directory.glob("*.bak"))), 1)

    def test_fee_import_keeps_original_signed_amount_and_uses_selected_conversion(self):
        row = self.fee_row()
        result = self.import_rows([row])
        self.assertEqual(result["added"]["fee"], 1)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.conn.execute(
            "SELECT amount,currency,total_czk FROM fees"
        ).fetchone(), (-2, "USD", -4))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)
        self.assertEqual(self.import_rows([row])["duplicates"]["fee"], 1)
        self.db.use_annual_rates = True
        self.db.create_annual_rates_table()
        self.db.insert_annual_rate(2024, "USD", 1, 25)
        with patch.object(self.db, "get_exchange_rate", wraps=DatabaseManager.get_exchange_rate.__get__(self.db)):
            refund = self.import_rows([self.fee_row(ID="refund", Total=3, **{"Time (UTC)": "2024-06-02 12:00:00+00:00"})])
        self.assertEqual(refund["added"]["fee"], 1)
        self.assertEqual(self.conn.execute("SELECT amount,total_czk FROM fees ORDER BY id DESC").fetchone(), (3, 75))

    def test_fee_instrument_is_optional_but_amount_currency_cannot_be_guessed(self):
        row = self.fee_row(ISIN=None)
        self.assertEqual(self.import_rows([row])["added"]["fee"], 1)
        self.assertIsNone(self.conn.execute("SELECT isin_id FROM fees").fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM securities").fetchone()[0], 0)
        for changes in ({"Total": None}, {"Currency (Total)": ""}, {"Total": float("inf")}):
            with self.subTest(changes=changes), self.assertLogs(self.logger, level="ERROR"):
                result = self.import_rows([{**row, **changes}])
            self.assertEqual(result["failed"]["fee"], 1)
            self.assertEqual(result["status"], "partial")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0], 1)

    def test_fee_identified_events_remain_distinct_and_anonymous_match_cannot_choose(self):
        row = self.fee_row()
        rows = [{**row, "ID": "one"}, {**row, "ID": "two"}]
        self.assertEqual(self.import_rows(rows)["added"]["fee"], 2)
        self.assertEqual(self.import_rows(rows)["duplicates"]["fee"], 2)
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([row])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0], 2)

    def test_fee_anonymous_and_mixed_indistinguishable_input_is_not_collapsed(self):
        row = self.fee_row()
        for rows in ([row, row], [row, {**row, "ID": "one"}]):
            with self.subTest(rows=len(rows)), self.assertLogs(self.logger, level="ERROR"):
                result = self.import_rows(rows)
            self.assertEqual(len(result["conflicts"]), 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0], 0)

    def test_fee_id_adoption_and_local_edit_protection(self):
        row = self.fee_row()
        self.import_rows([row])
        self.assertEqual(self.import_rows([{**row, "ID": "fee-one"}])["duplicates"]["fee"], 1)
        self.conn.execute("UPDATE fees SET amount=-99")
        self.conn.commit()
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.import_rows([{**row, "ID": "fee-one"}])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT amount FROM fees").fetchone()[0], -99)

    def test_fee_source_failure_rolls_back_fee_and_new_security(self):
        with (
            patch.object(ImportIdentity, "remember", side_effect=sqlite3.OperationalError("disk error")),
            self.assertLogs(self.logger, level="ERROR"),
        ):
            result = self.import_rows([self.fee_row()])
        self.assertEqual(result["failed"]["fee"], 1)
        for table in ("fees", "securities", "csv_identities"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_fee_cancellation_and_retry_keep_committed_rows_and_counts(self):
        rows = [self.fee_row(**{"Time (UTC)": f"2024-06-01 {hour}:00:00+00:00"}) for hour in (12, 13, 14)]
        cancel = Event()
        batches = self.db.import_dataframe_batches(pd.DataFrame(rows), batch_size=1, cancel_event=cancel)
        self.assertEqual(next(batches)["added"]["fee"], 1)
        cancel.set()
        self.assertEqual(list(batches)[-1]["status"], "cancelled")
        retried = self.import_rows(rows)
        self.assertEqual(retried["added"]["fee"], 2)
        self.assertEqual(retried["duplicates"]["fee"], 1)

    def test_fee_timezone_reconciliation_preserves_rows_and_recognizes_both_formats(self):
        old = {key: value for key, value in self.fee_row(ISIN=None).items() if key != "Time (UTC)"}
        old["Time"] = "2024-06-01 12:00:00"
        timestamp = int(datetime.fromisoformat(old["Time"]).replace(tzinfo=ZoneInfo("Europe/Prague")).timestamp())
        with patch.object(DatabaseManager, "timestr_to_timestamp", return_value=timestamp):
            self.import_rows([old])
        before = self.conn.execute("SELECT * FROM fees").fetchall()
        linked = self.db.reconcile_legacy_dataframe(
            pd.DataFrame([old]), source_timezone="UTC", imported_timezone="Europe/Prague",
        )
        self.assertEqual(linked["linked"], 1)
        for row in (old, self.utc(old)):
            self.assertEqual(self.import_rows([row])["duplicates"]["fee"], 1)
        self.assertEqual(self.conn.execute("SELECT * FROM fees").fetchall(), before)

    def test_previously_ignored_fee_requires_import_not_fabricated_reconciliation(self):
        row = self.fee_row()
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.reconcile_legacy_dataframe(
                pd.DataFrame([row]), source_timezone="UTC", imported_timezone="Europe/Prague",
            )
        self.assertEqual(result["linked"], 0)
        self.assertIn("import its original CSV normally", result["conflicts"][0]["message"])
        self.assertEqual(self.import_rows([row])["added"]["fee"], 1)

    def test_original_csv_reimport_proves_all_legacy_categories_without_changing_history(self):
        rows = [self.row(action, ID=action) for action in
                ("Market buy", "Market sell", "Interest on cash")] + [
                    self.row(Time=f"2024-06-{1 + index // 24:02} {index % 24:02}:00:00")
                    for index in range(32)
                ]
        buy, sell = [self.seed_legacy(row) for row in rows][:2]
        self.conn.execute(
            "INSERT INTO pairings(sale_trade_id,purchase_trade_id,quantity,method,locked,locked_reason) "
            "VALUES(?,?,1,'Manual',1,'Keep historical pairing')", (sell, buy),
        )
        self.conn.execute("UPDATE trades SET remaining_quantity=0 WHERE id=?", (buy,))
        self.conn.commit()
        before = {table: self.conn.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("trades", "interests", "dividends", "pairings")}
        self.downgrade()
        self.db.open_database(str(self.path))
        def parse_original(text):
            return int(datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Europe/Prague")).timestamp())

        with patch.object(DatabaseManager, "timestr_to_timestamp", side_effect=parse_original):
            result = self.import_rows(rows)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["duplicates"]["dividend"], 32)
        self.assertEqual(sum(result["duplicates"].values()), len(rows))
        self.assertEqual(sum(result["added"].values()), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], len(rows))
        self.rate.reset_mock()
        self.assertEqual(sum(self.import_rows(rows)["duplicates"].values()), len(rows))
        self.rate.assert_not_called()
        for table, records in before.items():
            self.assertEqual(self.conn.execute(f"SELECT * FROM {table}").fetchall(), records)

    def test_legacy_id_reimport_still_rejects_timestamp_and_financial_mismatches(self):
        row = self.row("Market buy", ID="old-buy")
        self.seed_legacy(row)
        before = self.conn.execute("SELECT * FROM trades").fetchall()
        timestamp = before[0][1]
        for changes, parsed_time in (
            ({"Total": 99}, timestamp),
            ({"No. of shares": 99}, timestamp),
            ({"Stamp duty reserve tax": 1, "Currency (Stamp duty reserve tax)": "USD"}, timestamp),
            ({}, timestamp + 3600),
        ):
            with (
                self.subTest(changes=changes, timestamp=parsed_time),
                patch.object(DatabaseManager, "timestr_to_timestamp", return_value=parsed_time),
                self.assertLogs(self.logger, level="ERROR"),
            ):
                result = self.import_rows([{**row, **changes}])
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertEqual(sum(result["duplicates"].values()), 0)
        self.assertEqual(self.conn.execute("SELECT * FROM trades").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)

    def test_legacy_id_proof_source_failure_preserves_transaction(self):
        row = self.row("Interest on cash", ID="old-interest")
        self.seed_legacy(row)
        before = self.conn.execute("SELECT * FROM interests").fetchall()
        with (
            patch.object(DatabaseManager, "timestr_to_timestamp", return_value=before[0][1]),
            patch.object(ImportIdentity, "remember", side_effect=sqlite3.OperationalError("disk error")),
            self.assertLogs(self.logger, level="ERROR"),
        ):
            result = self.import_rows([row])
        self.assertEqual(result["failed"]["interest"], 1)
        self.assertEqual(self.conn.execute("SELECT * FROM interests").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)

    def test_legacy_dividend_proof_rejects_changed_values_time_and_ambiguous_candidates(self):
        row = self.row()
        self.seed_legacy(row)
        before = self.conn.execute("SELECT * FROM dividends").fetchall()
        timestamp = before[0][1]
        for changes, parsed_time in (
            ({"Total": 99}, timestamp),
            ({"Withholding tax": 99}, timestamp),
            ({"No. of shares": 99}, timestamp),
            ({}, timestamp + 3600),
        ):
            with (
                self.subTest(changes=changes, timestamp=parsed_time),
                patch.object(DatabaseManager, "timestr_to_timestamp", return_value=parsed_time),
                self.assertLogs(self.logger, level="ERROR"),
            ):
                result = self.import_rows([{**row, **changes}])
            self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT * FROM dividends").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)
        self.seed_legacy(row)
        with (
            patch.object(DatabaseManager, "timestr_to_timestamp", return_value=timestamp),
            self.assertLogs(self.logger, level="ERROR"),
        ):
            result = self.import_rows([row])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0], 2)

    def test_legacy_dividend_source_failure_does_not_change_or_duplicate_dividend(self):
        row = self.row()
        self.seed_legacy(row)
        before = self.conn.execute("SELECT * FROM dividends").fetchall()
        with (
            patch.object(DatabaseManager, "timestr_to_timestamp", return_value=before[0][1]),
            patch.object(ImportIdentity, "remember", side_effect=sqlite3.OperationalError("disk error")),
            self.assertLogs(self.logger, level="ERROR"),
        ):
            result = self.import_rows([row])
        self.assertEqual(result["failed"]["dividend"], 1)
        self.assertEqual(self.conn.execute("SELECT * FROM dividends").fetchall(), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM csv_identities").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
