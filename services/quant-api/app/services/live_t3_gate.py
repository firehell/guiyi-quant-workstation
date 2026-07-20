from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import (
    LiveAggregatedBar,
    LiveAggregationCheckpoint,
    LiveIngestCheckpoint,
    LiveMinuteBar,
)
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.rqdata_ingest.jm_historical_catchup_execution import collect_active_binding_snapshot
from app.services.trading_session_clock import TradingSessionClock


TASK_ID = "JM-LIVE-T3-S6-05"
EXECUTION_FLAGS = {
    "GUIYI_LIVE_RUNTIME_ENABLED": True,
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
    "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED": False,
    "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
}


class LiveT3ApprovalError(RuntimeError):
    """Raised when a T3 approval packet is invalid or no longer current."""


def canonical_packet_hash(packet: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in packet.items() if key != "packet_hash"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_approval_packet(bound_facts: Mapping[str, Any]) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "approval_required",
        "product": "jm",
        "writes_authorized": False,
        "authorized_invocations": 2,
        "bound_facts": dict(bound_facts),
        "allowed_writes": [
            "live_minute_bars",
            "live_ingest_checkpoints",
            "live_aggregated_bars",
            "live_aggregation_checkpoints",
            "scheduler_heartbeat",
        ],
        "invalidation_rule": "non-live facts must match; approved live rows and checkpoints may only advance monotonically",
        "rollback": "preserve append-only live evidence; disable command-scoped flags and stop further invocations",
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def verify_approval_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
) -> None:
    packet_hash = str(packet.get("packet_hash") or "")
    if not approval_hash or approval_hash != packet_hash:
        raise LiveT3ApprovalError("approval_hash_mismatch")
    if canonical_packet_hash(packet) != packet_hash:
        raise LiveT3ApprovalError("packet_hash_invalid")
    if packet.get("task_id") != TASK_ID or packet.get("product") != "jm":
        raise LiveT3ApprovalError("packet_scope_invalid")
    bound = packet.get("bound_facts")
    if not isinstance(bound, Mapping):
        raise LiveT3ApprovalError("bound_facts_missing")
    for key, expected in bound.items():
        if key == "live_baseline":
            if not _live_baseline_compatible(expected, current_facts.get(key)):
                raise LiveT3ApprovalError("bound_fact_drift:live_baseline")
            continue
        if current_facts.get(key) != expected:
            raise LiveT3ApprovalError(f"bound_fact_drift:{key}")


def load_packet(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LiveT3ApprovalError("packet_not_object")
    return payload


def collect_bound_facts(
    session: Session,
    *,
    project_root: Path,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    execution_flags: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    source_env = environ if environ is not None else os.environ
    clock = TradingSessionClock(session)
    required_date = clock.latest_completed_trading_day(
        product="jm",
        exchange="DCE",
        now=current,
    )
    target = LiveTargetContractResolver(session).resolve_ready_actual_contract(
        product="jm",
        required_date=required_date,
    )
    coverage = target.get("historical_coverage") or {}
    historical = {
        period: {
            key: (coverage.get(period) or {}).get(key)
            for key in ("available", "latest_bar_time", "row_count", "quality_status", "data_version", "fresh_for_required_date")
        }
        for period in ("1m", "5m", "15m")
    }
    binding = collect_active_binding_snapshot(session)
    bind = session.get_bind()
    url = bind.url
    flags = dict(execution_flags) if execution_flags is not None else {
        name: _enabled(source_env, name) for name in EXECUTION_FLAGS
    }
    return {
        "git": _git_identity(project_root),
        "run_directory": str((project_root / "services" / "quant-api").resolve()),
        "database": {
            "driver": url.drivername,
            "host": url.host,
            "port": url.port,
            "database": url.database,
        },
        "required_historical_date": required_date.isoformat(),
        "actual_contract": target["actual_contract"],
        "dominant_mapping_date": target["dominant_mapping_date"],
        "historical": historical,
        "active_binding_sha256": binding["sha256"],
        "execution_flags": flags,
        "rqdata_environment": {
            "config_uri_present": bool(source_env.get("RQDATAC2_CONF") or source_env.get("RQDATAC_CONF")),
            "license_present": bool(source_env.get("RQDATA_LICENSE_KEY")),
            "username_password_present": bool(source_env.get("RQDATA_USERNAME") and source_env.get("RQDATA_PASSWORD")),
        },
        "live_baseline": _live_baseline(session),
        "forbidden_table_baseline": {
            "strategy_signals": _count(session, StrategySignal),
            "signal_events": _count(session, SignalEvent),
            "signal_notifications": _count(session, SignalNotification),
        },
    }


def _live_baseline(session: Session) -> dict[str, Any]:
    return {
        "live_minute_bars": _count(session, LiveMinuteBar),
        "live_aggregated_bars": _count(session, LiveAggregatedBar),
        "ingest_checkpoints": _checkpoint_rows(session, LiveIngestCheckpoint, "period"),
        "aggregation_checkpoints": _checkpoint_rows(session, LiveAggregationCheckpoint, "period"),
    }


def _live_baseline_compatible(expected: Any, current: Any) -> bool:
    if not isinstance(expected, Mapping) or not isinstance(current, Mapping):
        return False
    for key in ("live_minute_bars", "live_aggregated_bars"):
        try:
            if int(current.get(key, -1)) < int(expected.get(key, 0)):
                return False
        except (TypeError, ValueError):
            return False
    for key in ("ingest_checkpoints", "aggregation_checkpoints"):
        expected_rows = expected.get(key)
        current_rows = current.get(key)
        if not isinstance(expected_rows, list) or not isinstance(current_rows, list):
            return False
        current_identities = {
            (row.get("id"), row.get("contract_code"), row.get("period"))
            for row in current_rows
            if isinstance(row, Mapping)
        }
        for row in expected_rows:
            if not isinstance(row, Mapping):
                return False
            if (row.get("id"), row.get("contract_code"), row.get("period")) not in current_identities:
                return False
    return True


def _checkpoint_rows(session: Session, model: Any, period_field: str) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(model).order_by(model.id)))
    return [
        {
            "id": row.id,
            "contract_code": row.contract_code,
            "period": getattr(row, period_field),
            "status": row.status,
            "last_bar_at": str(getattr(row, "last_confirmed_bar_at", None) or getattr(row, "last_aggregated_bar_at", None) or ""),
            "last_source_bar_at": str(getattr(row, "last_source_bar_at", None) or ""),
        }
        for row in rows
    ]


def _count(session: Session, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _git_identity(project_root: Path) -> dict[str, str]:
    commit = _git(project_root, "rev-parse", "HEAD")
    branch = _git(project_root, "branch", "--show-current")
    status = _git(project_root, "status", "--porcelain=v1", "--untracked-files=no")
    return {
        "commit": commit,
        "branch": branch,
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _git(project_root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "EXECUTION_FLAGS",
    "LiveT3ApprovalError",
    "build_approval_packet",
    "canonical_packet_hash",
    "collect_bound_facts",
    "load_packet",
    "verify_approval_packet",
]
