"""In-memory import comparisons; no persistence or financial changes."""

import json
import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import TYPE_CHECKING

import pandas as pd

from tradingtools.db.import_identity import ImportIdentity

if TYPE_CHECKING:
    from tradingtools.db.dbmanager import DatabaseManager, ImportResult


@dataclass(frozen=True)
class ComparisonCandidate:
    record_id: int
    category: str
    stored: dict[str, object]
    source: dict[str, object] | None
    recorded: dict[str, object] | None = None


@dataclass(frozen=True)
class ImportComparison:
    file: str
    year: int | None
    row: int
    action: str
    reason: str
    code: str
    incoming: dict[str, object]
    source: dict[str, object] | None
    expected: dict[str, object] | None
    candidates: list[ComparisonCandidate]


def _scalar(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value)
    return str(value)


def build_comparisons(
    database: "DatabaseManager", frame: pd.DataFrame, result: "ImportResult",
    file: str, year: int | None = None,
) -> list[ImportComparison]:
    if database.conn is None:
        raise RuntimeError("Import comparison requires the worker's open database")
    identity = ImportIdentity(database.conn)
    comparisons = []
    for issue in result["conflicts"]:
        row = frame.iloc[issue["row"] - 1]
        category = issue.get("candidate_category", database._csv_category(issue["action"]))
        candidates = []
        for record_id in issue.get("candidate_ids", ()):
            stored = json.loads(identity.snapshot(category, record_id))
            original = database.conn.execute(
                "SELECT source,stored FROM csv_identities WHERE category=? AND record_id=?", (category, record_id),
            ).fetchone()
            candidates.append(ComparisonCandidate(
                record_id, category, stored, json.loads(original[0]) if original is not None else None,
                json.loads(original[1]) if original is not None else None,
            ))
        try:
            source = database._csv_source(row, database._csv_category(issue["action"]))
        except (ValueError, TypeError):
            # The conflict's reported validation error remains visible with the raw row.
            source = None
        comparisons.append(ImportComparison(
            file, year, issue["row"], issue["action"], issue["message"], issue.get("code", "identity"),
            {str(key): _scalar(value) for key, value in row.items()}, source,
            issue.get("expected"), candidates,
        ))
    return comparisons
