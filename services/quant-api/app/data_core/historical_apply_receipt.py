"""Durable reconciliation receipt for resumable JM historical apply."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


class PartialApplyReceiptStore:
    def __init__(
        self,
        path: Path,
        *,
        approval_basis_digest: str,
        approval_packet_hash: str,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("partial_apply_receipt_path_invalid")
        if not _sha256(approval_basis_digest) or not _sha256(approval_packet_hash):
            raise ValueError("partial_apply_receipt_binding_invalid")
        self._path = path
        self._approval_basis_digest = approval_basis_digest
        self._approval_packet_hash = approval_packet_hash
        if path.exists():
            self._document = self._read()
            if (
                self._document["approval_basis_digest"] != approval_basis_digest
                or self._document["approval_packet_hash"] != approval_packet_hash
            ):
                raise ValueError("partial_apply_receipt_binding_mismatch")
        else:
            self._document = {
                "schema_version": 2,
                "status": "in_progress",
                "approval_basis_digest": approval_basis_digest,
                "approval_packet_hash": approval_packet_hash,
                "progress_state_digest": None,
                "mapping": None,
                "datasets": {},
            }

    def begin_resume(self) -> None:
        if self._document["status"] == "passed":
            raise ValueError("partial_apply_receipt_terminal")
        if self._document["status"] == "blocked":
            self._document["status"] = "in_progress"
            self._persist()

    def record_mapping(
        self,
        *,
        status: str,
        row_count: int,
        mapping_digest: str,
        rows: Sequence[Mapping[str, Any]] = (),
        progress_state_digest: str | None = None,
    ) -> None:
        self._require_mutable()
        if (
            status not in {"passed", "blocked"}
            or row_count < 0
            or not _sha256(mapping_digest)
            or len(rows) != row_count
        ):
            raise ValueError("partial_apply_receipt_mapping_invalid")
        self._document["mapping"] = {
            "status": status,
            "row_count": row_count,
            "mapping_digest": mapping_digest,
            "rows": [dict(item) for item in rows],
        }
        if status == "blocked":
            self._document["status"] = "blocked"
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
        self._require_mutable()
        if (
            status not in {"passed", "blocked"}
            or not isinstance(published_window_count, int)
            or published_window_count < 0
            or not isinstance(gap_window_count, int)
            or gap_window_count < 0
            or status == "passed"
            and (gap_window_count != 0 or not partition_evidence)
        ):
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
        if status == "blocked":
            self._document["status"] = "blocked"
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

    def finalize_passed(
        self,
        *,
        expected_mapping_row_count: int,
        expected_mapping_digest: str,
        expected_datasets: Sequence[Mapping[str, str]],
        progress_state_digest: str,
    ) -> None:
        self._require_mutable()
        mapping = self._document.get("mapping")
        expected_keys = {_dataset_key(item) for item in expected_datasets}
        datasets = self._document.get("datasets")
        if (
            not isinstance(mapping, dict)
            or mapping.get("status") != "passed"
            or mapping.get("row_count") != expected_mapping_row_count
            or mapping.get("mapping_digest") != expected_mapping_digest
            or not expected_keys
            or not isinstance(datasets, dict)
            or set(datasets) != expected_keys
            or any(
                not isinstance(item, dict)
                or item.get("status") != "passed"
                or item.get("gap_window_count") != 0
                or not item.get("partition_evidence")
                for item in datasets.values()
            )
            or not _sha256(progress_state_digest)
        ):
            raise ValueError("partial_apply_receipt_finalize_invalid")
        self._document["status"] = "passed"
        self._document["progress_state_digest"] = progress_state_digest
        self._persist()

    def _read(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("partial_apply_receipt_invalid") from exc
        if not _valid_document(parsed):
            raise ValueError("partial_apply_receipt_invalid")
        return parsed

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._document["receipt_digest"] = _receipt_digest(self._document)
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

    def _require_mutable(self) -> None:
        if self._document["status"] == "passed":
            raise ValueError("partial_apply_receipt_terminal")


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


def _receipt_digest(document: Mapping[str, Any]) -> str:
    payload = dict(document)
    payload.pop("receipt_digest", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _valid_document(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "status",
        "approval_basis_digest",
        "approval_packet_hash",
        "progress_state_digest",
        "mapping",
        "datasets",
        "receipt_digest",
    }:
        return False
    if (
        value["schema_version"] != 2
        or value["status"] not in {"in_progress", "blocked", "passed"}
        or not _sha256(value["approval_basis_digest"])
        or not _sha256(value["approval_packet_hash"])
        or value["progress_state_digest"] is not None
        and not _sha256(value["progress_state_digest"])
        or value["receipt_digest"] != _receipt_digest(value)
    ):
        return False
    mapping = value["mapping"]
    if mapping is not None:
        if not isinstance(mapping, dict) or set(mapping) != {
            "status",
            "row_count",
            "mapping_digest",
            "rows",
        }:
            return False
        if (
            mapping["status"] not in {"passed", "blocked"}
            or not isinstance(mapping["row_count"], int)
            or mapping["row_count"] < 0
            or not _sha256(mapping["mapping_digest"])
            or not isinstance(mapping["rows"], list)
            or len(mapping["rows"]) != mapping["row_count"]
        ):
            return False
    datasets = value["datasets"]
    if not isinstance(datasets, dict):
        return False
    for key, item in datasets.items():
        if not isinstance(item, dict) or set(item) != {
            "dataset",
            "status",
            "planned_windows",
            "published_window_count",
            "gap_window_count",
            "partition_evidence",
        }:
            return False
        try:
            expected_key = _dataset_key(item["dataset"])
        except ValueError:
            return False
        if (
            key != expected_key
            or item["status"] not in {"passed", "blocked"}
            or not isinstance(item["planned_windows"], list)
            or not isinstance(item["partition_evidence"], list)
            or not isinstance(item["published_window_count"], int)
            or item["published_window_count"] < 0
            or not isinstance(item["gap_window_count"], int)
            or item["gap_window_count"] < 0
            or item["status"] == "passed"
            and (item["gap_window_count"] != 0 or not item["partition_evidence"])
        ):
            return False
    if value["status"] == "passed" and (
        mapping is None
        or mapping["status"] != "passed"
        or not datasets
        or any(item["status"] != "passed" for item in datasets.values())
        or not _sha256(value["progress_state_digest"])
    ):
        return False
    return True
