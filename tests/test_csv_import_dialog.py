import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from threading import Event, Thread, get_ident
from unittest.mock import Mock, patch

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.dialogs.csv_import_dialog import CSVImportDialog


class TestCSVImportDialog(unittest.TestCase):
    def setUp(self):
        gc.collect()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.logger = patch("tradingtools.db.dbmanager.setup_logger", return_value=Mock())
        self.logger.start()
        self.addCleanup(self.logger.stop)
        self.database = DatabaseManager()
        self.database.create_database(str(self.path / "test.db"))
        self.addCleanup(self.database.close)
        connection = self.database.conn
        assert connection is not None
        self.conn = connection
        self.csv = self.path / "test.csv"
        self.csv.write_text(
            "Action,Time (UTC),ID,Total,Currency (Total),Notes\n"
            "Interest on cash,2024-06-01 12:00:00+00:00,cash-1,2,CZK,Interest on cash\n"
            "Interest on cash,2024-06-02 12:00:00+00:00,cash-2,3,CZK,Interest on cash\n",
            encoding="utf-8",
        )

    def test_worker_commits_using_its_own_connection_and_reports_progress(self):
        dialog = CSVImportDialog(Mock(), str(self.path / "test.db"), str(self.csv))
        main_thread = get_ident()
        threads = []

        def rate(database, currency, date):
            threads.append(get_ident())
            return 1.0

        with patch.object(DatabaseManager, "get_exchange_rate", new=rate):
            worker = Thread(target=dialog._import)
            worker.start()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertTrue(all(thread != main_thread for thread in threads))
        messages = []
        while not dialog.messages.empty():
            messages.append(dialog.messages.get_nowait())
        self.assertEqual(messages[0]["status"], "running")
        self.assertEqual(messages[-1]["status"], "complete")
        self.assertEqual(messages[-1]["processed"], 2)
        self.assertEqual(self.conn.execute("SELECT SUM(total_czk) FROM interests").fetchone()[0], 5)

    def test_worker_reports_read_errors_and_pre_cancel_does_not_read(self):
        dialog = CSVImportDialog(Mock(), str(self.path / "test.db"), str(self.path / "missing.csv"))
        dialog._import()
        self.assertIsInstance(dialog.messages.get_nowait(), FileNotFoundError)
        dialog.cancel_event.set()
        with patch("tradingtools.dialogs.csv_import_dialog.pd.read_csv") as read:
            dialog._import()
        self.assertIsNone(dialog.messages.get_nowait())
        read.assert_not_called()

    def test_worker_returns_current_run_conflicts_without_overwriting_existing_amount(self):
        with patch.object(DatabaseManager, "get_exchange_rate", return_value=1.0):
            first = CSVImportDialog(Mock(), str(self.path / "test.db"), str(self.csv))
            first._import()
            self.csv.write_text(self.csv.read_text().replace("cash-1,2,", "cash-1,9,"), encoding="utf-8")
            second = CSVImportDialog(Mock(), str(self.path / "test.db"), str(self.csv))
            second._import()
        messages = []
        while not second.messages.empty():
            messages.append(second.messages.get_nowait())
        result = messages[-1]
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["comparisons"]), 1)
        self.assertEqual(result["comparisons"][0].row, 1)
        self.assertEqual(result["comparisons"][0].incoming["Total"], 9)
        self.assertEqual(self.conn.execute("SELECT SUM(total_czk) FROM interests").fetchone()[0], 5)

    def test_real_modal_window_remains_responsive_and_cancels_worker(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry("100x100")
        root.update()
        root.protocol("WM_DELETE_WINDOW", lambda: None)
        previous = root.protocol("WM_DELETE_WINDOW")
        dialog = CSVImportDialog(root, str(self.path / "test.db"), str(self.csv))
        entered = Event()
        gui_events = []

        def slow_rate(database, currency, date):
            entered.set()
            if not dialog.cancel_event.wait(timeout=5):
                raise TimeoutError("GUI did not respond")
            return 1.0

        def cancel_when_importing():
            gui_events.append(True)
            if entered.is_set():
                dialog._cancel()
            else:
                root.after(10, cancel_when_importing)

        root.after(10, cancel_when_importing)
        with patch.object(DatabaseManager, "get_exchange_rate", new=slow_rate):
            result = dialog.show()
        self.assertTrue(gui_events)
        assert result is not None
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["processed"], 1)
        self.assertFalse(dialog.worker.is_alive())
        self.assertEqual(root.protocol("WM_DELETE_WINDOW"), previous)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0], 1)

    def test_poll_updates_determinate_bar_and_finishes_after_closing_connection(self):
        dialog = CSVImportDialog(Mock(), str(self.path / "test.db"), str(self.csv))
        dialog.dialog = Mock()
        dialog.bar = Mock()
        dialog.label = Mock()
        with patch.object(DatabaseManager, "get_exchange_rate", return_value=1.0):
            dialog._import()
        dialog._poll()
        dialog.bar.configure.assert_called_once_with(mode="determinate", maximum=2, value=1)
        dialog.label.configure.assert_called_once_with(text="Processed 1 / 2 rows (50%)")
        dialog.dialog.destroy.assert_called_once()
        assert dialog.result is not None
        self.assertEqual(dialog.result["status"], "complete")
        self.conn.execute("BEGIN EXCLUSIVE")
        self.conn.rollback()


if __name__ == "__main__":
    unittest.main()
