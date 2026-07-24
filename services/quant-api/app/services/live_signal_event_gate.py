from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy import func, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from app.backtest.v1b_jm_tasks import JM_V1B_STRATEGY_CODE, JM_V1B_STRATEGY_VERSION
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.data_center import (
    DataDownloadTask,
    DataQualityReport,
    AfterMarketSchedulerCheckpoint,
    LiveAggregationCheckpoint,
    LiveAggregatedBar,
    LiveIngestCheckpoint,
    LiveMinuteBar,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.models.signal import SignalEvent, SignalNotification, SignalScanTask, StrategySignal
from app.services.after_market_real_acceptance import FORBIDDEN_COUNTERS
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash
from app.services.rqdata_ingest.jm_historical_catchup_execution import collect_active_binding_snapshot
from app.services.trading_session_clock import TradingSessionClock

TASK_ID = "JM-LIVE-SIGNAL-EVENT-S6-08"
FOUNDATION_TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
FOUNDATION_GATE = "JM_EOD_INCREMENTAL_AUTOMATION_READY"
FINAL_GATE = "JM_LIVE_SIGNAL_EVENT_PASSED"
PENDING_GATE = "PENDING_ELIGIBLE_EVENT"
REQUIRED_DB_REVISION = "20260721_0025"
MAX_RUNTIME_HEALTH_AGE_SECONDS = 180

FLAG_NAMES = (
    "GUIYI_LIVE_RUNTIME_ENABLED",
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
    "GUIYI_WECHAT_AUTOSEND_ENABLED",
    "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
    "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED",
)
ALLOWED_WRITES = (
    "live_minute_bars",
    "live_ingest_checkpoints",
    "live_aggregated_bars",
    "live_aggregation_checkpoints",
    "runtime_scheduler_lock_and_heartbeat",
    "strategy_signals_scoped",
    "signal_events_scoped",
)
FORBIDDEN_WRITES = (
    "signal_notifications",
    "signal_scan_tasks",
    "backtest_tasks",
    "backtest_reports",
    "backtest_trades",
    "backtest_orders",
    "profile_active_bindings",
    "historical_or_canonical_assets",
    "after_market_scheduler_or_checkpoint",
    "wechat_send",
    "orders_or_trades",
)


class LiveSignalEventGateError(RuntimeError):
    """Raised when S6-08 authorization or final acceptance fails closed."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LiveSignalEventGateError("json_artifact_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveSignalEventGateError("json_artifact_invalid") from exc
    if not isinstance(payload, dict):
        raise LiveSignalEventGateError("json_artifact_not_object")
    return payload


def validate_s6_final_receipt(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise LiveSignalEventGateError("s6_final_receipt_missing")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise LiveSignalEventGateError("s6_final_receipt_hash_mismatch")
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LiveSignalEventGateError("s6_final_receipt_invalid_json") from exc
    if not isinstance(receipt, dict):
        raise LiveSignalEventGateError("s6_final_receipt_not_object")
    if receipt.get("schema_version") != 2:
        raise LiveSignalEventGateError("s6_final_receipt_schema_invalid")
    if receipt.get("task_id") != FOUNDATION_TASK_ID:
        raise LiveSignalEventGateError("s6_final_receipt_task_invalid")
    if receipt.get("gate") != FOUNDATION_GATE:
        raise LiveSignalEventGateError("s6_final_receipt_gate_invalid")
    if receipt.get("status") != "completed":
        raise LiveSignalEventGateError("s6_final_receipt_status_invalid")
    if receipt.get("database_revision") != REQUIRED_DB_REVISION:
        raise LiveSignalEventGateError("s6_final_receipt_database_revision_invalid")
    runtime_commit = str(receipt.get("runtime_commit") or "")
    authorization_hash = str(receipt.get("authorization_hash") or "")
    if not _is_hex(runtime_commit, 40):
        raise LiveSignalEventGateError("s6_final_receipt_runtime_commit_invalid")
    if not _is_hex(authorization_hash, 64):
        raise LiveSignalEventGateError("s6_final_receipt_authorization_hash_invalid")
    boundaries = receipt.get("scope_boundaries")
    expected_boundaries = {
        "jm_eod_incremental_automation_ready": True,
        "jm_runtime_ready": False,
        "long_running_ready": False,
        "signal_event_ready": False,
        "notification_ready": False,
        "automatic_trading_ready": False,
    }
    if not isinstance(boundaries, Mapping) or dict(boundaries) != expected_boundaries:
        raise LiveSignalEventGateError("s6_final_receipt_scope_boundaries_invalid")
    d1_day = _validate_s6_day_evidence(receipt.get("d1"), "d1", require_runtime=True)
    outage_day, last_successful_day = _validate_s6_outage(receipt.get("d2_outage"))
    d2_day = _validate_s6_day_evidence(receipt.get("d2"), "d2", require_runtime=False)
    _validate_s6_deployment_lineage(receipt, runtime_commit, authorization_hash)
    if not (d1_day < d2_day and outage_day == d2_day and d1_day <= last_successful_day < d2_day):
        raise LiveSignalEventGateError("s6_final_receipt_d2_invalid")
    _validate_s6_forbidden_writes(receipt)
    return {"path": str(path.resolve()), "sha256": digest, "receipt": receipt}


def _validate_s6_deployment_lineage(
    receipt: Mapping[str, Any], runtime_commit: str, authorization_hash: str
) -> None:
    lineage = receipt.get("deployment_lineage")
    if not isinstance(lineage, Mapping):
        raise LiveSignalEventGateError("s6_final_receipt_deployment_lineage_invalid")
    required_commits = {
        "deployment_commit": None,
        "runtime_commit": runtime_commit,
        "d1_runtime_commit": (receipt.get("d1") or {}).get("runtime_commit"),
        "d2_outage_runtime_commit": (receipt.get("d2_outage") or {}).get("runtime_commit"),
    }
    for key, expected in required_commits.items():
        value = str(lineage.get(key) or "")
        if not _is_hex(value, 40) or (expected is not None and value != expected):
            raise LiveSignalEventGateError("s6_final_receipt_deployment_lineage_invalid")
    if any(lineage.get(key) is not True for key in (
        "deployment_is_ancestor",
        "d1_runtime_is_ancestor",
        "d2_outage_runtime_is_ancestor",
    )):
        raise LiveSignalEventGateError("s6_final_receipt_deployment_lineage_invalid")
    artifacts = {
        "deployment_receipt": None,
        "service_enable_packet": authorization_hash,
        "d1_service_enable_packet": (receipt.get("d1") or {}).get("authorization_hash"),
        "d2_outage_service_enable_packet": (receipt.get("d2_outage") or {}).get("authorization_hash"),
    }
    for key, expected_sha256 in artifacts.items():
        artifact = lineage.get(key)
        if not _valid_s6_evidence(artifact):
            raise LiveSignalEventGateError("s6_final_receipt_deployment_lineage_invalid")
        if expected_sha256 is not None and artifact.get("sha256") != expected_sha256:
            raise LiveSignalEventGateError("s6_final_receipt_deployment_lineage_invalid")


def _validate_s6_day_evidence(value: Any, name: str, *, require_runtime: bool) -> date:
    if not isinstance(value, Mapping):
        raise LiveSignalEventGateError(f"s6_final_receipt_{name}_invalid")
    try:
        trading_day = date.fromisoformat(str(value.get("trading_day") or ""))
    except ValueError as exc:
        raise LiveSignalEventGateError(f"s6_final_receipt_{name}_invalid") from exc
    required_hashes = ("execution_packet_hash", "receipt_sha256")
    if (
        not str(value.get("batch_id") or "")
        or any(not _is_sha256(str(value.get(key) or "")) for key in required_hashes)
        or not _valid_s6_evidence(value.get("evidence"))
    ):
        raise LiveSignalEventGateError(f"s6_final_receipt_{name}_invalid")
    if require_runtime and (
        not _is_hex(str(value.get("runtime_commit") or ""), 40)
        or not _is_sha256(str(value.get("authorization_hash") or ""))
    ):
        raise LiveSignalEventGateError(f"s6_final_receipt_{name}_invalid")
    return trading_day


def _validate_s6_outage(value: Any) -> tuple[date, date]:
    if not isinstance(value, Mapping):
        raise LiveSignalEventGateError("s6_final_receipt_d2_outage_invalid")
    try:
        outage_day = date.fromisoformat(str(value.get("trading_day") or ""))
        last_successful_day = date.fromisoformat(str(value.get("last_successful_before_outage") or ""))
    except ValueError as exc:
        raise LiveSignalEventGateError("s6_final_receipt_d2_outage_invalid") from exc
    archive_lag_trading_days = value.get("archive_lag_trading_days")
    heartbeat = value.get("heartbeat")
    if (
        not _is_hex(str(value.get("runtime_commit") or ""), 40)
        or not _is_sha256(str(value.get("authorization_hash") or ""))
        or not _valid_s6_evidence(value.get("evidence"))
        or isinstance(archive_lag_trading_days, bool)
        or not isinstance(archive_lag_trading_days, int)
        or archive_lag_trading_days != 1
        or not isinstance(heartbeat, Mapping)
        or heartbeat.get("status") != "degraded"
        or heartbeat.get("error_type") not in {"heartbeat_missing", "heartbeat_stale"}
    ):
        raise LiveSignalEventGateError("s6_final_receipt_d2_outage_invalid")
    return outage_day, last_successful_day


def _validate_s6_forbidden_writes(receipt: Mapping[str, Any]) -> None:
    counts = receipt.get("forbidden_write_counts")
    deltas = receipt.get("forbidden_write_deltas")
    if not isinstance(counts, Mapping) or not isinstance(deltas, Mapping):
        raise LiveSignalEventGateError("s6_final_receipt_forbidden_write_deltas_invalid")
    baseline, final = counts.get("baseline"), counts.get("final")
    if (
        not isinstance(baseline, Mapping)
        or not isinstance(final, Mapping)
        or set(baseline) != set(FORBIDDEN_COUNTERS)
        or set(final) != set(FORBIDDEN_COUNTERS)
        or set(deltas) != set(FORBIDDEN_COUNTERS)
    ):
        raise LiveSignalEventGateError("s6_final_receipt_forbidden_write_deltas_invalid")
    for key in FORBIDDEN_COUNTERS:
        before, after, delta = baseline[key], final[key], deltas[key]
        if (
            isinstance(before, bool)
            or isinstance(after, bool)
            or isinstance(delta, bool)
            or not all(isinstance(value, int) for value in (before, after, delta))
            or before < 0
            or after < 0
            or delta != 0
            or after - before != delta
        ):
            raise LiveSignalEventGateError("s6_final_receipt_forbidden_write_deltas_invalid")


def _valid_s6_evidence(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("path"), str)
        and bool(value["path"].strip())
        and isinstance(value.get("sha256"), str)
        and _is_sha256(value["sha256"])
    )


def build_service_approval_packet(
    *,
    target_trading_day: str | date,
    bound_facts: Mapping[str, Any],
    s6_final_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    trading_day = _date_value(target_trading_day)
    receipt = s6_final_receipt.get("receipt")
    if not isinstance(receipt, Mapping) or receipt.get("gate") != FOUNDATION_GATE:
        raise LiveSignalEventGateError("s6_final_receipt_not_validated")
    flags = bound_facts.get("feature_flags")
    authorization_config = bound_facts.get("authorization_config")
    if not isinstance(flags, Mapping) or any(
        (
            flags.get("GUIYI_LIVE_RUNTIME_ENABLED") is not True,
            flags.get("GUIYI_LIVE_SIGNAL_EVENTS_ENABLED") is not False,
            flags.get("GUIYI_WECHAT_AUTOSEND_ENABLED") is not False,
            flags.get("GUIYI_AFTER_MARKET_ARCHIVE_ENABLED") is not False,
        )
    ):
        raise LiveSignalEventGateError("packet_pre_enable_flags_invalid")
    if not isinstance(authorization_config, Mapping) or any(authorization_config.values()):
        raise LiveSignalEventGateError("packet_pre_enable_authorization_config_invalid")
    packet: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "approval_required",
        "target_gate": FINAL_GATE,
        "product": "jm",
        "exchange": "DCE",
        "target_trading_day": trading_day.isoformat(),
        "writes_authorized": False,
        "foundation_receipt": {
            "path": str(s6_final_receipt.get("path") or ""),
            "sha256": str(s6_final_receipt.get("sha256") or ""),
            "task_id": receipt.get("task_id"),
            "gate": receipt.get("gate"),
            "status": receipt.get("status"),
            "runtime_commit": receipt.get("runtime_commit"),
            "database_revision": receipt.get("database_revision"),
        },
        "bound_facts": dict(bound_facts),
        "allowed_writes": list(ALLOWED_WRITES),
        "forbidden_writes": list(FORBIDDEN_WRITES),
        "invalidation_rule": (
            "single trading day; immutable facts and forbidden counters must match; "
            "only scoped StrategySignal/SignalEvent and live runtime rows may advance"
        ),
        "rollback": (
            "set GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=false, clear its packet/hash, restart the existing "
            "live scheduler, and preserve accepted append-only SignalEvent evidence"
        ),
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def verify_service_approval_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    current_trading_day: str | date,
    execution_phase: bool = False,
) -> None:
    packet_hash = str(packet.get("packet_hash") or "")
    if approval_hash != packet_hash:
        raise LiveSignalEventGateError("approval_hash_mismatch")
    if canonical_packet_hash(packet) != packet_hash:
        raise LiveSignalEventGateError("packet_hash_invalid")
    if (
        packet.get("schema_version") != 1
        or packet.get("task_id") != TASK_ID
        or packet.get("target_gate") != FINAL_GATE
        or packet.get("product") != "jm"
        or packet.get("exchange") != "DCE"
        or packet.get("writes_authorized") is not False
    ):
        raise LiveSignalEventGateError("packet_scope_invalid")
    target_day = _date_value(str(packet.get("target_trading_day") or ""))
    if _date_value(current_trading_day) != target_day:
        raise LiveSignalEventGateError("target_trading_day_mismatch")
    foundation = packet.get("foundation_receipt")
    if not isinstance(foundation, Mapping) or foundation.get("gate") != FOUNDATION_GATE:
        raise LiveSignalEventGateError("foundation_receipt_invalid")
    bound = packet.get("bound_facts")
    if not isinstance(bound, Mapping):
        raise LiveSignalEventGateError("bound_facts_missing")
    expected_forbidden = bound.get("forbidden_table_baseline")
    if current_facts.get("forbidden_table_baseline") != expected_forbidden:
        raise LiveSignalEventGateError("forbidden_table_delta")
    if not _allowed_baseline_monotonic(
        bound.get("allowed_table_baseline"),
        current_facts.get("allowed_table_baseline"),
    ):
        raise LiveSignalEventGateError("allowed_table_baseline_regressed")
    for key, expected in bound.items():
        if key in {
            "allowed_table_baseline",
            "forbidden_table_baseline",
            "feature_flags",
            "authorization_config",
            "live_table_baseline",
        }:
            continue
        if current_facts.get(key) != expected:
            raise LiveSignalEventGateError(f"bound_fact_drift:{key}")
    flags = current_facts.get("feature_flags")
    if not isinstance(flags, Mapping):
        raise LiveSignalEventGateError("feature_flags_missing")
    if flags.get("GUIYI_WECHAT_AUTOSEND_ENABLED") is not False:
        raise LiveSignalEventGateError("wechat_autosend_must_be_false")
    if flags.get("GUIYI_LIVE_RUNTIME_ENABLED") is not True:
        raise LiveSignalEventGateError("live_runtime_must_be_true")
    expected_signal_flag = True if execution_phase else False
    if flags.get("GUIYI_LIVE_SIGNAL_EVENTS_ENABLED") is not expected_signal_flag:
        raise LiveSignalEventGateError("signal_event_flag_invalid")
    authorization_config = current_facts.get("authorization_config")
    if not isinstance(authorization_config, Mapping):
        raise LiveSignalEventGateError("authorization_config_missing")
    expected_authorization_config = execution_phase
    if (
        authorization_config.get("approval_packet_present") is not expected_authorization_config
        or authorization_config.get("approval_hash_present") is not expected_authorization_config
    ):
        raise LiveSignalEventGateError("authorization_config_invalid")
    live_errors = _live_baseline_errors(
        bound.get("live_table_baseline"),
        current_facts.get("live_table_baseline"),
        actual_contract=str(bound.get("actual_contract") or ""),
        target_trading_day=target_day.isoformat(),
    )
    if live_errors:
        raise LiveSignalEventGateError(f"live_table_scope_invalid:{live_errors[0]}")
    bound_flags = bound.get("feature_flags")
    if not isinstance(bound_flags, Mapping):
        raise LiveSignalEventGateError("bound_feature_flags_missing")
    for name in FLAG_NAMES:
        if name == "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED" and execution_phase:
            continue
        if flags.get(name) != bound_flags.get(name):
            raise LiveSignalEventGateError(f"bound_fact_drift:feature_flags:{name}")


def verify_foundation_receipt(packet: Mapping[str, Any]) -> None:
    foundation = packet.get("foundation_receipt")
    if not isinstance(foundation, Mapping):
        raise LiveSignalEventGateError("foundation_receipt_invalid")
    artifact = validate_s6_final_receipt(
        Path(str(foundation.get("path") or "")),
        expected_sha256=str(foundation.get("sha256") or ""),
    )
    receipt = artifact["receipt"]
    for key in ("task_id", "gate", "status", "runtime_commit", "database_revision"):
        if receipt.get(key) != foundation.get(key):
            raise LiveSignalEventGateError(f"foundation_receipt_drift:{key}")


def verify_signal_deltas(
    *,
    packet: Mapping[str, Any],
    current_facts: Mapping[str, Any],
    new_signal_rows: Sequence[Mapping[str, Any]],
    new_event_rows: Sequence[Mapping[str, Any]],
) -> None:
    bound = packet.get("bound_facts") if isinstance(packet.get("bound_facts"), Mapping) else {}
    for key, expected in bound.items():
        if key in {
            "allowed_table_baseline",
            "forbidden_table_baseline",
            "feature_flags",
            "authorization_config",
            "live_table_baseline",
        }:
            continue
        if current_facts.get(key) != expected:
            raise LiveSignalEventGateError(f"bound_fact_drift:{key}")
    expected_signal_delta = _baseline_delta(bound, current_facts, "strategy_signals")
    expected_event_delta = _baseline_delta(bound, current_facts, "signal_events")
    new_signal_count = sum(
        1
        for row in new_signal_rows
        if row.get("is_new") is True
        or (
            "is_new" not in row
            and int(row.get("id") or 0)
            > int((((bound.get("allowed_table_baseline") or {}).get("strategy_signals") or {}).get("max_id") or 0))
        )
    )
    if expected_signal_delta != new_signal_count:
        raise LiveSignalEventGateError("strategy_signal_delta_mismatch")
    if expected_event_delta != len(new_event_rows):
        raise LiveSignalEventGateError("signal_event_delta_mismatch")
    signal_keys = [str(row.get("dedupe_key") or "") for row in new_signal_rows]
    event_keys = [str(row.get("event_key") or "") for row in new_event_rows]
    if not all(signal_keys) or len(set(signal_keys)) != len(signal_keys):
        raise LiveSignalEventGateError("signal_dedupe_invalid")
    if not all(event_keys) or len(set(event_keys)) != len(event_keys):
        raise LiveSignalEventGateError("event_dedupe_invalid")
    errors = sorted(
        {
            error
            for row in new_signal_rows
            for error in _signal_scope_errors(packet, row)
        }
        | {
            error
            for row in new_event_rows
            for error in _event_scope_errors(packet, row)
        }
    )
    errors.extend(
        _allowed_table_mutation_errors(
            bound,
            current_facts,
            signal_ids={int(row.get("id") or 0) for row in new_signal_rows},
            event_ids={int(row.get("id") or 0) for row in new_event_rows},
        )
    )
    if errors:
        raise LiveSignalEventGateError(f"signal_event_scope_invalid:{errors[0]}")


def build_final_verification(
    *,
    packet: Mapping[str, Any],
    current_facts: Mapping[str, Any],
    new_signal_rows: Sequence[Mapping[str, Any]],
    new_event_rows: Sequence[Mapping[str, Any]],
    restored_flags: Mapping[str, bool],
    runtime_health: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    bound = packet.get("bound_facts") if isinstance(packet.get("bound_facts"), Mapping) else {}
    for key, expected in bound.items():
        if key in {
            "allowed_table_baseline",
            "forbidden_table_baseline",
            "feature_flags",
            "live_table_baseline",
        }:
            continue
        if current_facts.get(key) != expected:
            errors.append(f"bound_fact_drift:{key}")
    if current_facts.get("forbidden_table_baseline") != bound.get("forbidden_table_baseline"):
        errors.append("forbidden_table_delta")
    if not _allowed_baseline_monotonic(
        bound.get("allowed_table_baseline"),
        current_facts.get("allowed_table_baseline"),
    ):
        errors.append("allowed_table_baseline_regressed")
    errors.extend(
        _live_baseline_errors(
            bound.get("live_table_baseline"),
            current_facts.get("live_table_baseline"),
            actual_contract=str(bound.get("actual_contract") or ""),
            target_trading_day=str(packet.get("target_trading_day") or ""),
        )
    )
    if len({str(row.get("dedupe_key") or "") for row in new_signal_rows}) != len(new_signal_rows):
        errors.append("signal_dedupe_invalid")
    if len({str(row.get("event_key") or "") for row in new_event_rows}) != len(new_event_rows):
        errors.append("event_dedupe_invalid")
    for row in new_signal_rows:
        errors.extend(_signal_scope_errors(packet, row))
    for row in new_event_rows:
        errors.extend(_event_scope_errors(packet, row))
    errors.extend(
        _allowed_table_mutation_errors(
            bound,
            current_facts,
            signal_ids={int(row.get("id") or 0) for row in new_signal_rows},
            event_ids={int(row.get("id") or 0) for row in new_event_rows},
        )
    )
    expected_signal_delta = _baseline_delta(bound, current_facts, "strategy_signals")
    expected_event_delta = _baseline_delta(bound, current_facts, "signal_events")
    new_signal_count = sum(
        1
        for row in new_signal_rows
        if row.get("is_new") is True
        or (
            "is_new" not in row
            and int(row.get("id") or 0)
            > int((((bound.get("allowed_table_baseline") or {}).get("strategy_signals") or {}).get("max_id") or 0))
        )
    )
    if expected_signal_delta != new_signal_count:
        errors.append("strategy_signal_delta_mismatch")
    if expected_event_delta != len(new_event_rows):
        errors.append("signal_event_delta_mismatch")
    if restored_flags.get("GUIYI_LIVE_RUNTIME_ENABLED") is not True:
        errors.append("live_runtime_not_restored")
    if restored_flags.get("GUIYI_LIVE_SIGNAL_EVENTS_ENABLED") is not False:
        errors.append("signal_event_flag_not_restored")
    if restored_flags.get("GUIYI_WECHAT_AUTOSEND_ENABLED") is not False:
        errors.append("wechat_autosend_not_false")
    bound_flags = bound.get("feature_flags") if isinstance(bound.get("feature_flags"), Mapping) else {}
    for name in ("GUIYI_AFTER_MARKET_ARCHIVE_ENABLED", "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED"):
        if restored_flags.get(name) != bound_flags.get(name):
            errors.append(f"restored_flag_drift:{name}")
    scheduler_health = (runtime_health.get("components") or {}).get("scheduler") or {}
    if runtime_health.get("status") != "ok" or scheduler_health.get("status") != "ok":
        errors.append("runtime_health_not_ok")
    if scheduler_health.get("enabled") is not True:
        errors.append("runtime_scheduler_not_enabled")
    if (
        scheduler_health.get("signal_events_enabled") is not False
        or scheduler_health.get("signal_event_gate_status") != "disabled"
        or scheduler_health.get("signal_event_authorization_hash") is not None
    ):
        errors.append("runtime_signal_gate_not_disabled")
    verification_time = now or datetime.now(UTC)
    if not _runtime_health_is_fresh(
        runtime_health,
        scheduler_health,
        now=verification_time,
    ):
        errors.append("runtime_health_stale")
    latest_event_created_at = max(
        (
            created_at
            for row in new_event_rows
            if (created_at := _datetime_value(row.get("created_at"))) is not None
        ),
        default=None,
    )
    scheduler_heartbeat_at = _datetime_value(scheduler_health.get("heartbeat_at"))
    if new_event_rows and (
        latest_event_created_at is None
        or scheduler_heartbeat_at is None
        or scheduler_heartbeat_at < latest_event_created_at
    ):
        errors.append("runtime_health_precedes_signal_event")
    if not new_event_rows and not errors:
        status = "pending"
        gate = PENDING_GATE
    else:
        status = "passed" if not errors else "failed"
        gate = FINAL_GATE if not errors else "JM_LIVE_SIGNAL_EVENT_PENDING"
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": status,
        "gate": gate,
        "packet_hash": packet.get("packet_hash"),
        "authorization_hash": packet.get("packet_hash"),
        "target_trading_day": packet.get("target_trading_day"),
        "actual_contract": bound.get("actual_contract"),
        "runtime_commit": (current_facts.get("runtime") or {}).get("commit"),
        "database_revision": (current_facts.get("database") or {}).get("revision"),
        "profile_binding_sha256": current_facts.get("profile_binding_sha256"),
        "event_count": len(new_event_rows),
        "event_ids": [row.get("id") for row in new_event_rows],
        "signal_count": len(new_signal_rows),
        "latest_event_created_at": (
            latest_event_created_at.isoformat() if latest_event_created_at is not None else None
        ),
        "runtime_health_heartbeat_at": (
            scheduler_heartbeat_at.isoformat() if scheduler_heartbeat_at is not None else None
        ),
        "errors": sorted(set(errors)),
        "notification_ready": False,
        "long_running_ready": False,
        "runtime_ready": False,
        "auto_trading_ready": False,
    }


def publish_final_receipt(
    path: Path,
    *,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_facts: Mapping[str, Any],
    new_signal_rows: Sequence[Mapping[str, Any]],
    new_event_rows: Sequence[Mapping[str, Any]],
    restored_flags: Mapping[str, bool],
    runtime_health: Mapping[str, Any],
    confirm_final_gate: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not confirm_final_gate:
        raise LiveSignalEventGateError("confirm_final_gate_required")
    verify_foundation_receipt(packet)
    verify_service_approval_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=current_facts,
        current_trading_day=str(packet.get("target_trading_day") or ""),
        execution_phase=False,
    )
    verification = build_final_verification(
        packet=packet,
        current_facts=current_facts,
        new_signal_rows=new_signal_rows,
        new_event_rows=new_event_rows,
        restored_flags=restored_flags,
        runtime_health=runtime_health,
        now=now,
    )
    if verification.get("status") != "passed" or verification.get("gate") != FINAL_GATE:
        raise LiveSignalEventGateError("final_verification_not_passed")
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "completed",
        "gate": FINAL_GATE,
        "published_at": datetime.now(UTC).isoformat(),
        "authorization_hash": verification.get("authorization_hash"),
        "target_trading_day": verification.get("target_trading_day"),
        "actual_contract": verification.get("actual_contract"),
        "runtime_commit": verification.get("runtime_commit"),
        "database_revision": verification.get("database_revision"),
        "profile_binding_sha256": verification.get("profile_binding_sha256"),
        "event_count": verification.get("event_count"),
        "event_ids": list(verification.get("event_ids") or []),
        "latest_event_created_at": verification.get("latest_event_created_at"),
        "runtime_health_heartbeat_at": verification.get("runtime_health_heartbeat_at"),
        "notification_ready": False,
        "long_running_ready": False,
        "runtime_ready": False,
        "auto_trading_ready": False,
        "scope_note": "research observation only; not a trading instruction and does not place orders",
    }
    write_json_create_only(path, receipt)
    return receipt


def collect_bound_facts(
    session: Session,
    *,
    project_root: Path,
    output_root: Path,
    environ: Mapping[str, str],
    now: datetime | None = None,
    feature_flags: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    clock = TradingSessionClock(session)
    required_date = clock.latest_completed_trading_day(product="jm", exchange="DCE", now=current)
    target = LiveTargetContractResolver(session).resolve_ready_actual_contract(
        product="jm",
        required_date=required_date,
    )
    binding = collect_active_binding_snapshot(session)
    bind = session.get_bind()
    url = bind.url
    flags = (
        dict(feature_flags)
        if feature_flags is not None
        else {name: _enabled(environ, name) for name in FLAG_NAMES}
    )
    policy = _indicator_policy()
    return {
        "runtime": _runtime_identity(project_root, output_root),
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
            "revision": _database_revision(session),
        },
        "actual_contract": target["actual_contract"],
        "dominant_mapping_date": target["dominant_mapping_date"],
        "profile_binding_sha256": binding["sha256"],
        "strategy": _strategy_identity(project_root),
        "indicator_policy": policy,
        "quality_policy": {
            "quality_status": "passed",
            "warnings": "empty",
            "bar_status": "confirmed",
            "periods": ["5m", "15m"],
        },
        "feature_flags": flags,
        "authorization_config": {
            "approval_packet_present": bool(environ.get("GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET")),
            "approval_hash_present": bool(environ.get("GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH")),
        },
        "allowed_table_baseline": {
            "strategy_signals": _count_max_and_hashes(session, StrategySignal),
            "signal_events": _count_max_and_hashes(session, SignalEvent),
        },
        "live_table_baseline": _live_table_baseline(session),
        "forbidden_table_baseline": {
            "data_download_tasks": _table_baseline(session, DataDownloadTask),
            "market_data_files": _table_baseline(session, MarketDataFile),
            "data_quality_reports": _table_baseline(session, DataQualityReport),
            "profile_active_bindings": _table_baseline(session, ProfileActiveBinding),
            "after_market_scheduler_checkpoints": _table_baseline(session, AfterMarketSchedulerCheckpoint),
            "signal_notifications": _table_baseline(session, SignalNotification),
            "signal_scan_tasks": _table_baseline(session, SignalScanTask),
            "backtest_tasks": _table_baseline(session, BacktestTask),
            "backtest_reports": _table_baseline(session, BacktestReportModel),
            "backtest_trades": _table_baseline(session, BacktestTradeModel),
            "backtest_orders": _table_baseline(session, BacktestOrderModel),
        },
    }


def collect_new_signal_rows(session: Session, packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    baseline = ((packet.get("bound_facts") or {}).get("allowed_table_baseline") or {}).get("strategy_signals") or {}
    event_baseline = ((packet.get("bound_facts") or {}).get("allowed_table_baseline") or {}).get("signal_events") or {}
    signal_ids = set(
        session.scalars(
            select(SignalEvent.signal_id).where(
                SignalEvent.id > int(event_baseline.get("max_id") or 0),
                SignalEvent.signal_id.is_not(None),
            )
        )
    )
    rows = session.scalars(select(StrategySignal).where(StrategySignal.id.in_(signal_ids))) if signal_ids else []
    return [
        {
            "id": row.id,
            "is_new": row.id > int(baseline.get("max_id") or 0),
            "dedupe_key": row.dedupe_key,
            "strategy_name": row.strategy_name,
            "strategy_version": row.strategy_version,
            "symbol": row.symbol,
            "actual_contract": row.actual_contract,
            "period": row.period,
            "provider": row.provider,
            "source": row.source,
            "data_role": row.data_role,
            "status": row.status,
            "quality_status": row.quality_status,
            "profile_id": row.profile_id,
            "features": row.features,
        }
        for row in rows
    ]


def collect_new_event_rows(session: Session, packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    baseline = ((packet.get("bound_facts") or {}).get("allowed_table_baseline") or {}).get("signal_events") or {}
    rows = session.scalars(select(SignalEvent).where(SignalEvent.id > int(baseline.get("max_id") or 0)))
    result: list[dict[str, Any]] = []
    for row in rows:
        lineage = (row.payload or {}).get("formal_lineage") or {}
        bar = lineage.get("bar") if isinstance(lineage, Mapping) else {}
        live_bar_id = bar.get("live_bar_id") if isinstance(bar, Mapping) else None
        live_bar = session.get(LiveAggregatedBar, live_bar_id) if isinstance(live_bar_id, int) else None
        result.append(
            {
                "id": row.id,
                "event_key": row.event_key,
                "event_type": row.event_type,
                "source_mode": row.source_mode,
                "strategy_name": row.strategy_name,
                "strategy_version": row.strategy_version,
                "symbol": row.symbol,
                "actual_contract": row.actual_contract,
                "period": row.period,
                "trading_day": live_bar.trading_day.isoformat() if live_bar is not None else None,
                "bar_end": row.bar_end.isoformat() if row.bar_end else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "provider": row.provider,
                "data_role": row.data_role,
                "quality_status": row.quality_status,
                "profile_id": row.profile_id,
                "payload": row.payload,
            }
        )
    return result


def _signal_scope_errors(packet: Mapping[str, Any], row: Mapping[str, Any]) -> list[str]:
    bound = packet.get("bound_facts") if isinstance(packet.get("bound_facts"), Mapping) else {}
    features = row.get("features") if isinstance(row.get("features"), Mapping) else {}
    lineage = features.get("formal_lineage") if isinstance(features, Mapping) else None
    checks = (
        (row.get("strategy_name") == JM_V1B_STRATEGY_CODE, "signal_strategy_invalid"),
        (row.get("strategy_version") == JM_V1B_STRATEGY_VERSION, "signal_strategy_version_invalid"),
        (str(row.get("symbol") or "").lower() == "jm", "signal_symbol_invalid"),
        (row.get("actual_contract") == bound.get("actual_contract"), "signal_contract_invalid"),
        (row.get("period") in {"5m", "15m"}, "signal_period_invalid"),
        (row.get("provider") == "rqdata", "signal_provider_invalid"),
        (row.get("source") == "live_db_actual_contract", "signal_source_invalid"),
        (row.get("data_role") == "primary", "signal_role_invalid"),
        (row.get("status") == "entry_signal", "signal_status_invalid"),
        ((row.get("quality_status") or {}).get("status") == "passed", "signal_quality_invalid"),
        (row.get("profile_id") == "live_observation_v1", "signal_profile_invalid"),
        (features.get("source_mode") == "live_confirmed", "signal_source_mode_invalid"),
        (features.get("confirmed_bar") is True, "signal_bar_not_confirmed"),
        (features.get("observation_only") is True, "signal_observation_boundary_invalid"),
        (features.get("auto_order") is False, "signal_auto_order_invalid"),
        (isinstance(lineage, Mapping), "signal_lineage_missing"),
    )
    return [code for valid, code in checks if not valid]


def _event_scope_errors(packet: Mapping[str, Any], row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    bound = packet.get("bound_facts") if isinstance(packet.get("bound_facts"), Mapping) else {}
    lineage = (row.get("payload") or {}).get("formal_lineage")
    primary = lineage.get("primary") if isinstance(lineage, Mapping) else None
    contract = lineage.get("contract") if isinstance(lineage, Mapping) else None
    bar = lineage.get("bar") if isinstance(lineage, Mapping) else None
    checks = (
        (row.get("event_type") in {"signal_created", "signal_changed"}, "event_type_invalid"),
        (row.get("source_mode") == "live_confirmed", "event_source_mode_invalid"),
        (row.get("strategy_name") == JM_V1B_STRATEGY_CODE, "event_strategy_invalid"),
        (row.get("strategy_version") == JM_V1B_STRATEGY_VERSION, "event_strategy_version_invalid"),
        (str(row.get("symbol") or "").lower() == "jm", "event_symbol_invalid"),
        (row.get("actual_contract") == bound.get("actual_contract"), "event_contract_invalid"),
        (row.get("period") in {"5m", "15m"}, "event_period_invalid"),
        (str(row.get("trading_day") or "") == str(packet.get("target_trading_day") or ""), "event_trading_day_invalid"),
        (row.get("provider") == "rqdata", "event_provider_invalid"),
        (row.get("data_role") == "primary", "event_data_role_invalid"),
        ((row.get("quality_status") or {}).get("status") == "passed", "event_quality_invalid"),
        (row.get("profile_id") == "live_observation_v1", "event_profile_invalid"),
        (isinstance(lineage, Mapping), "event_lineage_missing"),
        (isinstance(primary, Mapping), "event_primary_lineage_missing"),
        (isinstance(contract, Mapping), "event_contract_lineage_missing"),
        (isinstance(bar, Mapping), "event_bar_lineage_missing"),
    )
    errors.extend(code for valid, code in checks if not valid)
    if isinstance(lineage, Mapping):
        lineage_checks = (
            (lineage.get("schema_version") == "signal_review_lineage_v1", "event_lineage_schema_invalid"),
            (lineage.get("resolver_name") == "ProfileLineageResolver", "event_lineage_resolver_invalid"),
            (lineage.get("resolver_contract_version") == "signal_profile_v1", "event_lineage_contract_invalid"),
            (lineage.get("quality_policy") == "passed_only", "event_lineage_quality_invalid"),
            (lineage.get("source_mode") == "live_confirmed", "event_lineage_source_invalid"),
        )
        errors.extend(code for valid, code in lineage_checks if not valid)
    if isinstance(primary, Mapping):
        primary_checks = (
            (primary.get("profile_id") == "live_observation_v1", "event_primary_profile_invalid"),
            (str(primary.get("instrument_symbol") or "").lower() == "jm", "event_primary_symbol_invalid"),
            (primary.get("contract_code") == bound.get("actual_contract"), "event_primary_contract_invalid"),
            (primary.get("period") == row.get("period"), "event_primary_period_invalid"),
            (primary.get("provider") == "rqdata", "event_primary_provider_invalid"),
            (primary.get("data_role") == "primary", "event_primary_role_invalid"),
            (primary.get("quality_status") == "passed", "event_primary_quality_invalid"),
        )
        errors.extend(code for valid, code in primary_checks if not valid)
    if isinstance(contract, Mapping) and contract.get("actual_contract") != bound.get("actual_contract"):
        errors.append("event_lineage_actual_contract_invalid")
    if isinstance(bar, Mapping):
        bar_checks = (
            (bar.get("confirmation_mode") == "live_confirmed", "event_confirmation_mode_invalid"),
            (bar.get("bar_status") == "confirmed", "event_bar_status_invalid"),
            (isinstance(bar.get("live_bar_id"), int), "event_live_bar_id_invalid"),
            (isinstance(bar.get("live_bar_revision"), int), "event_live_bar_revision_invalid"),
        )
        errors.extend(code for valid, code in bar_checks if not valid)
    return errors


def _allowed_baseline_monotonic(expected: Any, current: Any) -> bool:
    if not isinstance(expected, Mapping) or not isinstance(current, Mapping):
        return False
    for table in ("strategy_signals", "signal_events"):
        expected_row = expected.get(table)
        current_row = current.get(table)
        if not isinstance(expected_row, Mapping) or not isinstance(current_row, Mapping):
            return False
        for field in ("count", "max_id"):
            try:
                if int(current_row.get(field) or 0) < int(expected_row.get(field) or 0):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _baseline_delta(bound: Mapping[str, Any], current: Mapping[str, Any], table: str) -> int:
    expected = ((bound.get("allowed_table_baseline") or {}).get(table) or {}).get("count") or 0
    actual = ((current.get("allowed_table_baseline") or {}).get(table) or {}).get("count") or 0
    return int(actual) - int(expected)


def write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _database_revision(session: Session) -> str | None:
    try:
        return session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception as exc:
        raise LiveSignalEventGateError("database_revision_unavailable") from exc


def _runtime_identity(project_root: Path, output_root: Path) -> dict[str, Any]:
    status = _git(project_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise LiveSignalEventGateError("runtime_worktree_not_clean")
    resolved_output = output_root.resolve()
    if not resolved_output.is_dir():
        raise LiveSignalEventGateError("output_root_unavailable")
    lock_path = project_root / "uv.lock"
    tree_sha = _git(project_root, "rev-parse", "HEAD^{tree}")
    return {
        "commit": _git(project_root, "rev-parse", "HEAD"),
        "tree_sha": tree_sha,
        "tracked_state_sha256": hashlib.sha256(tree_sha.encode()).hexdigest(),
        "uv_lock_sha256": _file_sha256(lock_path),
        "project_root": str(project_root.resolve()),
        "output_root": str(resolved_output),
        "project_device_id": os.stat(project_root).st_dev,
        "output_device_id": os.stat(resolved_output).st_dev,
    }


def _strategy_identity(project_root: Path) -> dict[str, str]:
    strategy_root = project_root / "packages" / "quant-core" / "guiyi_quant" / "strategies" / JM_V1B_STRATEGY_CODE
    digest = hashlib.sha256()
    for path in sorted(strategy_root.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return {
        "code": JM_V1B_STRATEGY_CODE,
        "version": JM_V1B_STRATEGY_VERSION,
        "source_sha256": digest.hexdigest(),
    }


def _indicator_policy() -> dict[str, Any]:
    from guiyi_quant.strategies.indicator_policy import build_frozen_jm_v1b_policy_snapshot

    snapshot = build_frozen_jm_v1b_policy_snapshot(
        profile_id="live_observation_v1",
    ).to_dict()
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"snapshot": snapshot, "sha256": hashlib.sha256(encoded).hexdigest()}


def _live_table_baseline(session: Session) -> dict[str, Any]:
    return {
        "minute_groups": _live_bar_groups(session, LiveMinuteBar),
        "aggregate_groups": _live_bar_groups(session, LiveAggregatedBar),
        "minute_rows": _live_bar_rows(session, LiveMinuteBar),
        "aggregate_rows": _live_bar_rows(session, LiveAggregatedBar),
        "ingest_checkpoints": _live_checkpoint_rows(session, LiveIngestCheckpoint),
        "aggregation_checkpoints": _live_checkpoint_rows(session, LiveAggregationCheckpoint),
    }


def _live_bar_groups(session: Session, model: Any) -> list[dict[str, Any]]:
    fields = (
        model.provider,
        model.instrument_symbol,
        model.contract_code,
        model.period,
        model.trading_day,
        model.bar_status,
        model.quality_status,
    )
    rows = session.execute(
        select(*fields, func.count(model.id), func.max(model.id))
        .group_by(*fields)
        .order_by(*fields)
    )
    return [
        {
            "provider": row[0],
            "instrument_symbol": row[1],
            "contract_code": row[2],
            "period": row[3],
            "trading_day": row[4].isoformat() if row[4] else None,
            "bar_status": row[5],
            "quality_status": row[6],
            "count": int(row[7] or 0),
            "max_id": int(row[8] or 0),
        }
        for row in rows
    ]


def _live_checkpoint_rows(session: Session, model: Any) -> list[dict[str, Any]]:
    columns = list(sa_inspect(model).columns)
    rows = session.execute(select(*columns).order_by(model.id)).all()
    id_index = next(index for index, column in enumerate(columns) if column.name == "id")
    field_indexes = {column.name: index for index, column in enumerate(columns)}
    return [
        {
            "id": row[id_index],
            "provider": row[field_indexes["provider"]],
            "instrument_symbol": row[field_indexes["instrument_symbol"]],
            "contract_code": row[field_indexes["contract_code"]],
            "period": row[field_indexes["period"]],
            "source_mode": row[field_indexes["source_mode"]],
            "status": row[field_indexes["status"]],
            "last_bar_at": str(
                row[field_indexes.get("last_confirmed_bar_at", field_indexes.get("last_aggregated_bar_at"))]
                or ""
            ),
            "last_source_bar_at": str(
                (row[field_indexes["last_source_bar_at"]] or "")
                if "last_source_bar_at" in field_indexes
                else ""
            ),
            "last_success_at": str(row[field_indexes["last_success_at"]] or ""),
            "consecutive_error_count": int(row[field_indexes["consecutive_error_count"]] or 0),
            "row_sha256": _row_sha256(row),
        }
        for row in rows
    ]


def _live_bar_rows(session: Session, model: Any) -> list[dict[str, Any]]:
    columns = list(sa_inspect(model).columns)
    field_indexes = {column.name: index for index, column in enumerate(columns)}
    rows = session.execute(select(*columns).order_by(model.id)).all()
    return [
        {
            "id": row[field_indexes["id"]],
            "provider": row[field_indexes["provider"]],
            "instrument_symbol": row[field_indexes["instrument_symbol"]],
            "contract_code": row[field_indexes["contract_code"]],
            "period": row[field_indexes["period"]],
            "bar_datetime": str(row[field_indexes["bar_datetime"]] or ""),
            "trading_day": (
                row[field_indexes["trading_day"]].isoformat()
                if row[field_indexes["trading_day"]]
                else None
            ),
            "bar_status": row[field_indexes["bar_status"]],
            "quality_status": row[field_indexes["quality_status"]],
            "row_sha256": _row_sha256(row),
        }
        for row in rows
    ]


def _live_baseline_errors(
    expected: Any,
    current: Any,
    *,
    actual_contract: str,
    target_trading_day: str,
) -> list[str]:
    if not isinstance(expected, Mapping) or not isinstance(current, Mapping):
        return ["live_table_baseline_missing"]
    errors: list[str] = []
    current_live_rows: dict[str, list[Mapping[str, Any]]] = {}
    for row_name, allowed_periods in (
        ("minute_rows", {"1m"}),
        ("aggregate_rows", {"5m", "15m", "30m", "60m", "1d", "1w"}),
    ):
        expected_rows = _rows_by_id(expected.get(row_name))
        current_rows = _rows_by_id(current.get(row_name))
        current_live_rows[row_name] = list(current_rows.values())
        if not set(expected_rows).issubset(current_rows):
            errors.append(f"{row_name}_row_missing")
        for row_id, current_row in current_rows.items():
            expected_row = expected_rows.get(row_id)
            if (
                expected_row is not None
                and current_row.get("row_sha256") == expected_row.get("row_sha256")
            ):
                continue
            if not _live_group_in_scope(
                current_row,
                actual_contract=actual_contract,
                target_trading_day=target_trading_day,
                allowed_periods=allowed_periods,
            ):
                errors.append(f"{row_name}_delta_out_of_scope")
    for group_name, allowed_periods in (
        ("minute_groups", {"1m"}),
        ("aggregate_groups", {"5m", "15m", "30m", "60m", "1d", "1w"}),
    ):
        expected_groups = _rows_by_identity(expected.get(group_name), exclude={"count", "max_id"})
        current_groups = _rows_by_identity(current.get(group_name), exclude={"count", "max_id"})
        for identity, expected_row in expected_groups.items():
            current_row = current_groups.get(identity)
            if current_row is None or int(current_row.get("count") or 0) < int(expected_row.get("count") or 0):
                errors.append(f"{group_name}_regressed")
        for identity, current_row in current_groups.items():
            expected_count = int((expected_groups.get(identity) or {}).get("count") or 0)
            if int(current_row.get("count") or 0) <= expected_count:
                continue
            if not _live_group_in_scope(
                current_row,
                actual_contract=actual_contract,
                target_trading_day=target_trading_day,
                allowed_periods=allowed_periods,
            ):
                errors.append(f"{group_name}_delta_out_of_scope")
    for checkpoint_name, allowed_periods in (
        ("ingest_checkpoints", {"1m"}),
        ("aggregation_checkpoints", {"5m", "15m", "30m", "60m", "1d", "1w"}),
    ):
        expected_rows = {
            int(row.get("id") or 0): row
            for row in expected.get(checkpoint_name) or []
            if isinstance(row, Mapping)
        }
        current_rows = {
            int(row.get("id") or 0): row
            for row in current.get(checkpoint_name) or []
            if isinstance(row, Mapping)
        }
        if not set(expected_rows).issubset(current_rows):
            errors.append(f"{checkpoint_name}_row_missing")
        for row_id, current_row in current_rows.items():
            if current_row == expected_rows.get(row_id):
                continue
            if not _live_checkpoint_in_scope(
                current_row,
                actual_contract=actual_contract,
                target_trading_day=target_trading_day,
                allowed_periods=allowed_periods,
                live_rows=(
                    current_live_rows["minute_rows"]
                    if checkpoint_name == "ingest_checkpoints"
                    else current_live_rows["aggregate_rows"]
                ),
            ):
                errors.append(f"{checkpoint_name}_delta_out_of_scope")
    return sorted(set(errors))


def _rows_by_identity(value: Any, *, exclude: set[str]) -> dict[tuple[tuple[str, str], ...], Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[tuple[tuple[str, str], ...], Mapping[str, Any]] = {}
    for row in value:
        if not isinstance(row, Mapping):
            continue
        identity = tuple(sorted((str(key), str(item)) for key, item in row.items() if key not in exclude))
        result[identity] = row
    return result


def _live_group_in_scope(
    row: Mapping[str, Any],
    *,
    actual_contract: str,
    target_trading_day: str,
    allowed_periods: set[str],
) -> bool:
    return all(
        (
            row.get("provider") == "rqdata",
            str(row.get("instrument_symbol") or "").lower() == "jm",
            row.get("contract_code") == actual_contract,
            row.get("period") in allowed_periods,
            row.get("trading_day") == target_trading_day,
            row.get("bar_status") == "confirmed",
            row.get("quality_status") == "passed",
        )
    )


def _live_checkpoint_in_scope(
    row: Mapping[str, Any],
    *,
    actual_contract: str,
    target_trading_day: str,
    allowed_periods: set[str],
    live_rows: Sequence[Mapping[str, Any]],
) -> bool:
    checkpoint_scope_valid = all(
        (
            row.get("provider") == "rqdata",
            str(row.get("instrument_symbol") or "").lower() == "jm",
            row.get("contract_code") == actual_contract,
            row.get("period") in allowed_periods,
            row.get("status") != "failed",
            int(row.get("consecutive_error_count") or 0) == 0,
        )
    )
    if not checkpoint_scope_valid or not row.get("last_bar_at"):
        return False
    return any(
        _live_group_in_scope(
            live_row,
            actual_contract=actual_contract,
            target_trading_day=target_trading_day,
            allowed_periods=allowed_periods,
        )
        and live_row.get("bar_datetime") == row.get("last_bar_at")
        and live_row.get("period") == row.get("period")
        for live_row in live_rows
    )


def _rows_by_id(value: Any) -> dict[int, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        int(row.get("id") or 0): row
        for row in value
        if isinstance(row, Mapping) and int(row.get("id") or 0) > 0
    }


def _table_baseline(session: Session, model: Any) -> dict[str, Any]:
    columns = list(sa_inspect(model).columns)
    rows = session.execute(select(*columns).order_by(model.id)).all()
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(
                list(row),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        )
        digest.update(b"\n")
    return {"count": len(rows), "sha256": digest.hexdigest()}


def _count_max_and_hashes(session: Session, model: Any) -> dict[str, Any]:
    baseline = _count_and_max(session, model)
    baseline["row_hashes"] = _row_hashes(session, model)
    return baseline


def _row_hashes(session: Session, model: Any) -> dict[str, str]:
    columns = list(sa_inspect(model).columns)
    id_index = next(index for index, column in enumerate(columns) if column.name == "id")
    rows = session.execute(select(*columns).order_by(model.id)).all()
    return {
        str(row[id_index]): _row_sha256(row)
        for row in rows
    }


def _row_sha256(row: Sequence[Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(row),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _runtime_health_is_fresh(
    runtime_health: Mapping[str, Any],
    scheduler_health: Mapping[str, Any],
    *,
    now: datetime,
) -> bool:
    generated_at = _datetime_value(runtime_health.get("generated_at"))
    heartbeat_at = _datetime_value(scheduler_health.get("heartbeat_at"))
    heartbeat_age = scheduler_health.get("heartbeat_age_seconds")
    if generated_at is None or heartbeat_at is None:
        return False
    try:
        reported_age = int(heartbeat_age)
    except (TypeError, ValueError):
        return False
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return all(
        (
            -5 <= (current - generated_at).total_seconds() <= MAX_RUNTIME_HEALTH_AGE_SECONDS,
            -5 <= (current - heartbeat_at).total_seconds() <= MAX_RUNTIME_HEALTH_AGE_SECONDS,
            0 <= reported_age <= MAX_RUNTIME_HEALTH_AGE_SECONDS,
        )
    )


def _datetime_value(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _allowed_table_mutation_errors(
    bound: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    signal_ids: set[int],
    event_ids: set[int],
) -> list[str]:
    baseline = bound.get("allowed_table_baseline") or {}
    current_baseline = current.get("allowed_table_baseline") or {}
    errors: list[str] = []
    specs = (
        ("strategy_signals", signal_ids, "strategy_signal_unscoped_mutation"),
        ("signal_events", event_ids, "signal_event_unscoped_mutation"),
    )
    for table, allowed_ids, error in specs:
        expected_hashes = ((baseline.get(table) or {}).get("row_hashes") or {})
        current_hashes = ((current_baseline.get(table) or {}).get("row_hashes") or {})
        if not isinstance(expected_hashes, Mapping) or not isinstance(current_hashes, Mapping):
            errors.append(f"{table}_row_hashes_missing")
            continue
        changed_ids = {
            int(row_id)
            for row_id in set(expected_hashes) | set(current_hashes)
            if expected_hashes.get(row_id) != current_hashes.get(row_id)
        }
        if changed_ids != allowed_ids:
            errors.append(error)
    return errors


def _count(session: Session, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _count_and_max(session: Session, model: Any) -> dict[str, int]:
    count, max_id = session.execute(select(func.count(), func.max(model.id)).select_from(model)).one()
    return {"count": int(count or 0), "max_id": int(max_id or 0)}


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise LiveSignalEventGateError(f"required_file_missing:{path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(project_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise LiveSignalEventGateError("git_identity_unavailable") from exc


def _date_value(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LiveSignalEventGateError("target_trading_day_invalid") from exc


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value.lower())


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ALLOWED_WRITES",
    "FINAL_GATE",
    "FORBIDDEN_WRITES",
    "LiveSignalEventGateError",
    "PENDING_GATE",
    "TASK_ID",
    "build_final_verification",
    "build_service_approval_packet",
    "canonical_packet_hash",
    "collect_bound_facts",
    "collect_new_event_rows",
    "collect_new_signal_rows",
    "load_json",
    "publish_final_receipt",
    "validate_s6_final_receipt",
    "verify_foundation_receipt",
    "verify_service_approval_packet",
    "verify_signal_deltas",
    "write_json_create_only",
]
