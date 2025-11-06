import sqlite3
import os

import time
from datetime import datetime
from typing import Optional, Tuple, Dict, List
import pandas as pd
from cnb_rate import cnb_rate
import logging
from logger_config import setup_logger
from db.repositories.securities import SecuritiesRepository
from db.repositories.interests import InterestsRepository, InterestType
from db.repositories.dividends import DividendsRepository
from db.decorators import requires_connection, requires_repo




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
        self.logger = setup_logger('trading_tools.db')
        # repository instances (created when a connection exists)
        self.securities_repo: Optional[SecuritiesRepository] = None
        self.interests_repo: Optional[InterestsRepository] = None
        self.dividends_repo: Optional[DividendsRepository] = None
        
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
        # instantiate repositories now that connection exists
        self.securities_repo = SecuritiesRepository(self.conn, self.logger)
        self.interests_repo = InterestsRepository(self.conn, self.logger)
        self.dividends_repo = DividendsRepository(self.conn, self.logger)
        # create tables through repositories
        self.create_securities_table()
        self.create_interests_table()
        self.create_dividends_table()
        self.create_trades_table()
        
        # record initial version
        if self.get_db_version() == 0:
            self.update_db_version(
                self.CURRENT_VERSION,
                "Initial schema: versions, securities, and interests tables"
            )

    def open_database(self, file_path: str) -> None:
        """Open an existing database and verify its version is compatible."""
        # close existing
        self.close()
        self.conn = sqlite3.connect(file_path)
        self.current_db_path = file_path
        # instantiate repositories for the open connection
        self.securities_repo = SecuritiesRepository(self.conn, self.logger)
        self.interests_repo = InterestsRepository(self.conn, self.logger)
        self.dividends_repo = DividendsRepository(self.conn, self.logger)
        
        # Check version compatibility
        db_version = self.get_db_version()
        if db_version > self.CURRENT_VERSION:
            raise RuntimeError(
                f"Database version {db_version} is newer than supported version "
                f"{self.CURRENT_VERSION}. Please update the application."
            )
        # Future: elif db_version < self.CURRENT_VERSION:
        #     self.migrate_database(from_version=db_version)

    def save_database(self) -> None:
        if not self.conn:
            raise RuntimeError("No open database to save")
        self.conn.commit()

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

    ###########################################################################
    ## Importing DataFrames and managing tables
    ###########################################################################
    def import_dataframe(self, df: pd.DataFrame) -> Dict[str, object]:
        """Import a pandas DataFrame into the open DB as table_name.

        Returns metadata dict: { 'table': str, 'records': int, 'columns': List[str] }
        """
        if not self.conn:
            self.logger.error("Attempted to import DataFrame without database connection")
            raise RuntimeError("No open database to import into")
            
        self.logger.info(f"Starting import of DataFrame with {len(df)} rows")

        # Counters for read rows from CSV
        read_buy = 0
        read_sell = 0
        read_interest = 0
        read_dividend = 0
        read_insignificant = 0
        read_unknown = 0

        # Counters for successfully added records
        added_buy = 0
        added_sell = 0
        added_interest = 0
        added_dividend = 0

        for index, row in df.iterrows():
            # Safe access to columns whether row is Series or dict-like
            action = row.get('Action') if hasattr(row, 'get') else row['Action']
            time_str = row.get('Time') if hasattr(row, 'get') else row['Time']

            # Try to convert time string to timestamp for logging
            ts = None
            if time_str:
                try:
                    ts = DatabaseManager.timestr_to_timestamp(time_str)
                except ValueError:
                    ts = None

            # Process row based on action type
            if action in ("Market buy", "Limit buy", "Stock split open"):
                read_buy += 1
                print(f"Row {index}: {action} at {time_str} (ts={ts})")
                # TODO: Implement buy handling
                # added_buy += result_of_insert
            elif action in ("Market sell", "Limit sell", "Stock split close"):
                read_sell += 1
                print(f"Row {index}: {action} at {time_str} (ts={ts})")
                # TODO: Implement sell handling
                # added_sell += result_of_insert
            elif action in ("Interest on cash", "Lending interest"):
                read_interest += 1
                if row['Notes'] in ("Interest on cash"):
                    interest_type = InterestType.CASH_INTEREST
                elif row['Notes'] in ("Share lending interest"):
                    interest_type = InterestType.LENDING_INTEREST
                else:
                    interest_type = InterestType.UNKNOWN
                rows_inserted = self.insert_interest(ts, interest_type, row['ID'], row['Total'], row['Currency (Total)'])
                added_interest += rows_inserted
                print(f"Row {index}: {action} at {time_str} (ts={ts})")
            elif action in ("Dividend (Dividend)", "Dividend (Dividend manufactured payment)"):
                read_dividend += 1
                print(f"Row {index}: {action} at {time_str} (ts={ts})")
                # TODO: Implement dividend handling
                # added_dividend += result_of_insert
            elif action in ("Deposit", "Currency conversion", "Card debit", "Withdrawal", "Result adjustment"):
                read_insignificant += 1
                print(f"Row {index}: {action} (insignificant) at {time_str} (ts={ts})")
                # These are not stored in DB
            else:
                read_unknown += 1

        results = {
            "records": int(len(df)),
            "columns": list(df.columns),
            "read": {
                "buy": read_buy,
                "sell": read_sell,
                "interest": read_interest,
                "dividend": read_dividend,
                "insignificant": read_insignificant,
                "unknown": read_unknown,
            },
            "added": {
                "buy": added_buy,
                "sell": added_sell,
                "interest": added_interest,
                "dividend": added_dividend,
            },
        }
        
        self.logger.info(
            "Import complete: %d records processed (%d buys, %d sells, %d interests, %d dividends, %d other)",
            len(df), read_buy, read_sell, read_interest, read_dividend, read_insignificant + read_unknown
        )
        self.logger.info(
            "Records added to DB: %d buys, %d sells, %d interests, %d dividends",
            added_buy, added_sell, added_interest, added_dividend
        )
        
        return results

    ###########################################################################
    ## Securities
    ###########################################################################

    def create_securities_table(self) -> None:
        """Create the `securities` table with columns:

        - id INTEGER PRIMARY KEY AUTOINCREMENT
        - isin TEXT NOT NULL UNIQUE
        - ticker TEXT
        - name TEXT

        The table will be created if it does not already exist.
        """
        if not self.conn:
            raise RuntimeError("No open database to create table in")

        sql = (
            "CREATE TABLE IF NOT EXISTS securities ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "isin TEXT NOT NULL UNIQUE, "
            "ticker TEXT, "
            "name TEXT"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        self.conn.commit()

    def insert_security(self, isin: str, ticker: str | None, name: str | None) -> int:
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
        if not self.conn:
            self.logger.error("Attempted to insert security without database connection")
            raise RuntimeError("No open database to insert into")
        if not isin:
            self.logger.error("Attempted to insert security with empty ISIN")
            raise ValueError("isin must be provided")
        if not isinstance(isin, str):
            self.logger.error(f"Invalid ISIN type: {type(isin)}")
            raise ValueError("isin must be a string")
            
        self.logger.debug(f"Inserting security: ISIN={isin}, ticker={ticker}, name={name}")
        
        try:
            sql = "INSERT OR IGNORE INTO securities (isin, ticker, name) VALUES (?, ?, ?)"
            cur = self.conn.cursor()
            cur.execute(sql, (isin, ticker, name))
            self.conn.commit()
            inserted_id = cur.lastrowid
            self.logger.info(f"Inserted security {isin} with ID {inserted_id}")
            return inserted_id
        except sqlite3.IntegrityError as e:
            self.logger.warning(f"Attempted to insert duplicate security with ISIN {isin}")
            raise sqlite3.IntegrityError(f"Security with ISIN '{isin}' already exists") from e
        except sqlite3.Error as e:
            self.logger.error(f"Database error inserting security {isin}: {e}")
            raise sqlite3.DatabaseError(f"Failed to insert security: {e}") from e

    def insert_many_securities(self, rows) -> int:
        """Insert multiple securities. `rows` is an iterable of (isin, ticker, name).

        Returns number of rows inserted.
        """
        if not self.conn:
            raise RuntimeError("No open database to insert into")

        sql = "INSERT OR IGNORE INTO securities (isin, ticker, name) VALUES (?, ?, ?)"
        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        self.conn.commit()
        return cur.rowcount

    def get_securities_id(self, isin: str, ticker: str | None = None, name: str | None = None) -> int:
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
        if not self.conn:
            raise RuntimeError("No open database to query/insert into")
        if not isin:
            raise ValueError("`isin` must be provided")

        cur = self.conn.cursor()
        # Try to find existing
        cur.execute("SELECT id FROM securities WHERE isin = ?", (isin,))
        row = cur.fetchone()
        if row:
            return row[0]

        # Not found — insert. 
        return self.insert_security(isin, ticker, name)

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
        
        total_czk = total * self._rates.daily_rate(currency_of_total, datetime.fromtimestamp(timestamp))
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
    ) -> None:
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
            
        Raises:
            sqlite3.IntegrityError: If isin_id doesn't exist in securities table
            ValueError: If timestamp is negative or any numeric value is negative
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")

        # Convert currencies to CZK
        ts_dt = datetime.fromtimestamp(timestamp)
        total_czk = total * self._rates.daily_rate(currency_of_total, ts_dt)
        withholding_tax_czk = withholding_tax * self._rates.daily_rate(currency_of_withholding_tax, ts_dt)

        # Get or create the security ID
        isin_id = self.get_securities_id(isin, ticker, name)

        # Insert via repository
        self.dividends_repo.insert(
            timestamp=timestamp,
            isin_id=isin_id,
            number_of_shares=number_of_shares,
            price_for_share=price_for_share,
            currency_of_price=currency_of_price,
            total_czk=total_czk,
            withholding_tax_czk=withholding_tax_czk
        )
        
    ###########################################################################
    ## Trades
    ###########################################################################

    def create_trades_table(self) -> None:
        """Create the `trades` table with the requested columns.

        Columns:
        - id INTEGER PRIMARY KEY AUTOINCREMENT
        - timestamp INTEGER NOT NULL (Unix timestamp)
        - isin_id INTEGER NOT NULL REFERENCES securities(id)
        - id_string TEXT NOT NULL UNIQUE
        - number_of_shares REAL NOT NULL
        - price_for_share REAL NOT NULL
        - currency_of_price TEXT NOT NULL 
        - total_czk REAL NOT NULL
        - stamp_tax_czk REAL DEFAULT 0
        - conversion_fee_czk REAL DEFAULT 0
        - french_transaction_tax_czk REAL DEFAULT 0
        """
        if not self.conn:
            raise RuntimeError("No open database to create table in")

        sql = (
            "CREATE TABLE IF NOT EXISTS trades ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "
            "isin_id INTEGER NOT NULL, "
            "id_string TEXT NOT NULL UNIQUE, "
            "number_of_shares REAL NOT NULL, "
            "price_for_share REAL NOT NULL, "
            "currency_of_price TEXT NOT NULL, "
            "total_czk REAL NOT NULL, "
            "stamp_tax_czk REAL DEFAULT 0, "
            "conversion_fee_czk REAL DEFAULT 0, "
            "french_transaction_tax_czk REAL DEFAULT 0, "
            "FOREIGN KEY (isin_id) REFERENCES securities(id) ON DELETE RESTRICT"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        # Indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_isin_id ON trades(isin_id)")
        self.conn.commit()

    def insert_trade(
        self,
        timestamp: int,
        isin: str,
        ticker: str,
        name: str,
        id_string: str,
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
        """Insert a single trade record.

        Returns the inserted trade row id.
        """
        if not self.conn:
            raise RuntimeError("No open database to insert into")
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if any(v < 0 for v in [number_of_shares, price_for_share, total_czk, stamp_tax_czk, conversion_fee_czk, french_transaction_tax_czk]):
            raise ValueError("Numeric trade values must be non-negative")
        if not id_string:
            raise ValueError("id_string must be provided and non-empty")

        # Resolve isin_id from an ISIN string
        isin_id = self.get_securities_id(isin, ticker, name)

        # calculate values to CZK
        dt = datetime.fromtimestamp(timestamp)
        total_czk = total * self._rates.daily_rate(currency_of_total, dt)
        stamp_tax_czk = stamp_tax * self._rates.daily_rate(currency_of_stamp_tax, dt)
        conversion_fee_czk = conversion_fee * self._rates.daily_rate(currency_of_conversion_fee, dt)
        french_transaction_tax_czk = french_transaction_tax * self._rates.daily_rate(currency_of_french_transaction_tax, dt)


        sql = (
            "INSERT OR IGNORE INTO trades (timestamp, isin_id, id_string, number_of_shares, "
            "price_for_share, currency_of_price, total_czk, stamp_tax_czk, conversion_fee_czk, "
            "french_transaction_tax_czk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        cur = self.conn.cursor()
        cur.execute(sql, (
            timestamp, isin_id, id_string, number_of_shares,
            price_for_share, currency_of_price, total_czk, stamp_tax_czk,
            conversion_fee_czk, french_transaction_tax_czk
        ))
        self.conn.commit()
        return cur.lastrowid

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
            timestr: String in format "YYYY-MM-DD HH:MM:SS"
                    e.g., "2023-12-07 16:01:12"
            
        Returns:
            Unix timestamp (seconds since epoch)
            
        Raises:
            ValueError: If the string format is invalid
        """
        try:
            dt = datetime.strptime(timestr, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())
        except ValueError as e:
            raise ValueError(
                f"Invalid datetime string format. Expected 'YYYY-MM-DD HH:MM:SS', got '{timestr}'"
            ) from e
