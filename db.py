import sqlite3
import os
import enum
import time
from datetime import datetime
from typing import Optional, Tuple, Dict, List
import pandas as pd
import cnb_exchange_rate

class InterestType(enum.IntEnum):
    """Types of interest entries in the database."""
    UNKNOWN = 0
    CASH_INTEREST = 1
    LENDING_INTEREST = 2


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
        # close existing
        self.close()
        # create/connect with foreign key support
        self.conn = sqlite3.connect(file_path)
        self.conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        self.current_db_path = file_path
        
        # initialize database schema
        self.create_versions_table()
        self.create_securities_table()
        self.create_interests_table()
        self.create_dividends_table()
        
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
    def import_dataframe(self, table_name: str, df: pd.DataFrame) -> Dict[str, object]:
        """Import a pandas DataFrame into the open DB as table_name.

        Returns metadata dict: { 'table': str, 'records': int, 'columns': List[str] }
        """
        if not self.conn:
            raise RuntimeError("No open database to import into")

        # Write DataFrame to SQL (replace if exists)
        df.to_sql(table_name, self.conn, if_exists="replace", index=False)
        self.conn.commit()
        return {
            "table": table_name,
            "records": int(len(df)),
            "columns": list(df.columns),
        }

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
            raise RuntimeError("No open database to insert into")
        if not isin:
            raise ValueError("isin must be provided")
        if not isinstance(isin, str):
            raise ValueError("isin must be a string")
        
        try:
            sql = "INSERT INTO securities (isin, ticker, name) VALUES (?, ?, ?)"
            cur = self.conn.cursor()
            cur.execute(sql, (isin, ticker, name))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError as e:
            # Re-raise with more specific message
            raise sqlite3.IntegrityError(f"Security with ISIN '{isin}' already exists") from e
        except sqlite3.Error as e:
            # Wrap other SQLite errors with context
            raise sqlite3.DatabaseError(f"Failed to insert security: {e}") from e

    def insert_many_securities(self, rows) -> int:
        """Insert multiple securities. `rows` is an iterable of (isin, ticker, name).

        Returns number of rows inserted.
        """
        if not self.conn:
            raise RuntimeError("No open database to insert into")

        sql = "INSERT INTO securities (isin, ticker, name) VALUES (?, ?, ?)"
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
    def create_interests_table(self) -> None:
        """Create the `interests` table with columns:

        - id INTEGER PRIMARY KEY AUTOINCREMENT
        - timestamp INTEGER NOT NULL (Unix timestamp, seconds since epoch)
        - type INTEGER NOT NULL (0=unknown, 1=cash interest, 2=lending interest)
        - id_string TEXT UNIQUE
        - total_czk REAL NOT NULL

        The table will be created if it does not already exist.
        """
        if not self.conn:
            raise RuntimeError("No open database to create table in")

        sql = (
            "CREATE TABLE IF NOT EXISTS interests ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "  # Unix timestamp
            "type INTEGER NOT NULL CHECK (type IN (0,1,2)), "
            "id_string TEXT UNIQUE, "
            "total_czk REAL NOT NULL"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        # Create index on timestamp for range queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_interests_timestamp ON interests(timestamp)")
        self.conn.commit()

    def insert_interest(
        self, 
        timestamp: int, 
        type_: InterestType, 
        id_string: str, 
        total_czk: float
    ) -> None:
        """Insert a single interest record.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            type_: Interest type from InterestType enum
            id_string: Unique identifier for this interest record
            total_czk: Amount in CZK
            
        Raises:
            sqlite3.IntegrityError: If id_string already exists
            RuntimeError: If no database is open
            ValueError: If timestamp is negative
        """
        if not self.conn:
            raise RuntimeError("No open database to insert into")
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")

        sql = ("INSERT INTO interests "
               "(timestamp, type, id_string, total_czk) "
               "VALUES (?, ?, ?, ?)")
        
        cur = self.conn.cursor()
        cur.execute(sql, (timestamp, int(type_), id_string, total_czk))
        self.conn.commit()

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
        if not self.conn:
            raise RuntimeError("No open database to query")
            
        sql = ("SELECT id, timestamp, type, id_string, total_czk "
               "FROM interests "
               "WHERE timestamp BETWEEN ? AND ? "
               "ORDER BY timestamp")
               
        cur = self.conn.cursor()
        cur.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    ###########################################################################
    ## Dividends
    ###########################################################################
    def create_dividends_table(self) -> None:
        """Create the dividends table with columns:
        
        - id INTEGER PRIMARY KEY AUTOINCREMENT
        - timestamp INTEGER NOT NULL (Unix timestamp)
        - isin_id INTEGER NOT NULL REFERENCES securities(id)
        - number_of_shares REAL NOT NULL
        - price_for_share REAL NOT NULL
        - currency_of_price TEXT NOT NULL
        - total_czk REAL NOT NULL
        - withholding_tax_czk REAL NOT NULL
        """
        if not self.conn:
            raise RuntimeError("No open database to create table in")
            
        sql = (
            "CREATE TABLE IF NOT EXISTS dividends ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "
            "isin_id INTEGER NOT NULL, "
            "number_of_shares REAL NOT NULL, "
            "price_for_share REAL NOT NULL, "
            "currency_of_price TEXT NOT NULL, "
            "total_czk REAL NOT NULL, "
            "withholding_tax_czk REAL NOT NULL, "
            "FOREIGN KEY (isin_id) REFERENCES securities(id) ON DELETE RESTRICT"
            ")"
        )
        cur = self.conn.cursor()
        cur.execute(sql)
        # Create indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dividends_timestamp ON dividends(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dividends_isin_id ON dividends(isin_id)")
        self.conn.commit()
        
    def insert_dividend(
        self,
        timestamp: int,
        isin: int,
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
            isin_id: Foreign key to securities.id
            number_of_shares: Number of shares for dividend
            price_for_share: Price per share in original currency
            currency_of_price: Currency code of price_for_share
            total_czk: Total amount in CZK
            withholding_tax_czk: Withholding tax amount in CZK
            
        Raises:
            sqlite3.IntegrityError: If isin_id doesn't exist in securities table
            RuntimeError: If no database is open
            ValueError: If timestamp is negative
        """
        if not self.conn:
            raise RuntimeError("No open database to insert into")
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")

        isin_id = self.get_securities_id(isin, ticker, name)

        if (currency_of_total == 'CZK'):
            total_czk = total
        else
            total_czk = total * cnb_exchange_rate.daily_rate(currency_of_total, datetime.fromtimestamp(timestamp))

        if (currency_of_withholding_tax == 'CZK'):
            withholding_tax_czk = withholding_tax
        else:
            withholding_tax_czk = withholding_tax * cnb_exchange_rate.daily_rate(currency_of_withholding_tax, datetime.fromtimestamp(timestamp))

        sql = (
            "INSERT INTO dividends ("
            "timestamp, isin_id, number_of_shares, price_for_share, "
            "currency_of_price, total_czk, withholding_tax_czk"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        
        cur = self.conn.cursor()
        cur.execute(sql, (
            timestamp, isin_id, number_of_shares, price_for_share,
            currency_of_price, total_czk, withholding_tax_czk
        ))
        self.conn.commit()
        
    ###########################################################################
    ## Trades
    ###########################################################################







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



