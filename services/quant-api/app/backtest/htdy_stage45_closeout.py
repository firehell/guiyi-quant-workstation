from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.compute as pc
import pyarrow.parquet as pq


TASK_ID = "HTDY-STAGE45-CONTRACT-CLOSEOUT-R45"
BASELINE_GATE = "STAGE45_CLOSEOUT_BASELINE_READY"
DATA_EQUIVALENT_GATE = "HTDY_FROZEN_DATA_WINDOW_EQUIVALENT"
BLOCKED_DATA_GATE = "STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT"

PROTOCOL_PATH = Path("configs/oos/htdy_strict_validation_protocol_v1.json")
CANDIDATE_PATH = Path(
    "data/reports/htdy_trusted_backtest_candidate_x5_03/HTDY_TRUSTED_BACKTEST_CANDIDATE.json"
)
EVIDENCE_PATHS = {
    "x503": CANDIDATE_PATH,
    "x504": Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json"),
    "x505": Path("data/reports/htdy_rolling_oos_x5_05/ROLLING_OOS_VALIDATION_RESULT.json"),
    "x506b": Path(
        "data/reports/htdy_strategy_review_x5_06b/STRATEGY_REVIEW_CLOSED_LOOP_READY.json"
    ),
    "x507": Path("data/reports/htdy_stage5_acceptance_x5_07/STAGE5_ACCEPTANCE_PACKET.json"),
}

REQUIRED_FIELDS = (
    "datetime",
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "provider",
    "source",
    "data_role",
    "quality_status",
    "period",
    "symbol",
    "contract",
)
OPTIONAL_FIELDS = ("open_interest", "turnover")


def packet_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_packet_hash(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_verified_packet(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"evidence packet is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not verify_packet_hash(value):
        raise ValueError(f"evidence packet hash is invalid: {path.name}")
    return value


def build_baseline(repo_root: Path, *, source_commit: str) -> dict[str, Any]:
    protocol_path = repo_root / PROTOCOL_PATH
    if not protocol_path.is_file():
        raise FileNotFoundError("frozen validation protocol is missing")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    packets = {
        name: load_verified_packet(repo_root / relative_path)
        for name, relative_path in EVIDENCE_PATHS.items()
    }
    candidate = packets["x503"]
    acceptance = packets["x507"]
    execution = dict(candidate.get("execution_snapshot") or {})
    frozen = dict(protocol.get("frozen_data_policy") or {})
    if candidate.get("gate") != "HTDY_TRUSTED_BACKTEST_CANDIDATE":
        raise ValueError("X5-03 candidate Gate is invalid")
    if acceptance.get("research_outcome") != "REJECTED_RESEARCH_CANDIDATE":
        raise ValueError("X5-07 rejected research outcome is not preserved")
    protocol_file_hash = file_sha256(protocol_path)
    if candidate.get("protocol_hash") != protocol_file_hash:
        raise ValueError("candidate protocol hash does not match frozen protocol")
    if candidate.get("parameter_hash") != protocol.get("parameter_hash"):
        raise ValueError("candidate parameter hash does not match frozen protocol")

    evidence = {
        name: {
            "relative_path": EVIDENCE_PATHS[name].as_posix(),
            "packet_hash": packet["packet_hash"],
            "file_sha256": file_sha256(repo_root / EVIDENCE_PATHS[name]),
            "gate": packet.get("gate"),
            "status": packet.get("status"),
        }
        for name, packet in packets.items()
    }
    packet: dict[str, Any] = {
        "schema_version": "htdy_stage45_closeout_baseline_r4500_v1",
        "task_id": TASK_ID,
        "gate": BASELINE_GATE,
        "status": "completed",
        "source_commit": source_commit,
        "protocol_hash": protocol_file_hash,
        "parameter_hash": protocol.get("parameter_hash"),
        "protocol_file_sha256": protocol_file_hash,
        "candidate_identity": candidate.get("candidate_identity"),
        "report14_regression": candidate.get("report14_regression"),
        "profile_binding_identity": {
            key: execution.get(key)
            for key in (
                "profile_id",
                "profile_active_binding_id",
                "market_data_file_id",
                "data_version",
                "file_sha256",
                "relative_path",
            )
        },
        "actual_execution_data": {
            "data_version": execution.get("data_version"),
            "relative_path": execution.get("relative_path"),
            "file_sha256": execution.get("file_sha256"),
        },
        "frozen_protocol_data": {
            key: frozen.get(key)
            for key in (
                "data_version",
                "relative_path",
                "source_file_sha256",
                "full_window_start",
                "full_window_end",
            )
        },
        "evidence": evidence,
        "research_outcome": acceptance.get("research_outcome"),
        "boundaries": {
            "would_write_database": False,
            "would_modify_profile_binding": False,
            "would_modify_parquet": False,
            "would_modify_original_evidence": False,
            "would_run_strategy": False,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def load_window_rows(
    path: Path,
    *,
    start: datetime,
    end: datetime,
    fields: Sequence[str],
    declared_sha256: str,
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"asset is missing: {path.name}")
    actual_sha256 = file_sha256(path)
    if actual_sha256 != declared_sha256:
        raise ValueError(f"asset SHA256 mismatch: {path.name}")
    schema_names = set(pq.read_schema(path).names)
    missing = [field for field in fields if field not in schema_names]
    if missing:
        raise ValueError(f"asset is missing comparison fields: {','.join(missing)}")
    table = pq.ParquetFile(path).read(columns=list(fields))
    mask = pc.and_(
        pc.greater_equal(table["datetime"], pa_scalar(start)),
        pc.less_equal(table["datetime"], pa_scalar(end)),
    )
    rows = table.filter(mask).to_pylist()
    return {
        "actual_sha256": actual_sha256,
        "row_count": len(rows),
        "rows": rows,
    }


def pa_scalar(value: datetime):
    import pyarrow as pa

    return pa.scalar(value)


def compare_bar_rows(
    old_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
) -> dict[str, Any]:
    old_normalized = [_normalize_row(row, fields) for row in old_rows]
    new_normalized = [_normalize_row(row, fields) for row in new_rows]
    old_duplicates = _duplicate_datetimes(old_normalized)
    new_duplicates = _duplicate_datetimes(new_normalized)
    differences: list[dict[str, Any]] = []
    if old_duplicates:
        differences.append({"reason": "duplicate_datetime_old", "datetime": old_duplicates[0]})
    if new_duplicates:
        differences.append({"reason": "duplicate_datetime_new", "datetime": new_duplicates[0]})

    old_by_time = {row["datetime"]: row for row in old_normalized}
    new_by_time = {row["datetime"]: row for row in new_normalized}
    for timestamp in sorted(set(old_by_time) - set(new_by_time)):
        differences.append({"reason": "missing_in_new", "datetime": timestamp})
    for timestamp in sorted(set(new_by_time) - set(old_by_time)):
        differences.append({"reason": "extra_in_new", "datetime": timestamp})
    field_counts: Counter[str] = Counter()
    for timestamp in sorted(set(old_by_time) & set(new_by_time)):
        old_row = old_by_time[timestamp]
        new_row = new_by_time[timestamp]
        for field in fields:
            if old_row[field] != new_row[field]:
                field_counts[field] += 1
                differences.append(
                    {
                        "reason": "field_difference",
                        "datetime": timestamp,
                        "field": field,
                        "old": old_row[field],
                        "new": new_row[field],
                    }
                )
    equivalent = not differences and len(old_normalized) == len(new_normalized)
    old_ordered = sorted(old_normalized, key=lambda row: row["datetime"])
    new_ordered = sorted(new_normalized, key=lambda row: row["datetime"])
    packet: dict[str, Any] = {
        "schema_version": "htdy_frozen_data_window_equivalence_r4501_v1",
        "task_id": TASK_ID,
        "gate": DATA_EQUIVALENT_GATE if equivalent else BLOCKED_DATA_GATE,
        "comparison_result": "equivalent" if equivalent else "blocked_data_identity_drift",
        "row_count": len(old_normalized) if equivalent else None,
        "old_row_count": len(old_normalized),
        "new_row_count": len(new_normalized),
        "fields": list(fields),
        "old_first_bar": old_ordered[0] if old_ordered else None,
        "old_last_bar": old_ordered[-1] if old_ordered else None,
        "new_first_bar": new_ordered[0] if new_ordered else None,
        "new_last_bar": new_ordered[-1] if new_ordered else None,
        "old_ordered_bar_hash": packet_hash(old_ordered),
        "new_ordered_bar_hash": packet_hash(new_ordered),
        "old_field_hashes": _field_hashes(old_ordered, fields),
        "new_field_hashes": _field_hashes(new_ordered, fields),
        "difference_count": len(differences),
        "difference_fields": dict(sorted(field_counts.items())),
        "first_difference": differences[0] if differences else None,
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def build_data_equivalence(
    repo_root: Path,
    *,
    data_root: Path,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    if baseline.get("gate") != BASELINE_GATE or not verify_packet_hash(baseline):
        raise ValueError("R45-00 baseline prerequisite is invalid")
    protocol = json.loads((repo_root / PROTOCOL_PATH).read_text(encoding="utf-8"))
    candidate = load_verified_packet(repo_root / CANDIDATE_PATH)
    frozen = protocol["frozen_data_policy"]
    execution = candidate["execution_snapshot"]
    start = datetime.fromisoformat(frozen["full_window_start"])
    end = datetime.fromisoformat(frozen["full_window_end"])
    old_path = data_root / frozen["relative_path"]
    new_path = data_root / execution["relative_path"]
    common_fields = [*REQUIRED_FIELDS]
    old_schema = set(pq.read_schema(old_path).names) if old_path.is_file() else set()
    new_schema = set(pq.read_schema(new_path).names) if new_path.is_file() else set()
    common_fields.extend(field for field in OPTIONAL_FIELDS if field in old_schema and field in new_schema)
    old = load_window_rows(
        old_path,
        start=start,
        end=end,
        fields=common_fields,
        declared_sha256=frozen["source_file_sha256"],
    )
    new = load_window_rows(
        new_path,
        start=start,
        end=end,
        fields=common_fields,
        declared_sha256=execution["file_sha256"],
    )
    result = compare_bar_rows(old["rows"], new["rows"], fields=common_fields)
    result.update(
        {
            "old_identity": {
                "data_version": frozen["data_version"],
                "relative_path": frozen["relative_path"],
                "declared_sha256": frozen["source_file_sha256"],
                "actual_sha256": old["actual_sha256"],
            },
            "new_identity": {
                "profile_id": execution.get("profile_id"),
                "profile_active_binding_id": execution.get("profile_active_binding_id"),
                "market_data_file_id": execution.get("market_data_file_id"),
                "data_version": execution["data_version"],
                "relative_path": execution["relative_path"],
                "declared_sha256": execution["file_sha256"],
                "actual_sha256": new["actual_sha256"],
            },
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "baseline_packet_hash": baseline["packet_hash"],
            "boundaries": baseline["boundaries"],
        }
    )
    result.pop("packet_hash", None)
    result["packet_hash"] = packet_hash(result)
    return result


def write_evidence(
    output_dir: Path,
    *,
    stem: str,
    title: str,
    packet: Mapping[str, Any],
) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"evidence directory is already populated: {output_dir.name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{stem}.md").write_text(
        f"# {title}\n\n"
        f"Gate: `{packet.get('gate')}`\n\n"
        f"Packet hash: `{packet.get('packet_hash')}`\n\n"
        "This is a read-only, versioned audit artifact. It does not authorize strategy reruns, "
        "canonical writes, live signals, notifications, or trading.\n",
        encoding="utf-8",
    )


def _normalize_row(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            normalized[field] = value.isoformat()
        elif isinstance(value, date):
            normalized[field] = value.isoformat()
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"non-finite comparison value: {field}")
            normalized[field] = value
        else:
            normalized[field] = value
    return normalized


def _duplicate_datetimes(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    counts = Counter(str(row["datetime"]) for row in rows)
    return sorted(timestamp for timestamp, count in counts.items() if count > 1)


def _field_hashes(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> dict[str, str]:
    return {field: packet_hash([row[field] for row in rows]) for field in fields}
