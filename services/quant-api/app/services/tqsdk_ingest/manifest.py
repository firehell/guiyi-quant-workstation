from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
import hashlib

import pandas as pd


MANIFEST_COLUMNS = [
    "key",
    "provider",
    "data_type",
    "product",
    "exchange",
    "contract",
    "source_symbol",
    "period",
    "chunk_start",
    "chunk_end",
    "raw_path",
    "canonical_path",
    "rows",
    "checksum",
    "status",
    "error",
    "created_at",
    "updated_at",
]


class TqSdkCsvManifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=MANIFEST_COLUMNS)
        frame = pd.read_csv(self.path, dtype=str).fillna("")
        for column in MANIFEST_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame[MANIFEST_COLUMNS]

    def should_run(self, key: str, *, resume: bool, retry_failed: bool, force: bool = False) -> bool:
        if force:
            return True
        frame = self.load()
        if frame.empty or key not in set(frame["key"].astype(str)):
            return True
        row = frame[frame["key"].astype(str) == key].iloc[-1]
        status = str(row.get("status", ""))
        if status == "success":
            if not resume:
                return True
            if not self._checksum_matches(row):
                self.mark_existing_failed(key, "checksum mismatch")
                return False
            return False
        if status == "failed":
            return retry_failed or not resume
        if status == "empty":
            return False
        return True

    def mark(self, *, key: str, status: str, error: str | None = None, **values: Any) -> None:
        frame = self.load()
        now = datetime.now(UTC).isoformat()
        created_at = now
        if not frame.empty and key in set(frame["key"].astype(str)):
            previous = frame[frame["key"].astype(str) == key].iloc[-1]
            created_at = str(previous.get("created_at") or now)
            frame = frame[frame["key"].astype(str) != key]
        record = {column: "" for column in MANIFEST_COLUMNS}
        record.update(values)
        record["key"] = key
        record["status"] = status
        record["error"] = error or ""
        record["created_at"] = created_at
        record["updated_at"] = now
        for path_column in ["raw_path", "canonical_path"]:
            if isinstance(record.get(path_column), Path):
                record[path_column] = str(record[path_column])
        for date_column in ["chunk_start", "chunk_end"]:
            if isinstance(record.get(date_column), date):
                record[date_column] = record[date_column].isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([frame, pd.DataFrame([record])], ignore_index=True)[MANIFEST_COLUMNS].to_csv(self.path, index=False)

    def mark_existing_failed(self, key: str, error: str) -> None:
        frame = self.load()
        if frame.empty or key not in set(frame["key"].astype(str)):
            return
        idx = frame[frame["key"].astype(str) == key].index[-1]
        frame.loc[idx, "status"] = "failed"
        frame.loc[idx, "error"] = error
        frame.loc[idx, "updated_at"] = datetime.now(UTC).isoformat()
        frame.to_csv(self.path, index=False)

    def file_checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _checksum_matches(self, row: pd.Series) -> bool:
        checksum = str(row.get("checksum") or "")
        raw_path = Path(str(row.get("raw_path") or ""))
        canonical_path = Path(str(row.get("canonical_path") or ""))
        paths = [path for path in [canonical_path, raw_path] if str(path) and path.exists()]
        if not checksum or not paths:
            return False
        return any(self.file_checksum(path) == checksum for path in paths)
