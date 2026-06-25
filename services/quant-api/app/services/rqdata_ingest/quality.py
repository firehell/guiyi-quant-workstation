from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class QualityResult:
    status: str
    missing_fields: list[str] = field(default_factory=list)
    duplicate_rows: int = 0
    row_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def details(self) -> dict[str, Any]:
        return {
            "missing_fields": self.missing_fields,
            "duplicate_rows": self.duplicate_rows,
            "row_count": self.row_count,
            "notes": self.notes,
            "check_rule_version": "rqdata_structured_v1",
        }


def validate_frame(df: pd.DataFrame, required_fields: list[str], duplicate_keys: list[str] | None = None) -> QualityResult:
    missing = [field for field in required_fields if field not in df.columns]
    duplicate_rows = int(df.duplicated(subset=duplicate_keys).sum()) if duplicate_keys and not df.empty else 0
    notes: list[str] = []
    if df.empty:
        notes.append("empty dataframe")
    if missing:
        notes.append("missing required fields")
    if duplicate_rows:
        notes.append("duplicated keys")
    status = "failed" if missing else "warning" if duplicate_rows or df.empty else "passed"
    return QualityResult(
        status=status,
        missing_fields=missing,
        duplicate_rows=duplicate_rows,
        row_count=len(df),
        notes=notes,
    )

