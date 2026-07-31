"""Durable reconciliation receipt for resumable JM historical apply."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


class PartialApplyReceiptStore:
    def __init__(self, path: Path, *, bound_facts_digest: str) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("partial_apply_receipt_path_invalid")
        if not _sha256(bound_facts_digest):
            raise ValueError("partial_apply_receipt_binding_invalid")
        self._path = path
        self._bound_facts_digest = bound_facts_digest
        if path.exists():
            self._document = self._read()
            if self._document.get("bound_facts_digest") != bound_facts_digest:
                raise ValueError("partial_apply_receipt_binding_mismatch")
        else:
            self._document = {
                "schema_version": 1,
                "status": "in_progress",
                "bound_facts_digest": bound_facts_digest,
                "progress_state_digest": None,
                "mapping": None,
                "datasets": {},
            }

    def record_mapping(
        self,
        *,
        status: str,
        row_count: int,
        mapping_digest: str,
        rows: Sequence[Mapping[str, Any]] = (),
        progress_state_digest: str | None = None,
    ) -> None:
        if status not in {"passed", "blocked"} or row_count < 0 or not _sha256(mapping_digest):
            raise ValueError("partial_apply_receipt_mapping_invalid")
        self._document["mapping"] = {
            "status": status,
            "row_count": row_count,
            "mapping_digest": mapping_digest,
            "rows": [dict(item) for item in rows],
        }
        self._set_progress_state_digest(progress_state_digest)
        self._persist()

    def record_dataset(
        self,
        *,
        dataset: Mapping[str, str],
        status: str,
        planned_windows: Sequence[tuple[str, str]],
        published_window_count: int,
        gap_window_count: int,
        partition_evidence: Sequence[Mapping[str, Any]] = (),
        progress_state_digest: str | None = None,
    ) -> None:
        if status not in {"passed", "blocked"}:
            raise ValueError("partial_apply_receipt_dataset_invalid")
        key = _dataset_key(dataset)
        datasets = self._document["datasets"]
        assert isinstance(datasets, dict)
        datasets[key] = {
            "dataset": dict(dataset),
            "status": status,
            "planned_windows": [list(item) for item in planned_windows],
            "published_window_count": published_window_count,
            "gap_window_count": gap_window_count,
            "partition_evidence": [dict(item) for item in partition_evidence],
        }
        self._set_progress_state_digest(progress_state_digest)
        self._persist()

    def mapping_completed(self, *, mapping_digest: str) -> bool:
        mapping = self._document.get("mapping")
        return bool(
            isinstance(mapping, dict)
            and mapping.get("status") == "passed"
            and mapping.get("mapping_digest") == mapping_digest
        )

    def dataset_completed(self, dataset: Mapping[str, str]) -> bool:
        datasets = self._document.get("datasets")
        item = datasets.get(_dataset_key(dataset)) if isinstance(datasets, dict) else None
        return isinstance(item, dict) and item.get("status") == "passed"

    def completed_mapping(self) -> dict[str, Any] | None:
        mapping = self._document.get("mapping")
        if isinstance(mapping, dict) and mapping.get("status") == "passed":
            return json.loads(json.dumps(mapping))
        return None

    def completed_dataset(self, dataset: Mapping[str, str]) -> dict[str, Any] | None:
        datasets = self._document.get("datasets")
        item = datasets.get(_dataset_key(dataset)) if isinstance(datasets, dict) else None
        if isinstance(item, dict) and item.get("status") == "passed":
            return json.loads(json.dumps(item))
        return None

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._document))

    def _read(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("partial_apply_receipt_invalid") from exc
        if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
            raise ValueError("partial_apply_receipt_invalid")
        return parsed

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            self._document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)
        directory_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _set_progress_state_digest(self, value: str | None) -> None:
        if value is not None:
            if not _sha256(value):
                raise ValueError("partial_apply_receipt_progress_state_invalid")
            self._document["progress_state_digest"] = value


def _dataset_key(dataset: Mapping[str, str]) -> str:
    required = (
        "provider",
        "dataset_kind",
        "symbol",
        "contract_or_series",
        "frequency",
        "adjustment",
        "schema_version",
    )
    if set(dataset) != set(required) or any(not dataset.get(item) for item in required):
        raise ValueError("partial_apply_receipt_dataset_invalid")
    return "|".join(dataset[item] for item in required)


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )
