from datetime import datetime
from typing import List, Tuple
import sqlite3
from enum import IntEnum
from ..base import BaseRepository

class TradeType(IntEnum):
    """Types of trade entries in the database."""
    BUY = 1
    SELL = 2

class TradesRepository(BaseRepository):
    """Repository for the `trades` table operations."""

    def create_table(self) -> None:
        sql = (
            "CREATE TABLE IF NOT EXISTS trades ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "
            "isin_id INTEGER NOT NULL, "
            "id_string TEXT NOT NULL UNIQUE, "
            "trade_type INTEGER NOT NULL, "
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
               trade_type: TradeType,
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

        sql = (
            "INSERT OR IGNORE INTO trades (timestamp, isin_id, id_string, trade_type, number_of_shares, "
            "price_for_share, currency_of_price, total_czk, stamp_tax_czk, conversion_fee_czk, "
            "french_transaction_tax_czk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        cur = self.execute(sql, (
            timestamp, isin_id, id_string, int(trade_type), number_of_shares,
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

    def get_by_isin_and_date_range(self, isin_id: int, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get trades for a specific ISIN within a date range, ordered by time."""
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.isin_id = ? AND t.timestamp >= ? AND t.timestamp <= ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (isin_id, start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_summary_grouped_by_isin(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Return summary rows grouped by ISIN with total shares, ordered by security name."""
        sql = (
            "SELECT s.id AS isin_id, s.name, s.ticker, "
            "COALESCE(SUM(t.number_of_shares), 0.0) AS total_shares "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.timestamp >= ? AND t.timestamp <= ? "
            "GROUP BY s.id, s.name, s.ticker "
            "ORDER BY s.name COLLATE NOCASE"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()