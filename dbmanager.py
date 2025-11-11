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
from db.repositories.trades import TradesRepository, TradeType
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
        self.trades_repo: Optional[TradesRepository] = None
        
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
        self.trades_repo = TradesRepository(self.conn, self.logger)
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
        self.trades_repo = TradesRepository(self.conn, self.logger)
        
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
                
                # Parse using the exact CSV column names provided
                try:
                    isin = row.get('ISIN') if hasattr(row, 'get') else row['ISIN']
                    ticker = row.get('Ticker') if hasattr(row, 'get') else row['Ticker']
                    name = row.get('Name') if hasattr(row, 'get') else row['Name']
                    id_string = row.get('ID') if hasattr(row, 'get') else row['ID']
                    number_of_shares = float(row.get('No. of shares') if hasattr(row, 'get') else row['No. of shares'])
                    price_for_share, currency_of_price = DatabaseManager.safe_csv_read(row, 'Price / share', 'Currency (Price / share)')
                    total, currency_of_total = DatabaseManager.safe_csv_read(row, 'Total', 'Currency (Total)')
                    total = -total
                    stamp_tax, currency_of_stamp_tax = DatabaseManager.safe_csv_read(row, 'Stamp duty reserve tax', 'Currency (Stamp duty reserve tax)')
                    stamp_tax = -stamp_tax
                    conversion_fee, currency_of_conversion_fee = DatabaseManager.safe_csv_read(row, 'Currency conversion fee', 'Currency (Currency conversion fee)')
                    conversion_fee = -conversion_fee
                    french_transaction_tax, currency_of_french_transaction_tax = DatabaseManager.safe_csv_read(row, 'French transaction tax', 'Currency (French transaction tax)')
                    french_transaction_tax = -french_transaction_tax

                    self.logger.info(f"Importing row {index}: {action} at {time_str} ({ticker} / {number_of_shares} / {price_for_share} {currency_of_price})")

                    # Require ISIN and id_string at minimum for trades
                    if not isin or not id_string:
                        self.logger.warning(f"Row {index}: missing ISIN or ID for trade, skipping")
                    else:
                        try:
                            rowid = self.insert_trade(
                                timestamp=ts,
                                isin=isin,
                                ticker=ticker,
                                name=name,
                                id_string=id_string,
                                trade_type=TradeType.BUY,
                                number_of_shares=number_of_shares,
                                price_for_share=price_for_share,
                                currency_of_price=currency_of_price,
                                total=total,
                                currency_of_total=currency_of_total,
                                stamp_tax=stamp_tax,
                                currency_of_stamp_tax=currency_of_stamp_tax,
                                conversion_fee=conversion_fee,
                                currency_of_conversion_fee=currency_of_conversion_fee,
                                french_transaction_tax=french_transaction_tax,
                                currency_of_french_transaction_tax=currency_of_french_transaction_tax
                            )
                            if rowid:
                                added_buy += 1
                        except Exception as e:
                            self.logger.exception(f"Failed to insert buy trade for row {index}: {e}")
                except Exception as e:
                    self.logger.exception(f"Error parsing buy row {index}: {e}")

            elif action in ("Market sell", "Limit sell", "Stock split close"):
                read_sell += 1

                # Parse using the exact CSV column names for sells (same as buys)
                try:
                    isin = row.get('ISIN') if hasattr(row, 'get') else row['ISIN']
                    ticker = row.get('Ticker') if hasattr(row, 'get') else row['Ticker']
                    name = row.get('Name') if hasattr(row, 'get') else row['Name']
                    id_string = row.get('ID') if hasattr(row, 'get') else row['ID']
                    number_of_shares = -1 * float(row.get('No. of shares') if hasattr(row, 'get') else row['No. of shares'])
                    price_for_share, currency_of_price = DatabaseManager.safe_csv_read(row, 'Price / share', 'Currency (Price / share)')
                    total, currency_of_total = DatabaseManager.safe_csv_read(row, 'Total', 'Currency (Total)')
                    stamp_tax, currency_of_stamp_tax = DatabaseManager.safe_csv_read(row, 'Stamp duty reserve tax', 'Currency (Stamp duty reserve tax)')
                    stamp_tax = -stamp_tax
                    conversion_fee, currency_of_conversion_fee = DatabaseManager.safe_csv_read(row, 'Currency conversion fee', 'Currency (Currency conversion fee)')
                    conversion_fee = -conversion_fee
                    french_transaction_tax, currency_of_french_transaction_tax = DatabaseManager.safe_csv_read(row, 'French transaction tax', 'Currency (French transaction tax)')
                    french_transaction_tax = -french_transaction_tax

                    self.logger.info(f"Importing row {index}: {action} at {time_str} ({ticker} / {number_of_shares} / {price_for_share} {currency_of_price})")

                    if not isin or not id_string:
                        self.logger.warning(f"Row {index}: missing ISIN or ID for trade, skipping")
                    else:
                        try:
                            rowid = self.insert_trade(
                                timestamp=ts,
                                isin=isin,
                                ticker=ticker,
                                name=name,
                                id_string=id_string,
                                trade_type=TradeType.SELL,
                                number_of_shares=number_of_shares,
                                price_for_share=price_for_share,
                                currency_of_price=currency_of_price,
                                total=total,
                                currency_of_total=currency_of_total,
                                stamp_tax=stamp_tax,
                                currency_of_stamp_tax=currency_of_stamp_tax,
                                conversion_fee=conversion_fee,
                                currency_of_conversion_fee=currency_of_conversion_fee,
                                french_transaction_tax=french_transaction_tax,
                                currency_of_french_transaction_tax=currency_of_french_transaction_tax
                            )
                            if rowid:
                                added_sell += 1
                        except Exception as e:
                            self.logger.exception(f"Failed to insert sell trade for row {index}: {e}")
                except Exception as e:
                    self.logger.exception(f"Error parsing sell row {index}: {e}")

            elif action in ("Interest on cash", "Lending interest"):
                read_interest += 1

                # Parse using the exact CSV column names
                try:
                    note = row.get('Notes') if hasattr(row, 'get') else row['Notes']    
                    id_string = row.get('ID') if hasattr(row, 'get') else row['ID']
                    total, currency_of_total = DatabaseManager.safe_csv_read(row, 'Total', 'Currency (Total)')
                    
                    self.logger.info(f"Importing row {index}: {action} at {time_str} ({total} {currency_of_total})")

                    # Determine interest type
                    if note in ("Interest on cash"):
                        interest_type = InterestType.CASH_INTEREST
                    elif note in ("Share lending interest"):
                        interest_type = InterestType.LENDING_INTEREST
                    else:
                        interest_type = InterestType.UNKNOWN
                    
                    # Require ISIN and id_string at minimum for trades
                    if not id_string:
                        self.logger.warning(f"Row {index}: missing ID for interest, skipping")

                    else:
                        try:
                            rowcount = self.insert_interest(
                                timestamp = ts, 
                                type_ = interest_type,
                                id_string = id_string, 
                                total = total,
                                currency_of_total = currency_of_total
                            )
                            if rowcount:
                                added_interest += 1
                            else:
                                # INSERT OR IGNORE may return 0 if duplicate; treat as not added
                                pass
                        except Exception as e:
                            self.logger.exception(f"Failed to insert interest for row {index}: {e}")
                except Exception as e:
                    self.logger.exception(f"Error parsing interest row {index}: {e}")

            elif action in ("Dividend (Dividend)", "Dividend (Dividend manufactured payment)"):
                read_dividend += 1

                # Attempt to extract common dividend fields from the row in a tolerant way
                try:
                    isin = row.get('ISIN') if hasattr(row, 'get') else row['ISIN']
                    ticker = row.get('Ticker') if hasattr(row, 'get') else row['Ticker']
                    name = row.get('Name') if hasattr(row, 'get') else row['Name']

                    number_of_shares = float(row.get('No. of shares') if hasattr(row, 'get') else row['No. of shares'])
                    price_for_share, currency_of_price = DatabaseManager.safe_csv_read(row, 'Price / share', 'Currency (Price / share)')
                    total, currency_of_total = DatabaseManager.safe_csv_read(row, 'Total', 'Currency (Total)')
                    withholding_tax = float(row.get('Withholding tax') if hasattr(row, 'get') else row['Withholding tax']) if (row.get('Withholding tax') if hasattr(row, 'get') else row['Withholding tax']) else 0.0
                    currency_of_withholding_tax = row.get('Currency (Withholding tax)') if hasattr(row, 'get') else row['Currency (Withholding tax)']

                    self.logger.info(f"Importing row {index}: {action} at {time_str} ({ticker} / {number_of_shares} / {total} {currency_of_total})")

                    # Validate we have at least an ISIN and timestamp
                    if not isin:
                        self.logger.warning(f"Row {index}: missing ISIN, skipping dividend row")
                    else:
                        try:
                            rowcount = self.insert_dividend(
                                timestamp=ts,
                                isin=isin,
                                ticker=ticker,
                                name=name,
                                number_of_shares=number_of_shares,
                                price_for_share=price_for_share,
                                currency_of_price=currency_of_price,
                                total=total,
                                currency_of_total=currency_of_total,
                                withholding_tax=withholding_tax,
                                currency_of_withholding_tax=currency_of_withholding_tax
                            )
                            if rowcount:
                                added_dividend += 1
                            else:
                                # INSERT OR IGNORE may return 0 if duplicate; treat as not added
                                pass
                        except Exception as e:
                            self.logger.exception(f"Failed to insert dividend for row {index}: {e}")
                except Exception as e:
                    self.logger.exception(f"Error parsing dividend row {index}: {e}")
            elif action in ("Deposit", "Currency conversion", "Card debit", "Withdrawal", "Result adjustment"):
                read_insignificant += 1
                self.logger.info(f"Row {index}: {action} (insignificant) at {time_str}, skipping")
                # These are not stored in DB
            else:
                self.logger.warning(f"Row {index}: unknown action '{action}' at {time_str}, skipping")
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
    
    @staticmethod
    def safe_csv_read(row: pd.Series, val_key: str, curr_key: str) -> Tuple[float, str]:
        """
        Safely reads a numeric value and its currency from a CSV row, providing 
        defaults (0.0 and 'CZK') for missing or invalid data.
        
        This replaces the complex conditional expressions for optional fields like 
        taxes and fees.

        Args:
            row: Pandas Series or dict-like object representing the CSV row.
            val_key: The key for the numeric value (e.g., 'Stamp duty reserve tax').
            curr_key: The key for the currency (e.g., 'Currency (Stamp duty reserve tax)').

        Returns:
            A tuple: (float value, str currency).
        """
        
        # --- Helper for safe row retrieval ---
        def _get_raw(key):
            # Use .get() if available (works for Series and dicts)
            if hasattr(row, 'get'):
                return row.get(key)
            # Fallback for direct access
            return row[key]

        # 1. Retrieve raw values
        raw_val = _get_raw(val_key)
        raw_curr = _get_raw(curr_key)

        # 2. Sanitize value to float
        # Check for pandas NaN (pd.isna) or Python falsy values (e.g., None, empty string '')
        if pd.isna(raw_val) or not raw_val:
            return 0.0, 'CZK'
        else:
            # Value is present and not NaN, attempt float conversion
            try:
                value_out = float(raw_val)
            except (ValueError, TypeError):
                # Fallback if the non-empty value can't be converted (e.g., junk string)
                value_out = 0.0

        # 3. Sanitize currency to string (defaults to 'CZK')
        currency_out = str(raw_curr or 'CZK')

        return value_out, currency_out    

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
        isin_id = self.get_or_create_securities_id(isin, ticker, name)

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

    @requires_connection
    @requires_repo('trades_repo')
    def create_trades_table(self) -> None:
        """Create the `trades` table if it does not exist (delegates to repository)."""
        self.trades_repo.create_table()

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

        Returns the inserted trade row id.
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not id_string:
            raise ValueError("id_string must be provided and non-empty")

        # Resolve isin_id from an ISIN string
        isin_id = self.get_or_create_securities_id(isin, ticker, name)

        # calculate values to CZK
        dt = datetime.fromtimestamp(timestamp)
        total_czk = total * self._rates.daily_rate(currency_of_total, dt)
        stamp_tax_czk = stamp_tax * self._rates.daily_rate(currency_of_stamp_tax, dt)
        conversion_fee_czk = conversion_fee * self._rates.daily_rate(currency_of_conversion_fee, dt)
        french_transaction_tax_czk = french_transaction_tax * self._rates.daily_rate(currency_of_french_transaction_tax, dt)

        # Delegate actual insert to repository which returns row id
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
