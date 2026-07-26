from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable

import duckdb
import pandas as pd
import pyarrow.parquet as pq
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    MarketDataFile,
    ProfileActiveBinding,
    TradingCalendar,
    TradingSession,
)
from app.services.jm_session_contract import (
    JM_CONTRACT_TRADING_HOURS,
    JM_SESSION_PROVIDER,
    JM_SESSION_ROWS,
)
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars_strict
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic
from app.services.trading_session_clock import TradingSessionClock

TASK_ID = "FULL-HISTORY-DERIVED-PERIODS-005"
DERIVED_PERIOD_TARGETS_VERIFIED = "DERIVED_PERIOD_TARGETS_VERIFIED"
REPAIR_REQUIRED = "DERIVED_PERIOD_TARGETS_REPAIR_REQUIRED"
EVIDENCE_ONLY = "DERIVED_PERIOD_VERIFICATION_EVIDENCE_ONLY"
AUDIT_END = date(2026, 7, 10)
HARD_TARGET_START = date(2023, 1, 3)
EXPECTED_DATA_ROOT = Path("/Volumes/扩展盘/guiyi-quant-workstation")
DERIVED_PERIODS = ("5m", "15m", "30m", "60m", "1d")
PROFILE_PERIODS = ("1m", *DERIVED_PERIODS)


class RepairApprovalError(RuntimeError):
    pass


REPORT_COLUMNS = (
    "target_id",
    "requirement_level",
    "consumer",
    "profile_id",
    "product",
    "contract_role",
    "period",
    "target_start",
    "target_end",
    "effective_target_end",
    "calendar_boundary_status",
    "source_1m_file_id",
    "source_1m_path",
    "source_1m_version",
    "source_1m_checksum",
    "source_checksum_status",
    "source_1m_quality",
    "derived_file_id",
    "derived_path",
    "derived_version",
    "derived_data_role",
    "derived_quality",
    "physical_min_datetime",
    "physical_max_datetime",
    "window_class",
    "source_interval",
    "source_bar_count_status",
    "session_boundary_status",
    "source_gap_count",
    "recomputed_row_count",
    "content_comparison_status",
    "checksum_status",
    "lineage_status",
    "coverage_status",
    "active_binding_status",
    "recommended_action",
)


@dataclass(frozen=True)
class DerivedPeriodVerificationConfig:
    project_root: Path
    audit_end: date = AUDIT_END
    scan_mode: str = "quick"
    products: tuple[str, ...] = ()
    max_workers: int = 4
    require_postgresql: bool = True

    def __post_init__(self) -> None:
        if self.audit_end != AUDIT_END:
            raise ValueError(f"audit_end must be {AUDIT_END.isoformat()}")
        if self.scan_mode not in {"quick", "full"}:
            raise ValueError("scan_mode must be quick or full")
        if self.max_workers < 1:
            raise ValueError("max_workers must be positive")


@dataclass(frozen=True)
class DerivedPeriodVerificationResult:
    consumer_target_matrix: list[dict[str, Any]]
    derived_period_inventory: list[dict[str, Any]]
    lineage_residuals: list[dict[str, Any]]
    materialization_estimate: dict[str, Any]
    summary: dict[str, Any]


def build_consumer_targets(products: Iterable[str], *, audit_end: date = AUDIT_END) -> list[dict[str, Any]]:
    normalized = sorted({str(item).strip().lower() for item in products if str(item).strip()})
    targets: list[dict[str, Any]] = []

    def add(
        requirement: str,
        consumer: str,
        product: str,
        period: str,
        start: date | None,
        end: date,
        profile: str,
    ) -> None:
        targets.append(
            {
                "target_id": f"{requirement}:{consumer}:{product}:{period}:{start or 'source'}:{end}",
                "requirement_level": requirement,
                "consumer": consumer,
                "profile_id": profile,
                "product": product,
                "contract_role": "dominant_main",
                "period": period,
                "target_start": start.isoformat() if start else "",
                "target_end": end.isoformat(),
                "effective_target_end": end.isoformat(),
                "calendar_boundary_status": "unverified",
                "materialization_policy": "required" if requirement == "hard" else "verify_only",
            }
        )

    if "jm" in normalized:
        for period in ("5m", "15m", "1d"):
            add("hard", "backtest", "jm", period, date(2023, 6, 28), date(2026, 6, 28), "intraday_research_v1")
        for period in ("5m", "15m"):
            add("hard", "signal", "jm", period, date(2023, 1, 3), audit_end, "intraday_research_v1")
        for period in ("1m", "5m", "15m"):
            add("hard", "live_observation", "jm", period, date(2023, 1, 3), audit_end, "live_observation_v1")

    for product in normalized:
        for period in PROFILE_PERIODS:
            add("profile_eligible", "profile_registry", product, period, None, audit_end, "intraday_research_v1")
    return sorted(targets, key=lambda row: row["target_id"])


def run_derived_period_verification(
    config: DerivedPeriodVerificationConfig,
    session: Session,
) -> DerivedPeriodVerificationResult:
    root = config.project_root.resolve()
    dialect = session.get_bind().dialect.name
    if config.require_postgresql and dialect != "postgresql":
        raise RuntimeError(f"ENV_BLOCKED_DB: direct PostgreSQL required, got {dialect}")
    mount_root = _validate_data_environment(root) if config.require_postgresql else None
    session.execute(select(1)).scalar_one()

    products = tuple(sorted({item.strip().lower() for item in config.products if item.strip()}))
    if not products:
        products = _load_products(root / "data/universe/full_products_90.txt")
    targets = build_consumer_targets(products, audit_end=config.audit_end)
    files = list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.provider == "rqdata",
                MarketDataFile.data_type == "bars",
                MarketDataFile.instrument_symbol.in_(products),
                MarketDataFile.contract_code.is_not(None),
            )
        )
    )
    files = [item for item in files if str(item.contract_code or "").lower().endswith(".main")]
    bindings = list(
        session.scalars(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.binding_status == "active",
                ProfileActiveBinding.instrument_symbol.in_(products),
            )
        )
    )
    binding_map = {
        (item.profile_id, item.instrument_symbol.lower(), item.period): item
        for item in bindings
    }
    lineage_map = _load_processed_lineage(root)
    rows: list[dict[str, Any]] = []
    content_cache: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    physical_cache: dict[str, dict[str, Any]] = {}
    source_frame_cache: dict[str, pd.DataFrame] = {}
    clock = TradingSessionClock(session)
    current_product = ""
    for target in sorted(targets, key=lambda row: (row["product"], row["period"], row["target_id"])):
        product = target["product"]
        if product != current_product:
            source_frame_cache.clear()
            current_product = product
        period = target["period"]
        if period == "1m":
            source = _select_file(files, product, "1m", target)
            target = _with_effective_target_end(target, source=source, session=session)
            binding = binding_map.get((target["profile_id"], product, period))
            rows.append(
                _evaluate_source_target(
                    target,
                    source=source,
                    binding=binding,
                    physical_cache=physical_cache,
                )
            )
            continue
        source, derived = _select_lineage_pair(
            files,
            product,
            period,
            target,
            lineage_map=lineage_map,
        )
        target = _with_effective_target_end(target, source=source, session=session)
        binding = binding_map.get((target["profile_id"], product, period))
        row = _evaluate_target(
            target,
            source=source,
            derived=derived,
            lineage_map=lineage_map,
            binding=binding,
            scan_mode=config.scan_mode,
            clock=clock,
            content_cache=content_cache,
            physical_cache=physical_cache,
            source_frame_cache=source_frame_cache,
        )
        rows.append(row)

    row_by_target = {row["target_id"]: row for row in rows}
    targets = [
        {
            **target,
            "effective_target_end": row_by_target.get(target["target_id"], {}).get(
                "effective_target_end", target["target_end"]
            ),
            "calendar_boundary_status": row_by_target.get(target["target_id"], {}).get(
                "calendar_boundary_status", "unverified"
            ),
        }
        for target in targets
    ]
    residuals = [
        {**row, "residual_reason": _residual_reason(row)}
        for row in rows
        if _residual_reason(row)
    ]
    hard_residuals = [row for row in residuals if row["requirement_level"] == "hard"]
    distinct_paths = {
        row["derived_path"]
        for row in rows
        if row["derived_path"] and row["coverage_status"] == "covered"
    }
    materialization = {
        "distinct_covering_path_count": len(distinct_paths),
        "distinct_covering_bytes": sum(Path(path).stat().st_size for path in distinct_paths if Path(path).is_file()),
        "observed_004b_output_count": 248,
        "observed_004b_output_bytes": 569_651_889,
        "observed_004b_elapsed_seconds": 408.7689621448517,
        "estimated_all_90_four_period_bytes": 639_000_000,
        "estimated_all_90_four_period_elapsed_seconds": [480, 600],
        "estimated_all_90_derived_1d_incremental_bytes": [15_000_000, 25_000_000],
    }
    hard_rows = [row for row in rows if row["requirement_level"] == "hard"]
    derived_hard_rows = [row for row in hard_rows if row["period"] != "1m"]
    formal_gate_eligible = bool(
        not config.products
        and config.scan_mode == "full"
        and dialect == "postgresql"
        and len(hard_rows) == 8
        and not hard_residuals
        and all(row["content_comparison_status"] == "matched" for row in derived_hard_rows)
        and all(row["session_boundary_status"] == "passed" for row in derived_hard_rows)
    )
    status = (
        DERIVED_PERIOD_TARGETS_VERIFIED
        if formal_gate_eligible
        else REPAIR_REQUIRED
        if hard_residuals
        else EVIDENCE_ONLY
    )
    summary = {
        "status": status,
        "data_layer_status": "DATA_LAYER_REAUDIT_REQUIRED",
        "audit_end": config.audit_end.isoformat(),
        "scan_mode": config.scan_mode,
        "scope": "filtered_smoke" if config.products else "full_profile_inventory",
        "hard_scope": "jm_v1b_actual_consumers",
        "formal_gate_eligible": formal_gate_eligible,
        "full_content_comparison_scope": "hard_targets_only",
        "eligibility_verification_scope": "coverage_checksum_registration_lineage",
        "max_workers_requested": config.max_workers,
        "max_workers_effective": 1,
        "product_count": len(products),
        "consumer_target_count": len(targets),
        "derived_inventory_row_count": len(rows),
        "lineage_residual_count": len(residuals),
        "hard_residual_count": len(hard_residuals),
        "db_snapshot_source": "direct_postgresql" if dialect == "postgresql" else "test_database",
        "data_environment_git_commit": _git_commit(root),
        "execution_git_commit": _git_commit(Path(__file__).resolve().parents[5]),
        "execution_git_dirty": _git_dirty(Path(__file__).resolve().parents[5]),
        "data_root": str(root),
        "expected_data_root": str(EXPECTED_DATA_ROOT),
        "preflight_consistency_source": "task_frozen_b2_00_data_root",
        "mount_root": str(mount_root or "test_environment"),
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "profile_binding_changed": False,
    }
    return DerivedPeriodVerificationResult(targets, rows, residuals, materialization, summary)


def build_jm_session_repair_plan(
    session: Session,
    *,
    batch_id: str,
    audit_start: date = HARD_TARGET_START,
    audit_end: date = AUDIT_END,
    enforce_formal_counts: bool = True,
) -> dict[str, Any]:
    """Freeze the exact JM session/calendar metadata repair without writing DB state."""
    _validate_batch_id(batch_id)
    if audit_start > audit_end:
        raise RepairApprovalError("SESSION_REPAIR_INVALID_WINDOW")

    rqdata_contracts = list(
        session.scalars(
            select(Contract).where(
                func.lower(func.coalesce(Contract.product, Contract.instrument_symbol)) == "jm",
                Contract.provider == "rqdata",
                Contract.trading_hours.is_not(None),
            )
        )
    )
    declared_hours = sorted({str(item.trading_hours).strip() for item in rqdata_contracts})
    if declared_hours != [JM_CONTRACT_TRADING_HOURS]:
        raise RepairApprovalError(
            f"SESSION_REPAIR_CONTRACT_HOURS_DRIFT: declared={declared_hours}"
        )

    legacy_rows = list(
        session.scalars(
            select(TradingSession).where(
                TradingSession.exchange_code == "CNFE",
                func.lower(TradingSession.instrument_symbol) == "jm",
                TradingSession.session_name == "regular",
                TradingSession.is_active.is_(True),
            )
        )
    )
    if len(legacy_rows) != 1:
        raise RepairApprovalError(
            f"SESSION_REPAIR_LEGACY_ROW_DRIFT: active_count={len(legacy_rows)}"
        )
    legacy = legacy_rows[0]
    if legacy.start_time != time(9, 0) or legacy.end_time != time(15, 0):
        raise RepairApprovalError("SESSION_REPAIR_LEGACY_BOUNDARY_DRIFT")

    existing_dce = list(
        session.scalars(
            select(TradingSession).where(
                TradingSession.exchange_code == "DCE",
                func.lower(TradingSession.instrument_symbol) == "jm",
            )
        )
    )
    if existing_dce:
        raise RepairApprovalError(
            f"SESSION_REPAIR_DCE_ROWS_ALREADY_PRESENT: ids={[item.id for item in existing_dce]}"
        )

    all_trading_days = list(
        session.scalars(
            select(TradingCalendar.trade_date)
            .where(
                TradingCalendar.exchange_code == "DCE",
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.trade_date <= audit_end,
            )
            .order_by(TradingCalendar.trade_date)
        )
    )
    target_rows = list(
        session.scalars(
            select(TradingCalendar)
            .where(
                TradingCalendar.exchange_code == "DCE",
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.trade_date >= audit_start,
                TradingCalendar.trade_date <= audit_end,
            )
            .order_by(TradingCalendar.trade_date)
        )
    )
    if not target_rows:
        raise RepairApprovalError("SESSION_REPAIR_CALENDAR_MISSING")
    previous_by_day = {
        trading_day: all_trading_days[index - 1] if index else None
        for index, trading_day in enumerate(all_trading_days)
    }
    expected_night = {
        row.trade_date: _night_session_expected(
            row.trade_date,
            previous_by_day.get(row.trade_date),
        )
        for row in target_rows
    }

    operations: list[dict[str, Any]] = [
        {
            "action": "session_retire",
            "table": "trading_sessions",
            "identity": {"id": legacy.id},
            "before": _session_snapshot(legacy),
            "after": {**_session_snapshot(legacy), "is_active": False},
        }
    ]
    for name, start_time, end_time in JM_SESSION_ROWS:
        operations.append(
            {
                "action": "session_insert",
                "table": "trading_sessions",
                "identity": {
                    "exchange_code": "DCE",
                    "instrument_symbol": "jm",
                    "session_name": name,
                },
                "before": None,
                "after": {
                    "exchange_code": "DCE",
                    "instrument_symbol": "jm",
                    "session_name": name,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "crosses_midnight": False,
                    "is_active": True,
                    "provider": JM_SESSION_PROVIDER,
                },
            }
        )
    for row in target_rows:
        desired = expected_night[row.trade_date]
        if bool(row.has_night_session) == desired:
            continue
        operations.append(
            {
                "action": "calendar_update",
                "table": "trading_calendars",
                "identity": {"id": row.id, "trade_date": row.trade_date.isoformat()},
                "before": {
                    "id": row.id,
                    "exchange_code": row.exchange_code,
                    "trade_date": row.trade_date.isoformat(),
                    "has_night_session": bool(row.has_night_session),
                },
                "after": {
                    "id": row.id,
                    "exchange_code": row.exchange_code,
                    "trade_date": row.trade_date.isoformat(),
                    "has_night_session": desired,
                },
            }
        )

    operation_counts = {
        action: sum(item["action"] == action for item in operations)
        for action in ("calendar_update", "session_insert", "session_retire")
    }
    calendar_evidence = {
        "audit_start": audit_start.isoformat(),
        "audit_end": audit_end.isoformat(),
        "trading_day_count": len(target_rows),
        "night_enabled_count": sum(expected_night.values()),
        "night_disabled_count": len(expected_night) - sum(expected_night.values()),
        "derivation_rule": "adjacent_day_or_friday_to_monday",
    }
    contract_evidence = {
        "rqdata_contract_count": len(rqdata_contracts),
        "declared_trading_hours": declared_hours,
    }
    if enforce_formal_counts:
        expected_counts = {
            "rqdata_contract_count": 173,
            "trading_day_count": 851,
            "night_enabled_count": 827,
            "night_disabled_count": 24,
            "calendar_update": 827,
            "session_insert": 4,
            "session_retire": 1,
        }
        actual_counts = {
            "rqdata_contract_count": contract_evidence["rqdata_contract_count"],
            "trading_day_count": calendar_evidence["trading_day_count"],
            "night_enabled_count": calendar_evidence["night_enabled_count"],
            "night_disabled_count": calendar_evidence["night_disabled_count"],
            **operation_counts,
        }
        if actual_counts != expected_counts:
            raise RepairApprovalError(
                f"SESSION_REPAIR_FORMAL_COUNT_DRIFT: actual={actual_counts} expected={expected_counts}"
            )

    digest_payload = {
        "operations": operations,
        "contract_evidence": contract_evidence,
        "calendar_evidence": calendar_evidence,
    }
    digest = hashlib.sha256(_canonical_json(digest_payload).encode()).hexdigest()
    return {
        "task_id": TASK_ID,
        "batch_id": batch_id,
        "status": "SESSION_REPAIR_PLAN_FROZEN",
        "operations": operations,
        "operation_counts": operation_counts,
        "contract_evidence": contract_evidence,
        "calendar_evidence": calendar_evidence,
        "ledger_sha256": digest,
        "required_approval_statement": f"APPROVE {TASK_ID} {batch_id} {digest}",
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "profile_binding_changed": False,
    }


def apply_jm_session_repair_plan(
    plan: dict[str, Any],
    *,
    approval_statement: str,
    session: Session,
    require_postgresql: bool = True,
) -> dict[str, Any]:
    if plan.get("task_id") != TASK_ID:
        raise RepairApprovalError("SESSION_REPAIR_TASK_ID_MISMATCH")
    digest_payload = {
        "operations": plan.get("operations") or [],
        "contract_evidence": plan.get("contract_evidence") or {},
        "calendar_evidence": plan.get("calendar_evidence") or {},
    }
    digest = hashlib.sha256(_canonical_json(digest_payload).encode()).hexdigest()
    expected_statement = f"APPROVE {TASK_ID} {plan.get('batch_id')} {digest}"
    if plan.get("ledger_sha256") != digest or plan.get("required_approval_statement") != expected_statement:
        raise RepairApprovalError("SESSION_REPAIR_PLAN_DIGEST_MISMATCH")
    if approval_statement != expected_statement:
        raise RepairApprovalError("SESSION_REPAIR_APPROVAL_STATEMENT_MISMATCH")
    dialect = session.get_bind().dialect.name
    if require_postgresql and dialect != "postgresql":
        raise RepairApprovalError("ENV_BLOCKED_DB: direct PostgreSQL required")
    if dialect == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"{TASK_ID}:jm-session"})

    states = [_session_operation_state(session, operation) for operation in plan["operations"]]
    if states and all(state == "after" for state in states):
        return _session_repair_result(plan, status="ALREADY_APPLIED", session=session)
    if not states or not all(state == "before" for state in states):
        session.rollback()
        raise RepairApprovalError(f"SESSION_REPAIR_EVIDENCE_DRIFT: states={states}")

    try:
        for operation in plan["operations"]:
            action = operation["action"]
            if action == "session_retire":
                row = session.get(TradingSession, int(operation["identity"]["id"]))
                if row is None:
                    raise RepairApprovalError("SESSION_REPAIR_LEGACY_ROW_MISSING")
                row.is_active = False
            elif action == "session_insert":
                values = operation["after"]
                session.add(
                    TradingSession(
                        exchange_code=values["exchange_code"],
                        instrument_symbol=values["instrument_symbol"],
                        session_name=values["session_name"],
                        start_time=time.fromisoformat(values["start_time"]),
                        end_time=time.fromisoformat(values["end_time"]),
                        crosses_midnight=values["crosses_midnight"],
                        is_active=values["is_active"],
                        provider=values["provider"],
                    )
                )
            elif action == "calendar_update":
                row = session.get(TradingCalendar, int(operation["identity"]["id"]))
                if row is None:
                    raise RepairApprovalError("SESSION_REPAIR_CALENDAR_ROW_MISSING")
                row.has_night_session = bool(operation["after"]["has_night_session"])
            else:
                raise RepairApprovalError(f"SESSION_REPAIR_UNKNOWN_ACTION: {action}")
        session.flush()
        after_states = [_session_operation_state(session, item) for item in plan["operations"]]
        if not all(state == "after" for state in after_states):
            raise RepairApprovalError(f"SESSION_REPAIR_POST_VERIFY_FAILED: states={after_states}")
        session.commit()
    except Exception:
        session.rollback()
        raise
    return _session_repair_result(plan, status="APPLIED_VERIFIED", session=session)


def _session_repair_result(plan: dict[str, Any], *, status: str, session: Session) -> dict[str, Any]:
    sessions = list(
        session.scalars(
            select(TradingSession)
            .where(func.lower(TradingSession.instrument_symbol) == "jm")
            .order_by(TradingSession.exchange_code, TradingSession.start_time)
        )
    )
    return {
        "status": status,
        "task_id": TASK_ID,
        "batch_id": plan["batch_id"],
        "ledger_sha256": plan["ledger_sha256"],
        "operation_counts": plan["operation_counts"],
        "session_after": [_session_snapshot(item) for item in sessions],
        "rollback_method": "restore calendar/session before snapshots and delete only inserted DCE JM rows in one transaction",
        "writes_database": status == "APPLIED_VERIFIED",
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "profile_binding_changed": False,
    }


def _session_operation_state(session: Session, operation: dict[str, Any]) -> str:
    action = operation["action"]
    if action in {"session_retire", "calendar_update"}:
        model = TradingSession if action == "session_retire" else TradingCalendar
        row = session.get(model, int(operation["identity"]["id"]))
        if row is None:
            return "drift"
        snapshot = _session_snapshot(row) if action == "session_retire" else {
            "id": row.id,
            "exchange_code": row.exchange_code,
            "trade_date": row.trade_date.isoformat(),
            "has_night_session": bool(row.has_night_session),
        }
        if snapshot == operation["before"]:
            return "before"
        if snapshot == operation["after"]:
            return "after"
        return "drift"
    identity = operation["identity"]
    rows = list(
        session.scalars(
            select(TradingSession).where(
                TradingSession.exchange_code == identity["exchange_code"],
                func.lower(TradingSession.instrument_symbol) == identity["instrument_symbol"],
                TradingSession.session_name == identity["session_name"],
            )
        )
    )
    if not rows:
        return "before"
    if len(rows) == 1 and _session_snapshot(rows[0], include_id=False) == operation["after"]:
        return "after"
    return "drift"


def _session_snapshot(row: TradingSession, *, include_id: bool = True) -> dict[str, Any]:
    result = {
        "exchange_code": row.exchange_code,
        "instrument_symbol": row.instrument_symbol,
        "session_name": row.session_name,
        "start_time": row.start_time.isoformat(),
        "end_time": row.end_time.isoformat(),
        "crosses_midnight": bool(row.crosses_midnight),
        "is_active": bool(row.is_active),
        "provider": row.provider,
    }
    return {"id": row.id, **result} if include_id else result


def _night_session_expected(trading_day: date, previous_trading_day: date | None) -> bool:
    if previous_trading_day is None:
        return False
    gap = (trading_day - previous_trading_day).days
    return gap == 1 or (trading_day.weekday() == 0 and gap == 3)


def build_derived_period_repair_plan(
    residuals: Iterable[dict[str, Any]],
    *,
    batch_id: str,
) -> dict[str, Any]:
    _validate_batch_id(batch_id)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    blocked_residuals: list[dict[str, Any]] = []
    for row in residuals:
        if row.get("requirement_level") != "hard":
            continue
        if row.get("session_boundary_status") not in {None, "", "passed", "not_computed"}:
            blocked_residuals.append(
                {
                    "target_id": str(row.get("target_id") or ""),
                    "product": str(row.get("product") or ""),
                    "period": str(row.get("period") or ""),
                    "session_boundary_status": str(row.get("session_boundary_status") or ""),
                    "required_action": "repair_or_version_direct_session_reference_metadata_then_reverify",
                }
            )
            continue
        grouped.setdefault((str(row.get("product") or ""), str(row.get("period") or "")), []).append(row)
    operations = []
    for (product, period), rows in sorted(grouped.items()):
        source_evidence = {
            (
                str(row.get("source_1m_file_id") or ""),
                str(row.get("source_1m_path") or ""),
                str(row.get("source_1m_version") or ""),
                str(row.get("source_1m_checksum") or ""),
            )
            for row in rows
        }
        if len(source_evidence) != 1 or not all(next(iter(source_evidence))):
            blocked_residuals.extend(
                {
                    "target_id": str(row.get("target_id") or ""),
                    "product": product,
                    "period": period,
                    "session_boundary_status": str(row.get("session_boundary_status") or ""),
                    "required_action": "resolve_conflicting_or_incomplete_source_identity_then_reverify",
                }
                for row in rows
            )
            continue
        starts = sorted(str(row.get("target_start") or "") for row in rows if row.get("target_start"))
        ends = sorted(
            str(row.get("effective_target_end") or row.get("target_end") or "")
            for row in rows
            if row.get("effective_target_end") or row.get("target_end")
        )
        sample = rows[0]
        operations.append(
            {
                "target_id": "|".join(sorted(str(row.get("target_id") or "") for row in rows)),
                "requirement_level": "hard",
                "consumers": sorted({str(row.get("consumer") or "") for row in rows if row.get("consumer")}),
                "profile_id": str(sample.get("profile_id") or "intraday_research_v1"),
                "product": product,
                "contract_role": str(sample.get("contract_role") or "dominant_main"),
                "period": period,
                "target_start": starts[0] if starts else "",
                "target_end": ends[-1] if ends else "",
                "source_1m_file_id": sample.get("source_1m_file_id") or "",
                "source_1m_path": str(sample.get("source_1m_path") or ""),
                "source_1m_version": str(sample.get("source_1m_version") or ""),
                "source_1m_checksum": str(sample.get("source_1m_checksum") or ""),
                "source_1m_quality": str(sample.get("source_1m_quality") or ""),
            }
        )
    canonical = _canonical_json(operations)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return {
        "task_id": TASK_ID,
        "batch_id": batch_id,
        "status": "REPAIR_PLAN_FROZEN" if operations else "REPAIR_PLAN_BLOCKED",
        "operations": operations,
        "blocked_residuals": blocked_residuals,
        "ledger_sha256": digest,
        "required_approval_statement": f"APPROVE {TASK_ID} {batch_id} {digest}" if operations else "",
        "calls_rqdata": False,
        "profile_binding_changed": False,
    }


def apply_derived_period_repair_plan(
    plan: dict[str, Any],
    *,
    approval_statement: str,
    project_root: Path,
    session: Session,
    require_postgresql: bool = True,
) -> dict[str, Any]:
    root = project_root.resolve()
    if plan.get("task_id") != TASK_ID:
        raise RepairApprovalError("REPAIR_TASK_ID_MISMATCH")
    operations = list(plan.get("operations") or [])
    digest = hashlib.sha256(_canonical_json(operations).encode()).hexdigest()
    expected_statement = f"APPROVE {TASK_ID} {plan.get('batch_id')} {digest}"
    if plan.get("ledger_sha256") != digest or plan.get("required_approval_statement") != expected_statement:
        raise RepairApprovalError("REPAIR_PLAN_DIGEST_MISMATCH")
    if approval_statement != expected_statement:
        raise RepairApprovalError("REPAIR_APPROVAL_STATEMENT_MISMATCH")
    if require_postgresql and session.get_bind().dialect.name != "postgresql":
        raise RepairApprovalError("ENV_BLOCKED_DB: direct PostgreSQL required")
    if not operations:
        raise RepairApprovalError("REPAIR_PLAN_HAS_NO_OPERATIONS")

    batch_id = str(plan["batch_id"])
    _validate_batch_id(batch_id)
    evidence_dir = root / "data/reports/full_history_audit_v2_20260710/derived_periods_005_repairs" / batch_id
    if evidence_dir.exists():
        raise FileExistsError(f"repair evidence directory already exists: {evidence_dir}")
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "approval_ledger.json").write_text(
        json.dumps(
            {
                "status": "APPLYING",
                "task_id": TASK_ID,
                "batch_id": batch_id,
                "ledger_sha256": digest,
                "operations": operations,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    created: list[Path] = []
    registrations: list[dict[str, Any]] = []
    market_data_file_ids: list[int] = []
    try:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for operation in operations:
            grouped.setdefault(str(operation["product"]), []).append(operation)
        for product, product_operations in sorted(grouped.items()):
            periods_payload: dict[str, Any] = {}
            exchange = ""
            contract = f"{product}.MAIN"
            for operation in product_operations:
                source_id = int(operation["source_1m_file_id"])
                source_file = session.get(MarketDataFile, source_id)
                if source_file is None:
                    raise RepairApprovalError(f"REPAIR_SOURCE_FILE_MISSING: {source_id}")
                expected_source = {
                    "path": str(operation["source_1m_path"]),
                    "checksum": str(operation["source_1m_checksum"]),
                    "version": str(operation["source_1m_version"]),
                }
                actual_source = {
                    "path": str(Path(source_file.file_path).resolve(strict=False)),
                    "checksum": str(source_file.checksum or ""),
                    "version": str(source_file.data_version or ""),
                }
                expected_source["path"] = str(Path(expected_source["path"]).resolve(strict=False))
                if actual_source != expected_source:
                    raise RepairApprovalError(f"REPAIR_SOURCE_EVIDENCE_DRIFT: file_id={source_id}")
                if source_file.data_role != "primary" or source_file.quality_status != "passed" or source_file.period != "1m":
                    raise RepairApprovalError(f"REPAIR_SOURCE_NOT_PRIMARY_PASSED_1M: file_id={source_id}")
                if (
                    source_file.provider != "rqdata"
                    or str(source_file.instrument_symbol or "").lower() != product
                    or not str(source_file.contract_code or "").lower().endswith(".main")
                ):
                    raise RepairApprovalError(f"REPAIR_SOURCE_IDENTITY_MISMATCH: file_id={source_id}")
                source_path = Path(actual_source["path"])
                if not source_path.is_file() or sha256_file(source_path) != actual_source["checksum"]:
                    raise RepairApprovalError(f"REPAIR_SOURCE_CHECKSUM_DRIFT: file_id={source_id}")
                source = pd.read_parquet(source_path)
                start = _date(operation["target_start"])
                end = _date(operation["target_end"])
                trading_days = pd.to_datetime(source["trading_day"], errors="coerce").dt.date
                source_start = trading_days.min()
                source_end = trading_days.max()
                if (start and source_start > start) or (end and source_end < end):
                    raise RepairApprovalError(f"REPAIR_SOURCE_WINDOW_NOT_COVERED: file_id={source_id}")
                if start:
                    source = source.loc[trading_days >= start].copy()
                if end:
                    trading_days = pd.to_datetime(source["trading_day"], errors="coerce").dt.date
                    source = source.loc[trading_days <= end].copy()
                if source.empty:
                    raise RepairApprovalError(f"REPAIR_SOURCE_WINDOW_EMPTY: {product}:{operation['period']}")
                exchange = str(source["exchange"].dropna().iloc[0]).upper()
                clock = TradingSessionClock(session)
                if start and end:
                    trading_days, calendar_complete = clock.trading_days_between(
                        start,
                        end,
                        exchange=exchange,
                    )
                    if not calendar_complete:
                        raise RepairApprovalError(f"REPAIR_CALENDAR_METADATA_INCOMPLETE: {product}")
                else:
                    trading_days = sorted(set(pd.to_datetime(source["trading_day"]).dt.date))
                windows = clock.windows_for_trading_days(
                    trading_days,
                    product=product,
                    exchange=exchange,
                )
                if not windows:
                    raise RepairApprovalError(f"REPAIR_SESSION_METADATA_MISSING: {product}")
                aggregated = aggregate_standard_bars_strict(
                    source,
                    str(operation["period"]),
                    session_windows=tuple(windows),
                )
                if aggregated.diagnostics.source_gap_count or aggregated.diagnostics.unmatched_source_row_count:
                    raise RepairApprovalError(
                        f"REPAIR_SOURCE_GAP: {product}:{operation['period']} gaps={aggregated.diagnostics.source_gap_count}"
                    )
                frame = aggregated.frame
                version = (
                    f"fh_derived005_{product}_{operation['period']}_{start:%Y%m%d}_{end:%Y%m%d}"
                    if start and end
                    else f"fh_derived005_{product}_{operation['period']}_{batch_id}"
                )[:64]
                frame["data_role"] = "candidate"
                frame["data_version"] = version
                frame["source_market_data_file_id"] = source_id
                frame["source_path"] = str(source_path.resolve(strict=False))
                frame["source_data_version"] = actual_source["version"]
                frame["source_checksum"] = actual_source["checksum"]
                frame["source_profile_id"] = str(operation["profile_id"])
                quality = evaluate_standard_dominant_quality(frame, str(operation["period"]))
                if quality.status != "passed":
                    raise RepairApprovalError(f"REPAIR_DERIVED_QUALITY_FAILED: {product}:{operation['period']}")
                frame["quality_status"] = "passed"
                output_path = (
                    root
                    / "data/parquet/canonical/bars/provider=rqdata"
                    / f"period={operation['period']}"
                    / f"exchange={exchange}"
                    / f"symbol={product}"
                    / f"contract={contract}"
                    / f"{product}_MAIN_{operation['period']}_{start:%Y%m%d}_{end:%Y%m%d}_derived_periods_005.parquet"
                )
                if output_path.exists():
                    raise FileExistsError(f"repair output already exists: {output_path}")
                write_parquet_atomic(frame, output_path)
                created.append(output_path)
                with duckdb.connect() as connection:
                    readable_rows = int(
                        connection.execute(
                            "SELECT count(*) FROM read_parquet(?)",
                            [str(output_path)],
                        ).fetchone()[0]
                    )
                if readable_rows != len(frame):
                    raise RepairApprovalError(
                        f"REPAIR_DERIVED_DUCKDB_ROW_COUNT_MISMATCH: expected={len(frame)} actual={readable_rows}"
                    )
                periods_payload[str(operation["period"])] = {
                    "data_version": version,
                    "raw": {"path": str(source_path)},
                    "standard": {
                        "path": str(output_path),
                        "row_count": len(frame),
                        "min_datetime": pd.to_datetime(frame["datetime"]).min().isoformat(),
                        "max_datetime": pd.to_datetime(frame["datetime"]).max().isoformat(),
                        "checksum": sha256_file(output_path),
                    },
                    "lineage": {
                        "source_market_data_file_id": source_id,
                        "source_path": str(source_path.resolve(strict=False)),
                        "source_data_version": actual_source["version"],
                        "source_checksum": actual_source["checksum"],
                        "source_profile_id": str(operation["profile_id"]),
                        "source_interval": "1m",
                    },
                }
            starts = [_date(item["target_start"]) for item in product_operations]
            ends = [_date(item["target_end"]) for item in product_operations]
            summary_path = root / f"data/processed/v1b/{product}/{product}_{batch_id}_derived_periods_005.json"
            manifest_path = root / f"data/manifests/{product}_{batch_id}_derived_periods_005.csv"
            if summary_path.exists() or manifest_path.exists():
                raise FileExistsError(f"repair metadata output already exists for {product}")
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "symbol": product,
                        "contract": contract,
                        "exchange": exchange,
                        "start_date": min(item for item in starts if item).isoformat(),
                        "end_date": max(item for item in ends if item).isoformat(),
                        "data_role": "candidate",
                        "periods": periods_payload,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            created.append(summary_path)
            registration = register_dominant_v2_quality(
                session=session,
                summary_path=summary_path,
                manifest_path=manifest_path,
                data_role="candidate",
            )
            created.append(manifest_path)
            registrations.append(registration)
        market_data_file_ids = [
            int(item["market_data_file_id"])
            for registration in registrations
            for item in registration["periods"].values()
        ]
        (evidence_dir / "rollback_evidence.json").write_text(
            json.dumps(
                {
                    "status": "PREPARED_BEFORE_COMMIT",
                    "market_data_file_ids": market_data_file_ids,
                    "files": [str(path) for path in created],
                    "method": "Delete only the recorded candidate registrations and newly versioned files in one controlled rollback.",
                    "profile_binding_changed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        prepared = {
            "status": "PREPARED_BEFORE_COMMIT",
            "task_id": TASK_ID,
            "batch_id": batch_id,
            "ledger_sha256": digest,
            "market_data_file_ids": market_data_file_ids,
            "writes_database": True,
            "writes_parquet": True,
            "writes_manifest": True,
            "calls_rqdata": False,
            "profile_binding_changed": False,
            "registrations": registrations,
        }
        (evidence_dir / "apply_ledger.json").write_text(
            json.dumps(prepared, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            (evidence_dir / "failure_ledger.json").write_text(
                json.dumps(
                    {"status": "ROLLED_BACK", "error_type": type(exc).__name__},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        raise

    result = {
        "status": "APPLIED_VERIFIED",
        "task_id": TASK_ID,
        "batch_id": batch_id,
        "ledger_sha256": digest,
        "market_data_file_ids": market_data_file_ids,
        "writes_database": True,
        "writes_parquet": True,
        "writes_manifest": True,
        "calls_rqdata": False,
        "profile_binding_changed": False,
    }
    try:
        (evidence_dir / "apply_ledger.json").write_text(
            json.dumps({**result, "registrations": registrations}, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise RepairApprovalError(
            f"REPAIR_COMMITTED_EVIDENCE_FINALIZE_FAILED: recovery evidence remains at {evidence_dir}"
        ) from exc
    return result


def write_derived_period_reports(
    result: DerivedPeriodVerificationResult,
    output_dir: Path,
) -> dict[str, Path]:
    output = output_dir.resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.partial-{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        _write_csv(staging / "consumer_target_matrix.csv", result.consumer_target_matrix)
        _write_csv(staging / "derived_period_inventory.csv", result.derived_period_inventory, REPORT_COLUMNS)
        _write_csv(staging / "lineage_residuals.csv", result.lineage_residuals)
        (staging / "materialization_estimate.json").write_text(
            json.dumps(result.materialization_estimate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "verification_evidence.json").write_text(
            json.dumps(result.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "DERIVED_PERIODS_SUMMARY.md").write_text(_summary_markdown(result), encoding="utf-8")
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {path.stem: path for path in sorted(output.iterdir())}


def _select_file(
    files: list[MarketDataFile],
    product: str,
    period: str,
    target: dict[str, Any],
) -> MarketDataFile | None:
    candidates = [
        item
        for item in files
        if str(item.instrument_symbol or "").lower() == product
        and item.period == period
        and item.quality_status == "passed"
        and item.data_role in {"primary", "candidate"}
    ]
    start = _date(target.get("target_start"))
    end = _date(target.get("target_end"))

    def key(item: MarketDataFile) -> tuple[int, int, float, int]:
        item_start = _date(item.start_time) or date.min
        item_end = _date(item.end_time) or date.min
        covers = bool((start is None or item_start <= start) and (end is None or item_end >= end))
        excess = (start - item_start).days if start and item_start <= start else 999999
        return (0 if covers else 1, 0 if item.data_role == "primary" else 1, excess, -(item.id or 0))

    return min(candidates, key=key) if candidates else None


def _with_effective_target_end(
    target: dict[str, Any],
    *,
    source: MarketDataFile | None,
    session: Session,
) -> dict[str, Any]:
    result = dict(target)
    requested = _date(target.get("target_end"))
    exchange = _partition_value(source.file_path, "exchange") if source else ""
    if requested is None or not exchange:
        return result
    requested_row_exists = session.scalar(
        select(func.count())
        .select_from(TradingCalendar)
        .where(
            TradingCalendar.exchange_code.in_((exchange.upper(), "CNFE")),
            TradingCalendar.trade_date == requested,
        )
    )
    if not requested_row_exists:
        result["calendar_boundary_status"] = "unverified"
        return result
    effective = session.scalar(
        select(func.max(TradingCalendar.trade_date)).where(
            TradingCalendar.exchange_code.in_((exchange.upper(), "CNFE")),
            TradingCalendar.trade_date <= requested,
            TradingCalendar.is_trading_day.is_(True),
        )
    )
    if effective:
        result["effective_target_end"] = effective.isoformat()
        result["calendar_boundary_status"] = "verified"
    return result


def _partition_value(value: str | Path, key: str) -> str:
    prefix = f"{key}="
    return next(
        (part.removeprefix(prefix) for part in Path(value).parts if part.startswith(prefix)),
        "",
    )


def _select_lineage_pair(
    files: list[MarketDataFile],
    product: str,
    period: str,
    target: dict[str, Any],
    *,
    lineage_map: dict[str, tuple[str, ...]],
) -> tuple[MarketDataFile | None, MarketDataFile | None]:
    """Select an exact declared source/derived pair before legacy role preference.

    A candidate derived asset may be stronger audit evidence than an older primary
    asset when its processed summary names the exact registered passed-primary 1m
    source.  This affects evidence selection only; it never promotes the candidate.
    """
    sources = [
        item
        for item in files
        if str(item.instrument_symbol or "").lower() == product
        and item.period == "1m"
        and item.data_role == "primary"
        and item.quality_status == "passed"
    ]
    sources_by_path = {
        str(Path(item.file_path).resolve(strict=False)): item
        for item in sources
    }
    derived_candidates = [
        item
        for item in files
        if str(item.instrument_symbol or "").lower() == product
        and item.period == period
        and item.data_role in {"primary", "candidate"}
        and item.quality_status == "passed"
    ]
    start = _date(target.get("target_start"))
    end = _date(target.get("target_end"))

    def covers(item: MarketDataFile) -> bool:
        item_start = _date(item.start_time) or date.min
        item_end = _date(item.end_time) or date.min
        return bool((start is None or item_start <= start) and (end is None or item_end >= end))

    exact_pairs: list[tuple[MarketDataFile, MarketDataFile]] = []
    for derived in derived_candidates:
        derived_path = str(Path(derived.file_path).resolve(strict=False))
        declared_sources = lineage_map.get(derived_path, ())
        source = sources_by_path.get(declared_sources[0]) if len(declared_sources) == 1 else None
        if source is not None:
            exact_pairs.append((source, derived))

    if exact_pairs:
        def pair_key(pair: tuple[MarketDataFile, MarketDataFile]) -> tuple[int, int, int, int]:
            source, derived = pair
            source_start = _date(source.start_time) or date.min
            excess = (start - source_start).days if start and source_start <= start else 999999
            return (
                0 if covers(derived) else 1,
                0 if derived.data_role == "primary" else 1,
                excess,
                -(derived.id or 0),
            )

        return min(exact_pairs, key=pair_key)
    return (
        _select_file(files, product, "1m", target),
        _select_file(files, product, period, target),
    )


def _evaluate_target(
    target: dict[str, Any],
    *,
    source: MarketDataFile | None,
    derived: MarketDataFile | None,
    lineage_map: dict[str, tuple[str, ...]],
    binding: ProfileActiveBinding | None,
    scan_mode: str,
    clock: TradingSessionClock,
    content_cache: dict[tuple[str, str, str, str, str], dict[str, Any]],
    physical_cache: dict[str, dict[str, Any]],
    source_frame_cache: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    source_path = str(Path(source.file_path).resolve(strict=False)) if source else ""
    derived_path = str(Path(derived.file_path).resolve(strict=False)) if derived else ""
    if source_path and source_path not in physical_cache:
        physical_cache[source_path] = _physical_summary(Path(source_path))
    if derived_path and derived_path not in physical_cache:
        physical_cache[derived_path] = _physical_summary(Path(derived_path))
    source_physical = physical_cache.get(source_path, {})
    physical = physical_cache.get(derived_path, {})
    source_checksum_status = "missing"
    if source and source_physical.get("checksum_actual"):
        source_checksum_status = (
            "matched" if source.checksum == source_physical["checksum_actual"] else "mismatch"
        )
    declared_sources = lineage_map.get(derived_path, ())
    exact_source = bool(source_path and declared_sources == (source_path,))
    source_interval = physical.get("source_interval", "")
    source_count_status = physical.get("source_bar_count_status", "file_missing")
    checksum_status = "missing"
    if derived and physical.get("checksum_actual"):
        checksum_status = "matched" if derived.checksum == physical["checksum_actual"] else "mismatch"
    lineage_status = (
        "verified"
        if exact_source
        and source_interval == "1m"
        and source_count_status == "present"
        and source_checksum_status == "matched"
        and checksum_status == "matched"
        else "lineage_unverified"
    )
    coverage_target = dict(target)
    coverage_target["target_end"] = target.get("effective_target_end") or target.get("target_end")
    if not coverage_target.get("target_start") and source_physical.get("min_datetime"):
        coverage_target["target_start"] = source_physical["min_datetime"]
    coverage = _coverage_status(
        coverage_target,
        derived,
        bool(physical.get("physical_exists")),
        physical_start=physical.get("min_datetime"),
        physical_end=physical.get("max_datetime"),
    )
    content = {
        "session_boundary_status": "not_computed",
        "source_gap_count": "",
        "recomputed_row_count": "",
        "content_comparison_status": "not_computed",
    }
    if (
        scan_mode == "full"
        and target["requirement_level"] == "hard"
        and source_path
        and derived_path
        and Path(source_path).is_file()
        and Path(derived_path).is_file()
    ):
        cache_key = (source_path, derived_path, target["period"], target["target_start"], target["target_end"])
        if cache_key not in content_cache:
            content_cache[cache_key] = _compare_content(
                Path(source_path),
                Path(derived_path),
                period=target["period"],
                product=target["product"],
                target_start=_date(target["target_start"]),
                target_end=_date(target.get("effective_target_end") or target["target_end"]),
                clock=clock,
                source_frame_cache=source_frame_cache,
            )
        content = content_cache[cache_key]
        if content["content_comparison_status"] != "matched":
            lineage_status = "lineage_unverified"
    window_class = _window_class(derived)
    if content["session_boundary_status"] not in {"not_computed", "passed"}:
        recommended_action = "repair_or_version_direct_session_reference_metadata_then_reverify"
    elif coverage == "covered" and lineage_status == "verified":
        recommended_action = "none"
    else:
        recommended_action = "rebuild_from_exact_passed_1m_candidate"
    row = {
        **target,
        "source_1m_file_id": source.id if source else "",
        "source_1m_path": source_path,
        "source_1m_version": source.data_version if source else "",
        "source_1m_checksum": source.checksum if source else "",
        "source_checksum_status": source_checksum_status,
        "source_1m_quality": source.quality_status if source else "missing",
        "derived_file_id": derived.id if derived else "",
        "derived_path": derived_path,
        "derived_version": derived.data_version if derived else "",
        "derived_data_role": derived.data_role if derived else "",
        "derived_quality": derived.quality_status if derived else "missing",
        "physical_min_datetime": physical.get("min_datetime", ""),
        "physical_max_datetime": physical.get("max_datetime", ""),
        "window_class": window_class,
        "source_interval": source_interval,
        "source_bar_count_status": source_count_status,
        **content,
        "checksum_status": checksum_status,
        "lineage_status": lineage_status,
        "coverage_status": coverage,
        "active_binding_status": _binding_status(binding, derived),
        "recommended_action": recommended_action,
    }
    return {key: row.get(key, "") for key in (*REPORT_COLUMNS, "materialization_policy")}


def _evaluate_source_target(
    target: dict[str, Any],
    *,
    source: MarketDataFile | None,
    binding: ProfileActiveBinding | None,
    physical_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_path = str(Path(source.file_path).resolve(strict=False)) if source else ""
    if source_path and source_path not in physical_cache:
        physical_cache[source_path] = _physical_summary(Path(source_path))
    physical = physical_cache.get(source_path, {})
    checksum_status = "missing"
    if source and physical.get("checksum_actual"):
        checksum_status = "matched" if source.checksum == physical["checksum_actual"] else "mismatch"
    coverage_target = {**target, "target_end": target.get("effective_target_end") or target.get("target_end")}
    coverage = _coverage_status(
        coverage_target,
        source,
        bool(physical.get("physical_exists")),
        physical_start=physical.get("min_datetime"),
        physical_end=physical.get("max_datetime"),
    )
    verified = bool(
        source
        and source.data_role == "primary"
        and source.quality_status == "passed"
        and coverage == "covered"
        and checksum_status == "matched"
    )
    row = {
        **target,
        "source_1m_file_id": source.id if source else "",
        "source_1m_path": source_path,
        "source_1m_version": source.data_version if source else "",
        "source_1m_checksum": source.checksum if source else "",
        "source_checksum_status": checksum_status,
        "source_1m_quality": source.quality_status if source else "missing",
        "physical_min_datetime": physical.get("min_datetime", ""),
        "physical_max_datetime": physical.get("max_datetime", ""),
        "window_class": _window_class(source),
        "source_interval": "1m",
        "source_bar_count_status": "not_applicable_source",
        "session_boundary_status": "not_computed",
        "source_gap_count": "",
        "recomputed_row_count": "",
        "content_comparison_status": "not_computed",
        "checksum_status": checksum_status,
        "lineage_status": "verified" if verified else "lineage_unverified",
        "coverage_status": coverage,
        "active_binding_status": _binding_status(binding, source),
        "recommended_action": "none" if verified else "repair_passed_primary_1m_source_evidence",
    }
    return {key: row.get(key, "") for key in (*REPORT_COLUMNS, "materialization_policy")}


def _physical_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"physical_exists": False}
    try:
        parquet = pq.ParquetFile(path)
        columns = set(parquet.schema.names)
        selected = [column for column in ("datetime", "source_interval") if column in columns]
        frame = parquet.read(columns=selected).to_pandas()
    except Exception as exc:  # noqa: BLE001 - unreadable asset is evidence.
        return {"physical_exists": True, "read_error": type(exc).__name__}
    stamps = pd.to_datetime(frame.get("datetime"), errors="coerce")
    intervals = sorted(set(frame.get("source_interval", pd.Series(dtype=str)).dropna().astype(str)))
    return {
        "physical_exists": True,
        "min_datetime": stamps.min().isoformat() if not stamps.empty else "",
        "max_datetime": stamps.max().isoformat() if not stamps.empty else "",
        "source_interval": intervals[0] if intervals == ["1m"] else "|".join(intervals),
        "source_bar_count_status": "present" if "source_bar_count" in columns else "column_missing",
        "checksum_actual": sha256_file(path),
    }


def _load_processed_lineage(root: Path) -> dict[str, tuple[str, ...]]:
    declarations: dict[str, set[str]] = {}
    processed_root = root / "data/processed/v1b"
    if not processed_root.exists():
        return {}
    for path in sorted(processed_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in (payload.get("periods") or {}).values():
            standard = item.get("standard") or {}
            raw = item.get("raw") or {}
            standard_path = standard.get("path")
            raw_path = raw.get("path")
            if standard_path and raw_path:
                declarations.setdefault(str(_resolve(root, standard_path)), set()).add(
                    str(_resolve(root, raw_path))
                )
    return {path: tuple(sorted(sources)) for path, sources in declarations.items()}


def _compare_content(
    source_path: Path,
    derived_path: Path,
    *,
    period: str,
    product: str,
    target_start: date | None,
    target_end: date | None,
    clock: TradingSessionClock,
    source_frame_cache: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    source_key = str(source_path.resolve(strict=False))
    if source_frame_cache is not None and source_key in source_frame_cache:
        source = source_frame_cache[source_key].copy()
    else:
        source = pd.read_parquet(source_path)
        if source_frame_cache is not None:
            source_frame_cache[source_key] = source.copy()
    actual = pd.read_parquet(derived_path)
    source_dates = pd.to_datetime(source["trading_day"], errors="coerce").dt.date
    actual_dates = pd.to_datetime(actual["trading_day"], errors="coerce").dt.date
    if target_start:
        source = source.loc[source_dates >= target_start].copy()
        actual = actual.loc[actual_dates >= target_start].copy()
    if target_end:
        source_dates = pd.to_datetime(source["trading_day"], errors="coerce").dt.date
        actual_dates = pd.to_datetime(actual["trading_day"], errors="coerce").dt.date
        source = source.loc[source_dates <= target_end].copy()
        actual = actual.loc[actual_dates <= target_end].copy()
    exchange = str(source["exchange"].dropna().iloc[0]) if not source.empty else ""
    if target_start and target_end:
        trading_days, calendar_complete = clock.trading_days_between(
            target_start,
            target_end,
            exchange=exchange,
        )
        if not calendar_complete:
            return {
                "session_boundary_status": "calendar_metadata_incomplete",
                "source_gap_count": "",
                "recomputed_row_count": "",
                "content_comparison_status": "blocked_calendar_metadata",
            }
    else:
        trading_days = sorted(set(pd.to_datetime(source["trading_day"]).dt.date))
    windows = clock.windows_for_trading_days(
        trading_days,
        product=product,
        exchange=exchange,
    )
    if not windows:
        return {
            "session_boundary_status": "metadata_missing",
            "source_gap_count": "",
            "recomputed_row_count": "",
            "content_comparison_status": "blocked_session_metadata",
        }
    recomputed = aggregate_standard_bars_strict(source, period, session_windows=tuple(windows))
    expected = recomputed.frame.sort_values("datetime").reset_index(drop=True)
    actual = actual.sort_values("datetime").reset_index(drop=True)
    columns = ["datetime", "trading_day", "open", "high", "low", "close", "volume", "turnover", "open_interest", "source_bar_count"]
    matched = len(expected) == len(actual) and all(column in actual.columns for column in columns)
    if matched:
        matched = _datetime_series_equal(expected["datetime"], actual["datetime"])
    if matched:
        matched = pd.to_datetime(expected["trading_day"]).dt.date.equals(
            pd.to_datetime(actual["trading_day"]).dt.date
        )
    if matched:
        for column in ("open", "high", "low", "close", "volume", "turnover", "open_interest"):
            if not pd.Series(expected[column]).astype(float).round(9).equals(pd.Series(actual[column]).astype(float).round(9)):
                matched = False
                break
    if matched:
        matched = expected["source_bar_count"].astype(int).equals(actual["source_bar_count"].astype(int))
    return {
        "session_boundary_status": (
            "unmatched_source_rows"
            if recomputed.diagnostics.unmatched_source_row_count
            else "source_gap"
            if recomputed.diagnostics.source_gap_count
            else "passed"
        ),
        "source_gap_count": recomputed.diagnostics.source_gap_count,
        "recomputed_row_count": len(expected),
        "content_comparison_status": "matched" if matched else "mismatch",
    }


def _datetime_series_equal(expected: pd.Series, actual: pd.Series) -> bool:
    """Compare timestamps by value, independent of Parquet micro/nanosecond dtype."""
    left = pd.to_datetime(expected, errors="coerce").astype("datetime64[ns]").reset_index(drop=True)
    right = pd.to_datetime(actual, errors="coerce").astype("datetime64[ns]").reset_index(drop=True)
    return left.equals(right)


def _coverage_status(
    target: dict[str, Any],
    item: MarketDataFile | None,
    exists: bool,
    *,
    physical_start: Any = None,
    physical_end: Any = None,
) -> str:
    if item is None or not exists:
        return "missing"
    start = _date(target.get("target_start"))
    end = _date(target.get("target_end"))
    item_start = _date(item.start_time)
    item_end = _date(item.end_time)
    physical_start_date = _date(physical_start)
    physical_end_date = _date(physical_end)
    registered_covers = (start is None or item_start <= start) and (end is None or item_end >= end)
    physical_covers = (start is None or (physical_start_date is not None and physical_start_date <= start)) and (
        end is None or (physical_end_date is not None and physical_end_date >= end)
    )
    return "covered" if registered_covers and physical_covers else "partial"


def _window_class(item: MarketDataFile | None) -> str:
    start = _date(item.start_time) if item else None
    if start is None:
        return "missing"
    if start >= date(2023, 1, 1):
        return "2023+"
    if start >= date(2020, 1, 1):
        return "2020+"
    return "provider_earliest_candidate"


def _binding_status(binding: ProfileActiveBinding | None, derived: MarketDataFile | None) -> str:
    if binding is None:
        return "missing"
    if derived and binding.market_data_file_id == derived.id:
        return "active_selected"
    return "active_other_version"


def _residual_reason(row: dict[str, Any]) -> str:
    reasons = []
    if row["coverage_status"] != "covered":
        reasons.append(row["coverage_status"])
    if row["lineage_status"] != "verified":
        reasons.append(row["lineage_status"])
    if row["checksum_status"] != "matched":
        reasons.append(f"checksum_{row['checksum_status']}")
    if row.get("source_checksum_status") != "matched":
        reasons.append(f"source_checksum_{row.get('source_checksum_status') or 'missing'}")
    if row["content_comparison_status"] not in {"not_computed", "matched"}:
        reasons.append(row["content_comparison_status"])
    if row["session_boundary_status"] not in {"not_computed", "passed"}:
        reasons.append(row["session_boundary_status"])
    if row.get("calendar_boundary_status") != "verified":
        reasons.append("calendar_boundary_unverified")
    return "|".join(sorted(set(reasons)))


def _load_products(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"products file not found: {path}")
    return tuple(
        sorted(
            line.strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: Iterable[str] | None = None) -> None:
    fieldnames = list(columns or sorted({key for row in rows for key in row}))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summary_markdown(result: DerivedPeriodVerificationResult) -> str:
    summary = result.summary
    return "\n".join(
        [
            "# Derived Period Targets Verification",
            "",
            f"- status: `{summary['status']}`",
            f"- audit_end: `{summary['audit_end']}`",
            f"- hard_scope: `{summary['hard_scope']}`",
            f"- hard_residual_count: `{summary['hard_residual_count']}`",
            f"- lineage_residual_count: `{summary['lineage_residual_count']}`",
            "- writes_database: `false`",
            "- writes_parquet: `false`",
            "- writes_manifest: `false`",
            "- calls_rqdata: `false`",
            "- profile_binding_changed: `false`",
            "- data_layer_status: `DATA_LAYER_REAUDIT_REQUIRED`",
            "",
        ]
    )


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _validate_batch_id(value: str) -> None:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) is None:
        raise RepairApprovalError("REPAIR_BATCH_ID_INVALID")


def _date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _git_dirty(root: Path) -> bool:
    try:
        return bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return True


def _validate_data_environment(root: Path) -> Path:
    if root != EXPECTED_DATA_ROOT.resolve(strict=False):
        raise RuntimeError(
            f"ENV_BLOCKED_DATA_ROOT: root differs from frozen B2-00 task root: {root}"
        )
    volumes = Path("/Volumes")
    try:
        relative = root.relative_to(volumes)
    except ValueError as exc:
        raise RuntimeError(f"ENV_BLOCKED_DATA_ROOT: project root is not on /Volumes: {root}") from exc
    if not relative.parts:
        raise RuntimeError(f"ENV_BLOCKED_DATA_ROOT: invalid project root: {root}")
    mount_root = volumes / relative.parts[0]
    if not mount_root.is_mount():
        raise RuntimeError(f"ENV_BLOCKED_DATA_ROOT: external volume is not mounted: {mount_root}")
    canonical = root / "data/parquet/canonical/bars"
    if not canonical.is_dir() or next(canonical.rglob("*.parquet"), None) is None:
        raise RuntimeError(f"ENV_BLOCKED_DATA_ROOT: canonical bars root is missing or empty: {canonical}")
    return mount_root


__all__ = [
    "AUDIT_END",
    "DERIVED_PERIOD_TARGETS_VERIFIED",
    "DerivedPeriodVerificationConfig",
    "DerivedPeriodVerificationResult",
    "RepairApprovalError",
    "apply_derived_period_repair_plan",
    "build_consumer_targets",
    "build_derived_period_repair_plan",
    "run_derived_period_verification",
    "write_derived_period_reports",
]
