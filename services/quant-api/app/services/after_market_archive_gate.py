from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataDownloadTask, LiveMinuteBar, utc_now
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.rqdata_ingest.bar_sample import normalize_bar_frame
from app.services.rqdata_ingest.jm_historical_catchup import (
    CatchupItem,
    CatchupPlan,
    build_artifact_plan,
    canonical_packet_hash,
)
from app.services.rqdata_ingest.jm_historical_catchup_execution import (
    active_baseline_start,
    apply_profile_binding_candidates,
    apply_reference_snapshot,
    collect_active_binding_snapshot,
    collect_provider_reference_snapshot,
    materialize_execution_assets,
    register_execution_assets,
    stable_bar_frame_hash,
    validate_execution_paths_create_only,
)
from app.services.trading_session_clock import TradingSessionClock


TASK_ID = "JM-AFTER-MARKET-ARCHIVE-S6-06"
PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


class ArchiveGateError(RuntimeError):
    """Raised when a JM archive approval or execution contract fails."""


def build_archive_plan(
    *,
    output_root: Path,
    batch_id: str,
    trading_day: date,
    actual_contract: str,
    baseline_start: date,
    expected_source_rows: int,
    provider_final_1m_hash: str,
    include_week: bool,
) -> dict[str, Any]:
    actual = actual_contract.strip().upper()
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise ArchiveGateError("jm_actual_contract_required")
    derived = ["5m", "15m", "30m", "60m", "1d"]
    if include_week:
        derived.append("1w")
    items = [
        CatchupItem(
            product="jm",
            contract=actual,
            period="1m",
            source_role="direct",
            start=baseline_start,
            end=trading_day,
            mapping_start=trading_day,
            mapping_end=trading_day,
        ),
        *[
            CatchupItem(
                product="jm",
                contract=actual,
                period=period,
                source_role="derived_from_1m",
                start=baseline_start,
                end=trading_day,
                mapping_start=trading_day,
                mapping_end=trading_day,
            )
            for period in derived
        ],
    ]
    artifact = build_artifact_plan(
        CatchupPlan(
            product="jm",
            target=trading_day,
            weekly_target=trading_day,
            status="archive_required",
            items=tuple(items),
        ),
        output_root=output_root,
        batch_id=batch_id,
    )
    root = output_root.resolve(strict=False)
    artifact["task_id"] = TASK_ID
    artifact["expected_source_rows"] = int(expected_source_rows)
    artifact["provider_final_1m_hash"] = provider_final_1m_hash
    artifact["manifest_path"] = str(root / "manifests" / f"jm_after_market_archive_{batch_id}.csv")
    artifact["audit_root"] = str(root / "reports" / "jm_after_market_archive_s6_06" / batch_id)
    reference_root = root / "raw" / "rqdata" / "jm_historical_catchup" / f"batch={batch_id}" / "reference"
    artifact["reference_paths"] = [
        str(reference_root / name)
        for name in ("calendar.parquet", "rank1_mapping.parquet", "trading_parameters.parquet")
    ]
    for row in artifact["bars"]:
        role = "d" if row["source_role"] == "direct" else "d1m"
        row["data_version"] = f"{batch_id}_{actual}_{row['period']}_{role}_v1"
        if row["source_role"] == "direct":
            row["request_start"] = trading_day.isoformat()
    _validate_versions(artifact)
    return artifact


def build_approval_packet(
    *,
    bound_facts: Mapping[str, Any],
    execution_plan: Mapping[str, Any],
    reference_snapshot: Mapping[str, Any],
    binding_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "approval_required",
        "product": "jm",
        "writes_authorized": False,
        "bound_facts": dict(bound_facts),
        "execution_plan": dict(execution_plan),
        "reference_snapshot": dict(reference_snapshot),
        "binding_snapshot": dict(binding_snapshot),
        "rollback": {
            "active_binding": "compare-and-switch in one DB transaction",
            "existing_assets": "immutable",
            "new_files": "remove packet-listed create-only files after rollback",
            "live_rows": "comparison evidence only and never copied into historical",
        },
        "invalidation_rule": "any bound fact drift invalidates this packet",
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def collect_archive_packet(
    session: Session,
    *,
    client: Any,
    output_root: Path,
    trading_day: date,
    now: datetime,
    git_identity: Mapping[str, Any],
    database_identity: Mapping[str, Any],
    t3_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if t3_receipt.get("gate") != "T3_REAL_PASSED":
        raise ArchiveGateError("t3_real_passed_receipt_required")
    if str(t3_receipt.get("trading_day")) != trading_day.isoformat():
        raise ArchiveGateError("t3_trading_day_mismatch")
    clock = TradingSessionClock(session)
    if not clock.trading_day_closed(trading_day, product="jm", exchange="DCE", now=now):
        raise ArchiveGateError("trading_day_not_closed")
    calendar_start = trading_day - timedelta(days=35)
    calendar_end = trading_day + timedelta(days=7)
    provider_days = sorted(client.trading_dates(calendar_start, calendar_end))
    eligible = [day for day in provider_days if day <= trading_day]
    if not eligible or eligible[-1] != trading_day:
        raise ArchiveGateError("provider_final_trading_day_missing")
    mapping_start = max(calendar_start, trading_day - timedelta(days=21))
    reference = collect_provider_reference_snapshot(
        client,
        calendar_start=calendar_start,
        calendar_end=calendar_end,
        mapping_start=mapping_start,
        target=trading_day,
    )
    actual = str(reference["actual_contract"])
    if actual != str(t3_receipt.get("actual_contract")):
        raise ArchiveGateError("t3_actual_contract_mismatch")
    raw = client.contract_bars(actual, trading_day, trading_day, "1m")
    normalized = normalize_bar_frame(
        raw,
        symbol="jm",
        contract=actual,
        source_contract=actual,
        exchange="DCE",
        frequency="1m",
        data_version="archive_preflight",
    )
    source_days = pd.to_datetime(normalized["trading_day"], errors="coerce").dt.date
    target_frame = normalized.loc[source_days == trading_day].copy()
    expected_rows = clock.expected_minute_count(trading_day, product="jm", exchange="DCE")
    if len(target_frame) != expected_rows:
        raise ArchiveGateError(f"provider_final_row_count_mismatch:{len(target_frame)}!={expected_rows}")
    if target_frame["datetime"].duplicated().any():
        raise ArchiveGateError("provider_final_duplicate_bar")
    week_days, complete_week = clock.week_trading_days(trading_day, exchange="DCE")
    include_week = bool(complete_week and week_days and week_days[-1] == trading_day)
    baseline_start = active_baseline_start(session, contract=actual, periods=("1m",))
    batch_id = f"s606_{trading_day:%Y%m%d}_{str(git_identity['commit'])[:8]}"
    execution = build_archive_plan(
        output_root=output_root,
        batch_id=batch_id,
        trading_day=trading_day,
        actual_contract=actual,
        baseline_start=baseline_start,
        expected_source_rows=expected_rows,
        provider_final_1m_hash=stable_bar_frame_hash(target_frame),
        include_week=include_week,
    )
    validate_execution_paths_create_only({"product": "jm", "files": _planned_files(execution)})
    binding = collect_active_binding_snapshot(session)
    live = _live_snapshot(session, actual=actual, trading_day=trading_day)
    bound = {
        "git": dict(git_identity),
        "database": dict(database_identity),
        "output_root": str(output_root.resolve(strict=False)),
        "trading_day": trading_day.isoformat(),
        "trading_day_closed": True,
        "actual_contract": actual,
        "dominant_mapping_date": trading_day.isoformat(),
        "provider_final_row_count": len(target_frame),
        "provider_final_1m_hash": execution["provider_final_1m_hash"],
        "active_binding_sha256": binding["sha256"],
        "live_snapshot": live,
        "t3_packet_hash": t3_receipt.get("packet_hash"),
        "t3_receipt_hash": _stable_hash(t3_receipt),
        "include_completed_week": include_week,
    }
    return build_approval_packet(
        bound_facts=bound,
        execution_plan=execution,
        reference_snapshot=reference,
        binding_snapshot=binding,
    )


def execute_archive(
    session: Session,
    *,
    client: Any,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_packet: Mapping[str, Any],
    output_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    packet_hash = str(packet.get("packet_hash") or "")
    if approval_hash != packet_hash:
        raise ArchiveGateError("approval_hash_mismatch")
    if canonical_packet_hash(packet) != packet_hash:
        raise ArchiveGateError("packet_hash_invalid")
    if current_packet.get("bound_facts") != packet.get("bound_facts"):
        raise ArchiveGateError("bound_fact_drift")
    execution = dict(packet["execution_plan"])
    audit_root = Path(str(execution["audit_root"]))
    receipt_path = audit_root / "completion_receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("packet_hash") != packet_hash:
            raise ArchiveGateError("completion_receipt_mismatch")
        return {"status": "already_archived", "writes_performed": False, "receipt_path": str(receipt_path)}
    created_before = {path for path in _planned_files(execution) if Path(path).exists()}
    try:
        reference = apply_reference_snapshot(
            session,
            snapshot=packet["reference_snapshot"],
            batch_id=str(execution["batch_id"]),
            target=date.fromisoformat(str(execution["target"])),
        )
        materialized = materialize_execution_assets(
            session=session,
            client=client,
            plan=execution,
            reference_snapshot=packet["reference_snapshot"],
            output_root=output_root,
        )
        registration = register_execution_assets(
            session=session,
            materialized=materialized,
            manifest_path=Path(str(execution["manifest_path"])),
        )
        bindings = apply_profile_binding_candidates(
            session,
            artifact_plan=execution,
            registration=registration,
            expected_snapshot=packet["binding_snapshot"],
            project_root=project_root,
        )
        trading_day = date.fromisoformat(str(execution["target"]))
        reconciliation = reconcile_live_provider(
            session,
            actual_contract=str(materialized["actual_contract"]),
            trading_day=trading_day,
            canonical_1m=next(
                Path(str(row["canonical_path"]))
                for row in registration["rows"]
                if row["period"] == "1m"
            ),
        )
        target = LiveTargetContractResolver(session).resolve_ready_actual_contract(
            product="jm",
            required_date=trading_day,
        )
        quality = {
            "status": "passed",
            "task_id": TASK_ID,
            "packet_hash": packet_hash,
            "reference": reference,
            "assets": registration["rows"],
            "profile_switches": bindings["switches"],
            "consumer_target": target,
            "reconciliation": reconciliation,
        }
        _write_json(audit_root / "quality_gate.json", quality)
        session.commit()
    except Exception as exc:
        session.rollback()
        _cleanup_created(execution, existing=created_before)
        _record_failure(
            session,
            trading_day=date.fromisoformat(str(execution["target"])),
            actual_contract=str(packet["reference_snapshot"]["actual_contract"]),
            packet_hash=packet_hash,
            exc=exc,
        )
        raise
    final = {**quality, "status": "success", "gate": "JM_ARCHIVE_PASSED", "database_committed": True}
    _write_json(audit_root / "final_audit.json", final)
    _write_json(
        receipt_path,
        {
            "status": "completed",
            "gate": "JM_ARCHIVE_PASSED",
            "packet_hash": packet_hash,
            "trading_day": execution["target"],
            "actual_contract": materialized["actual_contract"],
            "manifest_path": registration["manifest_path"],
        },
    )
    return final


def reconcile_live_provider(
    session: Session,
    *,
    actual_contract: str,
    trading_day: date,
    canonical_1m: Path,
) -> dict[str, Any]:
    frame = pd.read_parquet(canonical_1m)
    days = pd.to_datetime(frame["trading_day"], errors="coerce").dt.date
    provider = frame.loc[days == trading_day].copy()
    provider["datetime"] = pd.to_datetime(provider["datetime"], errors="raise")
    provider_rows = {
        pd.Timestamp(row["datetime"]).to_pydatetime().replace(tzinfo=None): row
        for _, row in provider.iterrows()
    }
    live = list(
        session.scalars(
            select(LiveMinuteBar).where(
                LiveMinuteBar.provider == "rqdata",
                LiveMinuteBar.contract_code == actual_contract,
                LiveMinuteBar.period == "1m",
                LiveMinuteBar.trading_day == trading_day,
                LiveMinuteBar.bar_status == "confirmed",
                LiveMinuteBar.quality_status != "failed",
            )
        )
    )
    live_rows = {row.bar_datetime.replace(tzinfo=None): row for row in live}
    shared = sorted(set(provider_rows) & set(live_rows))
    mismatches = []
    fields = ("open", "high", "low", "close", "volume", "open_interest")
    for key in shared:
        provider_row = provider_rows[key]
        live_row = live_rows[key]
        changed = [field for field in fields if _number(getattr(live_row, field)) != _number(provider_row[field])]
        if changed:
            mismatches.append({"bar_datetime": key.isoformat(), "fields": changed})
    status = "matched" if set(provider_rows) == set(live_rows) and not mismatches else "differences_observed"
    return {
        "status": status,
        "live_reference_only": True,
        "provider_row_count": len(provider_rows),
        "live_row_count": len(live_rows),
        "exact_match_count": len(shared) - len(mismatches),
        "live_missing_count": len(set(provider_rows) - set(live_rows)),
        "provider_missing_count": len(set(live_rows) - set(provider_rows)),
        "revision_row_count": sum(1 for row in live if row.revision > 0),
        "ohlcv_mismatch_count": len(mismatches),
        "mismatch_samples": mismatches[:20],
    }


def _live_snapshot(session: Session, *, actual: str, trading_day: date) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(LiveMinuteBar).where(
                LiveMinuteBar.contract_code == actual,
                LiveMinuteBar.period == "1m",
                LiveMinuteBar.trading_day == trading_day,
            )
        )
    )
    values = [
        {
            "id": row.id,
            "bar_datetime": row.bar_datetime.isoformat(),
            "revision": row.revision,
            "bar_status": row.bar_status,
            "quality_status": row.quality_status,
        }
        for row in sorted(rows, key=lambda item: item.bar_datetime)
    ]
    return {"row_count": len(values), "sha256": _stable_hash(values)}


def _planned_files(plan: Mapping[str, Any]) -> list[str]:
    return [
        *[str(row["canonical_path"]) for row in plan.get("bars") or []],
        *[str(row["raw_path"]) for row in plan.get("bars") or [] if row.get("raw_path")],
        *[str(path) for path in plan.get("reference_paths") or []],
        str(plan["manifest_path"]),
        str(Path(str(plan["audit_root"])) / "quality_gate.json"),
        str(Path(str(plan["audit_root"])) / "final_audit.json"),
        str(Path(str(plan["audit_root"])) / "completion_receipt.json"),
    ]


def _cleanup_created(plan: Mapping[str, Any], *, existing: set[str]) -> None:
    for value in reversed(_planned_files(plan)):
        path = Path(value)
        if value not in existing and path.is_file():
            path.unlink()


def _record_failure(
    session: Session,
    *,
    trading_day: date,
    actual_contract: str,
    packet_hash: str,
    exc: Exception,
) -> None:
    task_no = f"archive:s606:jm:{actual_contract}:{trading_day.isoformat()}"
    task = session.scalar(select(DataDownloadTask).where(DataDownloadTask.task_no == task_no))
    if task is None:
        task = DataDownloadTask(
            task_no=task_no,
            provider="rqdata",
            data_type="after_market_archive",
            instrument_symbol="jm",
            contract_code=actual_contract,
            period="1m_bundle",
            start_time=datetime.combine(trading_day, datetime.min.time()),
            end_time=datetime.combine(trading_day, datetime.max.time()),
            status="failed",
            progress=0,
            result={},
            started_at=utc_now(),
        )
        session.add(task)
    task.status = "failed"
    task.error_message = _safe_error(exc)
    task.finished_at = utc_now()
    task.result = {
        "task_id": TASK_ID,
        "packet_hash": packet_hash,
        "error_type": type(exc).__name__,
        "active_binding_changed": False,
    }
    try:
        session.commit()
    except Exception:
        session.rollback()


def _validate_versions(plan: Mapping[str, Any]) -> None:
    invalid = [row["data_version"] for row in plan.get("bars") or [] if len(str(row["data_version"])) > 64]
    if invalid:
        raise ArchiveGateError("data_version_too_long")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise ArchiveGateError(f"output_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return format(float(value), ".10g")


def _safe_error(exc: Exception) -> str | None:
    value = str(exc).strip()
    if not value:
        return None
    lowered = value.lower()
    if any(part in lowered for part in ("password", "secret", "token", "webhook", "license", "cookie", "key")):
        return None
    return value[:200]


__all__ = [
    "ArchiveGateError",
    "build_approval_packet",
    "build_archive_plan",
    "collect_archive_packet",
    "execute_archive",
    "reconcile_live_provider",
]
