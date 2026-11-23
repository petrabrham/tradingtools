"""Conservative identity checks for CSV imports, independent of broker transport."""

import json
import math
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Callable


class ImportConflict(ValueError):
    """A source row cannot safely be inserted or treated as a duplicate."""

    def __init__(
        self, message: str, *, code: str = "identity",
        candidate_ids: tuple[int, ...] = (), candidate_category: str | None = None,
        expected: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.candidate_ids = candidate_ids
        self.candidate_category = candidate_category
        self.expected = expected


class LegacySourceRequired(ImportConflict):
    """An untracked legacy record needs exact original-CSV proof."""


class ImportIdentity:
    TABLES = {"buy": "trades", "sell": "trades", "interest": "interests", "dividend": "dividends", "fee": "fees"}
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
            raise ImportConflict("Local transaction changed since its source identity was recorded",
                                 code="local_edit", candidate_ids=(row[0],))

    def matches_values(self, category: str, record_id: int, expected: dict[str, object]) -> bool:
        stored = json.loads(self.snapshot(category, record_id))
        return all(
            math.isclose(stored[key], value, rel_tol=1e-12, abs_tol=1e-8)
            if isinstance(value, float) else stored[key] == value
            for key, value in expected.items()
        )

    def normalize_legacy_time(
        self, category: str, broker_id: str | None, source: dict[str, object],
        candidate_ids: tuple[int, ...], before_update: Callable[[int, int], None],
    ) -> bool:
        text = source.get("time")
        if not isinstance(text, str) or text.startswith("naive:"):
            return False
        incoming = datetime.fromisoformat(text)
        if incoming.utcoffset() is None:
            return False
        incoming = incoming.astimezone(timezone.utc)
        candidates = []
        for record_id in candidate_ids:
            record = self.conn.execute(
                "SELECT record_id,broker_id,source,stored,legacy_source FROM csv_identities "
                "WHERE category=? AND record_id=?", (category, record_id),
            ).fetchone()
            if record is None or (broker_id is not None and record[1] not in (None, broker_id)):
                continue
            previous = json.loads(record[2])
            previous_time = previous.get("time")
            if not isinstance(previous_time, str) or not previous_time.startswith("naive:"):
                continue
            if {key: value for key, value in previous.items() if key != "time"} != {
                key: value for key, value in source.items() if key != "time"
            }:
                continue
            old = datetime.fromisoformat(previous_time[6:])
            if old.utcoffset() is not None or old != incoming.replace(tzinfo=None):
                continue
            candidates.append((record, old))
        if len(candidates) != 1:
            return False
        record, old = candidates[0]
        self.check_stored(category, record)
        if record[4] not in (None, record[2]):
            return False
        stored = json.loads(record[3])
        old_timestamp, new_timestamp = stored["timestamp"], int(incoming.timestamp())
        # Reproduce the original local-time parser; do not infer a one/two-hour tolerance.
        if (
            int(old.timestamp()) != old_timestamp
            or int(old.replace(fold=0).timestamp()) != int(old.replace(fold=1).timestamp())
            or datetime.fromtimestamp(old_timestamp) != old.replace(microsecond=0)
        ):
            return False
        if (
            datetime.fromtimestamp(old_timestamp).date() != datetime.fromtimestamp(new_timestamp).date()
            or datetime.fromtimestamp(old_timestamp, timezone.utc).year != incoming.year
        ):
            return False
        before_update(record[0], new_timestamp)
        self.conn.execute(
            f"UPDATE {self.TABLES[category]} SET timestamp=? WHERE id=?", (new_timestamp, record[0]),
        )
        stored["timestamp"] = new_timestamp
        if self.snapshot(category, record[0]) != self.encode(stored):
            raise ImportConflict("Time normalization changed other stored fields", code="time_normalization")
        self.conn.execute(
            "UPDATE csv_identities SET source=?,stored=?,legacy_source=?,broker_id=COALESCE(broker_id,?) "
            "WHERE category=? AND record_id=?",
            (self.encode(source), self.encode(stored), record[2], broker_id, category, record[0]),
        )
        return True

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
                    raise ImportConflict("The same broker ID has different source content",
                                         code="source_changed", candidate_ids=(record[0],))
                return record[0]
        candidates = self.conn.execute(
            "SELECT record_id,broker_id,source,stored FROM csv_identities "
            "WHERE category=? AND (source=? OR legacy_source=?) AND (? IS NULL OR broker_id IS NULL)",
            (category, encoded, encoded, broker_id),
        ).fetchall()
        if len(candidates) > 1:
            raise ImportConflict("Multiple transactions match a source row without a unique broker ID",
                                 code="ambiguous", candidate_ids=tuple(row[0] for row in candidates))
        if candidates:
            record = candidates[0]
            self.check_stored(category, record)
            if broker_id is not None and record[1] is None:
                self.conn.execute(
                    "UPDATE csv_identities SET broker_id=? WHERE category=? AND record_id=?",
                    (broker_id, category, record[0]),
                )
            return record[0]
        if category not in ("dividend", "fee"):
            # Trades keep buy/sell in separate counters, but broker IDs span both.
            if category in ("buy", "sell"):
                opposite = "sell" if category == "buy" else "buy"
                other = self.conn.execute(
                    "SELECT record_id FROM csv_identities WHERE category=? AND broker_id=?",
                    (opposite, broker_id),
                ).fetchone()
                if other is not None:
                    raise ImportConflict("A broker trade ID changed its action", code="action",
                                         candidate_ids=(other[0],), candidate_category=opposite)
            return None

        # Proximity only supplies conflict candidates; normalization needs separate exact proof.
        source_time = str(source["time"])
        if source_time.startswith("naive:"):
            center = int(datetime.fromisoformat(source_time[6:]).timestamp())
        else:
            center = int(datetime.fromisoformat(source_time).timestamp())
        nearby = self.conn.execute(
            f"SELECT d.id,i.broker_id,i.source,i.stored FROM {self.TABLES[category]} d "
            "LEFT JOIN securities s ON s.id=d.isin_id "
            "LEFT JOIN csv_identities i ON i.category=? AND i.record_id=d.id "
            "WHERE s.isin IS ? AND d.timestamp BETWEEN ? AND ?",
            (category, source["ISIN"], center - 26 * 3600, center + 26 * 3600),
        ).fetchall()
        if any(record[2] is None for record in nearby):
            raise LegacySourceRequired(
                f"Legacy {category} requires reconciliation with its original CSV", code="legacy",
                candidate_ids=tuple(row[0] for row in nearby if row[2] is None),
            )
        nearby_sources = [(record, json.loads(record[2])) for record in nearby]
        for record, previous in nearby_sources:
            if str(previous["time"]).startswith("naive:") != source_time.startswith("naive:"):
                raise ImportConflict(f"Legacy {category} timezone requires explicit source CSV reconciliation",
                                     code="timezone", candidate_ids=tuple(
                                         item[0] for item, content in nearby_sources
                                         if str(content["time"]).startswith("naive:") != source_time.startswith("naive:")
                                     ))
            if previous["time"] == source["time"] and previous["Action"] == source["Action"]:
                if broker_id is None or record[1] is None:
                    raise ImportConflict(f"Different {category} content without distinct broker IDs is ambiguous",
                                         code="ambiguous", candidate_ids=tuple(
                                             item[0] for item, content in nearby_sources
                                             if content["time"] == source["time"] and content["Action"] == source["Action"]
                                             and (broker_id is None or item[1] is None)
                                         ))
        return None
