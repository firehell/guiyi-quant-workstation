from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ManifestChunk:
    key: str
    status: str = "pending"
    retry_count: int = 0
    error: str | None = None


class CsvManifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=["key", "status", "retry_count", "error"])
        return pd.read_csv(self.path)

    def should_run(self, key: str, *, resume: bool, retry_failed: bool) -> bool:
        frame = self.load()
        if frame.empty or key not in set(frame["key"].astype(str)):
            return True
        row = frame[frame["key"].astype(str) == key].iloc[-1]
        if row["status"] == "success":
            return not resume
        if row["status"] == "failed":
            return retry_failed or not resume
        return True

    def mark(self, key: str, status: str, error: str | None = None) -> None:
        frame = self.load()
        retry_count = 0
        if not frame.empty and key in set(frame["key"].astype(str)):
            retry_count = int(frame[frame["key"].astype(str) == key].iloc[-1].get("retry_count", 0) or 0)
            frame = frame[frame["key"].astype(str) != key]
        if status == "failed":
            retry_count += 1
        frame = pd.concat(
            [
                frame,
                pd.DataFrame([{"key": key, "status": status, "retry_count": retry_count, "error": error}]),
            ],
            ignore_index=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(self.path, index=False)

