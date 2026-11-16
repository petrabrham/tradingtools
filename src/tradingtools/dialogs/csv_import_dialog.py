"""Responsive CSV import using a worker-owned SQLite connection."""

import time
import tkinter as tk
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import ttk

import pandas as pd

from tradingtools.db.dbmanager import DatabaseManager, ImportResult
from tradingtools.import_diagnostics import build_comparisons


class CSVImportDialog:
    def __init__(self, parent: tk.Tk, database_path: str, csv_path: str) -> None:
        self.parent = parent
        self.database_path = database_path
        self.csv_path = csv_path
        self.cancel_event = Event()
        self.messages: Queue[ImportResult | Exception | None] = Queue()
        self.result: ImportResult | None = None
        self.error: Exception | None = None
        self.exit_requested = False

    def _import(self) -> None:
        database: DatabaseManager | None = None
        outcome: ImportResult | Exception | None = None
        try:
            if not self.cancel_event.is_set():
                frame = pd.read_csv(self.csv_path)
                if not self.cancel_event.is_set():
                    database = DatabaseManager()
                    database.open_database(self.database_path)
                    database.logger.info("Importing CSV file: %s", self.csv_path)
                    last_update = 0.0
                    for progress in database.import_dataframe_batches(
                        frame, batch_size=1, cancel_event=self.cancel_event,
                    ):
                        if progress["status"] != "running":
                            outcome = progress
                        elif time.monotonic() - last_update >= 0.1:
                            self.messages.put(progress)
                            last_update = time.monotonic()
                    if outcome is not None:
                        outcome["comparisons"] = build_comparisons(database, frame, outcome, self.csv_path)
        except Exception as error:
            outcome = error
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception as error:
                    outcome = error
        self.messages.put(outcome)

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.label.configure(text="Cancelling... waiting for the current operation to finish.")

    def _close_parent(self) -> None:
        self.exit_requested = True
        self._cancel()

    def _poll(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if isinstance(message, dict) and message["status"] == "running":
                    if not self.cancel_event.is_set():
                        self.bar.stop()
                        self.bar.configure(
                            mode="determinate", maximum=max(1, message["records"]),
                            value=message["processed"],
                        )
                        self.label.configure(
                            text=f"Processed {message['processed']} / {message['records']} rows "
                            f"({message['processed'] / max(1, message['records']):.0%})"
                        )
                    continue
                if isinstance(message, Exception):
                    self.error = message
                else:
                    self.result = message
                self.bar.stop()
                self.dialog.destroy()
                return
        except Empty:
            self.dialog.after(50, self._poll)

    def show(self) -> ImportResult | None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Import CSV")
        self.dialog.geometry("480x160")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.label = ttk.Label(self.dialog, text="Reading CSV and preparing import...", wraplength=440)
        self.label.pack(padx=20, pady=15)
        self.bar = ttk.Progressbar(self.dialog, mode="indeterminate", length=440)
        self.bar.pack(padx=20, fill="x")
        self.bar.start()
        self.cancel_button = ttk.Button(self.dialog, text="Cancel", command=self._cancel)
        self.cancel_button.pack(pady=15)
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        previous_close = self.parent.protocol("WM_DELETE_WINDOW")
        self.parent.protocol("WM_DELETE_WINDOW", self._close_parent)
        temporary_close = self.parent.protocol("WM_DELETE_WINDOW")
        try:
            self.dialog.wait_visibility()
            self.dialog.grab_set()
            self.worker = Thread(target=self._import, name="csv-import")
            self.worker.start()
            self.dialog.after(50, self._poll)
            self.parent.wait_window(self.dialog)
            self.worker.join()
        finally:
            self.parent.protocol("WM_DELETE_WINDOW", previous_close)
            self.parent.deletecommand(temporary_close)
            if self.dialog.winfo_exists():
                self.dialog.destroy()
        if self.error is not None:
            raise self.error
        return self.result
