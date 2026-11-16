"""Tk views for connection management and worker-owned synchronization."""

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Generic, TypeVar

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.trading212_api import Trading212API
from tradingtools.trading212_sync import (
    SyncProgress, Trading212Connection, load_connection, save_connection,
)


T = TypeVar("T")


@dataclass
class _Outcome(Generic[T]):
    value: T | None = None
    error: Exception | None = None


class Trading212WorkerDialog(Generic[T]):
    def __init__(
        self, parent: tk.Tk, title: str,
        job: Callable[[Event, Callable[[SyncProgress], None]], T],
    ) -> None:
        self.parent, self.title, self.job = parent, title, job
        self.cancel_event = Event()
        self.messages: Queue[SyncProgress | _Outcome[T]] = Queue()
        self.outcome: _Outcome[T] = _Outcome()
        self.exit_requested = False

    def _run(self) -> None:
        try:
            outcome = _Outcome(value=self.job(self.cancel_event, self.messages.put))
        except Exception as error:
            outcome = _Outcome[T](error=error)
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
                if isinstance(message, _Outcome):
                    self.outcome = message
                    self.bar.stop()
                    self.dialog.destroy()
                    return
                if self.cancel_event.is_set():
                    continue
                year = f" ({message.year})" if message.year is not None else ""
                wait = f" - waiting {message.wait_seconds:.0f}s" if message.wait_seconds is not None else ""
                text = message.phase + year + wait
                if message.processed is not None and message.records is not None:
                    self.bar.stop()
                    self.bar.configure(mode="determinate", maximum=max(1, message.records), value=message.processed)
                    text += f": {message.processed} / {message.records}"
                else:
                    if self.bar.cget("mode") != "indeterminate":
                        self.bar.configure(mode="indeterminate")
                        self.bar.start()
                self.label.configure(text=text)
        except Empty:
            self.dialog.after(50, self._poll)

    def show(self) -> T | None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(self.title)
        self.dialog.transient(self.parent)
        self.dialog.geometry("640x180")
        self.label = ttk.Label(self.dialog, text="Preparing...", wraplength=600)
        self.label.pack(padx=20, pady=20)
        self.bar = ttk.Progressbar(self.dialog, mode="indeterminate", length=600)
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
            worker = Thread(target=self._run, name="trading212")
            worker.start()
            self.dialog.after(50, self._poll)
            self.parent.wait_window(self.dialog)
            worker.join()
        finally:
            self.parent.protocol("WM_DELETE_WINDOW", previous_close)
            self.parent.deletecommand(temporary_close)
            if self.dialog.winfo_exists():
                self.dialog.destroy()
        if self.outcome.error is not None:
            raise self.outcome.error
        return self.outcome.value


class Trading212ConnectionDialog:
    def __init__(self, parent: tk.Tk, database_path: str, original: Trading212Connection | None) -> None:
        self.parent, self.database_path, self.original = parent, database_path, original
        self.result: Trading212Connection | None = None
        self.exit_requested = False

    def _work(self, title: str, job: Callable[[Event, Callable[[SyncProgress], None]], T]) -> T | None:
        worker_dialog = Trading212WorkerDialog(self.parent, title, job)
        try:
            return worker_dialog.show()
        finally:
            self.exit_requested = self.exit_requested or worker_dialog.exit_requested
            if self.exit_requested:
                self._cancel()
            elif self.dialog.winfo_exists():
                self.dialog.grab_set()

    def _choose_directory(self) -> None:
        directory = filedialog.askdirectory(parent=self.dialog, title="Choose protected CSV archive folder")
        if directory:
            self.archive.set(directory)

    def _cancel(self) -> None:
        self.key.set("")
        self.secret.set("")
        if self.dialog.winfo_exists():
            self.dialog.destroy()

    def _close_parent(self) -> None:
        self.exit_requested = True
        self._cancel()

    def _save(self) -> None:
        key, secret = self.key.get(), self.secret.get()
        try:
            if bool(key) != bool(secret) or (self.original is None and not key):
                raise ValueError("Enter both API Key and Secret")
            environment = self.environment.get()
            if environment not in ("live", "demo"):
                raise ValueError("Choose live or demo")
            selected_environment = "live" if environment == "live" else "demo"
            first_year = int(self.first_year.get())
            directory = str(Path(self.archive.get()).resolve()) if self.archive.get().strip() else ""
            Trading212Connection(
                selected_environment, self.original.account_id if self.original else 1,
                directory, first_year,
            )

            def verify(cancel: Event, notify: Callable[[SyncProgress], None]) -> int:
                api = Trading212API(
                    selected_environment, self.original.account_id if self.original else None,
                    on_progress=lambda event: notify(SyncProgress(event.phase, event.year, wait_seconds=event.wait_seconds)),
                )
                return (
                    api.verify_credentials(key, secret, cancel_event=cancel) if key else
                    api.verify_account(cancel_event=cancel)
                )

            account_id = self._work("Verify Trading212 account", verify)
            if self.exit_requested or account_id is None:
                return
            if not messagebox.askyesno(
                "Confirm Trading212 connection",
                f"Bind this database to {selected_environment} account {account_id}?\n"
                f"Archive from {first_year} in:\n{directory}\n\n"
                "Only history export is used. CSV archives contain sensitive financial data.",
                parent=self.dialog,
            ):
                return
            connection = Trading212Connection(selected_environment, account_id, directory, first_year)

            def store(cancel: Event, notify: Callable[[SyncProgress], None]) -> bool:
                database = DatabaseManager()
                try:
                    database.open_database(self.database_path)
                    if load_connection(database) != self.original:
                        raise ValueError("The saved connection changed; reopen connection settings")
                    if key:
                        api = Trading212API(selected_environment, account_id)
                        api.save_credentials(key, secret, cancel_event=cancel)
                    if cancel.is_set():
                        raise InterruptedError("Connection setup cancelled")
                    notify(SyncProgress("Saving non-secret connection settings"))
                    save_connection(database, connection)
                    return True
                finally:
                    database.close()

            if self._work("Save Trading212 connection", store):
                self.result = connection
                self._cancel()
        except InterruptedError:
            if not self.exit_requested:
                messagebox.showinfo("Cancelled", "Connection setup cancelled.", parent=self.dialog)
        except Exception as error:
            if not self.exit_requested:
                messagebox.showerror("Trading212 connection", str(error), parent=self.dialog)
        finally:
            self.key.set("")
            self.secret.set("")

    def _delete_credentials(self) -> None:
        original = self.original
        if original is None or not messagebox.askyesno(
            "Remove saved credentials",
            "Remove the local key pair? The database, binding and archive remain unchanged.\n"
            "This does not revoke the key at Trading212.", parent=self.dialog,
        ):
            return

        def remove(cancel: Event, notify: Callable[[SyncProgress], None]) -> bool:
            if cancel.is_set():
                raise InterruptedError("Credential deletion cancelled")
            notify(SyncProgress("Removing local credentials"))
            Trading212API(original.environment, original.account_id).delete_credentials()
            return True

        try:
            if self._work("Remove credentials", remove):
                messagebox.showinfo("Credentials removed", "The local key pair was removed.", parent=self.dialog)
        except Exception as error:
            if not self.exit_requested:
                messagebox.showerror("Trading212 credentials", str(error), parent=self.dialog)

    def show(self) -> Trading212Connection | None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Trading212 connection")
        self.dialog.transient(self.parent)
        frame = ttk.Frame(self.dialog, padding=15)
        frame.pack(fill="both", expand=True)
        self.environment = tk.StringVar(value=self.original.environment if self.original else "live")
        self.first_year = tk.StringVar(value=str(self.original.first_year) if self.original else "")
        self.archive = tk.StringVar(value=self.original.archive_directory if self.original else "")
        self.key, self.secret = tk.StringVar(), tk.StringVar()
        ttk.Label(frame, text="Environment").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            frame, textvariable=self.environment, values=("live", "demo"),
            state="disabled" if self.original else "readonly",
        ).grid(row=0, column=1, sticky="ew")
        for row, (label, variable) in enumerate((
            ("First archive year", self.first_year), ("Archive folder", self.archive),
            ("API Key", self.key), ("Secret", self.secret),
        ), start=1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=variable, show="*" if row >= 3 else "", width=55).grid(
                row=row, column=1, sticky="ew", padx=8,
            )
        ttk.Button(frame, text="Browse...", command=self._choose_directory).grid(row=2, column=2)
        text = (
            f"Bound account: {self.original.account_id}. Leave both key fields blank to reuse credentials."
            if self.original else "Choose the first year of your account history. Credentials use Windows Credential Manager."
        )
        ttk.Label(frame, text=text, wraplength=540).grid(row=5, column=0, columnspan=3, pady=10)
        ttk.Button(frame, text="Verify and save", command=self._save).grid(row=6, column=1, sticky="e")
        ttk.Button(frame, text="Cancel", command=self._cancel).grid(row=6, column=2)
        if self.original:
            ttk.Button(frame, text="Remove saved credentials", command=self._delete_credentials).grid(row=6, column=0)
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        previous_close = self.parent.protocol("WM_DELETE_WINDOW")
        self.parent.protocol("WM_DELETE_WINDOW", self._close_parent)
        temporary_close = self.parent.protocol("WM_DELETE_WINDOW")
        try:
            self.dialog.wait_visibility()
            self.dialog.grab_set()
            self.parent.wait_window(self.dialog)
        finally:
            self.parent.protocol("WM_DELETE_WINDOW", previous_close)
            self.parent.deletecommand(temporary_close)
            self.key.set("")
            self.secret.set("")
            if self.dialog.winfo_exists():
                self.dialog.destroy()
        return self.result
