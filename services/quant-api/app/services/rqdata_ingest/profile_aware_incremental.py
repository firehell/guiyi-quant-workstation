from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import PROJECT_ROOT
from app.models.data_center import DataProfile, MarketDataFile
from app.services.data_profile_registry import DataProfileRegistry
from app.services.profile_active_switch import rollback_profile_active_binding, switch_profile_active_binding
from app.services.profile_binding_candidate_generator import DEFAULT_PROFILE_IDS, load_products_file
from app.services.profile_binding_validator import ProfileBindingValidationError
from app.services.rqdata_ingest.dominant_v2_incremental import IncrementalTailResult, append_dominant_v2_tail
from app.services.trading_session_clock import TradingSessionClock


DEFAULT_CLOSURE_DIR = PROJECT_ROOT / "data" / "reports" / "profile_incremental_closure_latest"
DEFAULT_PERIODS = ("1m", "1d", "1w")
DOMINANT_CONTRACT_ROLE = "dominant_main"


@dataclass(frozen=True)
class IncrementalSwitchTarget:
    profile_id: str
    instrument_symbol: str
    contract_code: str
    period: str
    data_version: str
    market_data_file_id: int
    contract_role: str = DOMINANT_CONTRACT_ROLE


def run_profile_aware_incremental_closure(
    *,
    session: Session,
    client: Any | None,
    output_root: Path,
    products: list[str],
    periods: tuple[str, ...] = DEFAULT_PERIODS,
    target_end: date,
    profile_ids: list[str] | None = None,
    exchange: str = "DCE",
    dry_run: bool = True,
    commit: bool = False,
    batch_id: str | None = None,
    output_dir: Path = DEFAULT_CLOSURE_DIR,
    now: datetime | None = None,
    allow_quality_failed: bool = False,
) -> dict[str, Any]:
    """Build candidate parquet versions, validate profile bindings, then switch atomically.

    The DB registration and profile active switch share one session transaction. If any
    requested product/period fails, the transaction is rolled back and active bindings
    remain unchanged. Parquet writes are intentionally retained as orphan candidates
    for inspection/recovery.
    """

    if allow_quality_failed:
        raise ValueError("profile-aware incremental closure must not downgrade failed quality to warning")
    normalized_products = [item.strip().lower() for item in products if item.strip()]
    normalized_periods = tuple(item.strip().lower() for item in periods if item.strip())
    run_batch_id = batch_id or _default_batch_id(target_end)
    clock = TradingSessionClock(session)

    period_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    orphan_candidates: list[dict[str, Any]] = []
    switch_targets: list[IncrementalSwitchTarget] = []

    try:
        for product in normalized_products:
            for period in normalized_periods:
                gate = _weekly_confirmation_gate(clock, target_end=target_end, period=period, exchange=exchange, product=product, now=now)
                if gate["status"] != "passed":
                    failures.append({"product": product, "period": period, **gate})
                    period_results.append({"product": product, "period": period, **gate})
                    continue

                result = append_dominant_v2_tail(
                    client=client,
                    output_root=output_root,
                    product=product,
                    exchange=exchange,
                    period=period,
                    target_end=target_end,
                    dry_run=dry_run,
                    register=not dry_run,
                    allow_quality_failed=False,
                    session=session if not dry_run else None,
                )
                result_payload = _result_payload(result)
                period_results.append(result_payload)
                if result.output_path:
                    orphan_candidates.append(
                        {
                            "product": product,
                            "period": period,
                            "standard_path": result.output_path,
                            "summary_path": result.summary_path or "",
                            "status": result.status,
                        }
                    )
                if result.status == "failed":
                    failures.append(result_payload)
                    continue
                if result.status != "updated" or result.registered is None:
                    continue
                switch_targets.extend(
                    _switch_targets_for_result(
                        session=session,
                        product=product,
                        period=period,
                        registered=result.registered,
                        profile_ids=profile_ids or list(DEFAULT_PROFILE_IDS),
                        project_root=output_root.parent if output_root.name == "data" else PROJECT_ROOT,
                    )
                )

        if dry_run:
            payload = _base_payload(
                batch_id=run_batch_id,
                mode="dry-run",
                target_end=target_end,
                products=normalized_products,
                periods=normalized_periods,
                period_results=period_results,
                failures=failures,
                switch_targets=switch_targets,
                committed=False,
            )
            _write_json(output_dir / f"{run_batch_id}_dry_run.json", payload)
            return payload

        if failures:
            session.rollback()
            payload = _base_payload(
                batch_id=run_batch_id,
                mode="apply",
                target_end=target_end,
                products=normalized_products,
                periods=normalized_periods,
                period_results=period_results,
                failures=failures,
                switch_targets=switch_targets,
                committed=False,
            )
            payload["status"] = "failed"
            payload["orphan_candidates"] = orphan_candidates
            _write_failure_ledger(output_dir, run_batch_id, payload)
            return payload

        switch_rows: list[dict[str, Any]] = []
        for target in switch_targets:
            try:
                dry_switch = switch_profile_active_binding(
                    session,
                    profile_id=target.profile_id,
                    instrument_symbol=target.instrument_symbol,
                    contract_code=target.contract_code,
                    period=target.period,
                    data_version=target.data_version,
                    market_data_file_id=target.market_data_file_id,
                    contract_role=target.contract_role,
                    dry_run=True,
                    commit=False,
                    project_root=PROJECT_ROOT,
                )
                if dry_switch.get("status") == "unchanged":
                    switch_rows.append({**asdict(target), "status": "unchanged", "binding_id": dry_switch.get("binding_id")})
                    continue
                applied = switch_profile_active_binding(
                    session,
                    profile_id=target.profile_id,
                    instrument_symbol=target.instrument_symbol,
                    contract_code=target.contract_code,
                    period=target.period,
                    data_version=target.data_version,
                    market_data_file_id=target.market_data_file_id,
                    contract_role=target.contract_role,
                    dry_run=False,
                    commit=False,
                    project_root=PROJECT_ROOT,
                )
                switch_rows.append(
                    {
                        **asdict(target),
                        "status": applied.get("status") or "switched",
                        "binding_id": applied.get("binding_id"),
                        "previous_market_data_file_id": applied.get("previous_market_data_file_id"),
                        "previous_data_version": applied.get("previous_data_version"),
                    }
                )
            except (ProfileBindingValidationError, ValueError) as exc:
                failures.append({**asdict(target), "status": "failed", "error": str(exc)})

        if failures:
            session.rollback()
            payload = _base_payload(
                batch_id=run_batch_id,
                mode="apply",
                target_end=target_end,
                products=normalized_products,
                periods=normalized_periods,
                period_results=period_results,
                failures=failures,
                switch_targets=switch_targets,
                committed=False,
            )
            payload["status"] = "failed"
            payload["switch_rows"] = switch_rows
            payload["orphan_candidates"] = orphan_candidates
            _write_failure_ledger(output_dir, run_batch_id, payload)
            return payload

        if commit:
            session.commit()
        else:
            session.rollback()

        payload = _base_payload(
            batch_id=run_batch_id,
            mode="apply",
            target_end=target_end,
            products=normalized_products,
            periods=normalized_periods,
            period_results=period_results,
            failures=[],
            switch_targets=switch_targets,
            committed=commit,
        )
        payload["status"] = "success"
        payload["switch_rows"] = switch_rows
        _write_success_ledger(output_dir, run_batch_id, switch_rows, committed=commit)
        _write_json(output_dir / f"{run_batch_id}_result.json", payload)
        return payload
    except Exception:
        session.rollback()
        raise


def rollback_profile_aware_incremental_closure(
    *,
    session: Session,
    output_dir: Path,
    batch_id: str,
    dry_run: bool = True,
    commit: bool = False,
) -> dict[str, Any]:
    rows = [row for row in _read_csv(output_dir / "success_ledger.csv") if row.get("batch_id") == batch_id]
    rollback_rows: list[dict[str, Any]] = []
    errors = 0
    rolled_back = 0
    for row in reversed(rows):
        try:
            result = rollback_profile_active_binding(
                session,
                profile_id=str(row.get("profile_id") or ""),
                binding_id=_parse_int(row.get("binding_id")),
                instrument_symbol=str(row.get("instrument_symbol") or "") or None,
                contract_code=str(row.get("contract_code") or "") or None,
                period=str(row.get("period") or "") or None,
                dry_run=dry_run,
                commit=False,
            )
            if result.get("status") in {"rolled_back", "ready"}:
                rolled_back += 1
            rollback_rows.append({"batch_id": batch_id, **row, **result})
        except ValueError as exc:
            errors += 1
            rollback_rows.append({"batch_id": batch_id, **row, "status": "failed", "error": str(exc)})
    if commit and errors == 0 and not dry_run:
        session.commit()
    else:
        session.rollback()
    _append_csv(output_dir / "rollback_ledger.csv", rollback_rows)
    return {
        "batch_id": batch_id,
        "status": "rolled_back" if commit and errors == 0 and not dry_run else "dry_run",
        "candidate_count": len(rows),
        "rolled_back": rolled_back,
        "errors": errors,
        "committed": commit and errors == 0 and not dry_run,
        "rollback_ledger": str(output_dir / "rollback_ledger.csv"),
    }


def audit_profile_incremental_orphans(*, session: Session, output_dir: Path, batch_id: str) -> dict[str, Any]:
    failure_path = output_dir / f"{batch_id}_failure.json"
    if not failure_path.exists():
        return {"batch_id": batch_id, "status": "no_failure_ledger", "orphans": []}
    payload = json.loads(failure_path.read_text(encoding="utf-8"))
    orphans: list[dict[str, Any]] = []
    for row in payload.get("orphan_candidates") or []:
        path = str(row.get("standard_path") or "")
        if not path:
            continue
        registered = session.scalar(select(MarketDataFile).where(MarketDataFile.file_path == path))
        physical_exists = Path(path).exists()
        if registered is None and physical_exists:
            orphans.append({**row, "recovery_action": "safe_retry_or_manual_archive", "registered": False})
    report = {"batch_id": batch_id, "status": "passed" if not orphans else "orphans_found", "orphans": orphans}
    _write_json(output_dir / f"{batch_id}_orphan_report.json", report)
    return report


def _switch_targets_for_result(
    *,
    session: Session,
    product: str,
    period: str,
    registered: dict[str, Any],
    profile_ids: list[str],
    project_root: Path,
) -> list[IncrementalSwitchTarget]:
    period_payload = (registered.get("periods") or {}).get(period) or {}
    file_id = _parse_int(period_payload.get("market_data_file_id"))
    data_version = str(period_payload.get("data_version") or "")
    if file_id is None or not data_version:
        return []
    contract_code = str(registered.get("contract") or f"{product}.MAIN")
    registry = DataProfileRegistry(session, project_root=PROJECT_ROOT)
    targets: list[IncrementalSwitchTarget] = []
    for profile in session.scalars(select(DataProfile).where(DataProfile.profile_id.in_(profile_ids), DataProfile.is_active.is_(True))):
        if not _profile_accepts_target(registry, profile, product=product, period=period):
            continue
        targets.append(
            IncrementalSwitchTarget(
                profile_id=profile.profile_id,
                instrument_symbol=product,
                contract_code=contract_code,
                period=period,
                data_version=data_version,
                market_data_file_id=file_id,
            )
        )
    return targets


def _profile_accepts_target(registry: DataProfileRegistry, profile: DataProfile, *, product: str, period: str) -> bool:
    if DOMINANT_CONTRACT_ROLE not in list(profile.contract_roles or []):
        return False
    if period not in list(profile.periods or []):
        return False
    config = registry.load_profile_config(profile.profile_id)
    binding_scope = config.get("binding_scope") or {}
    explicit_products = {str(item).strip().lower() for item in binding_scope.get("products") or []}
    if explicit_products and product not in explicit_products:
        return False
    products_file = binding_scope.get("products_file")
    if products_file:
        file_path = Path(str(products_file))
        if not file_path.is_absolute():
            file_path = PROJECT_ROOT / file_path
        if file_path.exists() and product not in load_products_file(file_path):
            return False
    return True


def _weekly_confirmation_gate(
    clock: TradingSessionClock,
    *,
    target_end: date,
    period: str,
    exchange: str,
    product: str,
    now: datetime | None,
) -> dict[str, Any]:
    if period != "1w":
        return {"status": "passed"}
    week_days, complete = clock.week_trading_days(target_end, exchange=exchange)
    if not complete:
        return {"status": "blocked", "reason": "weekly_calendar_incomplete", "week_trading_days": [item.isoformat() for item in week_days]}
    if not week_days:
        return {"status": "blocked", "reason": "weekly_has_no_trading_day", "week_trading_days": []}
    last_trading_day = week_days[-1]
    if target_end != last_trading_day:
        return {
            "status": "blocked",
            "reason": "weekly_not_last_actual_trading_day",
            "last_actual_trading_day": last_trading_day.isoformat(),
            "week_trading_days": [item.isoformat() for item in week_days],
        }
    if now is not None and now.date() <= target_end and not clock.trading_day_closed(target_end, product=product, exchange=exchange, now=now):
        return {"status": "blocked", "reason": "weekly_last_trading_day_not_closed", "last_actual_trading_day": last_trading_day.isoformat()}
    return {"status": "passed", "last_actual_trading_day": last_trading_day.isoformat()}


def _base_payload(
    *,
    batch_id: str,
    mode: str,
    target_end: date,
    products: list[str],
    periods: tuple[str, ...],
    period_results: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    switch_targets: list[IncrementalSwitchTarget],
    committed: bool,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "mode": mode,
        "status": "blocked" if failures else "ready",
        "target_end": target_end.isoformat(),
        "products": products,
        "periods": list(periods),
        "period_results": period_results,
        "failure_count": len(failures),
        "failures": failures,
        "switch_target_count": len(switch_targets),
        "switch_targets": [asdict(item) for item in switch_targets],
        "committed": committed,
        "writes_database": False if mode == "dry-run" else committed,
    }


def _result_payload(result: IncrementalTailResult) -> dict[str, Any]:
    payload = asdict(result)
    if result.registered is not None:
        payload["registered"] = result.registered
    return payload


def _default_batch_id(target_end: date) -> str:
    return f"profile_incremental_{target_end:%Y%m%d}_{datetime.now(UTC):%H%M%S}"


def _write_success_ledger(output_dir: Path, batch_id: str, rows: list[dict[str, Any]], *, committed: bool) -> None:
    enriched = [{**row, "batch_id": batch_id, "committed": committed, "applied_at": datetime.now(UTC).isoformat()} for row in rows]
    _append_csv(output_dir / "success_ledger.csv", enriched)


def _write_failure_ledger(output_dir: Path, batch_id: str, payload: dict[str, Any]) -> None:
    _write_json(output_dir / f"{batch_id}_failure.json", payload)
    rows = [{**row, "batch_id": batch_id} for row in payload.get("failures", [])]
    _append_csv(output_dir / "failure_ledger.csv", rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    existing = _read_csv(path)
    merged = existing + rows
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in merged:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

