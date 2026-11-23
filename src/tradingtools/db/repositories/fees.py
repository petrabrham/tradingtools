import math
from enum import IntEnum

from ..base import BaseRepository


class FeeType(IntEnum):
    ADR = 1


class FeesRepository(BaseRepository):
    """Standalone fees, excluding costs already stored on trades."""

    TABLE_SQL = (
        "CREATE TABLE IF NOT EXISTS fees ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp INTEGER NOT NULL, "
        "type INTEGER NOT NULL CHECK(type IN (1)), "
        "isin_id INTEGER, "
        "amount REAL NOT NULL, "
        "currency TEXT NOT NULL, "
        "total_czk REAL NOT NULL, "
        "FOREIGN KEY(isin_id) REFERENCES securities(id) ON DELETE RESTRICT)"
    )

    def create_table(self) -> None:
        self.execute(self.TABLE_SQL)
        self.execute("CREATE INDEX IF NOT EXISTS idx_fees_timestamp ON fees(timestamp)")
        self.execute("CREATE INDEX IF NOT EXISTS idx_fees_isin_id ON fees(isin_id)")
        self.commit()

    def insert(
        self, timestamp: int, type_: FeeType, isin_id: int | None,
        amount: float, currency: str, total_czk: float,
    ) -> int:
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not math.isfinite(amount) or not math.isfinite(total_czk):
            raise ValueError("Fee amounts must be finite")
        if not currency.strip():
            raise ValueError("Fee currency must not be empty")
        cursor = self.execute(
            "INSERT INTO fees(timestamp,type,isin_id,amount,currency,total_czk) VALUES(?,?,?,?,?,?)",
            (timestamp, int(type_), isin_id, amount, currency, total_czk),
        )
        self.commit()
        return cursor.rowcount
