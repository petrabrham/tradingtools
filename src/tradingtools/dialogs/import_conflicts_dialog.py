"""Current-run-only, read-only import comparisons."""

import tkinter as tk
from tkinter import ttk

from tradingtools.import_diagnostics import ImportComparison


class ImportConflictsDialog:
    def __init__(self, parent: tk.Tk, comparisons: list[ImportComparison]) -> None:
        self.parent, self.comparisons = parent, comparisons

    @staticmethod
    def _display(mapping: dict[str, object] | None, key: str) -> str:
        if mapping is None or key not in mapping:
            return "(unavailable)"
        value = mapping[key]
        return "(empty)" if value is None else str(value)

    def _select_conflict(self, event: object = None) -> None:
        selection = self.list.selection()
        if not selection:
            return
        self.current = self.comparisons[int(selection[0])]
        item = self.current
        self.reason.configure(text=f"{item.file}\nRow {item.row}: {item.reason}\n"
                                   "Source values and stored CZK fields are separate; unavailable values are not zero.")
        values = [f"{candidate.category} #{candidate.record_id}" for candidate in item.candidates]
        self.candidates.configure(values=values or ["No matching database candidate"])
        self.candidates.current(0)
        self._select_candidate()

    def _select_candidate(self, event: object = None) -> None:
        self.details.delete(*self.details.get_children())
        item = self.current
        index = self.candidates.current()
        candidate = item.candidates[index] if item.candidates and index >= 0 else None
        for prefix, stored, incoming in (
            ("Source", candidate.source if candidate else None, item.source),
            ("Stored", candidate.stored if candidate else None, item.expected),
            ("Recorded baseline", candidate.stored if candidate else None, candidate.recorded if candidate else None),
            ("Original CSV", None, item.incoming),
        ):
            for key in sorted(set(stored or {}) | set(incoming or {})):
                different = (
                    stored is not None and incoming is not None and key in stored and key in incoming
                    and stored[key] != incoming[key]
                )
                self.details.insert(
                    "", "end", values=(f"{prefix}: {key}", self._display(stored, key), self._display(incoming, key)),
                    tags=("different",) if different else (),
                )

    def show(self) -> None:
        window = tk.Toplevel(self.parent)
        window.title("Import conflicts - read only (current run)")
        window.geometry("1050x650")
        window.transient(self.parent)
        ttk.Label(window, text="No changes or permanent dismissals are made here. Reimport CSV to recheck.").pack(pady=8)
        list_frame = ttk.Frame(window)
        list_frame.pack(fill="x", padx=10)
        self.list = ttk.Treeview(list_frame, columns=("year", "row", "action", "reason"), show="headings", height=7)
        for key in ("year", "row", "action", "reason"):
            self.list.heading(key, text=key.title())
            self.list.column(key, width=80 if key in ("year", "row") else 300)
        self.list.pack(side="left", fill="x", expand=True)
        list_scrollbar = ttk.Scrollbar(list_frame, command=self.list.yview)
        self.list.configure(yscrollcommand=list_scrollbar.set)
        list_scrollbar.pack(side="right", fill="y")
        for index, item in enumerate(self.comparisons):
            self.list.insert("", "end", iid=str(index), values=(item.year or "", item.row, item.action, item.reason))
        self.list.bind("<<TreeviewSelect>>", self._select_conflict)
        self.reason = ttk.Label(window, wraplength=1000)
        self.reason.pack(fill="x", padx=10, pady=8)
        self.candidates = ttk.Combobox(window, state="readonly", width=50)
        self.candidates.pack()
        self.candidates.bind("<<ComboboxSelected>>", self._select_candidate)
        frame = ttk.Frame(window)
        frame.pack(fill="both", expand=True, padx=10, pady=8)
        self.details = ttk.Treeview(frame, columns=("field", "stored", "incoming"), show="headings")
        for key, label in (("field", "Field / units"), ("stored", "Database now"), ("incoming", "CSV / expected / recorded baseline")):
            self.details.heading(key, text=label)
            self.details.column(key, width=300)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=scrollbar.set)
        self.details.tag_configure("different", background="#ffe4c4")
        self.details.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Button(window, text="Close", command=window.destroy).pack(pady=8)
        if self.comparisons:
            self.list.selection_set("0")
            self._select_conflict()
        previous_grab = self.parent.grab_current()
        try:
            window.wait_visibility()
            window.grab_set()
            self.parent.wait_window(window)
        finally:
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
