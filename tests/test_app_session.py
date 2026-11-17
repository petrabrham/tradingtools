import os
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from tradingtools.app import TradingToolsApp
from tradingtools.config.config_loader import ConfigLoader
from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.ui.menu_manager import MenuManager


class TestApplicationSession(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        appdata = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {"APPDATA": appdata}))
        self.stack.enter_context(patch.object(ConfigLoader, "_instance", None))
        self.stack.enter_context(patch.object(ConfigLoader, "_config", None))
        self.config = ConfigLoader()
        self.stack.enter_context(
            patch("tradingtools.app.get_config", return_value=self.config)
        )
        self.showerror = self.stack.enter_context(
            patch("tradingtools.app.messagebox.showerror")
        )
        self.stack.enter_context(
            patch("tradingtools.db.dbmanager.setup_logger", return_value=Mock())
        )
        self.app = TradingToolsApp.__new__(TradingToolsApp)
        self.db = Mock(conn=None, current_db_path=None)
        self.root = Mock()
        self.menu_manager = Mock()
        self.filter_manager = Mock()
        self.update_title = Mock()
        self.update_views = Mock()
        self.app.db = self.db
        self.app.root = self.root
        self.app.menu_manager = self.menu_manager
        self.app.filter_manager = self.filter_manager
        self.app.update_title = self.update_title
        self.app.update_views = self.update_views
        self.app.use_json_tax_rates = Mock()
        self.app.data_operation_active = False
        self.app._exit_after_operation = False
        self.directory = Path(appdata)

    def test_exit_and_startup_reconnect_real_database_and_restore_rate_mode(self):
        path = self.directory / "session.db"
        self.app.db = DatabaseManager()
        self.addCleanup(self.app.db.close)
        self.app.db.use_annual_rates = True
        self.app.db.create_database(str(path))
        self.app.on_exit()
        self.assertIsNone(self.app.db.conn)
        self.root.destroy.assert_called_once_with()

        self.config.reload()
        self.app.db.use_annual_rates = False
        self.app.restore_last_database()
        self.assertEqual(self.app.db.current_db_path, str(path.resolve()))
        self.assertIsNotNone(self.app.db.conn)
        self.assertTrue(self.app.db.use_annual_rates)
        self.update_title.assert_called_once_with()
        self.menu_manager.update_states.assert_called_once_with(self.app.db)
        self.filter_manager.update_year_list.assert_called_once_with()
        self.filter_manager.init_date_filters_from_db.assert_called_once_with()
        self.filter_manager.update_filters.assert_called_once_with()
        self.update_views.assert_called_once_with()
        self.menu_manager.update_exchange_rate_display.assert_called_once_with(
            self.app.db
        )
        self.showerror.assert_not_called()

    def test_exit_without_connection_clears_previous_path(self):
        self.config.save_last_database_path(str(self.directory / "previous.db"))
        self.app.on_exit()
        self.config.reload()
        self.assertEqual(self.config.get_last_database_path(), "")
        self.db.close.assert_called_once_with()
        self.root.destroy.assert_called_once_with()

    def test_startup_skips_empty_missing_or_directory_paths(self):
        for path in (None, str(self.directory / "missing.db"), str(self.directory)):
            with self.subTest(path=path):
                self.config.save_last_database_path(path)
                self.app.restore_last_database()
                self.db.open_database.assert_not_called()
                self.showerror.assert_not_called()
        self.assertFalse((self.directory / "missing.db").exists())

    def test_failed_restore_closes_partial_connection_and_reports_error(self):
        path = self.directory / "invalid.db"
        path.touch()
        self.config.save_last_database_path(str(path))
        self.db.open_database.side_effect = sqlite3.DatabaseError("Invalid database")
        self.app.restore_last_database()
        self.db.close.assert_called_once_with()
        self.showerror.assert_called_once()
        self.db.logger.exception.assert_called_once()

    def test_invalid_saved_path_is_reported(self):
        self.config._config = {"last_database_path": ["invalid"]}
        self.app.restore_last_database()
        self.showerror.assert_called_once()
        self.db.open_database.assert_not_called()

    def test_failed_save_keeps_window_and_connection_open_and_reports_error(self):
        with patch.object(
            self.config, "save_last_database_path",
            side_effect=PermissionError("Config is read-only"),
        ):
            self.app.on_exit()
        self.db.close.assert_not_called()
        self.root.destroy.assert_not_called()
        self.showerror.assert_called_once()

    def test_manual_connect_uses_same_connection_flow(self):
        with (
            patch("tradingtools.app.filedialog.askopenfilename", return_value="manual.db"),
            patch.object(self.app, "_connect_database") as connect,
        ):
            self.app.open_database()
        connect.assert_called_once_with("manual.db")

    def test_startup_restores_after_widgets_and_registers_window_close(self):
        with ExitStack() as stack:
            root = Mock()
            for name in (
                "DatabaseManager", "TaxRatesLoader", "CountryResolver", "MenuManager",
                "FilterManager", "TradesView", "InterestsView", "RealizedIncomeView",
                "DividendsView", "PairsView", "OpenPositionsView",
                "tk.StringVar", "tk.BooleanVar",
            ):
                stack.enter_context(patch("tradingtools.app." + name))
            stack.enter_context(patch("tradingtools.app.tk.Tk", return_value=root))
            stack.enter_context(patch.object(TradingToolsApp, "update_views"))
            stack.enter_context(patch.object(TradingToolsApp, "update_title"))
            events = []
            stack.enter_context(patch.object(
                TradingToolsApp, "create_widgets",
                side_effect=lambda: events.append("widgets"),
            ))
            stack.enter_context(patch.object(
                TradingToolsApp, "restore_last_database",
                side_effect=lambda: events.append("restore"),
            ))
            app = TradingToolsApp()
            self.assertEqual(events, ["widgets", "restore"])
            root.protocol.assert_called_once_with("WM_DELETE_WINDOW", app.on_exit)

    def test_exit_menu_uses_session_shutdown_handler(self):
        menu = Mock()
        with patch("tradingtools.ui.menu_manager.tk.Menu", return_value=menu):
            MenuManager(self.app.root, self.app).create_menu()
        menu.add_command.assert_any_call(label="Exit", command=self.app.on_exit)

    def test_csv_read_failure_never_shows_success_or_uses_uninitialized_result(self):
        self.db.conn = Mock()
        self.db.current_db_path = "synthetic.db"
        with (
            patch("tradingtools.app.filedialog.askopenfilename", return_value="synthetic.csv"),
            patch("tradingtools.app.CSVImportDialog.show", side_effect=ValueError("Invalid CSV")),
            patch("tradingtools.app.messagebox.showinfo") as info,
        ):
            self.app.open_csv_file()
        self.showerror.assert_called_once()
        info.assert_not_called()
        self.db.import_dataframe.assert_not_called()
        self.update_views.assert_called_once()

    def test_csv_partial_import_shows_issues_not_success(self):
        self.db.conn = Mock()
        self.db.current_db_path = "synthetic.db"
        self.db.import_dataframe.return_value = {
            "records": 5, "processed": 5, "status": "partial",
            "read": {"buy": 1, "sell": 0, "interest": 1, "dividend": 0, "fee": 1, "insignificant": 1, "unknown": 1},
            "added": {"buy": 0, "sell": 0, "interest": 1, "dividend": 0, "fee": 1},
            "duplicates": {"buy": 0, "sell": 0, "interest": 0, "dividend": 0},
            "errors": [{"row": 2, "action": "Market buy", "message": "Missing ID"}],
            "unknown_actions": {"Dividend adjustment": 1},
        }
        with (
            patch("tradingtools.app.filedialog.askopenfilename", return_value="synthetic.csv"),
            patch("tradingtools.app.CSVImportDialog.show", return_value=self.db.import_dataframe.return_value),
            patch("tradingtools.app.messagebox.showinfo") as info,
            patch("tradingtools.app.messagebox.showwarning") as warning,
        ):
            self.app.open_csv_file()
        info.assert_not_called()
        self.showerror.assert_not_called()
        title, message = warning.call_args.args
        self.assertEqual(title, "Import incomplete")
        self.assertIn("Failed: 1", message)
        self.assertIn("Dividend adjustment: 1", message)
        self.assertIn("Fee:         1 / 1", message)
        self.assertIn("Row 2 (Market buy): Missing ID", message)
        self.filter_manager.update_year_list.assert_called_once()
        self.update_views.assert_called_once()

    def test_csv_duplicate_only_import_still_shows_success_with_zero_added(self):
        self.db.conn = Mock()
        self.db.current_db_path = "synthetic.db"
        self.db.import_dataframe.return_value = {
            "records": 1, "processed": 1, "status": "complete",
            "read": {"buy": 1, "sell": 0, "interest": 0, "dividend": 0, "insignificant": 0, "unknown": 0},
            "added": {"buy": 0, "sell": 0, "interest": 0, "dividend": 0},
            "duplicates": {"buy": 1, "sell": 0, "interest": 0, "dividend": 0},
            "errors": [], "unknown_actions": {},
            "time_normalized": 1, "time_backup": "synthetic.db.pre-time-normalization-example.bak",
        }
        with (
            patch("tradingtools.app.filedialog.askopenfilename", return_value="synthetic.csv"),
            patch("tradingtools.app.CSVImportDialog.show", return_value=self.db.import_dataframe.return_value),
            patch("tradingtools.app.messagebox.showinfo") as info,
            patch("tradingtools.app.messagebox.showwarning") as warning,
        ):
            self.app.open_csv_file()
        warning.assert_not_called()
        self.showerror.assert_not_called()
        self.assertEqual(info.call_args.args[0], "Success")
        self.assertIn("Duplicates: 1", info.call_args.args[1])
        self.assertIn("Automatically normalized times: 1 (included in duplicates)", info.call_args.args[1])
        self.assertIn("Before-normalization backup: synthetic.db.pre-time-normalization-example.bak",
                      info.call_args.args[1])

    def test_csv_cancelled_before_import_does_not_show_success(self):
        self.db.conn = Mock()
        self.db.current_db_path = "synthetic.db"
        with (
            patch("tradingtools.app.filedialog.askopenfilename", return_value="synthetic.csv"),
            patch("tradingtools.app.CSVImportDialog.show", return_value=None),
            patch("tradingtools.app.messagebox.showinfo") as info,
        ):
            self.app.open_csv_file()
        info.assert_not_called()
        self.showerror.assert_not_called()
        self.db.import_dataframe.assert_not_called()

    def test_busy_guard_blocks_database_import_and_second_sync_handlers(self):
        self.app.data_operation_active = True
        with (
            patch("tradingtools.app.messagebox.showwarning") as warning,
            patch("tradingtools.app.filedialog.askopenfilename") as choose,
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
        ):
            for handler in (
                self.app.create_database, self.app.open_database, self.app.release_database,
                self.app.save_database_as, self.app.open_csv_file, self.app.import_annual_rates,
                self.app.read_trading212_transactions, self.app.configure_trading212,
                self.app.refresh_trading212_years,
            ):
                handler()
        self.assertEqual(warning.call_count, 9)
        choose.assert_not_called()
        worker.assert_not_called()
        self.db.close.assert_not_called()
        self.db.open_database.assert_not_called()

    def test_busy_menu_disables_all_competing_data_commands(self):
        menu = Mock()
        manager = MenuManager(self.root, self.app)
        manager.file_menu = menu
        manager.options_menu = Mock()
        self.app.data_operation_active = True
        self.db.conn = Mock()
        manager.update_states(self.db)
        for label in (
            "New Database", "Connect Database", "Save Database Copy As...", "Release Database",
            "Import CSV", "Read transactions from Trading212...", "Import Annual Exchange Rates...",
            "Refresh older Trading212 years...",
        ):
            menu.entryconfig.assert_any_call(label, state="disabled")
        manager.options_menu.entryconfig.assert_any_call("Trading212 connection...", state="disabled")

    def test_sync_cleanup_refreshes_partial_results_and_retains_only_current_comparisons(self):
        from tradingtools.trading212_sync import SyncResult, Trading212Connection

        binding = Trading212Connection("demo", 123, str(self.directory / "archive"), 2020)
        self.db.current_db_path = "synthetic.db"
        outcome = SyncResult(status="partial", comparisons=[Mock()])
        with (
            patch("tradingtools.app.load_connection", return_value=binding),
            patch("tradingtools.app.Trading212RefreshDialog") as refresh,
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
            patch.object(self.app, "_show_sync_result") as summary,
        ):
            worker.return_value.show.return_value = outcome
            worker.return_value.exit_requested = False
            self.app.read_trading212_transactions()
        self.assertFalse(self.app.data_operation_active)
        self.assertEqual(self.app.last_import_comparisons, outcome.comparisons)
        self.filter_manager.update_year_list.assert_called_once()
        self.update_views.assert_called_once()
        summary.assert_called_once_with(outcome)
        refresh.assert_not_called()

    def test_sync_root_close_exits_only_after_worker_cleanup_without_summary(self):
        from tradingtools.trading212_sync import SyncResult, Trading212Connection

        self.db.current_db_path = "synthetic.db"
        binding = Trading212Connection("demo", 123, str(self.directory / "archive"), 2020)
        with (
            patch("tradingtools.app.load_connection", return_value=binding),
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
            patch.object(self.app, "_show_sync_result") as summary,
            patch.object(self.app, "on_exit") as close,
        ):
            worker.return_value.show.return_value = SyncResult(status="cancelled")
            worker.return_value.exit_requested = True
            self.app.read_trading212_transactions()
        self.assertFalse(self.app.data_operation_active)
        summary.assert_not_called()
        close.assert_called_once()

    def test_invalid_connection_settings_restore_guard_and_never_show_uninitialized_result(self):
        self.db.current_db_path = "synthetic.db"
        with (
            patch("tradingtools.app.load_connection", side_effect=ValueError("Invalid saved connection")),
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
            patch.object(self.app, "_show_sync_result") as summary,
        ):
            self.app.read_trading212_transactions()
        self.assertFalse(self.app.data_operation_active)
        worker.assert_not_called()
        summary.assert_not_called()
        self.showerror.assert_called_once()

    def test_setup_is_only_automatic_for_database_without_saved_connection(self):
        from tradingtools.trading212_sync import SyncResult, Trading212Connection

        binding = Trading212Connection("demo", 123, str(self.directory / "archive"), 2020)
        self.db.current_db_path = "synthetic.db"
        with (
            patch("tradingtools.app.load_connection", side_effect=[None, binding]),
            patch.object(self.app, "_setup_trading212", return_value=binding) as setup,
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
            patch.object(self.app, "_show_sync_result"),
        ):
            worker.return_value.show.return_value = SyncResult()
            worker.return_value.exit_requested = False
            self.app.read_trading212_transactions()
            self.app.read_trading212_transactions()
        setup.assert_called_once()

    def test_explicit_refresh_passes_selected_years_to_worker_and_cancel_does_not_start_it(self):
        from threading import Event
        from tradingtools.trading212_sync import SyncResult, Trading212Connection

        binding = Trading212Connection("demo", 123, str(self.directory / "archive"), 2020)
        self.db.current_db_path = "synthetic.db"
        with (
            patch("tradingtools.app.load_connection", return_value=binding),
            patch("tradingtools.app.Trading212RefreshDialog") as options,
            patch("tradingtools.app.Trading212WorkerDialog") as worker,
            patch("tradingtools.app.Trading212Sync") as sync,
            patch.object(self.app, "_show_sync_result"),
        ):
            options.return_value.show.return_value = (2020, 2022)
            options.return_value.exit_requested = False
            worker.return_value.show.side_effect = lambda: worker.call_args.args[2](Event(), Mock())
            worker.return_value.exit_requested = False
            sync.return_value.run.return_value = SyncResult()
            self.app.refresh_trading212_years()
            self.assertEqual(sync.call_args.kwargs["refresh_years"], (2020, 2022))
            worker.reset_mock()
            options.return_value.show.return_value = None
            self.app.refresh_trading212_years()
            worker.assert_not_called()
        self.assertFalse(self.app.data_operation_active)


if __name__ == "__main__":
    unittest.main()
