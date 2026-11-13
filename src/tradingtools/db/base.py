import sqlite3
from typing import Optional, Any, Sequence
import logging

class BaseRepository:
    """Small helper base repository to wrap common DB operations."""

    def __init__(self, conn: sqlite3.Connection, logger: Optional[logging.Logger] = None):
        self.conn = conn
        self.logger = logger or logging.getLogger("trading_tools.db")

    def _cursor(self) -> sqlite3.Cursor:
        return self.conn.cursor()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> sqlite3.Cursor:
        if params is None:
            params = ()
        self.logger.debug("SQL execute: %s -- %s", sql, params)
        cur = self._cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq_of_params) -> sqlite3.Cursor:
        self.logger.debug("SQL executemany: %s -- %s items", sql, len(seq_of_params))
        cur = self._cursor()
        cur.executemany(sql, seq_of_params)
        return cur

    def commit(self) -> None:
        try:
            self.conn.commit()
        except Exception:
            # Let caller handle exceptions; log for debugging
            self.logger.exception("Failed to commit transaction")
            raise
