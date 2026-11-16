"""Local Trading212 workflow; HTTP and archive rules remain in Trading212API."""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable, Literal

import pandas as pd

from tradingtools.db.dbmanager import DatabaseManager, ImportResult
from tradingtools.import_diagnostics import ImportComparison, build_comparisons
from tradingtools.trading212_api import APIProgress, ArchivedCSV, Trading212API


_CONNECTION_KEY = "trading212.connection"
_STATE_VERSION = 1


@dataclass(frozen=True)
class Trading212Connection:
    environment: Literal["live", "demo"]
    account_id: int
    archive_directory: str
    first_year: int

    def __post_init__(self) -> None:
        if self.environment not in ("live", "demo"):
            raise ValueError("Invalid Trading212 environment")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("Invalid Trading212 account ID")
        if type(self.first_year) is not int or not 1 <= self.first_year <= Trading212API.current_archive_year():
            raise ValueError("First archive year must not be in the future")
        if (
            not isinstance(self.archive_directory, str) or not self.archive_directory.strip()
            or not Path(self.archive_directory).is_absolute()
        ):
            raise ValueError("Choose an absolute archive directory")


def load_connection(database: DatabaseManager) -> Trading212Connection | None:
    text = database.get_setting(_CONNECTION_KEY, "")
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict) or set(data) != {
        "version", "environment", "account_id", "archive_directory", "first_year", "timezone",
    }:
        raise ValueError("Invalid saved Trading212 connection")
    if type(data["version"]) is not int or data["version"] != 1 or data["timezone"] != "Europe/Prague":
        raise ValueError("Unsupported saved Trading212 connection")
    return Trading212Connection(
        data["environment"], data["account_id"], data["archive_directory"], data["first_year"],
    )


def save_connection(database: DatabaseManager, connection: Trading212Connection) -> None:
    previous = load_connection(database)
    if previous is not None and (
        previous.environment != connection.environment or previous.account_id != connection.account_id
    ):
        raise ValueError("This database is already bound to another Trading212 account/environment")
    database.set_setting(_CONNECTION_KEY, json.dumps({
        "version": 1, "environment": connection.environment, "account_id": connection.account_id,
        "archive_directory": connection.archive_directory, "first_year": connection.first_year,
        "timezone": "Europe/Prague",
    }), "Non-secret Trading212 connection")


@dataclass(frozen=True)
class SyncProgress:
    phase: str
    year: int | None = None
    processed: int | None = None
    records: int | None = None
    wait_seconds: float | None = None


@dataclass(frozen=True)
class ReportImport:
    report: ArchivedCSV
    status: str
    counts: dict[str, int]
    processed: int
    records: int
    unknown_actions: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    conflicts: int = 0
    read_counts: dict[str, int] = field(default_factory=dict)
    skipped_actions: dict[str, int] = field(default_factory=dict)
    issues: tuple[str, ...] = ()


@dataclass
class SyncResult:
    status: Literal["complete", "partial", "cancelled", "failed"] = "complete"
    reports: list[ReportImport] = field(default_factory=list)
    comparisons: list[ImportComparison] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        lines = [f"Synchronization: {self.status}"]
        for item in self.reports:
            archive = f"{item.report.year}: archived ({'full year' if item.report.complete else 'year to date'})"
            if item.status in ("failed", "cancelled") and not item.read_counts:
                lines.append(
                    f"{archive}, {item.status}; final row counts unavailable. "
                    "Already committed rows are kept; reimport is safe."
                )
                continue
            if item.status == "already imported":
                lines.append(f"{archive}, already imported (unchanged CSV).")
                continue
            lines.append(
                f"{archive}, {item.status}; "
                f"{item.processed}/{item.records} processed; "
                "read / added: "
                + ", ".join(
                    f"{key}: {value} / {item.counts.get(key, 0)}"
                    for key, value in item.read_counts.items() if key not in ("unknown", "insignificant")
                )
                + f"; duplicates: {item.counts.get('duplicates', 0)}"
                + f"; errors: {item.errors}, conflicts: {item.conflicts}"
            )
            if item.unknown_actions:
                lines.append("  Unsupported: " + ", ".join(
                    f"{action}: {count}" for action, count in item.unknown_actions.items()
                ))
            if item.skipped_actions:
                lines.append("  Intentionally skipped: " + ", ".join(
                    f"{action}: {count}" for action, count in item.skipped_actions.items()
                ))
            lines.extend(item.issues)
            if item.errors > len(item.issues):
                lines.append("  See the application log for further row errors.")
        if self.error:
            lines.append(self.error)
        if self.comparisons:
            lines.append("Conflict comparisons are available for this run only.")
        return "\n".join(lines)


class Trading212Sync:
    def __init__(
        self, database_path: str, connection: Trading212Connection, *,
        refresh_years: tuple[int, ...] = (), cancel_event: Event | None = None,
        on_progress: Callable[[SyncProgress], None] | None = None,
        api_factory: Callable[..., Trading212API] = Trading212API,
    ) -> None:
        self.database_path = database_path
        self.connection = connection
        self.refresh_years = refresh_years
        self.cancel_event = cancel_event if cancel_event is not None else Event()
        self.on_progress = on_progress
        self.api_factory = api_factory

    def _emit(self, progress: SyncProgress) -> None:
        if self.on_progress is not None:
            self.on_progress(progress)

    def run(self) -> SyncResult:
        result = SyncResult()
        database = DatabaseManager()
        current_year: int | None = None
        current_report: ArchivedCSV | None = None
        current_key: str | None = None
        importing = False
        imported: set[tuple[int, str]] = set()
        attempted_at: str | None = None

        def api_progress(progress: APIProgress) -> None:
            nonlocal current_year
            if progress.year is not None:
                current_year = progress.year
            self._emit(SyncProgress(progress.phase, current_year, wait_seconds=progress.wait_seconds))

        def state_key(report: ArchivedCSV) -> str:
            if type(report.year) is not int or not 1 <= report.year <= Trading212API.current_archive_year():
                raise ValueError("Invalid verified report year")
            if not re.fullmatch(r"[a-f0-9]{64}", report.sha256):
                raise ValueError("Invalid verified report hash")
            return f"trading212.import.{report.year}.{report.sha256}"

        def save_status(key: str, status: str, meta: ImportResult | None = None) -> None:
            now = datetime.now(timezone.utc).isoformat()
            payload: dict[str, object] = {
                "version": _STATE_VERSION, "status": status,
                "attempted_at": attempted_at, "updated_at": now,
            }
            if status == "complete":
                payload["completed_at"] = now
            if meta is not None:
                payload.update(
                    processed=meta["processed"], records=meta["records"],
                    added=sum(meta["added"].values()), duplicates=sum(meta["duplicates"].values()),
                    failed=sum(meta["failed"].values()),
                )
            database.set_setting(key, json.dumps(payload), "Trading212 report import status (no row details)")

        def import_report(report: ArchivedCSV, *, refreshed: bool) -> None:
            nonlocal current_report, current_key, importing, current_year, attempted_at
            if self.cancel_event.is_set():
                raise InterruptedError("Synchronization cancelled")
            if report.year < self.connection.first_year:
                return
            identity = (report.year, report.sha256)
            if identity in imported:
                result.reports = [
                    replace(item, report=report) if (item.report.year, item.report.sha256) == identity else item
                    for item in result.reports
                ]
                return
            key = state_key(report)
            previous_text = database.get_setting(key, "")
            if previous_text:
                previous = json.loads(previous_text)
                if (
                    not isinstance(previous, dict) or type(previous.get("version")) is not int
                    or previous.get("version") != _STATE_VERSION
                    or previous.get("status") not in ("running", "complete", "partial", "cancelled", "failed")
                ):
                    raise ValueError("Invalid saved report import status")
                if previous["status"] == "complete" and not refreshed:
                    result.reports = [
                        item for item in result.reports
                        if (item.report.year, item.report.sha256) != identity
                    ]
                    result.reports.append(ReportImport(report, "already imported", {}, 0, 0))
                    return
            current_report, current_key, current_year = report, key, report.year
            attempted_at = datetime.now(timezone.utc).isoformat()
            self._emit(SyncProgress("Reading archived CSV", report.year))
            save_status(key, "running")
            importing = True
            frame = pd.read_csv(report.path)
            final: ImportResult | None = None
            last_update = 0.0
            for meta in database.import_dataframe_batches(frame, batch_size=100, cancel_event=self.cancel_event):
                if meta["status"] != "running":
                    final = meta
                if time.monotonic() - last_update >= 0.1 or meta["status"] != "running":
                    self._emit(SyncProgress("Importing CSV", report.year, meta["processed"], meta["records"]))
                    last_update = time.monotonic()
            if final is None:
                raise RuntimeError("Report import returned no result")
            save_status(key, final["status"], final)
            importing = False
            result.comparisons.extend(build_comparisons(database, frame, final, str(report.path), report.year))
            counts = dict(final["added"])
            counts["duplicates"] = sum(final["duplicates"].values())
            result.reports = [
                item for item in result.reports
                if not (item.report.year == report.year and item.report.sha256 == report.sha256)
            ]
            result.reports.append(ReportImport(
                report, final["status"], counts, final["processed"], final["records"],
                final["unknown_actions"], len(final["errors"]), len(final["conflicts"]),
                final["read"], final["skipped_actions"],
                tuple(f"  Row {issue['row']} ({issue['action']}): {issue['message']}" for issue in final["errors"][:5]),
            ))
            imported.add(identity)
            if final["status"] == "cancelled":
                raise InterruptedError("Synchronization cancelled during import")
            if final["status"] == "partial":
                result.status = "partial"

        try:
            database.open_database(self.database_path)
            if load_connection(database) != self.connection:
                raise ValueError("The database connection settings changed; reopen synchronization")
            api = self.api_factory(
                environment=self.connection.environment, account_id=self.connection.account_id,
                logger=database.logger, on_progress=api_progress,
            )
            if api.verify_account(cancel_event=self.cancel_event) != self.connection.account_id:
                raise ValueError("Trading212 account does not match the database")
            api.get_archived_csvs(
                self.connection.archive_directory, cancel_event=self.cancel_event,
                on_report=lambda report: import_report(report, refreshed=False),
            )
            api.sync_yearly_csv(
                self.connection.archive_directory, self.connection.first_year,
                refresh_years=self.refresh_years, cancel_event=self.cancel_event,
                on_report=lambda report: import_report(report, refreshed=report.year in self.refresh_years),
            )
            if self.cancel_event.is_set():
                result.status = "cancelled"
        except Exception as error:
            result.status = "cancelled" if isinstance(error, InterruptedError) else "failed"
            result.error = str(error)
            database.logger.error("Trading212 synchronization %s: %s", result.status, error)
            if importing and current_report is not None and current_key is not None and database.conn is not None:
                result.reports.append(ReportImport(current_report, result.status, {}, 0, 0))
                try:
                    save_status(current_key, result.status)
                except (ValueError, sqlite3.Error, OSError) as state_error:
                    database.logger.error("Could not save final import status: %s", state_error)
                    result.error += f"\nCould not save final import status: {state_error}"
        finally:
            database.close()
        return result
