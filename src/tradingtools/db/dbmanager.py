import sqlite3
import os

import time
import math
import tempfile
from pathlib import Path
from contextlib import contextmanager
from numbers import Real
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo
from threading import Event
from typing import Optional, Tuple, Dict, List, Iterator, Generator, Literal, TypedDict
import pandas as pd
from tradingtools.config.cnb_rate import cnb_rate
import logging
from tradingtools.config.logger_config import setup_logger
from tradingtools.db.repositories.securities import SecuritiesRepository
from tradingtools.db.repositories.interests import InterestsRepository, InterestType
from tradingtools.db.repositories.dividends import DividendsRepository
from tradingtools.db.repositories.fees import FeesRepository, FeeType
from tradingtools.db.repositories.trades import TradesRepository, TradeType
from tradingtools.db.repositories.pairings import PairingsRepository
from tradingtools.db.decorators import requires_connection, requires_repo
from tradingtools.db.import_identity import ImportConflict, ImportIdentity, LegacySourceRequired


class ImportIssue(TypedDict):
    row: int
    action: str
    message: str


class ImportResult(TypedDict):
    records: int
    columns: List[str]
    processed: int
    status: Literal["running", "complete", "partial", "cancelled"]
    read: Dict[str, int]
    added: Dict[str, int]
    duplicates: Dict[str, int]
    failed: Dict[str, int]
    errors: List[ImportIssue]
    unknown_actions: Dict[str, int]
    skipped_actions: Dict[str, int]
    conflicts: List[ImportIssue]


class ReconciliationResult(TypedDict):
    linked: int
    conflicts: List[ImportIssue]
    status: Literal["complete", "partial"]


class DatabaseManager:
    """Simple SQLite database manager.

    Responsibilities:
    - Manage a sqlite3 connection and current database path
    - Provide create/open/save/save-as operations
    - Import pandas DataFrame into the DB
    """

    # Current schema version of the database
    CURRENT_VERSION = 2

    def __init__(self) -> None:
        self.conn: Optional[sqlite3.Connection] = None
        self.current_db_path: Optional[str] = None
        self._rates = cnb_rate()
        self.use_annual_rates = False  # False = daily CNB rates, True = annual GFŘ rates
        self.logger = setup_logger('trading_tools.db')
        # repository instances (created when a connection exists)
        self.securities_repo: Optional[SecuritiesRepository] = None
        self.interests_repo: Optional[InterestsRepository] = None
        self.dividends_repo: Optional[DividendsRepository] = None
        self.fees_repo: Optional[FeesRepository] = None
        self.trades_repo: Optional[TradesRepository] = None
        self.pairings_repo: Optional[PairingsRepository] = None
        
    def get_db_version(self) -> int:
        """Get the current database schema version."""
        if not self.conn:
            raise RuntimeError("No open database to check version")
        
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT MAX(version) FROM versions")
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            # versions table doesn't exist yet
            return 0

    def create_versions_table(self) -> None:
        """Create the versions table to track schema changes."""
        if not self.conn:
            raise RuntimeError("No open database connection")
            
        sql = (
            "CREATE TABLE IF NOT EXISTS versions ("
            "version INTEGER NOT NULL, "
            "timestamp TEXT DEFAULT CURRENT_TIMESTAMP, "
            "description TEXT"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        self.conn.commit()
    
    def create_settings_table(self) -> None:
        """Create the settings table to store database configuration."""
        if not self.conn:
            raise RuntimeError("No open database connection")
            
        sql = (
            "CREATE TABLE IF NOT EXISTS settings ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL, "
            "description TEXT"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        self.conn.commit()
    
    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """Get a setting value from the database."""
        if not self.conn:
            return default
            
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default
        except sqlite3.OperationalError:
            # settings table doesn't exist yet
            return default
    
    def set_setting(self, key: str, value: str, description: str = None) -> None:
        """Set a setting value in the database."""
        if not self.conn:
            raise RuntimeError("No open database connection")
            
        sql = "INSERT OR REPLACE INTO settings (key, value, description) VALUES (?, ?, ?)"
        cur = self.conn.cursor()
        cur.execute(sql, (key, value, description))
        self.conn.commit()
        
    def update_db_version(self, version: int, description: str) -> None:
        """Record a new database version."""
        if not self.conn:
            raise RuntimeError("No open database connection")
            
        sql = "INSERT INTO versions (version, description) VALUES (?, ?)"
        cur = self.conn.cursor()
        cur.execute(sql, (version, description))
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None
                self.current_db_path = None

    def create_database(self, file_path: str) -> None:
        self.logger.info(f"Creating new database at {file_path}")
        # close existing
        self.close()
        # create/connect with foreign key support
        self.conn = sqlite3.connect(file_path)
        self.conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        self.current_db_path = file_path
        self.logger.debug("Enabled foreign key constraints")

        existing_version = self.get_db_version()
        if existing_version:
            self.open_database(file_path)
            return

        # initialize database schema
        self.create_versions_table()
        self.create_settings_table()
        
        # Store exchange rate mode setting
        rate_mode = "annual" if self.use_annual_rates else "daily"
        self.set_setting(
            "exchange_rate_mode",
            rate_mode,
            "Exchange rate calculation method: 'daily' for CNB daily rates, 'annual' for GFŘ annual rates"
        )
        
        # instantiate repositories now that connection exists
        self.securities_repo = SecuritiesRepository(self.conn, self.logger)
        self.interests_repo = InterestsRepository(self.conn, self.logger)
        self.dividends_repo = DividendsRepository(self.conn, self.logger)
        self.fees_repo = FeesRepository(self.conn, self.logger)
        self.trades_repo = TradesRepository(self.conn, self.logger)
        self.pairings_repo = PairingsRepository(self.conn, self.logger)
        # create tables through repositories
        self.create_securities_table()
        self.create_interests_table()
        self.create_dividends_table()
        self.fees_repo.create_table()
        self.create_trades_table()
        self.create_pairings_table()
        self.conn.execute(ImportIdentity.SCHEMA)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_source ON csv_identities(category,source)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_csv_legacy_source ON csv_identities(category,legacy_source)")
        self.conn.commit()
        
        # Create annual rates table if using annual exchange rates
        if self.use_annual_rates:
            self.create_annual_rates_table()
        
        # record initial version
        if self.get_db_version() == 0:
            self.update_db_version(
                self.CURRENT_VERSION,
                "Initial schema including CSV source identities and standalone fees"
            )

    def open_database(self, file_path: str) -> None:
        """Open an existing database and verify its version is compatible."""
        # close existing
        self.close()
        self.conn = sqlite3.connect(file_path)
        self.conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        self.current_db_path = file_path
        self.logger.debug("Enabled foreign key constraints")
        
        # Load exchange rate mode from database
        rate_mode = self.get_setting("exchange_rate_mode", "daily")
        self.use_annual_rates = (rate_mode == "annual")
        self.logger.info(f"Loaded exchange rate mode: {rate_mode}")
        
        # instantiate repositories for the open connection
        self.securities_repo = SecuritiesRepository(self.conn, self.logger)
        self.interests_repo = InterestsRepository(self.conn, self.logger)
        self.dividends_repo = DividendsRepository(self.conn, self.logger)
        self.fees_repo = FeesRepository(self.conn, self.logger)
        self.trades_repo = TradesRepository(self.conn, self.logger)
        self.pairings_repo = PairingsRepository(self.conn, self.logger)
        
        # Check version compatibility
        db_version = self.get_db_version()
        if db_version > self.CURRENT_VERSION:
            self.close()
            raise RuntimeError(
                f"Database version {db_version} is newer than supported version "
                f"{self.CURRENT_VERSION}. Please update the application."
            )
        if db_version < self.CURRENT_VERSION:
            try:
                self._migrate_csv_identities(db_version)
            except Exception:
                self.logger.exception("Database identity migration failed")
                self.close()
                raise

    def _backup_before_identity_migration(self) -> Path:
        if self.conn is None or self.current_db_path is None:
            raise RuntimeError("No database to back up")
        if self.current_db_path == ":memory:":
            raise RuntimeError("Persist the legacy database before identity migration")
        path = Path(self.current_db_path)
        descriptor, name = tempfile.mkstemp(
            prefix=path.name + ".pre-v2-", suffix=".bak", dir=path.resolve().parent,
        )
        os.close(descriptor)
        backup = Path(name)
        target: sqlite3.Connection | None = None
        try:
            target = sqlite3.connect(backup)
            with target:
                self.conn.backup(target)
        except Exception:
            if target is not None:
                target.close()
                target = None
            backup.unlink()
            raise
        finally:
            if target is not None:
                target.close()
        self.logger.info("Saved pre-migration database backup: %s", backup)
        return backup

    def _migrate_csv_identities(self, version: int) -> None:
        if self.conn is None:
            raise RuntimeError("No database to migrate")
        if version != 1:
            raise RuntimeError(f"No supported identity migration from schema version {version}")
        if self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='dividends'"
        ).fetchone():
            raise RuntimeError("Custom dividend triggers require manual migration")
        backup = self._backup_before_identity_migration()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            indexes = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='dividends' AND sql IS NOT NULL"
            ).fetchall()
            sequence = self.conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='dividends'"
            ).fetchone()
            self.conn.execute(DividendsRepository.TABLE_SQL.format(table="dividends_v2"))
            self.conn.execute("INSERT INTO dividends_v2 SELECT * FROM dividends")
            self.conn.execute("DROP TABLE dividends")
            self.conn.execute("ALTER TABLE dividends_v2 RENAME TO dividends")
            if sequence is not None:
                self.conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name='dividends'", sequence)
            for (sql,) in indexes:
                self.conn.execute(sql)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dividends_timestamp ON dividends(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dividends_isin_id ON dividends(isin_id)")
            self.conn.execute(ImportIdentity.SCHEMA)
            self.conn.execute("CREATE INDEX idx_csv_source ON csv_identities(category,source)")
            self.conn.execute("CREATE INDEX idx_csv_legacy_source ON csv_identities(category,legacy_source)")
            self.conn.execute(FeesRepository.TABLE_SQL)
            self.conn.execute("CREATE INDEX idx_fees_timestamp ON fees(timestamp)")
            self.conn.execute("CREATE INDEX idx_fees_isin_id ON fees(isin_id)")
            if self.conn.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Foreign-key validation failed during identity migration")
            self.conn.execute(
                "INSERT INTO versions(version,description) VALUES(?,?)",
                (2, "CSV source identities; distinct same-time dividends; standalone fees"),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            self.logger.error("Migration rolled back; original backup retained at %s", backup)
            raise

    @contextmanager
    def _csv_transaction(self) -> Generator[None, None, None]:
        if self.conn is None:
            raise RuntimeError("No open database for CSV transaction")
        if self.conn.in_transaction:
            raise RuntimeError("Finish the pending transaction before importing CSV")
        repositories = [
            repo for repo in (
                self.securities_repo, self.trades_repo, self.interests_repo, self.dividends_repo,
                self.fees_repo,
            ) if repo is not None
        ]
        previous = [repo.defer_commit for repo in repositories]
        try:
            for repo in repositories:
                repo.defer_commit = True
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                yield
        finally:
            for repo, deferred in zip(repositories, previous):
                repo.defer_commit = deferred

    def release_database(self) -> None:
        self.logger.info(f"Database release requested for {self.current_db_path}")
        if not self.conn:
            raise RuntimeError("No open database to release")
        self.close()

    def save_database_as(self, file_path: str) -> None:
        if not self.conn:
            raise RuntimeError("No open database to save")

        # Create new connection and copy contents using backup
        new_conn = sqlite3.connect(file_path)
        try:
            with new_conn:
                # Use the sqlite3 backup API
                self.conn.backup(new_conn)
        finally:
            # switch to the new connection
            self.close()
            self.conn = new_conn
            self.current_db_path = file_path

    def get_all_years_with_data(self) -> list:
        """Return a sorted list of all years (int) with any data in dividends, interests, or trades tables."""
        if not self.conn:
            return []
        years = set()
        cur = self.conn.cursor()
        # Dividends
        try:
            cur.execute("SELECT DISTINCT strftime('%Y', datetime(timestamp, 'unixepoch')) FROM dividends")
            years.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
        except Exception:
            pass
        # Interests
        try:
            cur.execute("SELECT DISTINCT strftime('%Y', datetime(timestamp, 'unixepoch')) FROM interests")
            years.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
        except Exception:
            pass
        # Trades
        try:
            cur.execute("SELECT DISTINCT strftime('%Y', datetime(timestamp, 'unixepoch')) FROM trades")
            years.update(int(row[0]) for row in cur.fetchall() if row[0] is not None)
        except Exception:
            pass
        return sorted(years)

    ###########################################################################
    ## Exchange Rate Helper
    ###########################################################################
    def get_exchange_rate(self, currency: str, dt: datetime) -> float:
        """Get exchange rate for currency at given datetime.
        
        Uses either daily CNB rates or annual GFŘ rates based on use_annual_rates setting.
        For annual rates, validates that the rate exists in the database.
        
        Args:
            currency: Three-letter currency code
            dt: Datetime for the transaction
            
        Returns:
            Exchange rate (CZK per 1 unit of currency)
            
        Raises:
            ValueError: If annual rate is not found in database
        """
        if self.use_annual_rates:
            # Use annual GFŘ rate from database
            year = dt.year
            rate = self.get_annual_rate_from_db(currency, year)
            if rate is None:
                raise ValueError(
                    f"Annual exchange rate for {currency} in year {year} not found in database. "
                    f"Please import exchange rates for year {year} before importing transactions."
                )
            return rate
        else:
            # Use daily CNB rate
            return self._rates.daily_rate(currency, dt)

    ###########################################################################
    ## Importing DataFrames and managing tables
    ###########################################################################
    def import_dataframe(
        self, df: pd.DataFrame, *, cancel_event: Event | None = None,
    ) -> ImportResult:
        """Import all rows and return the final cumulative result."""
        for result in self.import_dataframe_batches(df, cancel_event=cancel_event):
            if result["status"] != "running":
                return result
        raise RuntimeError("CSV import did not produce a final result")

    def import_dataframe_batches(
        self, df: pd.DataFrame, *, batch_size: int = 100,
        cancel_event: Event | None = None,
    ) -> Iterator[ImportResult]:
        """Yield cumulative snapshots between execution batches; rows commit separately."""
        if not self.conn:
            self.logger.error("Attempted to import DataFrame without database connection")
            raise RuntimeError("No open database to import into")
        if type(batch_size) is not int or batch_size <= 0:
            self.logger.error("Invalid CSV import batch size")
            raise ValueError("CSV import batch size must be a positive integer")
        if (
            not df.columns.is_unique or "Action" not in df.columns
            or not ("Time" in df.columns or "Time (UTC)" in df.columns)
        ):
            self.logger.error("CSV import requires unique columns, Action and Time or Time (UTC)")
            raise ValueError("CSV import requires unique columns, Action and Time or Time (UTC)")

        categories = ("buy", "sell", "interest", "dividend", "fee")
        result: ImportResult = {
            "records": len(df), "columns": list(df.columns), "processed": 0, "status": "running",
            "read": dict.fromkeys((*categories, "insignificant", "unknown"), 0),
            "added": dict.fromkeys(categories, 0),
            "duplicates": dict.fromkeys(categories, 0),
            "failed": dict.fromkeys((*categories, "unknown"), 0),
            "errors": [], "unknown_actions": {}, "skipped_actions": {}, "conflicts": [],
        }
        ambiguous_sources = self._ambiguous_anonymous_sources(df, cancel_event)
        self.logger.info("Starting import of DataFrame with %d rows", len(df))
        for position, (_, row) in enumerate(df.iterrows(), start=1):
            if cancel_event is not None and cancel_event.is_set():
                result["status"] = "cancelled"
                break
            action = ""
            category = "unknown"
            try:
                action = self._csv_text(row, "Action", required=True)
                category = self._csv_category(action)
                result["read"][category] += 1
                if category in ("unknown", "insignificant"):
                    counts = result["unknown_actions"] if category == "unknown" else result["skipped_actions"]
                    counts[action] = counts.get(action, 0) + 1
                    if category == "unknown":
                        self.logger.warning("Row %d: unsupported action '%s', skipping", position, action)
                    else:
                        self.logger.info("Row %d: %s (insignificant), skipping", position, action)
                else:
                    if category in ambiguous_sources:
                        if ImportIdentity.encode(self._csv_source(row, category)) in ambiguous_sources[category]:
                            raise ImportConflict(f"Indistinguishable no-ID {category} events occur more than once in this CSV")
                    inserted = self._import_csv_row(row, category)
                    counts = result["added"] if inserted else result["duplicates"]
                    counts[category] += 1
            except (ValueError, TypeError, sqlite3.Error, OSError) as error:
                if isinstance(error, sqlite3.Error) and self.conn is not None:
                    self.conn.rollback()
                if not action:
                    result["read"][category] += 1
                result["failed"][category] += 1
                issue: ImportIssue = {"row": position, "action": action, "message": str(error)}
                result["errors"].append(issue)
                if isinstance(error, ImportConflict):
                    result["conflicts"].append(issue)
                self.logger.error("Failed to import row %d (%s): %s", position, action, error)
            result["processed"] += 1
            if position % batch_size == 0 and position < len(df):
                yield deepcopy(result)
        if result["status"] != "cancelled":
            result["status"] = "partial" if result["errors"] or result["unknown_actions"] else "complete"
        self.logger.info(
            "CSV import %s: %d/%d rows processed, %d added, %d duplicates, %d failed, %d unsupported",
            result["status"], result["processed"], result["records"],
            sum(result["added"].values()), sum(result["duplicates"].values()),
            len(result["errors"]), result["read"]["unknown"],
        )
        yield deepcopy(result)

    @staticmethod
    def _csv_category(action: str) -> str:
        if action in ("Market buy", "Limit buy", "Stock split open"):
            return "buy"
        if action in ("Market sell", "Limit sell", "Stock split close"):
            return "sell"
        if action in ("Interest on cash", "Lending interest"):
            return "interest"
        if action in ("Dividend (Dividend)", "Dividend (Dividend manufactured payment)"):
            return "dividend"
        if action == "ADR Fee":
            return "fee"
        if action in ("Deposit", "Currency conversion", "Card debit", "Withdrawal", "Result adjustment"):
            return "insignificant"
        return "unknown"

    @staticmethod
    def _csv_text(row: pd.Series, key: str, *, required: bool = False) -> str:
        raw = row.get(key)
        if raw is None or pd.isna(raw) or raw == "":
            if required:
                raise ValueError(f"Missing {key}")
            return ""
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"Invalid {key}: expected non-empty text")
        return raw

    @staticmethod
    def _csv_number(row: pd.Series, key: str, *, required: bool = False) -> float:
        raw = row.get(key)
        if raw is None or pd.isna(raw) or raw == "":
            if required:
                raise ValueError(f"Missing {key}")
            return 0.0
        if isinstance(raw, bool) or not isinstance(raw, (str, Real)):
            raise ValueError(f"Invalid numeric {key}")
        try:
            value = float(raw)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid numeric {key}") from None
        if not math.isfinite(value):
            raise ValueError(f"Non-finite numeric {key}")
        return value

    def _csv_source(
        self, row: pd.Series, category: str, *, source_timezone: str | None = None,
    ) -> dict[str, object]:
        time_str = self._csv_text(row, "Time") or self._csv_text(row, "Time (UTC)", required=True)
        total, currency = self.safe_csv_read(row, "Total", "Currency (Total)", required=True)
        source: dict[str, object] = {
            "Action": self._csv_text(row, "Action", required=True),
            "time": ImportIdentity.source_time(time_str, source_timezone),
            "Total": total, "Currency (Total)": currency,
        }
        if category == "fee":
            source["ISIN"] = self._csv_text(row, "ISIN") or None
            for field in ("No. of shares", "Price / share"):
                raw = row.get(field)
                source[field] = (
                    None if raw is None or pd.isna(raw) or raw == "" else self._csv_number(row, field)
                )
            source["Currency (Price / share)"] = self._csv_text(row, "Currency (Price / share)") or None
            return source
        if category == "interest":
            note = self._csv_text(row, "Notes")
            source["interest_type"] = (
                1 if note == "Interest on cash" else 2 if note == "Share lending interest" else 0
            )
            return source

        source["ISIN"] = self._csv_text(row, "ISIN", required=True)
        source["No. of shares"] = self._csv_number(row, "No. of shares", required=True)
        amount, currency = self.safe_csv_read(row, "Price / share", "Currency (Price / share)", required=True)
        source["Price / share"], source["Currency (Price / share)"] = amount, currency
        optional = (
            ("Withholding tax",) if category == "dividend" else
            ("Stamp duty reserve tax", "Currency conversion fee", "French transaction tax")
        )
        for field in optional:
            amount, currency = self.safe_csv_read(row, field, f"Currency ({field})")
            source[field] = amount
            source[f"Currency ({field})"] = currency if amount else "CZK"
        return source

    def _ambiguous_anonymous_sources(
        self, df: pd.DataFrame, cancel_event: Event | None = None,
    ) -> dict[str, set[str]]:
        counts: Dict[tuple[str, str], int] = {}
        anonymous: set[tuple[str, str]] = set()
        for _, row in df.iterrows():
            if cancel_event is not None and cancel_event.is_set():
                break
            try:
                category = self._csv_category(self._csv_text(row, "Action"))
                if category not in ("dividend", "fee"):
                    continue
                key = (category, ImportIdentity.encode(self._csv_source(row, category)))
                counts[key] = counts.get(key, 0) + 1
                if not self._csv_text(row, "ID"):
                    anonymous.add(key)
            except (ValueError, TypeError):
                # The normal row path reports invalid fields with their row position.
                continue
        return {
            category: {source for kind, source in anonymous if kind == category and counts[(kind, source)] > 1}
            for category in ("dividend", "fee")
        }

    def _import_csv_row(self, row: pd.Series, category: str) -> int:
        if self.conn is None:
            raise RuntimeError("No open database for CSV identity check")
        source = self._csv_source(row, category)
        broker_id = self._csv_text(row, "ID", required=category not in ("dividend", "fee")) or None
        identity = ImportIdentity(self.conn)

        def link_legacy(candidates: list[int], timestamp: int) -> int:
            if not candidates:
                raise ImportConflict(
                    f"Legacy {category} timestamp differs; explicit source timezone reconciliation is required"
                )
            expected = self._legacy_csv_values(row, category, timestamp, None)
            matching = [
                record_id for record_id in candidates if identity.matches_values(category, record_id, expected)
            ]
            if len(matching) != 1:
                raise ImportConflict(
                    f"Legacy {category} does not uniquely match CSV values; original rates and contents must be verified"
                )
            identity.remember(category, matching[0], broker_id, source)
            self.logger.info("Verified original CSV for legacy %s record %d", category, matching[0])
            return 0

        with self._csv_transaction():
            time_str = self._csv_text(row, "Time") or self._csv_text(row, "Time (UTC)", required=True)
            try:
                if identity.match(category, broker_id, source) is not None:
                    return 0
            except LegacySourceRequired:
                timestamp = self.timestr_to_timestamp(time_str)
                legacy_rows = self.conn.execute(
                    f"SELECT d.id FROM {identity.TABLES[category]} d "
                    "LEFT JOIN securities s ON s.id=d.isin_id "
                    "LEFT JOIN csv_identities i ON i.category=? AND i.record_id=d.id "
                    "WHERE i.record_id IS NULL AND d.timestamp=? AND s.isin IS ?",
                    (category, timestamp, source["ISIN"]),
                ).fetchall()
                return link_legacy([record_id for (record_id,) in legacy_rows], timestamp)
            if category in ("buy", "sell", "interest"):
                table = identity.TABLES[category]
                legacy = self.conn.execute(
                    f"SELECT id,timestamp FROM {table} WHERE id_string=?", (broker_id,),
                ).fetchone()
                if legacy is not None:
                    timestamp = self.timestr_to_timestamp(time_str)
                    if legacy[1] != timestamp:
                        raise ImportConflict("Legacy transaction timestamp differs; explicit source timezone reconciliation is required")
                    return link_legacy([legacy[0]], timestamp)
            inserted = self._insert_csv_row(row, category)
            if not inserted:
                raise ImportConflict("An existing transaction has no matching source identity")
            record_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            identity.remember(category, record_id, broker_id, source)
        return inserted

    def _insert_csv_row(self, row: pd.Series, category: str) -> int:
        time_str = self._csv_text(row, "Time") or self._csv_text(row, "Time (UTC)", required=True)
        timestamp = self.timestr_to_timestamp(time_str)
        total, currency_of_total = self.safe_csv_read(row, "Total", "Currency (Total)", required=True)
        self.logger.info("Importing %s at %s", category, time_str)
        if category == "fee":
            if self.fees_repo is None:
                raise RuntimeError("Fee repository is unavailable")
            isin = self._csv_text(row, "ISIN")
            isin_id = (
                self.get_or_create_securities_id(
                    isin, self._csv_text(row, "Ticker"), self._csv_text(row, "Name"),
                ) if isin else None
            )
            total_czk = total * self.get_exchange_rate(currency_of_total, datetime.fromtimestamp(timestamp))
            return self.fees_repo.insert(timestamp, FeeType.ADR, isin_id, total, currency_of_total, total_czk)
        if category == "interest":
            note = self._csv_text(row, "Notes")
            if note == "Interest on cash":
                interest_type = InterestType.CASH_INTEREST
            elif note == "Share lending interest":
                interest_type = InterestType.LENDING_INTEREST
            else:
                interest_type = InterestType.UNKNOWN
            return self.insert_interest(
                timestamp, interest_type, self._csv_text(row, "ID", required=True),
                total, currency_of_total,
            )
        isin = self._csv_text(row, "ISIN", required=True)
        ticker = self._csv_text(row, "Ticker")
        name = self._csv_text(row, "Name")
        number_of_shares = self._csv_number(row, "No. of shares", required=True)
        price, currency_of_price = self.safe_csv_read(
            row, "Price / share", "Currency (Price / share)", required=True,
        )
        if category == "dividend":
            tax, tax_currency = self.safe_csv_read(row, "Withholding tax", "Currency (Withholding tax)")
            return self.insert_dividend(
                timestamp, isin, ticker, name, number_of_shares, price, currency_of_price,
                total, currency_of_total, tax, tax_currency, distinct_event=True,
            )
        id_string = self._csv_text(row, "ID", required=True)
        stamp_tax, stamp_currency = self.safe_csv_read(row, "Stamp duty reserve tax", "Currency (Stamp duty reserve tax)")
        fee, fee_currency = self.safe_csv_read(row, "Currency conversion fee", "Currency (Currency conversion fee)")
        french_tax, french_currency = self.safe_csv_read(row, "French transaction tax", "Currency (French transaction tax)")
        return self.insert_trade(
            timestamp, isin, ticker, name, id_string,
            TradeType.BUY if category == "buy" else TradeType.SELL,
            number_of_shares if category == "buy" else -number_of_shares,
            price, currency_of_price, -total if category == "buy" else total, currency_of_total,
            -stamp_tax, stamp_currency, -fee, fee_currency, -french_tax, french_currency,
        )

    def reconcile_legacy_dataframe(
        self, df: pd.DataFrame, *, source_timezone: str, imported_timezone: str,
    ) -> ReconciliationResult:
        """Attach proven original CSV sources; never change transaction values or times."""
        if self.conn is None:
            raise RuntimeError("No open database for source reconciliation")
        ZoneInfo(source_timezone)
        ZoneInfo(imported_timezone)
        if not df.columns.is_unique or "Action" not in df or not ("Time" in df or "Time (UTC)" in df):
            raise ValueError("Original CSV needs unique columns, Action and Time or Time (UTC)")
        identity = ImportIdentity(self.conn)
        linked = 0
        conflicts: List[ImportIssue] = []
        ambiguous_sources = self._ambiguous_anonymous_sources(df)
        for position, (_, row) in enumerate(df.iterrows(), start=1):
            action = ""
            try:
                action = self._csv_text(row, "Action", required=True)
                category = self._csv_category(action)
                if category == "unknown":
                    raise ImportConflict("Unsupported action in original CSV")
                if category not in identity.TABLES:
                    continue
                original = self._csv_source(row, category)
                broker_id = self._csv_text(row, "ID", required=category not in ("dividend", "fee")) or None
                if identity.encode(original) in ambiguous_sources.get(category, set()):
                    raise ImportConflict("Original CSV contains indistinguishable no-ID events")
                source = self._csv_source(row, category, source_timezone=source_timezone)
                text = self._csv_text(row, "Time") or self._csv_text(row, "Time (UTC)", required=True)
                date = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if date.utcoffset() is None:
                    date = identity.localize(date, imported_timezone)
                timestamp = int(date.timestamp())
                with self._csv_transaction():
                    if category == "fee":
                        candidates = self.conn.execute(
                            "SELECT f.id FROM fees f LEFT JOIN securities s ON s.id=f.isin_id "
                            "LEFT JOIN csv_identities i ON i.category='fee' AND i.record_id=f.id "
                            "WHERE f.timestamp=? AND s.isin IS ? "
                            "AND (? IS NULL OR i.broker_id IS NULL OR i.broker_id=?)",
                            (timestamp, source["ISIN"], broker_id, broker_id),
                        ).fetchall()
                        if not candidates:
                            raise ImportConflict("Fee has no historical record; import its original CSV normally")
                    elif category == "dividend":
                        candidates = self.conn.execute(
                            "SELECT d.id FROM dividends d JOIN securities s ON s.id=d.isin_id "
                            "WHERE d.timestamp=? AND s.isin=?",
                            (timestamp, source["ISIN"]),
                        ).fetchall()
                    else:
                        candidates = self.conn.execute(
                            f"SELECT id FROM {identity.TABLES[category]} WHERE id_string=? AND timestamp=?",
                            (broker_id, timestamp),
                        ).fetchall()
                    expected = self._legacy_csv_values(row, category, timestamp, imported_timezone)
                    matching = [
                        record_id for (record_id,) in candidates
                        if identity.matches_values(category, record_id, expected)
                    ]
                    if len(matching) != 1:
                        raise ImportConflict("Original CSV does not uniquely match an unchanged local transaction")
                    record_id = matching[0]
                    previous = self.conn.execute(
                        "SELECT record_id,broker_id,source,stored FROM csv_identities "
                        "WHERE category=? AND record_id=?", (category, record_id),
                    ).fetchone()
                    if previous is not None:
                        identity.check_stored(category, previous)
                        if previous[2] not in (identity.encode(original), identity.encode(source)):
                            raise ImportConflict("A different original source is already linked to this transaction")
                        if broker_id is not None and previous[1] not in (None, broker_id):
                            raise ImportConflict("Another broker ID is already linked to this transaction")
                        self.conn.execute(
                            "UPDATE csv_identities SET source=?,broker_id=COALESCE(broker_id,?),"
                            "legacy_source=CASE WHEN ?<>? THEN ? ELSE legacy_source END "
                            "WHERE category=? AND record_id=?",
                            (identity.encode(source), broker_id, identity.encode(original),
                             identity.encode(source), identity.encode(original), category, record_id),
                        )
                    else:
                        identity.remember(category, record_id, broker_id, source)
                        if original != source:
                            self.conn.execute(
                                "UPDATE csv_identities SET legacy_source=? WHERE category=? AND record_id=?",
                                (identity.encode(original), category, record_id),
                            )
                linked += 1
            except (ValueError, TypeError, sqlite3.Error, OSError) as error:
                issue: ImportIssue = {"row": position, "action": action, "message": str(error)}
                conflicts.append(issue)
                self.logger.error("Source reconciliation conflict at row %d: %s", position, error)
        return {"linked": linked, "conflicts": conflicts, "status": "partial" if conflicts else "complete"}

    def _legacy_csv_values(
        self, row: pd.Series, category: str, timestamp: int, imported_timezone: str | None,
    ) -> dict[str, object]:
        date = (
            datetime.fromtimestamp(timestamp, ZoneInfo(imported_timezone)).replace(tzinfo=None)
            if imported_timezone is not None else datetime.fromtimestamp(timestamp)
        )

        def converted(field: str, *, required: bool = False) -> float:
            amount, currency = self.safe_csv_read(row, field, f"Currency ({field})", required=required)
            return amount * self.get_exchange_rate(currency, date)

        values: dict[str, object] = {"timestamp": timestamp}
        total = converted("Total", required=True)
        if category == "fee":
            if self.conn is None:
                raise RuntimeError("No open database for source reconciliation")
            isin = self._csv_text(row, "ISIN")
            security = self.conn.execute("SELECT id FROM securities WHERE isin=?", (isin,)).fetchone() if isin else None
            if isin and security is None:
                raise ImportConflict("Original CSV security is not present in the database")
            amount, currency = self.safe_csv_read(row, "Total", "Currency (Total)", required=True)
            values.update(
                type=int(FeeType.ADR), isin_id=security[0] if security else None,
                amount=amount, currency=currency, total_czk=total,
            )
            return values
        if category == "interest":
            note = self._csv_text(row, "Notes")
            values.update(
                type=1 if note == "Interest on cash" else 2 if note == "Share lending interest" else 0,
                id_string=self._csv_text(row, "ID", required=True), total_czk=total,
            )
            return values
        if self.conn is None:
            raise RuntimeError("No open database for source reconciliation")
        security = self.conn.execute(
            "SELECT id FROM securities WHERE isin=?", (self._csv_text(row, "ISIN", required=True),),
        ).fetchone()
        if security is None:
            raise ImportConflict("Original CSV security is not present in the database")
        price, currency = self.safe_csv_read(row, "Price / share", "Currency (Price / share)", required=True)
        shares = self._csv_number(row, "No. of shares", required=True)
        values.update(isin_id=security[0], price_for_share=price, currency_of_price=currency)
        if category == "dividend":
            tax = converted("Withholding tax")
            values.update(number_of_shares=shares, net_czk=total, gross_czk=total + tax, withholding_tax_czk=tax)
        else:
            values.update(
                id_string=self._csv_text(row, "ID", required=True),
                trade_type=int(TradeType.BUY if category == "buy" else TradeType.SELL),
                number_of_shares=shares if category == "buy" else -shares,
                total_czk=-total if category == "buy" else total,
                stamp_tax_czk=-converted("Stamp duty reserve tax"),
                conversion_fee_czk=-converted("Currency conversion fee"),
                french_transaction_tax_czk=-converted("French transaction tax"),
            )
        return values
    
    @staticmethod
    def safe_csv_read(
        row: pd.Series, val_key: str, curr_key: str, *, required: bool = False,
    ) -> Tuple[float, str]:
        """Read a finite amount; only absent optional amounts default to zero/CZK."""
        value = DatabaseManager._csv_number(row, val_key, required=required)
        currency = DatabaseManager._csv_text(row, curr_key, required=required or value != 0)
        return value, currency or "CZK"

    ###########################################################################
    ## Securities
    ###########################################################################

    @requires_connection
    def create_securities_table(self) -> None:
        """Create the `securities` table if it does not exist."""
        self.securities_repo.create_table()


    @requires_connection
    @requires_repo('securities_repo')
    def insert_security(
        self, 
        isin: str, 
        ticker: Optional[str], 
        name: Optional[str]
    ) -> int:
        """Insert a single security into the securities table.

        Args:
            isin: ISIN code (must be non-empty)
            ticker: Optional ticker symbol
            name: Optional security name
        
        Returns:
            Integer id of the securities row.

        Raises:
            RuntimeError: If no database is open
            ValueError: If isin is empty or invalid
            sqlite3.IntegrityError: If isin already exists in the table
            sqlite3.DatabaseError: For other database errors
        """
        return self.securities_repo.insert(isin, ticker, name)

# TODO: Continue here
    @requires_connection
    @requires_repo('securities_repo')
    def get_securities_id(self, isin: str) -> int:
        """Get the `id` for a security by `isin`.

        If a security with the given `isin` exists, return its id.

        Args:
            isin: ISIN code (must be non-empty) if exists.

        Returns:
            Integer id of the securities row.

        Raises:
            RuntimeError: If no database is open
            ValueError: If `isin` is empty
            sqlite3.DatabaseError: For unexpected database errors
        """
        return self.securities_repo.get_id(isin)

    @requires_connection
    @requires_repo('securities_repo')
    def get_or_create_securities_id(self, isin: str, ticker: Optional[str] = None, name: Optional[str] = None) -> int:
        """Get the `id` for a security by `isin`.

        If a security with the given `isin` exists, return its id.
        Otherwise insert a new security (using the optional `ticker` and `name`) and
        return the newly-created id.

        Args:
            isin: ISIN code (must be non-empty)
            ticker: Optional ticker symbol
            name: Optional security name

        Returns:
            Integer id of the securities row.

        Raises:
            RuntimeError: If no database is open
            ValueError: If `isin` is empty
            sqlite3.DatabaseError: For unexpected database errors
        """
        return self.securities_repo.get_or_create(isin, ticker, name)

    ###########################################################################
    ## Interests
    ###########################################################################
    @requires_connection
    def create_interests_table(self) -> None:
        """Create the `interests` table if it does not exist."""
        self.interests_repo.create_table()

    @requires_connection
    @requires_repo('interests_repo')
    def insert_interest(
        self, 
        timestamp: int, 
        type_: InterestType, 
        id_string: str, 
        total: float,
        currency_of_total: str
    ) -> int:
        """Insert a single interest record.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            type_: Interest type from InterestType enum
            id_string: Unique identifier for this interest record
            total: Amount in original currency
            currency_of_total: Currency code for the total amount
            
        Returns:
            Number of rows inserted (1 on success, 0 if duplicate id_string)
            
        Raises:
            ValueError: If timestamp is negative
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        
        dt = datetime.fromtimestamp(timestamp)
        total_czk = total * self.get_exchange_rate(currency_of_total, dt)
        if self.interests_repo is None:
            raise RuntimeError("Interest repository is unavailable")
        return self.interests_repo.insert(timestamp, type_, id_string, total_czk)

    @requires_connection
    @requires_repo('interests_repo')
    def get_interests_by_date_range(
        self, 
        start_timestamp: int, 
        end_timestamp: int
    ) -> List[Tuple]:
        """Get interests within the given timestamp range.
        
        Args:
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            List of (id, timestamp, type, id_string, total_czk) tuples
        """
        return self.interests_repo.get_by_date_range(start_timestamp, end_timestamp)

    ###########################################################################
    ## Dividends
    ###########################################################################
    @requires_connection
    @requires_repo('dividends_repo')
    def create_dividends_table(self) -> None:
        """Create the `dividends` table if it does not exist."""
        self.dividends_repo.create_table()
        
    @requires_connection
    @requires_repo('dividends_repo')
    def insert_dividend(
        self,
        timestamp: int,
        isin: str,
        ticker: str, 
        name: str,
        number_of_shares: float,
        price_for_share: float,
        currency_of_price: str,
        total: float,
        currency_of_total: str,
        withholding_tax: float,
        currency_of_withholding_tax: str,
        *,
        distinct_event: bool = False,
    ) -> int:
        """Insert a single dividend record.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            isin: ISIN string for the security
            ticker: Ticker symbol
            name: Security name
            number_of_shares: Number of shares for dividend
            price_for_share: Price per share in original currency
            currency_of_price: Currency code of price_for_share
            total: Total amount in original currency
            currency_of_total: Currency code for total
            withholding_tax: Withholding tax in original currency
            currency_of_withholding_tax: Currency code for withholding tax

        Returns:
            Number of rows inserted (1 on success, 0 for the existing timestamp/ISIN).

        Raises:
            sqlite3.IntegrityError: If isin_id doesn't exist in securities table
            ValueError: If timestamp is negative or any numeric value is negative
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")

        # Convert currencies to CZK
        ts_dt = datetime.fromtimestamp(timestamp)
        net_czk = total * self.get_exchange_rate(currency_of_total, ts_dt)
        withholding_tax_czk = withholding_tax * self.get_exchange_rate(currency_of_withholding_tax, ts_dt)
        gross_czk = net_czk + withholding_tax_czk

        # Get or create the security ID
        isin_id = self.get_or_create_securities_id(isin, ticker, name)

        # Insert via repository
        if self.dividends_repo is None:
            raise RuntimeError("Dividend repository is unavailable")
        return self.dividends_repo.insert(
            timestamp=timestamp,
            isin_id=isin_id,
            number_of_shares=number_of_shares,
            price_for_share=price_for_share,
            currency_of_price=currency_of_price,
            gross_czk=gross_czk,
            net_czk=net_czk,
            withholding_tax_czk=withholding_tax_czk,
            distinct_event=distinct_event,
        )
        
    ###########################################################################
    ## Trades
    ###########################################################################

    @requires_connection
    @requires_repo('trades_repo')
    def create_trades_table(self) -> None:
        """Create the `trades` table if it does not exist (delegates to repository)."""
        self.trades_repo.create_table()

    @requires_connection
    @requires_repo('pairings_repo')
    def create_pairings_table(self) -> None:
        """Create the `pairings` table if it does not exist (delegates to repository)."""
        self.pairings_repo.create_table()

    @requires_connection
    @requires_repo('trades_repo')
    def insert_trade(
        self,
        timestamp: int,
        isin: str,
        ticker: str,
        name: str,
        id_string: str,
        trade_type: TradeType,
        number_of_shares: float,
        price_for_share: float,
        currency_of_price: str,
        total: float,
        currency_of_total: str,
        stamp_tax: float,
        currency_of_stamp_tax: str,
        conversion_fee: float,
        currency_of_conversion_fee: str,
        french_transaction_tax: float,
        currency_of_french_transaction_tax: str
    ) -> int:
        """Insert a single trade record (delegates to TradesRepository).

        Returns the inserted trade row ID, or zero for a duplicate broker ID.
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not id_string:
            raise ValueError("id_string must be provided and non-empty")

        # calculate values to CZK
        dt = datetime.fromtimestamp(timestamp)
        total_czk = total * self.get_exchange_rate(currency_of_total, dt)
        stamp_tax_czk = stamp_tax * self.get_exchange_rate(currency_of_stamp_tax, dt)
        conversion_fee_czk = conversion_fee * self.get_exchange_rate(currency_of_conversion_fee, dt)
        french_transaction_tax_czk = french_transaction_tax * self.get_exchange_rate(currency_of_french_transaction_tax, dt)

        isin_id = self.get_or_create_securities_id(isin, ticker, name)

        # Delegate actual insert to repository which returns row id
        if self.trades_repo is None:
            raise RuntimeError("Trade repository is unavailable")
        return self.trades_repo.insert(
            timestamp=timestamp,
            isin_id=isin_id,
            id_string=id_string,
            trade_type=trade_type,
            number_of_shares=number_of_shares,
            price_for_share=price_for_share,
            currency_of_price=currency_of_price,
            total_czk=total_czk,
            stamp_tax_czk=stamp_tax_czk,
            conversion_fee_czk=conversion_fee_czk,
            french_transaction_tax_czk=french_transaction_tax_czk,
        )

    ###########################################################################
    ## Annual Exchange Rates (for databases using annual GFŘ rates)
    ###########################################################################

    @requires_connection
    def create_annual_rates_table(self) -> None:
        """Create the `annual_rates` table for storing GFŘ unified annual rates.
        
        This table stores annual exchange rates (jednotný kurz) from GFŘ.
        Each rate represents the arithmetic mean of daily CNB rates for the entire year.
        """
        sql = (
            "CREATE TABLE IF NOT EXISTS annual_rates ("
            "year INTEGER NOT NULL, "
            "currency TEXT NOT NULL, "
            "amount INTEGER NOT NULL, "
            "rate REAL NOT NULL, "
            "country TEXT, "
            "PRIMARY KEY (year, currency)"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        self.conn.commit()
        self.logger.info("Created annual_rates table")

    @requires_connection
    def get_annual_rate_from_db(self, currency: str, year: int) -> Optional[float]:
        """Get annual exchange rate from database.
        
        Args:
            currency: Three-letter currency code
            year: Year for the rate
            
        Returns:
            Exchange rate (CZK per 1 unit of currency), or None if not found
        """
        sql = "SELECT rate, amount FROM annual_rates WHERE currency = ? AND year = ?"
        cur = self.conn.cursor()
        cur.execute(sql, (currency, year))
        row = cur.fetchone()
        if row:
            rate, amount = row
            # Return rate per 1 unit of currency
            return rate / amount
        return None

    @requires_connection
    def insert_annual_rate(self, year: int, currency: str, amount: int, rate: float, country: str = None) -> None:
        """Insert or update annual exchange rate.
        
        Args:
            year: Year for the rate
            currency: Three-letter currency code
            amount: Number of currency units (e.g., 1 for USD, 100 for JPY)
            rate: Exchange rate in CZK for the specified amount
            country: Optional country name
        """
        sql = "INSERT OR REPLACE INTO annual_rates (year, currency, amount, rate, country) VALUES (?, ?, ?, ?, ?)"
        cur = self.conn.cursor()
        cur.execute(sql, (year, currency, amount, rate, country))
        self.conn.commit()
        self.logger.debug(f"Inserted annual rate: {year} {currency} {amount}={rate} CZK")

    @requires_connection
    def get_all_annual_rates_for_year(self, year: int) -> List[Tuple[str, int, float, Optional[str]]]:
        """Get all annual exchange rates for a specific year.
        
        Args:
            year: Year to query
            
        Returns:
            List of tuples: (currency, amount, rate, country)
        """
        sql = "SELECT currency, amount, rate, country FROM annual_rates WHERE year = ? ORDER BY currency"
        cur = self.conn.cursor()
        cur.execute(sql, (year,))
        return cur.fetchall()

    @requires_connection
    def get_available_annual_rate_years(self) -> List[int]:
        """Get list of years for which annual rates are available.
        
        Returns:
            List of years, sorted ascending
        """
        sql = "SELECT DISTINCT year FROM annual_rates ORDER BY year"
        cur = self.conn.cursor()
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]

    def import_annual_rates_from_file(self, file_path: str, year: int) -> Dict[str, object]:
        """Import annual exchange rates from GFŘ text file.
        
        Expected format (both '.' and ',' work as decimal separator):
        Austrálie dolar 1 AUD 15,31
        Brazílie real 1 BRL 4,29
        EMU euro 1 EUR 25,16
        Japonsko jen 100 JPY 15,35
        
        Args:
            file_path: Path to the text file
            year: Year for these rates
            
        Returns:
            Dict with import statistics: {'imported': int, 'skipped': int, 'errors': List[str]}
        """
        if not self.conn:
            raise RuntimeError("No open database to import into")
        
        if not self.use_annual_rates:
            raise RuntimeError("Cannot import annual rates into database configured for daily rates")
        
        self.logger.info(f"Importing annual rates from {file_path} for year {year}")
        
        imported = 0
        skipped = 0
        errors = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        # Parse line: "Country name amount CURRENCY rate"
                        # Example: "Austrálie dolar 1 AUD 15,31"
                        parts = line.split()
                        if len(parts) < 3:
                            errors.append(f"Line {line_num}: Invalid format (too few parts): {line}")
                            skipped += 1
                            continue
                        
                        # Currency code is the second-to-last part
                        currency = parts[-2]
                        
                        # Rate is the last part (replace comma with dot)
                        rate_str = parts[-1].replace(',', '.')
                        rate = float(rate_str)
                        
                        # Amount is the third-to-last part
                        amount = int(parts[-3])
                        
                        # Country name is everything before amount
                        country = ' '.join(parts[:-3])
                        
                        # Insert into database
                        self.insert_annual_rate(year, currency, amount, rate, country)
                        imported += 1
                        
                    except ValueError as e:
                        errors.append(f"Line {line_num}: Parse error: {e} - {line}")
                        skipped += 1
                    except Exception as e:
                        errors.append(f"Line {line_num}: Unexpected error: {e} - {line}")
                        skipped += 1
        
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading file: {e}")
        
        self.logger.info(f"Import complete: {imported} rates imported, {skipped} skipped")
        if errors:
            for error in errors[:10]:  # Log first 10 errors
                self.logger.warning(error)
        
        return {
            'imported': imported,
            'skipped': skipped,
            'errors': errors
        }

    ###########################################################################
    ## Helper functions
    ###########################################################################
    @staticmethod
    def datetime_to_timestamp(dt: datetime) -> int:
        """Convert Python datetime to Unix timestamp."""
        return int(dt.timestamp())

    @staticmethod
    def timestamp_to_datetime(ts: int) -> datetime:
        """Convert Unix timestamp to Python datetime."""
        return datetime.fromtimestamp(ts)

    @staticmethod
    def timestr_to_timestamp(timestr: str) -> int:
        """Convert a datetime string to Unix timestamp.
        
        Args:
            timestr: String in one of supported formats:
                    - "YYYY-MM-DD HH:MM:SS" (legacy)
                    - "YYYY-MM-DD HH:MM:SS+00:00" (UTC export)
                    e.g., "2023-12-07 16:01:12"
                          "2026-01-05 08:00:33+00:00"
            
        Returns:
            Unix timestamp (seconds since epoch)
            
        Raises:
            ValueError: If the string format is invalid
        """
        # Legacy broker export format
        try:
            dt = datetime.strptime(timestr, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        except ValueError:
            pass

        # Newer broker export format (UTC with offset)
        try:
            dt = datetime.fromisoformat(timestr)
            return int(dt.timestamp())
        except ValueError as e:
            raise ValueError(
                f"Invalid datetime string format. Expected 'YYYY-MM-DD HH:MM:SS' or ISO datetime with offset, got '{timestr}'"
            ) from e
