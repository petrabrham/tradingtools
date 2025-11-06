from datetime import datetime
from typing import List, Tuple
import sqlite3
from ..base import BaseRepository

class TradesRepository(BaseRepository):
    """Repository for the `trades` table operations."""

    def create_table(self) -> None:
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
        cur = self.execute(sql)
        # Indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_isin_id ON trades(isin_id)")
        self.commit()

    def insert(self,
               timestamp: int,
               isin_id: int,
               id_string: str,
               number_of_shares: float,
               price_for_share: float,
               currency_of_price: str,
               total_czk: float,
               stamp_tax_czk: float = 0.0,
               conversion_fee_czk: float = 0.0,
               french_transaction_tax_czk: float = 0.0) -> int:
        """Insert a single trade record and return the inserted row id."""
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not id_string:
            raise ValueError("id_string must be provided and non-empty")
        if any(v < 0 for v in [number_of_shares, price_for_share, total_czk, stamp_tax_czk, conversion_fee_czk, french_transaction_tax_czk]):
            raise ValueError("Numeric trade values must be non-negative")

        sql = (
            "INSERT OR IGNORE INTO trades (timestamp, isin_id, id_string, number_of_shares, "
            "price_for_share, currency_of_price, total_czk, stamp_tax_czk, conversion_fee_czk, "
            "french_transaction_tax_czk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        cur = self.execute(sql, (
            timestamp, isin_id, id_string, number_of_shares,
            price_for_share, currency_of_price, total_czk, stamp_tax_czk,
            conversion_fee_czk, french_transaction_tax_czk
        ))
        self.commit()
        return cur.lastrowid

    def get_by_date_range(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.timestamp >= ? AND t.timestamp <= ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_by_isin(self, isin_id: int) -> List[Tuple]:
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.isin_id = ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (isin_id,))
        return cur.fetchall()