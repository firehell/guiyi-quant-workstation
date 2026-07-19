"""Read-only R4501B reconstruction of a frozen 15m window completion."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow.parquet as pq

from app.backtest.htdy_stage45_closeout import (
    BASELINE_GATE,
    REQUIRED_FIELDS,
    compare_bar_rows,
    file_sha256,
    load_verified_packet,
    packet_hash,
    write_evidence,
)
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality


TASK_ID = "HTDY-FROZEN-DATA-WINDOW-EQUIVALENCE-R4501B"
OLD_PACKET_HASH = "142de03ada02555ce2d734e532cee097b5c23e4d91b6f92d62121b8e771b4c47"
BASELINE_PACKET_HASH = "2cd937d4754e36f62e65ed972d633af2bd5b9d8128607af5a87c7e9cdf800efd"
EXPECTED_ORDERED_HASH = "c32df4e6b52e9efa0c71c6851d04cc9e0abd2a39f204776729b9a35037f6eba0"
PROTOCOL = Path("configs/oos/htdy_strict_validation_protocol_v1.json")
BASELINE = Path("data/reports/htdy_stage45_closeout_r45/baseline/BASELINE.json")
ORIGINAL_FAILURE = Path("data/reports/htdy_stage45_closeout_r45/data_equivalence/DATA_EQUIVALENCE.json")
CANDIDATE = Path("data/reports/htdy_trusted_backtest_candidate_x5_03/HTDY_TRUSTED_BACKTEST_CANDIDATE.json")
MANIFEST = Path("data/manifests/rqdata_jm_v2_history_20200102_20260711.csv")
ONE_MINUTE_RELATIVE_PATH = Path("data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1m_20200102_20260711_v2.parquet")
OUTPUT_ROOT = Path("data/reports/htdy_stage45_closeout_r45")
FIELDS = (*REQUIRED_FIELDS, "open_interest", "turnover")
COMPLETION_START = datetime.fromisoformat("2026-07-10T09:15:00")
COMPLETION_END = datetime.fromisoformat("2026-07-10T15:00:00")
REQUIRED_COMPLETION_TIMES = (
    "2026-07-10T09:15:00",
    "2026-07-10T09:30:00",
    "2026-07-10T09:45:00",
    "2026-07-10T10:00:00",
    "2026-07-10T10:15:00",
    "2026-07-10T10:45:00",
    "2026-07-10T11:00:00",
    "2026-07-10T11:15:00",
    "2026-07-10T11:30:00",
    "2026-07-10T13:45:00",
    "2026-07-10T14:00:00",
    "2026-07-10T14:15:00",
    "2026-07-10T14:30:00",
    "2026-07-10T14:45:00",
    "2026-07-10T15:00:00",
)


def build_completion_rows(
    old_rows: Sequence[Mapping[str, Any]],
    rebuilt_rows: Sequence[Mapping[str, Any]],
    execution_rows: Sequence[Mapping[str, Any]],
    *,
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    """Return only the versioned completion after proving old base equality."""
    old_by_time = {_timestamp(row): row for row in old_rows}
    rebuilt_by_time = {_timestamp(row): row for row in rebuilt_rows}
    execution_by_time = {_timestamp(row): row for row in execution_rows}
    if len(old_by_time) != len(old_rows) or len(rebuilt_by_time) != len(rebuilt_rows) or len(execution_by_time) != len(execution_rows):
        raise ValueError("duplicate datetime in immutable base or rebuilt data")
    for stamp, old in old_by_time.items():
        if stamp not in rebuilt_by_time or not _same(old, rebuilt_by_time[stamp], fields):
            raise ValueError("rebuilt 15m does not exactly preserve immutable base")
    rebuilt_extras = sorted(set(rebuilt_by_time) - set(old_by_time))
    execution_extras = sorted(set(execution_by_time) - set(old_by_time))
    required_times = list(REQUIRED_COMPLETION_TIMES)
    if rebuilt_extras != required_times or execution_extras != required_times:
        raise ValueError("completion must contain exactly the 15 execution-side bars")
    completion = [rebuilt_by_time[stamp] for stamp in rebuilt_extras]
    for row in completion:
        stamp = _timestamp(row)
        if stamp not in execution_by_time or not _same(row, execution_by_time[stamp], fields):
            raise ValueError("completion row differs from execution asset")
    return [_normalized(row, fields) for row in completion]


def run_completion(repo_root: Path, data_root: Path) -> dict[str, dict[str, Any]]:
    baseline = load_verified_packet(repo_root / BASELINE)
    failed = load_verified_packet(repo_root / ORIGINAL_FAILURE)
    candidate = load_verified_packet(repo_root / CANDIDATE)
    if baseline.get("gate") != BASELINE_GATE or baseline.get("packet_hash") != BASELINE_PACKET_HASH:
        raise ValueError("R45-00 baseline identity is invalid")
    if failed.get("packet_hash") != OLD_PACKET_HASH or failed.get("gate") != "STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT":
        raise ValueError("original R45-01 failure packet is invalid")
    protocol = _load_json(repo_root / PROTOCOL)
    frozen = protocol["frozen_data_policy"]
    execution = candidate["execution_snapshot"]
    if candidate.get("gate") != "HTDY_TRUSTED_BACKTEST_CANDIDATE" or candidate.get("packet_hash") != baseline.get("evidence", {}).get("x503", {}).get("packet_hash"):
        raise ValueError("candidate packet prerequisite is invalid")
    if file_sha256(repo_root / PROTOCOL) != baseline.get("protocol_hash") or candidate.get("protocol_hash") != baseline.get("protocol_hash") or candidate.get("parameter_hash") != baseline.get("parameter_hash"):
        raise ValueError("protocol or candidate packet identity mismatch")
    if frozen.get("data_role") != "primary" or frozen.get("quality_status") != "passed":
        raise ValueError("frozen data policy is not primary+passed")
    if execution.get("data_role") != "primary" or execution.get("quality_status") != "passed":
        raise ValueError("execution identity is not primary+passed")
    _verify_manifest(repo_root / MANIFEST, execution)
    _verify_manifest_row(repo_root / MANIFEST, "1m", {"market_data_file_id": 71290, "data_quality_report_id": 68568, "row_count": 532155})
    old_path = data_root / frozen["relative_path"]
    one_minute_path = data_root / ONE_MINUTE_RELATIVE_PATH
    execution_path = data_root / execution["relative_path"]
    _verify_file(old_path, frozen["source_file_sha256"])
    _verify_file(execution_path, execution["file_sha256"])
    one_minute_sha = _manifest_value(repo_root / MANIFEST, "1m", "checksum")
    _verify_file(one_minute_path, one_minute_sha)
    start = datetime.fromisoformat(frozen["full_window_start"])
    end = datetime.fromisoformat(frozen["full_window_end"])
    old_rows = _rows(old_path, start, end)
    execution_rows = _rows(execution_path, start, end)
    one_minute = _frame(one_minute_path, start, end)
    if set(one_minute["quality_status"].astype(str)) != {"passed"} or set(one_minute["data_role"].astype(str)) != {"primary"}:
        raise ValueError("passed 1m identity does not satisfy primary+passed")
    rebuilt = aggregate_standard_bars(one_minute, "15m")
    quality = evaluate_standard_dominant_quality(rebuilt, "15m")
    if quality.status != "passed":
        raise ValueError("rebuilt 15m quality did not pass")
    rebuilt["quality_status"] = "passed"
    rebuilt_rows = _frame_rows(rebuilt, start, end)
    completion_rows = build_completion_rows(old_rows, rebuilt_rows, execution_rows, fields=FIELDS)
    combined_rows = old_rows + completion_rows
    comparison = compare_bar_rows(combined_rows, execution_rows, fields=FIELDS)
    if comparison["gate"] != "HTDY_FROZEN_DATA_WINDOW_EQUIVALENT" or comparison["row_count"] != 19381:
        raise ValueError("combined frozen window is not equivalent to execution asset")
    if comparison["new_ordered_bar_hash"] != EXPECTED_ORDERED_HASH:
        raise ValueError("combined ordered bar hash is not the approved execution identity")
    completion: dict[str, Any] = {
        "schema_version": "htdy_frozen_reference_completion_r4501b_v1",
        "task_id": TASK_ID,
        "gate": "HTDY_FROZEN_REFERENCE_COMPLETION_READY",
        "reference_mode": "immutable_base_plus_versioned_completion",
        "base_row_count": len(old_rows),
        "completion_row_count": len(completion_rows),
        "completion_start": COMPLETION_START.isoformat(),
        "completion_end": COMPLETION_END.isoformat(),
        "completion_rows": completion_rows,
        "old_file_sha256": frozen["source_file_sha256"],
        "passed_1m_sha256": one_minute_sha,
        "quality_status": quality.status,
        "boundaries": _boundaries(),
    }
    completion["packet_hash"] = packet_hash(completion)
    revalidated: dict[str, Any] = {
        "schema_version": "htdy_frozen_data_window_equivalence_r4501b_v1",
        "task_id": TASK_ID,
        "gate": comparison["gate"],
        "comparison": comparison,
        "old_row_count": comparison["old_row_count"],
        "base_row_count": len(old_rows),
        "completion_row_count": len(completion_rows),
        "composite_row_count": comparison["new_row_count"],
        "execution_row_count": len(execution_rows),
        "difference_count": comparison["difference_count"],
        "composite_ordered_bar_hash": comparison["old_ordered_bar_hash"],
        "execution_ordered_bar_hash": comparison["new_ordered_bar_hash"],
        "old_failure_packet_hash": OLD_PACKET_HASH,
        "completion_packet_hash": completion["packet_hash"],
        "baseline_packet_hash": BASELINE_PACKET_HASH,
        "boundaries": _boundaries(),
    }
    revalidated["packet_hash"] = packet_hash(revalidated)
    acceptance: dict[str, Any] = {
        "schema_version": "r45_01_current_acceptance_v1",
        "task_id": TASK_ID,
        "gate": "HTDY_FROZEN_DATA_WINDOW_EQUIVALENT",
        "baseline_packet_hash": BASELINE_PACKET_HASH,
        "original_failure_packet_hash": OLD_PACKET_HASH,
        "completion_packet_hash": completion["packet_hash"],
        "revalidated_packet_hash": revalidated["packet_hash"],
        "ordered_bar_hash": EXPECTED_ORDERED_HASH,
        "boundaries": _boundaries(),
    }
    acceptance["packet_hash"] = packet_hash(acceptance)
    return {"completion": completion, "revalidated": revalidated, "acceptance": acceptance}


def write_outputs(repo_root: Path, packets: Mapping[str, Mapping[str, Any]]) -> None:
    root = repo_root / OUTPUT_ROOT
    targets = (root / "data_completion_r4501b", root / "data_equivalence_revalidated_r4501b", root / "R45_01_ACCEPTANCE.json")
    if any(target.exists() and (target.is_file() or any(target.iterdir())) for target in targets):
        raise ValueError("R4501B evidence targets are already populated")
    write_evidence(root / "data_completion_r4501b", stem="DATA_COMPLETION", title="HTDY Frozen Data Completion R4501B", packet=packets["completion"])
    write_evidence(root / "data_equivalence_revalidated_r4501b", stem="DATA_EQUIVALENCE_REVALIDATED", title="HTDY Frozen Data Equivalence Revalidated R4501B", packet=packets["revalidated"])
    pointer = root / "R45_01_ACCEPTANCE.json"
    if pointer.exists():
        raise ValueError("R45_01_ACCEPTANCE.json already exists")
    pointer.write_text(json.dumps(packets["acceptance"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rows(path: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    return _frame_rows(_frame(path, start, end), start, end)


def _frame(path: Path, start: datetime, end: datetime) -> pd.DataFrame:
    frame = pq.ParquetFile(path).read().to_pandas()
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    return frame[(frame["datetime"] >= start) & (frame["datetime"] <= end)].copy()


def _frame_rows(frame: pd.DataFrame, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = frame[(frame["datetime"] >= start) & (frame["datetime"] <= end)][list(FIELDS)].to_dict("records")
    return [_normalized(row, FIELDS) for row in rows]


def _normalized(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for field in fields:
        item = row[field]
        if hasattr(item, "to_pydatetime"):
            item = item.to_pydatetime()
        if isinstance(item, datetime):
            item = item.replace(tzinfo=None).isoformat()
        elif hasattr(item, "isoformat") and not isinstance(item, str):
            item = item.isoformat()
        value[field] = item
    return value


def _timestamp(row: Mapping[str, Any]) -> str:
    item = row["datetime"]
    if hasattr(item, "to_pydatetime"):
        item = item.to_pydatetime()
    return item.replace(tzinfo=None).isoformat() if isinstance(item, datetime) else str(item)


def _same(left: Mapping[str, Any], right: Mapping[str, Any], fields: Sequence[str]) -> bool:
    return _normalized(left, fields) == _normalized(right, fields)


def _verify_file(path: Path, expected: str) -> None:
    if not path.is_file() or file_sha256(path) != expected:
        raise ValueError(f"declared file identity mismatch: {path.name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_value(path: Path, period: str, key: str) -> str:
    row = pd.read_csv(path).query("period == @period")
    if len(row) != 1:
        raise ValueError(f"manifest identity missing for {period}")
    return str(row.iloc[0][key])


def _verify_manifest(path: Path, execution: Mapping[str, Any]) -> None:
    row = pd.read_csv(path).query("period == '15m'")
    if len(row) != 1:
        raise ValueError("15m execution manifest identity missing")
    values = row.iloc[0]
    for key, manifest_key in (("data_version", "data_version"), ("file_sha256", "checksum"), ("market_data_file_id", "market_data_file_id")):
        if str(values[manifest_key]) != str(execution[key]):
            raise ValueError("execution manifest identity mismatch")
    if str(values["data_role"]) != "primary" or str(values["quality_status"]) != "passed":
        raise ValueError("execution manifest is not primary+passed")
    if int(values["market_data_file_id"]) != 71338 or int(values["data_quality_report_id"]) != 68804 or int(values["row_count"]) != 35477:
        raise ValueError("execution manifest file or quality identity mismatch")


def _verify_manifest_row(path: Path, period: str, expected: Mapping[str, int]) -> None:
    row = pd.read_csv(path).query("period == @period")
    if len(row) != 1 or any(int(row.iloc[0][key]) != value for key, value in expected.items()):
        raise ValueError("passed 1m manifest identity mismatch")
    if str(row.iloc[0]["data_role"]) != "primary" or str(row.iloc[0]["quality_status"]) != "passed":
        raise ValueError("passed 1m manifest is not primary+passed")
    actual_path = Path(str(row.iloc[0]["standard_path"]))
    if actual_path.is_absolute():
        actual_path = Path(*actual_path.parts[actual_path.parts.index("data"):]) if "data" in actual_path.parts else actual_path
    if actual_path != ONE_MINUTE_RELATIVE_PATH:
        raise ValueError("passed 1m manifest path is not the fixed relative identity")


def _boundaries() -> dict[str, bool]:
    return {"would_call_rqdata": False, "would_modify_parquet": False, "would_modify_manifest": False, "would_modify_profile": False, "would_write_database": False, "would_run_strategy": False, "would_modify_x5_evidence": False}
