from typing import Optional
import sqlite3
from ..base import BaseRepository

class SecuritiesRepository(BaseRepository):
    """Repository for the `securities` table operations."""

    def create_table(self) -> None:
        sql = (
            "CREATE TABLE IF NOT EXISTS securities ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "isin TEXT NOT NULL UNIQUE, "
            "ticker TEXT, "
            "name TEXT"
            ")"
        )
        cur = self.execute(sql)
        # commit using base
        self.commit()

    def insert(self, isin: str, ticker: Optional[str], name: Optional[str]) -> int:
        if not self.conn:
            raise RuntimeError("No open database to insert into")
        if not isin:
            raise ValueError("isin must be provided")
        if not isinstance(isin, str):
            raise ValueError("isin must be a string")

        sql = "INSERT OR IGNORE INTO securities (isin, ticker, name) VALUES (?, ?, ?)"
        try:
            cur = self.execute(sql, (isin, ticker, name))
            self.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # caller will handle duplicate behaviour
            raise

    def get_id(self, isin: str) -> Optional[int]:
        if not self.conn:
            raise RuntimeError("No open database to query/insert into")
        if not isin:
            raise ValueError("`isin` must be provided")

        cur = self.execute("SELECT id FROM securities WHERE isin = ?", (isin,))
        row = cur.fetchone()
        if row:
            return row[0]
        return None

    def get_or_create(self, isin: str, ticker: Optional[str] = None, name: Optional[str] = None) -> int:
        """Return an existing id for ISIN or insert and return new id."""
        existing = self.get_id(isin)
        if existing:
            return existing
        # not found -> insert
        try:
            return self.insert(isin, ticker, name)
        except sqlite3.IntegrityError:
            # race: another thread inserted concurrently — re-query
            existing = self.get_id(isin)
            if existing:
                return existing
            raise
