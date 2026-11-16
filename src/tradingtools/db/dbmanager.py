import sqlite3
import os

import time
import math
from numbers import Real
from copy import deepcopy
from datetime import datetime
from threading import Event
from typing import Optional, Tuple, Dict, List, Iterator, Literal, TypedDict
import pandas as pd
from tradingtools.config.cnb_rate import cnb_rate
import logging
from tradingtools.config.logger_config import setup_logger
from tradingtools.db.repositories.securities import SecuritiesRepository
from tradingtools.db.repositories.interests import InterestsRepository, InterestType
from tradingtools.db.repositories.dividends import DividendsRepository
from tradingtools.db.repositories.trades import TradesRepository, TradeType
from tradingtools.db.repositories.pairings import PairingsRepository
from tradingtools.db.decorators import requires_connection, requires_repo


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



class DatabaseManager:
    """Simple SQLite database manager.

    Responsibilities:
    - Manage a sqlite3 connection and current database path
    - Provide create/open/save/save-as operations
    - Import pandas DataFrame into the DB
    """

    # Current schema version of the database
    CURRENT_VERSION = 1

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
        self.trades_repo: Optional[TradesRepository] = None
        self.pairings_repo: Optional[PairingsRepository] = None
        
    def get_db_version(self) -> int:
        """Get the current database schema version."""
        if not self.conn:
            raise RuntimeError("No open database to check version")
        
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT version FROM versions ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else 0
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
        self.trades_repo = TradesRepository(self.conn, self.logger)
        self.pairings_repo = PairingsRepository(self.conn, self.logger)
        # create tables through repositories
        self.create_securities_table()
        self.create_interests_table()
        self.create_dividends_table()
        self.create_trades_table()
        self.create_pairings_table()
        
        # Create annual rates table if using annual exchange rates
        if self.use_annual_rates:
            self.create_annual_rates_table()
        
        # record initial version
        if self.get_db_version() == 0:
            self.update_db_version(
                self.CURRENT_VERSION,
                "Initial schema: versions, settings, securities, and interests tables"
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
        self.trades_repo = TradesRepository(self.conn, self.logger)
        self.pairings_repo = PairingsRepository(self.conn, self.logger)
        
        # Check version compatibility
        db_version = self.get_db_version()
        if db_version > self.CURRENT_VERSION:
            raise RuntimeError(
                f"Database version {db_version} is newer than supported version "
                f"{self.CURRENT_VERSION}. Please update the application."
            )
        # Future: elif db_version < self.CURRENT_VERSION:
        #     self.migrate_database(from_version=db_version)

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

        categories = ("buy", "sell", "interest", "dividend")
        result: ImportResult = {
            "records": len(df), "columns": list(df.columns), "processed": 0, "status": "running",
            "read": dict.fromkeys((*categories, "insignificant", "unknown"), 0),
            "added": dict.fromkeys(categories, 0),
            "duplicates": dict.fromkeys(categories, 0),
            "failed": dict.fromkeys((*categories, "unknown"), 0),
            "errors": [], "unknown_actions": {}, "skipped_actions": {},
        }
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
                    inserted = self._import_csv_row(row, category)
                    counts = result["added"] if inserted else result["duplicates"]
                    counts[category] += 1
            except (ValueError, TypeError, sqlite3.Error, OSError) as error:
                if isinstance(error, sqlite3.Error) and self.conn is not None:
                    self.conn.rollback()
                if not action:
                    result["read"][category] += 1
                result["failed"][category] += 1
                result["errors"].append({"row": position, "action": action, "message": str(error)})
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

    def _import_csv_row(self, row: pd.Series, category: str) -> int:
        time_str = self._csv_text(row, "Time") or self._csv_text(row, "Time (UTC)", required=True)
        timestamp = self.timestr_to_timestamp(time_str)
        total, currency_of_total = self.safe_csv_read(row, "Total", "Currency (Total)", required=True)
        self.logger.info("Importing %s at %s", category, time_str)
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
                total, currency_of_total, tax, tax_currency,
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
        currency_of_withholding_tax: str
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
            withholding_tax_czk=withholding_tax_czk
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
