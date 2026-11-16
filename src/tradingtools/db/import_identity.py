"""Conservative identity checks for CSV imports, independent of broker transport."""

import json
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class ImportConflict(ValueError):
    """A source row cannot safely be inserted or treated as a duplicate."""


class ImportIdentity:
    TABLES = {"buy": "trades", "sell": "trades", "interest": "interests", "dividend": "dividends"}
    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS csv_identities ("
        "category TEXT NOT NULL, record_id INTEGER NOT NULL, broker_id TEXT, "
        "source TEXT NOT NULL, stored TEXT NOT NULL, legacy_source TEXT, "
        "PRIMARY KEY(category, record_id), UNIQUE(category, broker_id))"
    )

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @staticmethod
    def encode(source: dict[str, object]) -> str:
        return json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def localize(value: datetime, zone: str) -> datetime:
        timezone_info = ZoneInfo(zone)
        first = value.replace(tzinfo=timezone_info, fold=0)
        second = value.replace(tzinfo=timezone_info, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ImportConflict("Ambiguous or nonexistent local time; explicit timestamp offset is required")
        if first.astimezone(timezone.utc).astimezone(timezone_info).replace(tzinfo=None) != value:
            raise ImportConflict("Nonexistent local time")
        return first

    @staticmethod
    def source_time(text: str, source_timezone: str | None = None) -> str:
        date = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if date.utcoffset() is None:
            if source_timezone is None:
                return "naive:" + date.isoformat()
            date = ImportIdentity.localize(date, source_timezone)
        return date.astimezone(timezone.utc).isoformat()

    def snapshot(self, category: str, record_id: int) -> str:
        table = self.TABLES[category]
        cursor = self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,))
        row = cursor.fetchone()
        if row is None:
            raise ImportConflict("CSV identity refers to a missing local record")
        values = {
            column[0]: value for column, value in zip(cursor.description, row)
            if column[0] not in ("id", "remaining_quantity")
        }
        return self.encode(values)

    def remember(
        self, category: str, record_id: int, broker_id: str | None, source: dict[str, object],
    ) -> None:
        self.conn.execute(
            "INSERT INTO csv_identities(category,record_id,broker_id,source,stored) VALUES(?,?,?,?,?)",
            (category, record_id, broker_id, self.encode(source), self.snapshot(category, record_id)),
        )

    def check_stored(self, category: str, row: tuple) -> None:
        if self.snapshot(category, row[0]) != row[3]:
            raise ImportConflict("Local transaction changed since its source identity was recorded")

    def match(self, category: str, broker_id: str | None, source: dict[str, object]) -> int | None:
        encoded = self.encode(source)
        if broker_id is not None:
            record = self.conn.execute(
                "SELECT record_id,broker_id,source,stored FROM csv_identities WHERE category=? AND broker_id=?",
                (category, broker_id),
            ).fetchone()
            if record:
                self.check_stored(category, record)
                legacy_match = self.conn.execute(
                    "SELECT 1 FROM csv_identities WHERE category=? AND record_id=? AND legacy_source=?",
                    (category, record[0], encoded),
                ).fetchone()
                if record[2] != encoded and legacy_match is None:
                    raise ImportConflict("The same broker ID has different source content")
                return record[0]
        candidates = self.conn.execute(
            "SELECT record_id,broker_id,source,stored FROM csv_identities "
            "WHERE category=? AND (source=? OR legacy_source=?) AND (? IS NULL OR broker_id IS NULL)",
            (category, encoded, encoded, broker_id),
        ).fetchall()
        if len(candidates) > 1:
            raise ImportConflict("Multiple transactions match a source row without a unique broker ID")
        if candidates:
            record = candidates[0]
            self.check_stored(category, record)
            if broker_id is not None and record[1] is None:
                self.conn.execute(
                    "UPDATE csv_identities SET broker_id=? WHERE category=? AND record_id=?",
                    (broker_id, category, record[0]),
                )
            return record[0]
        if category != "dividend":
            # Trades keep buy/sell in separate counters, but broker IDs span both.
            if category in ("buy", "sell"):
                opposite = "sell" if category == "buy" else "buy"
                if self.conn.execute(
                    "SELECT 1 FROM csv_identities WHERE category=? AND broker_id=?",
                    (opposite, broker_id),
                ).fetchone():
                    raise ImportConflict("A broker trade ID changed its action")
            return None

        # Never infer the original timezone of an old dividend from a nearby timestamp.
        source_time = str(source["time"])
        if source_time.startswith("naive:"):
            center = int(datetime.fromisoformat(source_time[6:]).timestamp())
        else:
            center = int(datetime.fromisoformat(source_time).timestamp())
        nearby = self.conn.execute(
            "SELECT d.id,i.broker_id,i.source,i.stored FROM dividends d "
            "JOIN securities s ON s.id=d.isin_id "
            "LEFT JOIN csv_identities i ON i.category='dividend' AND i.record_id=d.id "
            "WHERE s.isin=? AND d.timestamp BETWEEN ? AND ?",
            (source["ISIN"], center - 26 * 3600, center + 26 * 3600),
        ).fetchall()
        for record in nearby:
            if record[2] is None:
                raise ImportConflict("Legacy dividend requires reconciliation with its original CSV")
            previous = json.loads(record[2])
            if str(previous["time"]).startswith("naive:") != source_time.startswith("naive:"):
                raise ImportConflict("Legacy dividend timezone requires explicit source CSV reconciliation")
            if previous["time"] == source["time"] and previous["Action"] == source["Action"]:
                if broker_id is None or record[1] is None:
                    raise ImportConflict("Different dividend content without distinct broker IDs is ambiguous")
        return None
