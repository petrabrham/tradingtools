import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import Mock, patch

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.dialogs.trading212_dialog import (
    Trading212ConnectionDialog, Trading212RefreshDialog, Trading212WorkerDialog,
)
from tradingtools.dialogs.import_conflicts_dialog import ImportConflictsDialog
from tradingtools.import_diagnostics import ComparisonCandidate, ImportComparison
from tradingtools.trading212_sync import SyncProgress, load_connection


class TestTrading212Dialog(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("100x100")
        self.root.update()
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

    def tearDown(self):
        self.root.destroy()
        # Release Tk variable/exception cycles on their owning thread.
        gc.collect()

    def test_worker_stays_off_tk_thread_and_root_close_waits_for_cancellation(self):
        entered = Event()
        threads = []
        events = []
        handlers = []
        main_thread = get_ident()
        previous = self.root.protocol("WM_DELETE_WINDOW")

        def job(cancel, notify):
            threads.append(get_ident())
            notify(SyncProgress("Importing CSV", 2024, 1, 100))
            entered.set()
            if not cancel.wait(5):
                raise TimeoutError("Tk did not process cancellation")
            return "cleaned up"

        dialog = Trading212WorkerDialog(self.root, "Test synchronization", job)

        def close_when_entered():
            events.append(True)
            if entered.is_set():
                handler = self.root.protocol("WM_DELETE_WINDOW")
                handlers.append(handler)
                self.root.tk.call(handler)
            else:
                self.root.after(10, close_when_entered)

        self.root.after(10, close_when_entered)
        self.assertEqual(dialog.show(), "cleaned up")
        self.assertTrue(dialog.exit_requested)
        self.assertTrue(dialog.cancel_event.is_set())
        self.assertTrue(events)
        self.assertNotEqual(threads, [main_thread])
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.root.protocol("WM_DELETE_WINDOW"), previous)
        self.assertFalse(self.root.tk.call("info", "commands", handlers[0]))

    def test_progress_close_cancels_without_requesting_app_exit_and_surfaces_errors(self):
        entered = Event()

        def job(cancel, notify):
            entered.set()
            if not cancel.wait(5):
                raise TimeoutError("Tk did not process cancellation")
            raise InterruptedError("Cancelled")

        dialog = Trading212WorkerDialog(self.root, "Test cancellation", job)

        def cancel_when_entered():
            if entered.is_set():
                dialog.dialog.tk.call(dialog.dialog.protocol("WM_DELETE_WINDOW"))
            else:
                self.root.after(10, cancel_when_entered)

        self.root.after(10, cancel_when_entered)
        with self.assertRaisesRegex(InterruptedError, "Cancelled"):
            dialog.show()
        self.assertFalse(dialog.exit_requested)
        self.assertTrue(self.root.winfo_exists())

    def test_refresh_selects_years_without_text_parsing_and_restores_root_close_handler(self):
        previous = self.root.protocol("WM_DELETE_WINDOW")
        for close_root in (False, True):
            dialog = Trading212RefreshDialog(self.root, 2020)

            def choose():
                if close_root:
                    self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))
                else:
                    dialog.years.selection_set(0)
                    dialog.years.selection_set(2)
                    dialog._confirm()

            def when_visible():
                if hasattr(dialog, "years") and dialog.years.winfo_viewable():
                    self.root.after(10, choose)
                else:
                    self.root.after(10, when_visible)

            self.root.after(10, when_visible)
            with patch("tradingtools.dialogs.trading212_dialog.Trading212API.current_archive_year", return_value=2024):
                result = dialog.show()
            self.assertEqual(result, None if close_root else (2020, 2022))
            self.assertEqual(dialog.exit_requested, close_root)
            self.assertEqual(self.root.protocol("WM_DELETE_WINDOW"), previous)

    def test_vault_failure_never_binds_database_or_reports_success_and_clears_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.db"
            with patch("tradingtools.db.dbmanager.setup_logger", return_value=Mock()):
                database = DatabaseManager()
                try:
                    database.create_database(str(path))
                    dialog = Trading212ConnectionDialog(self.root, str(path), None)

                    def save():
                        dialog.environment.set("demo")
                        dialog.first_year.set("2020")
                        dialog.archive.set(str(Path(directory) / "archive"))
                        dialog.key.set("synthetic-key")
                        dialog.secret.set("synthetic-secret")
                        dialog._save()

                    def save_when_visible():
                        if dialog.dialog.winfo_viewable():
                            self.root.after(10, save)
                        else:
                            self.root.after(10, save_when_visible)

                    self.root.after(10, save_when_visible)
                    with (
                        patch("tradingtools.dialogs.trading212_dialog.Trading212API") as api,
                        patch("tradingtools.dialogs.trading212_dialog.messagebox.askyesno", return_value=True),
                        patch("tradingtools.dialogs.trading212_dialog.messagebox.showerror",
                              side_effect=lambda *a, **kw: dialog._cancel()) as error,
                    ):
                        api.return_value.verify_credentials.return_value = 123
                        api.return_value.save_credentials.side_effect = RuntimeError("Synthetic vault failure")
                        self.assertIsNone(dialog.show())
                    error.assert_called_once()
                    self.assertIn("Synthetic vault failure", error.call_args.args[1])
                    self.assertIsNone(load_connection(database))
                    self.assertEqual(dialog.key.get(), "")
                    self.assertEqual(dialog.secret.get(), "")
                finally:
                    database.close()

    def test_read_only_viewer_separates_raw_source_and_same_unit_recorded_differences(self):
        comparison = ImportComparison(
            "synthetic.csv", 2024, 1, "Interest on cash", "Local edit", "local_edit",
            {"Total": 2, "Currency (Total)": "USD"}, {"Total": 2}, None,
            [ComparisonCandidate(1, "interest", {"total_czk": 999}, {"Total": 2}, {"total_czk": 4})],
        )
        viewer = ImportConflictsDialog(self.root, [comparison])
        rows = []

        def inspect_when_visible():
            if hasattr(viewer, "details") and viewer.details.winfo_viewable():
                rows.extend(viewer.details.item(item) for item in viewer.details.get_children())
                viewer.details.winfo_toplevel().destroy()
            else:
                self.root.after(10, inspect_when_visible)

        self.root.after(20, inspect_when_visible)
        viewer.show()
        source = next(row for row in rows if row["values"][0] == "Source: Total")
        recorded = next(row for row in rows if row["values"][0] == "Recorded baseline: total_czk")
        expected = next(row for row in rows if row["values"][0] == "Stored: total_czk")
        self.assertEqual(source["tags"], "")
        self.assertIn("different", recorded["tags"])
        self.assertEqual(str(recorded["values"][1]), "999")
        self.assertEqual(str(recorded["values"][2]), "4")
        self.assertEqual(expected["values"][2], "(unavailable)")


if __name__ == "__main__":
    unittest.main()
