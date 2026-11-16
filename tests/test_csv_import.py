import io
import logging
import sqlite3
import unittest
from threading import Event
from unittest.mock import patch

import pandas as pd

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.db.repositories.interests import InterestType


class TestCSVImport(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("trading_tools.test_csv_import")
        with patch("tradingtools.db.dbmanager.setup_logger", return_value=self.logger):
            self.db = DatabaseManager()
        self.db.create_database(":memory:")
        self.addCleanup(self.db.close)
        connection = self.db.conn
        assert connection is not None
        self.conn = connection
        rate_patch = patch.object(self.db, "get_exchange_rate", return_value=2.0)
        self.rate = rate_patch.start()
        self.addCleanup(rate_patch.stop)

    @staticmethod
    def row(action: object = "Market buy", **values: object) -> dict[str, object]:
        return {
            "Action": action, "Time (UTC)": "2024-06-01 12:00:00+00:00",
            "ISIN": "US0000000001", "Ticker": "TEST", "Name": "Synthetic security",
            "ID": action, "No. of shares": 2, "Price / share": 5,
            "Currency (Price / share)": "USD", "Total": 10, "Currency (Total)": "USD",
            "Stamp duty reserve tax": 1, "Currency (Stamp duty reserve tax)": "USD",
            "Currency conversion fee": 0.5, "Currency (Currency conversion fee)": "USD",
            "French transaction tax": 0.25, "Currency (French transaction tax)": "USD",
            "Withholding tax": 1, "Currency (Withholding tax)": "USD",
            "Notes": "Interest on cash", **values,
        }

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_actual_added_and_duplicate_counts_preserve_financial_values(self):
        rows = [
            self.row(), self.row("Market sell"),
            self.row("Interest on cash"),
            self.row("Lending interest", Notes="Share lending interest"),
            self.row("Dividend (Dividend)"),
        ]
        df = pd.DataFrame(rows)
        first = self.db.import_dataframe(df)
        self.assertEqual(first["added"], {"buy": 1, "sell": 1, "interest": 2, "dividend": 1})
        second = self.db.import_dataframe(df)
        self.assertEqual(second["added"], {"buy": 0, "sell": 0, "interest": 0, "dividend": 0})
        self.assertEqual(second["duplicates"], first["added"])
        trades = self.conn.execute(
            "SELECT number_of_shares,total_czk,stamp_tax_czk,conversion_fee_czk,"
            "french_transaction_tax_czk FROM trades ORDER BY id"
        ).fetchall()
        self.assertEqual(trades, [(2, -20, -2, -1, -0.5), (-2, 20, -2, -1, -0.5)])
        self.assertEqual(self.conn.execute(
            "SELECT gross_czk,net_czk,withholding_tax_czk FROM dividends"
        ).fetchone(), (22, 20, 2))
        self.assertEqual(self.count("interests"), 2)

    def test_errors_and_unknown_actions_are_not_success_or_duplicates(self):
        df = pd.DataFrame([
            self.row("Interest on cash", ID="good"),
            self.row("Market buy", **{"No. of shares": "bad"}),
            self.row("Dividend adjustment"),
            self.row("Deposit"),
        ], index=[8, 8, 1, 2])
        with self.assertLogs(self.logger, level="WARNING"):
            result = self.db.import_dataframe(df)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["failed"]["buy"], 1)
        self.assertEqual(result["duplicates"]["buy"], 0)
        self.assertEqual(result["errors"][0]["row"], 2)
        self.assertEqual(result["unknown_actions"], {"Dividend adjustment": 1})
        self.assertEqual(result["skipped_actions"], {"Deposit": 1})
        self.assertEqual(self.count("trades"), 0)
        self.assertEqual(self.count("interests"), 1)

    def test_invalid_financial_fields_never_silently_become_zero(self):
        rows = [
            self.row(ID="bad-total", Total="junk"),
            self.row(ID="bad-fee", **{"Currency conversion fee": "junk"}),
            self.row(ID="bad-currency", **{"Currency (Total)": float("nan")}),
            self.row(ID=float("nan")),
            self.row(ID="bad-time", **{"Time (UTC)": "invalid"}),
            self.row(ID="infinite", **{"No. of shares": float("inf")}),
        ]
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.import_dataframe(pd.DataFrame(rows))
        self.assertEqual(result["failed"]["buy"], len(rows))
        self.assertEqual(self.count("trades"), 0)
        self.assertEqual(len(result["errors"]), len(rows))

    def test_optional_blank_fees_and_legacy_time_remain_supported(self):
        df = pd.read_csv(io.StringIO(
            "Action,Time,ID,ISIN,No. of shares,Price / share,Currency (Price / share),"
            "Total,Currency (Total),Currency conversion fee,Currency (Currency conversion fee)\n"
            "Market buy,2024-06-01 12:00:00,trade-1,US0000000001,2,5,USD,10,USD,,\n"
        ))
        result = self.db.import_dataframe(df)
        self.assertEqual(result["added"]["buy"], 1)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.conn.execute(
            "SELECT timestamp,total_czk,conversion_fee_czk FROM trades"
        ).fetchone(), (self.db.timestr_to_timestamp("2024-06-01 12:00:00"), -20, 0))

    def test_cancellable_batches_report_cumulative_snapshots_and_keep_committed_rows(self):
        df = pd.DataFrame([self.row("Interest on cash", ID=f"cash-{i}") for i in range(5)])
        event = Event()
        batches = self.db.import_dataframe_batches(df, batch_size=2, cancel_event=event)
        first = next(batches)
        self.assertEqual((first["status"], first["processed"], first["added"]["interest"]), ("running", 2, 2))
        event.set()
        remaining = list(batches)
        self.assertEqual(remaining[-1]["status"], "cancelled")
        self.assertEqual(remaining[-1]["processed"], 2)
        self.assertEqual(first["status"], "running")
        self.assertEqual(self.count("interests"), 2)
        resumed = self.db.import_dataframe(df)
        self.assertEqual(resumed["added"]["interest"], 3)
        self.assertEqual(resumed["duplicates"]["interest"], 2)

    def test_integrity_failures_are_not_ignored_as_duplicates(self):
        repo = self.db.interests_repo
        assert repo is not None
        with self.assertRaises(sqlite3.IntegrityError):
            repo.insert(0, InterestType.CASH_INTEREST, "cash", float("nan"))

    def test_missing_rate_is_reported_and_valid_later_rows_continue(self):
        def rate(currency, date):
            if currency == "USD":
                raise ValueError("Annual exchange rate for USD in year 2024 not found in database")
            return 1.0

        self.rate.side_effect = rate
        df = pd.DataFrame([
            self.row(ID="no-rate"),
            self.row("Interest on cash", **{"ID": "cash-good", "Currency (Total)": "CZK"}),
        ])
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.import_dataframe(df)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed"]["buy"], 1)
        self.assertIn("Annual exchange rate", result["errors"][0]["message"])
        self.assertEqual(result["added"]["interest"], 1)
        self.assertEqual(self.count("securities"), 0)
        self.assertEqual(self.count("trades"), 0)

    def test_database_error_rolls_back_failed_row_before_continuing(self):
        self.conn.executescript(
            "CREATE TRIGGER reject_interest BEFORE INSERT ON interests "
            "WHEN NEW.id_string='rejected' BEGIN "
            "INSERT INTO interests(timestamp,type,id_string,total_czk) VALUES(0,1,'leaked',1); "
            "SELECT RAISE(FAIL,'Synthetic insertion failure'); END;"
        )
        df = pd.DataFrame([
            self.row("Interest on cash", ID="rejected"),
            self.row("Interest on cash", ID="good"),
        ])
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.import_dataframe(df)
        self.assertEqual(result["failed"]["interest"], 1)
        self.assertEqual(result["added"]["interest"], 1)
        self.assertEqual(self.conn.execute("SELECT id_string FROM interests").fetchall(), [("good",)])

    def test_cancellation_during_a_batch_does_not_start_the_next_row(self):
        event = Event()

        def rate(currency, date):
            event.set()
            return 2.0

        self.rate.side_effect = rate
        df = pd.DataFrame([self.row("Interest on cash", ID=f"cash-{i}") for i in range(3)])
        result = self.db.import_dataframe(df, cancel_event=event)
        self.assertEqual((result["status"], result["processed"]), ("cancelled", 1))
        self.assertEqual(self.count("interests"), 1)
        self.assertEqual(sum(result["read"].values()), 1)

    def test_batches_finish_once_and_earlier_snapshots_are_independent(self):
        df = pd.DataFrame([
            self.row("Interest on cash", ID="cash-1"),
            self.row("Interest on cash", ID="cash-2"),
            self.row("Interest on cash", ID="cash-3"),
        ])
        batches = list(self.db.import_dataframe_batches(df, batch_size=1))
        self.assertEqual([item["processed"] for item in batches], [1, 2, 3])
        self.assertEqual([item["status"] for item in batches], ["running", "running", "complete"])
        self.assertEqual([item["added"]["interest"] for item in batches], [1, 2, 3])
        batches[0]["added"]["interest"] = 999
        self.assertEqual(batches[-1]["added"]["interest"], 3)

    def test_missing_action_and_invalid_structure_are_explicit_errors(self):
        df = pd.DataFrame([self.row(Action=pd.NA)])
        with self.assertLogs(self.logger, level="ERROR"):
            result = self.db.import_dataframe(df)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["read"]["unknown"], 1)
        self.assertEqual(result["failed"]["unknown"], 1)
        for invalid in (
            pd.DataFrame([{"Action": "Deposit"}]),
            pd.DataFrame([["Deposit", "Deposit", "2024-01-01"]], columns=["Action", "Action", "Time"]),
        ):
            with self.subTest(columns=list(invalid.columns)), self.assertLogs(self.logger, level="ERROR"):
                with self.assertRaises(ValueError):
                    self.db.import_dataframe(invalid)
        for size in (0, -1, True):
            with self.subTest(size=size), self.assertLogs(self.logger, level="ERROR"):
                with self.assertRaises(ValueError):
                    list(self.db.import_dataframe_batches(pd.DataFrame([self.row()]), batch_size=size))

    def test_pre_cancelled_and_empty_import_have_final_results_without_writes(self):
        event = Event()
        event.set()
        result = self.db.import_dataframe(pd.DataFrame([self.row()]), cancel_event=event)
        self.assertEqual((result["status"], result["records"], result["processed"]), ("cancelled", 1, 0))
        self.assertEqual(self.count("trades"), 0)
        empty = self.db.import_dataframe(pd.DataFrame(columns=["Action", "Time"]))
        self.assertEqual((empty["status"], empty["processed"]), ("complete", 0))

    def test_blank_legacy_column_falls_back_to_explicit_utc_without_changing_parser(self):
        df = pd.DataFrame([self.row(Time=float("nan"))])
        result = self.db.import_dataframe(df)
        self.assertEqual(result["added"]["buy"], 1)
        self.assertEqual(self.conn.execute("SELECT timestamp FROM trades").fetchone()[0],
                         self.db.timestr_to_timestamp("2024-06-01 12:00:00+00:00"))

    def test_annual_mode_and_distinct_dividend_actions(self):
        with patch.object(self.db, "get_exchange_rate", wraps=DatabaseManager.get_exchange_rate.__get__(self.db)):
            self.db.use_annual_rates = True
            self.db.create_annual_rates_table()
            self.db.insert_annual_rate(2024, "USD", 1, 25)
            self.db.insert_annual_rate(2024, "CZK", 1, 1)
            df = pd.DataFrame([
                self.row("Dividend (Dividend)", **{"Withholding tax": "", "Currency (Withholding tax)": ""}),
                self.row("Dividend (Dividend manufactured payment)", ID="other-dividend"),
            ])
            result = self.db.import_dataframe(df)
        self.assertEqual(result["added"]["dividend"], 2)
        self.assertEqual(result["duplicates"]["dividend"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT gross_czk,net_czk,withholding_tax_czk FROM dividends"
        ).fetchone(), (250, 250, 0))

    def test_limit_and_stock_split_actions_keep_trade_signs(self):
        df = pd.DataFrame([self.row(action) for action in (
            "Limit buy", "Limit sell", "Stock split open", "Stock split close",
        )])
        result = self.db.import_dataframe(df)
        self.assertEqual((result["added"]["buy"], result["added"]["sell"]), (2, 2))
        self.assertEqual(self.conn.execute(
            "SELECT number_of_shares,total_czk FROM trades ORDER BY id"
        ).fetchall(), [(2, -20), (-2, 20), (2, -20), (-2, 20)])


if __name__ == "__main__":
    unittest.main()
