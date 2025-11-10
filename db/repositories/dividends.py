from datetime import datetime
from typing import Optional, List, Tuple
import sqlite3
from ..base import BaseRepository

class DividendsRepository(BaseRepository):
    """Repository for the `dividends` table operations."""

    def create_table(self) -> None:
        """Create the `dividends` table if it does not exist."""
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
            "UNIQUE (timestamp, isin_id),"
            "FOREIGN KEY (isin_id) REFERENCES securities(id) ON DELETE RESTRICT"
            ")"
        )
        cur = self.execute(sql)
        # Create indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dividends_timestamp ON dividends(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dividends_isin_id ON dividends(isin_id)")
        self.commit()

    def insert(self, 
        timestamp: int,
        isin_id: int,
        number_of_shares: float,
        price_for_share: float,
        currency_of_price: str,
        total_czk: float,
        withholding_tax_czk: float
    ) -> int:
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
            ValueError: If timestamp is negative or any numeric value is negative
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if any(v < 0 for v in [number_of_shares, price_for_share, total_czk, withholding_tax_czk]):
            raise ValueError("Numeric dividend values must be non-negative")

        sql = (
            "INSERT OR IGNORE INTO dividends ("
            "timestamp, isin_id, number_of_shares, price_for_share, "
            "currency_of_price, total_czk, withholding_tax_czk"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        
        cur = self.execute(sql, (
            timestamp, isin_id, number_of_shares, price_for_share,
            currency_of_price, total_czk, withholding_tax_czk
        ))
        self.commit()
        return cur.lastrowid
        
    def get_by_date_range(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get dividends within the given timestamp range.
        
        Args:
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            List of tuples with dividend records ordered by timestamp
        """
        sql = (
            "SELECT d.*, s.isin, s.ticker, s.name "
            "FROM dividends d "
            "JOIN securities s ON d.isin_id = s.id "
            "WHERE d.timestamp >= ? AND d.timestamp <= ? "
            "ORDER BY d.timestamp"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_by_isin(self, isin_id: int) -> List[Tuple]:
        """Get all dividends for a security by its ID.
        
        Args:
            isin_id: ID from securities table
            
        Returns:
            List of tuples with dividend records ordered by timestamp
        """
        sql = (
            "SELECT d.*, s.isin, s.ticker, s.name "
            "FROM dividends d "
            "JOIN securities s ON d.isin_id = s.id "
            "WHERE d.isin_id = ? "
            "ORDER BY d.timestamp"
        )
        cur = self.execute(sql, (isin_id,))
        return cur.fetchall()

    def get_summary_by_date_range(self, start_timestamp: int, end_timestamp: int) -> Tuple[float, float, float]:
        """Get dividend summary totals within the given timestamp range.
        
        Args:
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            Tuple of (total_gross_czk, total_tax_czk, total_net_czk)
        """
        sql = (
            "SELECT "
            "COALESCE(SUM(total_czk), 0.0) as total_gross, "
            "COALESCE(SUM(withholding_tax_czk), 0.0) as total_tax, "
            "COALESCE(SUM(total_czk - withholding_tax_czk), 0.0) as total_net "
            "FROM dividends "
            "WHERE timestamp >= ? AND timestamp <= ?"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        result = cur.fetchone()
        return (result[0], result[1], result[2]) if result else (0.0, 0.0, 0.0)

    def get_summary_grouped_by_isin(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get dividend summary grouped by ISIN within the given timestamp range.
        
        Args:
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            List of tuples: (isin_id, isin, ticker, name, total_gross_czk, total_tax_czk)
            Ordered by name
        """
        sql = (
            "SELECT "
            "d.isin_id, "
            "s.isin, "
            "s.ticker, "
            "s.name, "
            "COALESCE(SUM(d.total_czk), 0.0) as total_gross, "
            "COALESCE(SUM(d.withholding_tax_czk), 0.0) as total_tax "
            "FROM dividends d "
            "JOIN securities s ON d.isin_id = s.id "
            "WHERE d.timestamp >= ? AND d.timestamp <= ? "
            "GROUP BY d.isin_id, s.isin, s.ticker, s.name "
            "ORDER BY s.name"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_by_isin_and_date_range(self, isin_id: int, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get all dividends for a specific security within a date range.
        
        Args:
            isin_id: ID from securities table
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            List of tuples with dividend records ordered by timestamp
            Format: (id, timestamp, isin_id, number_of_shares, price_for_share, 
                     currency_of_price, total_czk, withholding_tax_czk, isin, ticker, name)
        """
        sql = (
            "SELECT d.*, s.isin, s.ticker, s.name "
            "FROM dividends d "
            "JOIN securities s ON d.isin_id = s.id "
            "WHERE d.isin_id = ? AND d.timestamp >= ? AND d.timestamp <= ? "
            "ORDER BY d.timestamp"
        )
        cur = self.execute(sql, (isin_id, start_timestamp, end_timestamp))
        return cur.fetchall()