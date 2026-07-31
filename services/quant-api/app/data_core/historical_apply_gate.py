"""Hash-bound authorization contract for the one JM data-core apply Gate."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Callable, Mapping


class HistoricalApplyGateError(ValueError):
    """Raised before any migration, provider, filesystem, or metadata write."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_ACTUAL_JM_CONTRACT = re.compile(r"JM\d{4}\Z")
_MAX_PACKET_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedApplyProgress:
    approved_state_digest: str
    current_state_digest: str
    mapping_rows: tuple[dict[str, Any], ...]
    completed_datasets: tuple[dict[str, Any], ...]


def build_apply_approval_packet(*, bound_facts: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_bound_facts(bound_facts)
    packet = {
        "schema_version": 1,
        "gate": "GY-DATA-CORE-V2-JM-HISTORICAL-APPLY",
        "bound_facts": normalized,
    }
    return {**packet, "packet_hash": _digest(packet)}


def verify_apply_approval_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    progress_receipt: Mapping[str, Any] | None = None,
    verified_progress: VerifiedApplyProgress | None = None,
) -> None:
    if not isinstance(packet, Mapping):
        raise HistoricalApplyGateError("approval_packet_invalid")
    if not isinstance(approval_hash, str) or len(approval_hash) != 64:
        raise HistoricalApplyGateError("approval_hash_invalid")
    expected = build_apply_approval_packet(
        bound_facts=_validate_bound_facts(packet.get("bound_facts"))
    )
    if (
        packet.get("schema_version") != expected["schema_version"]
        or packet.get("gate") != expected["gate"]
        or packet.get("packet_hash") != expected["packet_hash"]
        or approval_hash != expected["packet_hash"]
    ):
        raise HistoricalApplyGateError("approval_packet_mismatch")
    normalized_current = _validate_bound_facts(current_facts)
    if normalized_current == expected["bound_facts"]:
        return
    del progress_receipt
    approved_state = expected["bound_facts"]["current_state"]
    current_state = normalized_current["current_state"]
    if not (
        isinstance(verified_progress, VerifiedApplyProgress)
        and verified_progress.approved_state_digest == approved_state["state_digest"]
        and verified_progress.current_state_digest == current_state["state_digest"]
    ):
        raise HistoricalApplyGateError("approval_facts_changed")


def verify_approved_apply_progress(
    approved_facts: Mapping[str, Any],
    current_facts: Mapping[str, Any],
    *,
    verify_partition: Callable[[Mapping[str, Any], Mapping[str, Any]], bool],
) -> VerifiedApplyProgress:
    approved = _validate_bound_facts(approved_facts)
    current = _validate_bound_facts(current_facts)
    approved_without_state = dict(approved)
    current_without_state = dict(current)
    initial = approved_without_state.pop("current_state")
    progressed = current_without_state.pop("current_state")
    if approved_without_state != current_without_state or not callable(verify_partition):
        raise HistoricalApplyGateError("approval_facts_changed")
    if _digest({"items": initial["catalog_items"]}) != initial["catalog_digest"]:
        raise HistoricalApplyGateError("approval_facts_invalid")
    if _digest({"rows": initial["mapping_rows"]}) != initial["mapping_digest"]:
        raise HistoricalApplyGateError("approval_facts_invalid")
    if (
        _digest({"plans": initial["dataset_write_plan"]})
        != initial["dataset_write_plan_digest"]
    ):
        raise HistoricalApplyGateError("approval_facts_invalid")
    if _digest({"items": progressed["catalog_items"]}) != progressed["catalog_digest"]:
        raise HistoricalApplyGateError("approval_facts_changed")
    if _digest({"rows": progressed["mapping_rows"]}) != progressed["mapping_digest"]:
        raise HistoricalApplyGateError("approval_facts_changed")
    if (
        _digest({"plans": progressed["dataset_write_plan"]})
        != progressed["dataset_write_plan_digest"]
    ):
        raise HistoricalApplyGateError("approval_facts_changed")
    for field in (
        "calendar_digest",
        "session_digest",
        "trading_days",
        "session_windows",
    ):
        if initial[field] != progressed[field]:
            raise HistoricalApplyGateError("approval_facts_changed")

    mapping_plan = approved["mapping_write_plan"]
    initial_rows = _mapping_rows_by_day(initial["mapping_rows"])
    current_rows = _mapping_rows_by_day(progressed["mapping_rows"])
    if any(current_rows.get(day) != row for day, row in initial_rows.items()):
        raise HistoricalApplyGateError("approval_facts_changed")
    allowed_days = set(mapping_plan["trading_days"])
    allowed_contracts = set(mapping_plan["allowed_contracts"])
    if any(
        day not in allowed_days
        or row.get("symbol") != "jm"
        or row.get("rank") != 1
        or row.get("actual_contract") not in allowed_contracts
        or not isinstance(row.get("data_version"), str)
        or not row["data_version"]
        for day, row in current_rows.items()
    ):
        raise HistoricalApplyGateError("approval_facts_changed")
    expected_missing = sorted(allowed_days - set(current_rows))
    if (
        progressed["missing_mapping_days"] != expected_missing
        or progressed["mapping_complete"] is not (not expected_missing)
    ):
        raise HistoricalApplyGateError("approval_facts_changed")

    initial_catalog = _catalog_items_by_dataset(initial["catalog_items"])
    current_catalog = _catalog_items_by_dataset(progressed["catalog_items"])
    completed: list[dict[str, Any]] = []
    plans = _write_plans_by_dataset(progressed["dataset_write_plan"])
    if set(plans) != set(current_catalog):
        raise HistoricalApplyGateError("approval_facts_changed")
    for key, initial_item in initial_catalog.items():
        current_item = current_catalog.get(key)
        if current_item is None:
            raise HistoricalApplyGateError("approval_facts_changed")
        for partition in initial_item.get("partitions", []):
            if partition not in current_item.get("partitions", []):
                raise HistoricalApplyGateError("approval_facts_changed")
    for key, current_item in current_catalog.items():
        dataset = current_item["dataset"]
        windows = _approved_dataset_windows(
            approved,
            dataset,
            mapping_rows=current_rows,
        )
        if not windows:
            raise HistoricalApplyGateError("approval_facts_changed")
        initial_partitions = initial_catalog.get(key, {}).get("partitions", [])
        for partition in current_item.get("partitions", []):
            if not verify_partition(dataset, partition):
                raise HistoricalApplyGateError("approval_progress_partition_invalid")
            if partition not in initial_partitions and not _effect_within_windows(
                partition, windows
            ):
                raise HistoricalApplyGateError("approval_facts_changed")
        initial_gaps = initial_catalog.get(key, {}).get("gaps", [])
        current_gaps = current_item.get("gaps", [])
        for gap in current_gaps:
            if gap not in initial_gaps and not _effect_within_windows(gap, windows):
                raise HistoricalApplyGateError("approval_facts_changed")
        plan = plans.get(key)
        partitions = current_item.get("partitions", [])
        expected_mapping_windows = _serialize_windows(windows)
        expected_missing_windows = _serialize_windows(
            _missing_windows(windows, partitions)
        )
        if (
            plan is None
            or plan.get("mapping_valid_windows") != expected_mapping_windows
            or plan.get("missing_windows") != expected_missing_windows
        ):
            raise HistoricalApplyGateError("approval_facts_changed")
        if not expected_missing_windows and partitions:
            completed.append(
                {"dataset": dataset, "partition_evidence": list(partitions)}
            )
    return VerifiedApplyProgress(
        approved_state_digest=initial["state_digest"],
        current_state_digest=progressed["state_digest"],
        mapping_rows=tuple(current_rows[day] for day in sorted(current_rows)),
        completed_datasets=tuple(completed),
    )


def _mapping_rows_by_day(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise HistoricalApplyGateError("approval_facts_invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("trading_day"), str):
            raise HistoricalApplyGateError("approval_facts_invalid")
        row = dict(item)
        day = row["trading_day"]
        if day in result:
            raise HistoricalApplyGateError("approval_facts_invalid")
        result[day] = row
    return result


def _dataset_token(dataset: Mapping[str, Any]) -> str:
    return json.dumps(dict(dataset), sort_keys=True, separators=(",", ":"))


def _catalog_items_by_dataset(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise HistoricalApplyGateError("approval_facts_invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("dataset"), Mapping):
            raise HistoricalApplyGateError("approval_facts_invalid")
        normalized = dict(item)
        key = _dataset_token(normalized["dataset"])
        if key in result:
            raise HistoricalApplyGateError("approval_facts_invalid")
        result[key] = normalized
    return result


def _write_plans_by_dataset(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise HistoricalApplyGateError("approval_facts_invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"dataset", "mapping_valid_windows", "missing_windows"}
            or not isinstance(item.get("dataset"), Mapping)
            or not isinstance(item.get("mapping_valid_windows"), list)
            or not isinstance(item.get("missing_windows"), list)
        ):
            raise HistoricalApplyGateError("approval_facts_changed")
        key = _dataset_token(item["dataset"])
        if key in result:
            raise HistoricalApplyGateError("approval_facts_changed")
        result[key] = dict(item)
    return result


def _serialize_windows(
    windows: tuple[tuple[datetime, datetime], ...],
) -> list[list[str]]:
    return [[start.isoformat(), end.isoformat()] for start, end in windows]


def _missing_windows(
    windows: tuple[tuple[datetime, datetime], ...],
    partitions: list[Mapping[str, Any]],
) -> tuple[tuple[datetime, datetime], ...]:
    covered: list[tuple[datetime, datetime]] = []
    for partition in partitions:
        try:
            start = _aware_datetime(partition.get("coverage_start"))
            end = _aware_datetime(partition.get("coverage_end"))
        except (TypeError, ValueError):
            raise HistoricalApplyGateError(
                "approval_progress_partition_invalid"
            ) from None
        if start >= end:
            raise HistoricalApplyGateError("approval_progress_partition_invalid")
        covered.append((start, end))

    missing: list[tuple[datetime, datetime]] = []
    for window_start, window_end in windows:
        cursor = window_start
        clipped = sorted(
            (
                max(window_start, start),
                min(window_end, end),
            )
            for start, end in covered
            if start < window_end and end > window_start
        )
        for covered_start, covered_end in clipped:
            if cursor < covered_start:
                missing.append((cursor, covered_start))
            cursor = max(cursor, covered_end)
        if cursor < window_end:
            missing.append((cursor, window_end))
    return tuple(missing)


def _approved_dataset_windows(
    facts: Mapping[str, Any],
    dataset: Mapping[str, Any],
    *,
    mapping_rows: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[datetime, datetime], ...]:
    scope = facts["scope"]
    if not (
        dataset.get("provider") == "rqdata"
        and dataset.get("symbol") == "jm"
        and dataset.get("adjustment") == "none"
        and dataset.get("schema_version") == "canonical-bar-v1"
    ):
        return ()
    kind = dataset.get("dataset_kind")
    frequency = dataset.get("frequency")
    if frequency not in scope["direct_frequency_matrix"].get(kind, []):
        return ()
    if kind == "continuous":
        if dataset.get("contract_or_series") != "JM.MAIN":
            return ()
        return ((
            _aware_datetime(scope["window"]["start"]),
            _aware_datetime(scope["window"]["end"]),
        ),)
    contract = dataset.get("contract_or_series")
    if kind != "actual_dominant" or contract not in scope["contract_or_series"][1:]:
        return ()
    return tuple(
        (
            _aware_datetime(item["start"]),
            _aware_datetime(item["end"]),
        )
        for item in facts["current_state"]["session_windows"]
        if mapping_rows.get(item["trading_day"], {}).get("actual_contract")
        == contract
    )


def _effect_within_windows(
    effect: Mapping[str, Any],
    windows: tuple[tuple[datetime, datetime], ...],
) -> bool:
    start = effect.get("coverage_start", effect.get("gap_start"))
    end = effect.get("coverage_end", effect.get("gap_end"))
    try:
        parsed_start = _aware_datetime(start)
        parsed_end = _aware_datetime(end)
    except (TypeError, ValueError):
        return False
    return any(
        window_start <= parsed_start < parsed_end <= window_end
        for window_start, window_end in windows
    )


def load_apply_approval_packet(
    path: Path,
    *,
    approval_hash: str,
) -> dict[str, Any]:
    """Load and self-verify a packet before a database session is opened."""
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise HistoricalApplyGateError("approval_packet_path_invalid")
    try:
        stat_result = path.stat()
        if not path.is_file() or stat_result.st_size > _MAX_PACKET_BYTES:
            raise HistoricalApplyGateError("approval_packet_path_invalid")
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except HistoricalApplyGateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalApplyGateError("approval_packet_invalid") from exc
    if not isinstance(parsed, Mapping):
        raise HistoricalApplyGateError("approval_packet_invalid")
    verify_apply_approval_packet(
        parsed,
        approval_hash=approval_hash,
        current_facts=parsed.get("bound_facts"),
    )
    return dict(parsed)


def _validate_bound_facts(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HistoricalApplyGateError("approval_facts_invalid")
    required = {
        "task_head",
        "source_checkout",
        "migration_revisions",
        "scope",
        "plan_digest",
        "mapping_write_plan",
        "current_state",
        "write_set",
        "rollback",
    }
    if set(value) != required:
        raise HistoricalApplyGateError("approval_facts_invalid")
    task_head = value["task_head"]
    source_checkout = value["source_checkout"]
    plan_digest = value["plan_digest"]
    migrations = value["migration_revisions"]
    scope = value["scope"]
    write_set = value["write_set"]
    rollback = value["rollback"]
    current_state = value["current_state"]
    mapping_write_plan = value["mapping_write_plan"]
    if (
        not _git_sha(task_head)
        or not _sha256(plan_digest)
        or not isinstance(source_checkout, str)
        or not Path(source_checkout).is_absolute()
    ):
        raise HistoricalApplyGateError("approval_facts_invalid")
    if not (
        isinstance(migrations, list)
        and migrations == ["20260730_0026", "20260730_0027"]
    ):
        raise HistoricalApplyGateError("approval_facts_invalid")
    normalized_scope = _validate_scope(scope)
    normalized_write_set = _validate_write_set(write_set)
    normalized_rollback = _validate_rollback(rollback)
    normalized_state = _validate_current_state(current_state)
    normalized_mapping_plan = _validate_mapping_write_plan(
        mapping_write_plan,
        contracts=normalized_scope["contract_or_series"] if normalized_scope else [],
    )
    if (
        normalized_scope is None
        or normalized_write_set is None
        or normalized_rollback is None
        or normalized_state is None
        or normalized_mapping_plan is None
    ):
        raise HistoricalApplyGateError("approval_facts_invalid")
    return {
        "task_head": task_head,
        "source_checkout": str(Path(source_checkout)),
        "migration_revisions": list(migrations),
        "scope": normalized_scope,
        "plan_digest": plan_digest,
        "mapping_write_plan": normalized_mapping_plan,
        "current_state": normalized_state,
        "write_set": normalized_write_set,
        "rollback": normalized_rollback,
    }


def _validate_scope(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "symbol",
        "provider",
        "schema_version",
        "dataset_kinds",
        "direct_frequencies",
        "direct_frequency_matrix",
        "window",
        "contract_or_series",
    }:
        return None
    contracts = value["contract_or_series"]
    if not (
        value["symbol"] == "jm"
        and value["provider"] == "rqdata"
        and value["schema_version"] == "canonical-bar-v1"
        and value["dataset_kinds"] == ["continuous", "actual_dominant"]
        and value["direct_frequencies"] == ["1m", "1d", "1w"]
        and value["direct_frequency_matrix"]
        == {
            "continuous": ["1m", "1d", "1w"],
            "actual_dominant": ["1m", "1d"],
        }
        and isinstance(contracts, list)
        and contracts
        and contracts == sorted(set(contracts))
        and contracts[0] == "JM.MAIN"
        and all(
            isinstance(item, str) and _ACTUAL_JM_CONTRACT.fullmatch(item)
            for item in contracts[1:]
        )
    ):
        return None
    window = value["window"]
    if not isinstance(window, Mapping) or set(window) != {"start", "end"}:
        return None
    try:
        start = _aware_datetime(window["start"])
        end = _aware_datetime(window["end"])
    except (TypeError, ValueError):
        return None
    if start >= end:
        return None
    return {
        "symbol": "jm",
        "provider": "rqdata",
        "schema_version": "canonical-bar-v1",
        "dataset_kinds": ["continuous", "actual_dominant"],
        "direct_frequencies": ["1m", "1d", "1w"],
        "direct_frequency_matrix": {
            "continuous": ["1m", "1d", "1w"],
            "actual_dominant": ["1m", "1d"],
        },
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "contract_or_series": list(contracts),
    }


def _validate_write_set(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "canonical_root",
        "staging_root",
        "postgresql_target",
        "postgresql_tables",
        "writes_legacy_market_data_assets",
        "partial_apply_receipt",
    }:
        return None
    root = value["canonical_root"]
    staging_root = value["staging_root"]
    postgresql_target = value["postgresql_target"]
    receipt = value["partial_apply_receipt"]
    expected_tables = [
        "market_datasets",
        "market_partitions",
        "data_gaps",
        "main_contract_map",
    ]
    root_path = Path(root) if isinstance(root, str) else None
    staging_path = Path(staging_root) if isinstance(staging_root, str) else None
    receipt_path = Path(receipt) if isinstance(receipt, str) else None
    if not (
        isinstance(root, str)
        and root_path is not None
        and root_path.is_absolute()
        and _is_data_core_root(root_path, leaf="canonical")
        and isinstance(staging_root, str)
        and staging_path is not None
        and staging_path.is_absolute()
        and _is_data_core_root(staging_path, leaf="staging")
        and staging_path.parent == root_path.parent
        and receipt_path is not None
        and receipt_path.is_absolute()
        and receipt_path.parent.parts[-4:]
        == ("data", "parquet", "data-core-v2", "receipts")
        and receipt_path.parent.parent == root_path.parent
        and _valid_postgresql_target(postgresql_target)
        and value["postgresql_tables"] == expected_tables
        and value["writes_legacy_market_data_assets"] is False
    ):
        return None
    return {
        "canonical_root": str(root_path),
        "staging_root": str(staging_path),
        "postgresql_target": dict(postgresql_target),
        "postgresql_tables": expected_tables,
        "writes_legacy_market_data_assets": False,
        "partial_apply_receipt": str(receipt_path),
    }


def _valid_postgresql_target(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "drivername",
        "username",
        "host",
        "port",
        "database",
    }:
        return False
    return bool(
        value["drivername"] == "postgresql+psycopg"
        and isinstance(value["username"], str)
        and value["username"].strip()
        and (value["host"] is None or isinstance(value["host"], str))
        and (value["port"] is None or type(value["port"]) is int)
        and isinstance(value["database"], str)
        and value["database"].strip()
    )


def _validate_current_state(value: object) -> dict[str, Any] | None:
    required = {
        "catalog_digest",
        "mapping_digest",
        "calendar_digest",
        "session_digest",
        "dataset_write_plan_digest",
        "mapping_complete",
        "missing_mapping_days",
        "trading_days",
        "session_windows",
        "catalog_items",
        "mapping_rows",
        "dataset_write_plan",
        "state_digest",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return None
    if any(
        not _sha256(value[field])
        for field in (
            "catalog_digest",
            "mapping_digest",
            "calendar_digest",
            "session_digest",
            "dataset_write_plan_digest",
            "state_digest",
        )
    ):
        return None
    if type(value["mapping_complete"]) is not bool:
        return None
    if not isinstance(value["missing_mapping_days"], list) or not isinstance(
        value["dataset_write_plan"], list
    ):
        return None
    if not isinstance(value["trading_days"], list) or not isinstance(
        value["session_windows"], list
    ):
        return None
    if not isinstance(value["catalog_items"], list) or not isinstance(
        value["mapping_rows"], list
    ):
        return None
    normalized = json.loads(json.dumps(dict(value), sort_keys=True))
    expected_digest = normalized.pop("state_digest")
    if _digest(normalized) != expected_digest:
        return None
    normalized["state_digest"] = expected_digest
    return normalized


def _validate_mapping_write_plan(
    value: object,
    *,
    contracts: list[str],
) -> dict[str, Any] | None:
    required = {
        "provider",
        "symbol",
        "rank",
        "start_day",
        "end_day",
        "trading_days",
        "allowed_contracts",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return None
    days = value["trading_days"]
    allowed = value["allowed_contracts"]
    try:
        parsed_days = [datetime.fromisoformat(item).date() for item in days]
        start_day = datetime.fromisoformat(value["start_day"]).date()
        end_day = datetime.fromisoformat(value["end_day"]).date()
    except (TypeError, ValueError):
        return None
    if not (
        value["provider"] == "rqdata"
        and value["symbol"] == "jm"
        and value["rank"] == 1
        and isinstance(days, list)
        and days
        and days == sorted(set(days))
        and parsed_days[0] == start_day
        and parsed_days[-1] == end_day
        and isinstance(allowed, list)
        and allowed == contracts[1:]
        and allowed == sorted(set(allowed))
    ):
        return None
    return {
        "provider": "rqdata",
        "symbol": "jm",
        "rank": 1,
        "start_day": start_day.isoformat(),
        "end_day": end_day.isoformat(),
        "trading_days": list(days),
        "allowed_contracts": list(allowed),
    }


def _is_data_core_root(path: Path, *, leaf: str) -> bool:
    return path.parts[-4:] == ("data", "parquet", "data-core-v2", leaf)


def _validate_rollback(value: object) -> dict[str, Any] | None:
    expected = {
        "deletes_physical_data": False,
        "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        return None
    return expected


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("datetime must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed


def _git_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value)
    )


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
