import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional
from enum import IntEnum
from ..base import BaseRepository

class InterestType(IntEnum):
    """Types of interest entries in the database."""
    UNKNOWN = 0
    CASH_INTEREST = 1
    LENDING_INTEREST = 2

class InterestsRepository(BaseRepository):
    """Repository for the `interests` table operations."""

    def create_table(self) -> None:
        """Create the `interests` table if it does not exist."""
        sql = (
            "CREATE TABLE IF NOT EXISTS interests ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "  # Unix timestamp
            "type INTEGER NOT NULL CHECK (type IN (0,1,2)), "
            "id_string TEXT UNIQUE, "
            "total_czk REAL NOT NULL"
            ")"
        )
        self.execute(sql)
        # Create index on timestamp for range queries
        self.execute("CREATE INDEX IF NOT EXISTS idx_interests_timestamp ON interests(timestamp)")
        self.commit()

    def insert(self, timestamp: int, type_: InterestType, id_string: str, total_czk: float) -> int:
        """Insert a single interest record.
        
        Args:
            timestamp: Unix timestamp (seconds since epoch)
            type_: Interest type from InterestType enum
            id_string: Unique identifier for this interest record
            total_czk: Amount in CZK
            
        Returns:
            Number of rows inserted (1 on success, 0 if id_string exists)
            
        Raises:
            ValueError: If timestamp is negative
        """
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")

        sql = ("INSERT OR IGNORE INTO interests "
               "(timestamp, type, id_string, total_czk) "
               "VALUES (?, ?, ?, ?)")
        
        cur = self.execute(sql, (timestamp, int(type_), id_string, total_czk))
        self.commit()
        return cur.rowcount

    def get_by_date_range(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get interests within the given timestamp range.
        
        Args:
            start_timestamp: Start of range (inclusive)
            end_timestamp: End of range (inclusive)
            
        Returns:
            List of tuples with interest records
        """
        if not self.conn:
            raise RuntimeError("No open database to query")

        sql = (
            "SELECT id, timestamp, type, id_string, total_czk "
            "FROM interests "
            "WHERE timestamp >= ? AND timestamp <= ? "
            "ORDER BY timestamp"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()