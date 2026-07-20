from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    DataQualityReport,
    FeeMarginRule,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
    TradingCalendar,
    TradingSession,
    utc_now,
)
from app.services.profile_active_switch import switch_profile_active_binding
from app.services.rqdata_ingest.actual_contract_bars_pilot import _evaluate_actual_contract_bar_quality
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars
from app.services.rqdata_ingest.bar_sample import (
    _ensure_reference_rows,
    _record_canonical_file_and_quality,
    _record_raw_file,
    _start_task,
    normalize_bar_frame,
)
from app.services.rqdata_ingest.dominant_v2_incremental import merge_dominant_frames
from app.services.rqdata_ingest.dominant_v2_parquet import _download_dominant_raw, _filter_by_datetime
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality, normalize_jm_dominant_raw_frame
from app.services.rqdata_ingest.jm_historical_catchup import (
    CatchupPlan,
    build_approval_packet,
    build_profile_binding_plan,
    build_rqdata_request_plan,
    canonical_packet_hash,
    verify_approval_packet,
)
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic


PRODUCT = "jm"
CONTINUOUS_CONTRACT = "jm.MAIN"
PROVIDER = "rqdata"
RULE = "volume_open_interest"
CONTINUOUS_DIRECT_PERIODS = ("1m", "1d", "1w")
CONTINUOUS_DERIVED_PERIODS = ("5m", "15m", "30m", "60m", "1d")
ACTUAL_DIRECT_PERIODS = ("1m", "1d")
ACTUAL_DERIVED_PERIODS = ("5m", "15m", "30m", "60m")
DIRECT_LOOKBACK_DAYS = {"1m": 2, "1d": 5, "1w": 14}


class S603ExecutionError(RuntimeError):
    """Raised when a real S6-03 precondition or execution gate fails."""


def collect_provider_reference_snapshot(
    client: Any,
    *,
    calendar_start: date,
    calendar_end: date,
    mapping_start: date,
    target: date,
) -> dict[str, Any]:
    trading_days = set(client.trading_dates(calendar_start, calendar_end))
    if target not in trading_days:
        raise S603ExecutionError("provider_target_not_trading_day")
    calendar = []
    current = calendar_start
    while current <= calendar_end:
        calendar.append({"trade_date": current.isoformat(), "is_trading_day": current in trading_days})
        current += timedelta(days=1)

    mapping_frame = client.dominant_contracts(PRODUCT, mapping_start, target, 1)
    mapping = _mapping_records(mapping_frame)
    target_mapping = next((row for row in mapping if row["trade_date"] == target.isoformat()), None)
    if target_mapping is None:
        raise S603ExecutionError("provider_rank1_mapping_target_missing")
    actual_contract = str(target_mapping["contract_code"]).upper()
    if not actual_contract.startswith("JM") or actual_contract.endswith(".MAIN"):
        raise S603ExecutionError("provider_rank1_mapping_not_jm_actual")

    parameter_frame = client.trading_parameters(actual_contract, mapping_start, target)
    price_tick = client.price_tick(actual_contract)
    multiplier = client.contract_multiplier(actual_contract)
    parameters = _parameter_records(
        parameter_frame,
        contract=actual_contract,
        price_tick=price_tick,
        multiplier=multiplier,
    )
    if not any(row["trade_date"] == target.isoformat() for row in parameters):
        raise S603ExecutionError("provider_trading_parameter_target_missing")
    return {
        "provider": PROVIDER,
        "product": PRODUCT,
        "provider_final_day": target.isoformat(),
        "actual_contract": actual_contract,
        "calendar_start": calendar_start.isoformat(),
        "calendar_end": calendar_end.isoformat(),
        "mapping_start": mapping_start.isoformat(),
        "calendar": calendar,
        "rank1_mapping": mapping,
        "trading_parameters": parameters,
    }


def build_execution_artifact_plan(
    *,
    output_root: Path,
    batch_id: str,
    target: date,
    continuous_start: date,
    actual_contract: str,
    actual_start: date,
    continuous_gap_start: date | None = None,
    actual_gap_start: date | None = None,
    weekly_target: date | None = None,
) -> dict[str, Any]:
    root = output_root.resolve(strict=False)
    batch = _safe_slug(batch_id)
    actual = actual_contract.strip().upper()
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise S603ExecutionError("jm_actual_contract_required")
    continuous_gap = continuous_gap_start or actual_gap_start or actual_start
    actual_gap = actual_gap_start or actual_start
    rows: list[dict[str, Any]] = []
    for contract, periods, start in (
        (CONTINUOUS_CONTRACT, CONTINUOUS_DIRECT_PERIODS, continuous_start),
        (actual, ACTUAL_DIRECT_PERIODS, actual_start),
    ):
        for period in periods:
            gap_start = continuous_gap if contract == CONTINUOUS_CONTRACT else actual_gap
            request_start = gap_start - timedelta(days=DIRECT_LOOKBACK_DAYS[period])
            item_end = weekly_target if contract == CONTINUOUS_CONTRACT and period == "1w" and weekly_target else target
            raw_path = (
                root
                / "raw"
                / "rqdata"
                / "jm_historical_catchup"
                / f"batch={batch}"
                / ("continuous" if contract == CONTINUOUS_CONTRACT else "actual")
                / f"{contract.replace('.', '_')}_{period}_raw.parquet"
            )
            rows.append(
                _artifact_row(
                    root=root,
                    batch=batch,
                    contract=contract,
                    period=period,
                    source_role="direct",
                    output_start=start,
                    request_start=request_start,
                    end=item_end,
                    raw_path=raw_path,
                )
            )
    for contract, periods, start in (
        (CONTINUOUS_CONTRACT, CONTINUOUS_DERIVED_PERIODS, continuous_start),
        (actual, ACTUAL_DERIVED_PERIODS, actual_start),
    ):
        for period in periods:
            rows.append(
                _artifact_row(
                    root=root,
                    batch=batch,
                    contract=contract,
                    period=period,
                    source_role="derived_from_1m",
                    output_start=start,
                    request_start=None,
                    end=target,
                    raw_path=None,
                )
            )
    return {
        "product": PRODUCT,
        "batch_id": batch,
        "target": target.isoformat(),
        "bars": sorted(rows, key=lambda row: (row["contract"], row["period"], row["source_role"])),
        "manifest_path": str(root / "manifests" / f"jm_historical_catchup_{batch}.csv"),
        "audit_root": str(root / "reports" / "jm_historical_catchup_s6_03" / batch),
    }


def expected_execution_paths(
    *,
    output_root: Path,
    batch_id: str,
    target: date,
    continuous_start: date,
    actual_contract: str,
    actual_start: date,
    weekly_target: date | None = None,
) -> dict[str, Any]:
    root = output_root.resolve(strict=False)
    batch = _safe_slug(batch_id)
    actual = actual_contract.strip().upper()
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise S603ExecutionError("jm_actual_contract_required")

    files: list[Path] = []
    reference_root = root / "raw" / "rqdata" / "jm_historical_catchup" / f"batch={batch}" / "reference"
    files.extend(reference_root / name for name in ("calendar.parquet", "rank1_mapping.parquet", "trading_parameters.parquet"))

    for period in CONTINUOUS_DIRECT_PERIODS:
        item_end = weekly_target if period == "1w" and weekly_target else target
        files.append(
            root
            / "raw"
            / "rqdata"
            / "jm_historical_catchup"
            / f"batch={batch}"
            / "continuous"
            / f"jm_MAIN_{period}_raw.parquet"
        )
        files.append(
            _canonical_path(
                root,
                batch=batch,
                contract=CONTINUOUS_CONTRACT,
                period=period,
                start=continuous_start,
                end=item_end,
                role="direct",
            )
        )
    for period in CONTINUOUS_DERIVED_PERIODS:
        files.append(
            _canonical_path(
                root,
                batch=batch,
                contract=CONTINUOUS_CONTRACT,
                period=period,
                start=continuous_start,
                end=target,
                role="derived_from_1m",
            )
        )

    for period in ACTUAL_DIRECT_PERIODS:
        files.append(
            root
            / "raw"
            / "rqdata"
            / "jm_historical_catchup"
            / f"batch={batch}"
            / "actual"
            / f"{actual}_{period}_raw.parquet"
        )
        files.append(
            _canonical_path(
                root,
                batch=batch,
                contract=actual,
                period=period,
                start=actual_start,
                end=target,
                role="direct",
            )
        )
    for period in ACTUAL_DERIVED_PERIODS:
        files.append(
            _canonical_path(
                root,
                batch=batch,
                contract=actual,
                period=period,
                start=actual_start,
                end=target,
                role="derived_from_1m",
            )
        )

    files.extend(
        (
            root / "manifests" / f"jm_historical_catchup_{batch}.csv",
            root / "reports" / "jm_historical_catchup_s6_03" / batch / "quality_gate.json",
            root / "reports" / "jm_historical_catchup_s6_03" / batch / "final_audit.json",
            root / "reports" / "jm_historical_catchup_s6_03" / batch / "completion_receipt.json",
        )
    )
    return {
        "product": PRODUCT,
        "batch_id": batch,
        "target": target.isoformat(),
        "continuous_start": continuous_start.isoformat(),
        "actual_contract": actual,
        "actual_start": actual_start.isoformat(),
        "files": [str(path) for path in files],
    }


def validate_execution_paths_create_only(paths: Mapping[str, Any]) -> None:
    if paths.get("product") != PRODUCT:
        raise S603ExecutionError("jm_only")
    collisions = sorted(str(path) for path in _paths(paths) if path.exists())
    if collisions:
        raise S603ExecutionError(f"output_already_exists:{','.join(collisions)}")


def apply_reference_snapshot(
    session: Session,
    *,
    snapshot: Mapping[str, Any],
    batch_id: str,
    target: date,
) -> dict[str, Any]:
    version = f"{_safe_slug(batch_id)}_reference_v1"
    calendar_rows = list(snapshot.get("calendar") or [])
    mapping_rows = list(snapshot.get("rank1_mapping") or [])
    parameter_rows = list(snapshot.get("trading_parameters") or [])
    calendar_dates = [_day(row["trade_date"]) for row in calendar_rows]
    target_mapping = next((row for row in mapping_rows if _day(row["trade_date"]) == target), None)
    target_parameter = next((row for row in parameter_rows if _day(row["trade_date"]) == target), None)
    if not calendar_dates or max(calendar_dates) < target:
        raise S603ExecutionError("trading_calendar_target_missing")
    if target_mapping is None:
        raise S603ExecutionError("rank1_mapping_target_missing")
    if target_parameter is None:
        raise S603ExecutionError("trading_parameter_target_missing")
    contract = str(target_mapping["contract_code"]).strip().upper()
    if contract != str(target_parameter["contract_code"]).strip().upper():
        raise S603ExecutionError("reference_actual_contract_mismatch")
    if not contract.startswith("JM") or contract.endswith(".MAIN"):
        raise S603ExecutionError("rank1_mapping_not_jm_actual")
    if not session.scalar(
        select(TradingSession.id).where(
            TradingSession.instrument_symbol == PRODUCT,
            TradingSession.is_active.is_(True),
        )
    ):
        raise S603ExecutionError("jm_trading_session_missing")

    for row in calendar_rows:
        trade_date = _day(row["trade_date"])
        existing = session.scalar(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code == "DCE",
                TradingCalendar.trade_date == trade_date,
            )
        )
        values = {
            "is_trading_day": bool(row["is_trading_day"]),
            "has_night_session": bool(
                row.get(
                    "has_night_session",
                    existing.has_night_session if existing is not None else True,
                )
            ),
            "provider": PROVIDER,
            "remark": f"JM S6-03 reference refresh {version}",
        }
        if existing is None:
            session.add(TradingCalendar(exchange_code="DCE", trade_date=trade_date, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)

    for row in mapping_rows:
        trade_date = _day(row["trade_date"])
        row_contract = str(row["contract_code"]).strip().upper()
        existing = session.scalar(
            select(MainContractMap).where(
                MainContractMap.instrument_symbol == PRODUCT,
                MainContractMap.trade_date == trade_date,
                MainContractMap.rank == 1,
                MainContractMap.rule == RULE,
                MainContractMap.provider == PROVIDER,
                MainContractMap.data_version == version,
            )
        )
        if existing is None:
            session.add(
                MainContractMap(
                    instrument_symbol=PRODUCT,
                    trade_date=trade_date,
                    rank=1,
                    contract_code=row_contract,
                    rule=RULE,
                    provider=PROVIDER,
                    data_version=version,
                    raw_payload=dict(row),
                )
            )
        elif existing.contract_code != row_contract:
            raise S603ExecutionError(f"reference_mapping_version_conflict:{trade_date.isoformat()}")

    for row in parameter_rows:
        trade_date = _day(row["trade_date"])
        row_contract = str(row["contract_code"]).strip().upper()
        existing = session.scalar(
            select(FuturesTradingParameter).where(
                FuturesTradingParameter.contract_code == row_contract,
                FuturesTradingParameter.trade_date == trade_date,
                FuturesTradingParameter.provider == PROVIDER,
                FuturesTradingParameter.data_version == version,
            )
        )
        values = _parameter_values(row)
        if existing is None:
            session.add(
                FuturesTradingParameter(
                    contract_code=row_contract,
                    trade_date=trade_date,
                    provider=PROVIDER,
                    data_version=version,
                    raw_payload=dict(row),
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        fee = session.scalar(
            select(FeeMarginRule).where(
                FeeMarginRule.provider == PROVIDER,
                FeeMarginRule.contract_code == row_contract,
                FeeMarginRule.effective_date == trade_date,
                FeeMarginRule.source == version,
            )
        )
        if fee is None:
            session.add(
                FeeMarginRule(
                    provider=PROVIDER,
                    exchange_code=str(row.get("exchange_code") or "DCE"),
                    instrument_symbol=PRODUCT,
                    contract_code=row_contract,
                    price_tick=values["price_tick"],
                    volume_multiple=values["contract_multiplier"],
                    margin_rate=values["short_margin_ratio"] or values["long_margin_ratio"],
                    open_fee=values["open_commission"],
                    close_fee=values["close_commission"],
                    close_today_fee=values["close_today_commission"],
                    fee_type=str(row.get("commission_type") or "") or None,
                    effective_date=trade_date,
                    source=version,
                )
            )
    session.flush()
    return {
        "status": "passed",
        "data_version": version,
        "actual_contract": contract,
        "latest_calendar_date": max(calendar_dates).isoformat(),
        "latest_mapping_date": max(_day(row["trade_date"]) for row in mapping_rows).isoformat(),
        "latest_parameter_date": max(_day(row["trade_date"]) for row in parameter_rows).isoformat(),
        "calendar_rows": len(calendar_rows),
        "mapping_rows": len(mapping_rows),
        "parameter_rows": len(parameter_rows),
    }


def materialize_execution_assets(
    *,
    session: Session,
    client: Any,
    plan: Mapping[str, Any],
    reference_snapshot: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    root = output_root.resolve(strict=False)
    batch = str(plan["batch_id"])
    target = _day(plan["target"])
    bars = list(plan.get("bars") or [])
    if not bars or any(row.get("product") != PRODUCT for row in bars):
        raise S603ExecutionError("jm_only_artifact_plan_required")
    planned_paths = {
        "product": PRODUCT,
        "files": [
            *[str(row["canonical_path"]) for row in bars],
            *[str(row["raw_path"]) for row in bars if row.get("raw_path")],
            *_reference_path_values(root, batch),
            str(plan["manifest_path"]),
            str(Path(str(plan["audit_root"])) / "quality_gate.json"),
            str(Path(str(plan["audit_root"])) / "final_audit.json"),
            str(Path(str(plan["audit_root"])) / "completion_receipt.json"),
        ],
    }
    validate_execution_paths_create_only(planned_paths)
    _write_reference_raw(root=root, batch=batch, snapshot=reference_snapshot)

    row_by_key = {
        (str(row["contract"]), str(row["period"]), str(row["source_role"])): row
        for row in bars
    }
    materialized: list[dict[str, Any]] = []
    continuous_frames: dict[str, pd.DataFrame] = {}
    for period in CONTINUOUS_DIRECT_PERIODS:
        row = row_by_key.get((CONTINUOUS_CONTRACT, period, "direct"))
        if row is None:
            continue
        baseline = _load_active_continuous_baseline(session, output_root=root, period=period)
        item_end = _day(row["end"])
        raw = _download_dominant_raw(
            client=client,
            product=PRODUCT,
            exchange="DCE",
            period=period,
            start_date=_day(row["request_start"]),
            end_date=item_end,
        )
        normalized = normalize_jm_dominant_raw_frame(
            raw,
            symbol=PRODUCT,
            exchange="DCE",
            interval=period,
            data_version=str(row["data_version"]),
        )
        normalized = _filter_by_datetime(normalized, start_date=_day(row["request_start"]), end_date=item_end)
        merged = merge_dominant_frames(baseline, normalized)
        merged = _filter_by_datetime(merged, start_date=_day(row["output_start"]), end_date=item_end)
        merged["data_version"] = str(row["data_version"])
        quality = evaluate_standard_dominant_quality(merged, period)
        _require_passed_quality(quality.status, contract=CONTINUOUS_CONTRACT, period=period)
        merged["quality_status"] = quality.status
        write_parquet_atomic(raw, Path(str(row["raw_path"])))
        write_parquet_atomic(merged, Path(str(row["canonical_path"])))
        continuous_frames[period] = merged
        materialized.append(_materialized_row(row, frame=merged, raw_frame=raw, quality=quality))

    for period in CONTINUOUS_DERIVED_PERIODS:
        row = row_by_key.get((CONTINUOUS_CONTRACT, period, "derived_from_1m"))
        if row is None:
            continue
        one_minute = continuous_frames.get("1m")
        if one_minute is None:
            raise S603ExecutionError("continuous_1m_source_missing")
        frame = aggregate_standard_bars(one_minute, period, source_period="1m")
        frame["data_version"] = str(row["data_version"])
        quality = evaluate_standard_dominant_quality(frame, period)
        _require_passed_quality(quality.status, contract=CONTINUOUS_CONTRACT, period=period)
        frame["quality_status"] = quality.status
        write_parquet_atomic(frame, Path(str(row["canonical_path"])))
        materialized.append(_materialized_row(row, frame=frame, raw_frame=None, quality=quality))

    actual_contract = str(reference_snapshot["actual_contract"]).upper()
    actual_direct: dict[str, pd.DataFrame] = {}
    for period in ACTUAL_DIRECT_PERIODS:
        row = row_by_key.get((actual_contract, period, "direct"))
        if row is None:
            continue
        baseline = _load_active_baseline(
            session,
            output_root=root,
            contract=actual_contract,
            period=period,
        )
        raw = client.contract_bars(actual_contract, _day(row["request_start"]), target, period)
        if raw.empty:
            raise S603ExecutionError(f"provider_actual_rows_missing:{actual_contract}:{period}")
        frame = normalize_bar_frame(
            raw,
            symbol=PRODUCT,
            contract=actual_contract,
            source_contract=actual_contract,
            exchange="DCE",
            frequency=period,
            data_version=str(row["data_version"]),
        )
        if period == "1m" and plan.get("expected_source_rows") is not None:
            source_days = pd.to_datetime(frame["trading_day"], errors="coerce").dt.date
            target_source = frame.loc[source_days == target]
            expected_rows = int(plan["expected_source_rows"])
            if len(target_source) != expected_rows:
                raise S603ExecutionError(
                    f"provider_actual_row_count_mismatch:{actual_contract}:{target.isoformat()}:"
                    f"{len(target_source)}!={expected_rows}"
                )
            expected_hash = str(plan.get("provider_final_1m_hash") or "")
            if expected_hash and stable_bar_frame_hash(target_source) != expected_hash:
                raise S603ExecutionError("provider_final_1m_hash_drift")
        frame = merge_dominant_frames(baseline, frame)
        frame = _filter_by_datetime(frame, start_date=_day(row["output_start"]), end_date=target)
        quality = _evaluate_actual_contract_bar_quality(frame, period)
        _require_passed_quality(quality.status, contract=actual_contract, period=period)
        frame["quality_status"] = quality.status
        write_parquet_atomic(raw, Path(str(row["raw_path"])))
        write_parquet_atomic(frame, Path(str(row["canonical_path"])))
        actual_direct[period] = frame
        materialized.append(_materialized_row(row, frame=frame, raw_frame=raw, quality=quality))

    actual_derived = sorted(
        (
            (period, row)
            for (contract, period, role), row in row_by_key.items()
            if contract == actual_contract and role == "derived_from_1m"
        ),
        key=lambda item: item[0],
    )
    for period, row in actual_derived:
        one_minute = actual_direct.get("1m")
        if one_minute is None:
            raise S603ExecutionError("actual_1m_source_missing")
        frame = aggregate_standard_bars(one_minute, period, source_period="1m")
        frame["data_version"] = str(row["data_version"])
        quality = _evaluate_actual_contract_bar_quality(frame, period)
        _require_passed_quality(quality.status, contract=actual_contract, period=period)
        frame["quality_status"] = quality.status
        write_parquet_atomic(frame, Path(str(row["canonical_path"])))
        materialized.append(_materialized_row(row, frame=frame, raw_frame=None, quality=quality))

    return {
        "status": "passed",
        "task_id": str(plan.get("task_id") or "JM-HISTORICAL-CATCHUP-S6-03"),
        "batch_id": batch,
        "target": target.isoformat(),
        "actual_contract": actual_contract,
        "assets": materialized,
        "reference_paths": _reference_path_values(root, batch),
    }


def register_execution_assets(
    *,
    session: Session,
    materialized: Mapping[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_version: dict[str, dict[str, Any]] = {}
    _ensure_reference_rows(session, symbol=PRODUCT, contract=CONTINUOUS_CONTRACT, exchange="DCE")
    _ensure_reference_rows(session, symbol=PRODUCT, contract=str(materialized["actual_contract"]), exchange="DCE")
    for item in materialized.get("assets") or []:
        frame = pd.read_parquet(item["canonical_path"])
        quality = (
            evaluate_standard_dominant_quality(frame, str(item["period"]))
            if item["contract"] == CONTINUOUS_CONTRACT
            else _evaluate_actual_contract_bar_quality(frame, str(item["period"]))
        )
        _require_passed_quality(quality.status, contract=str(item["contract"]), period=str(item["period"]))
        datetimes = pd.to_datetime(frame["datetime"], errors="raise")
        task = _start_task(
            session=session,
            symbol=PRODUCT,
            contract=str(item["contract"]),
            frequency=str(item["period"]),
            start_date=datetimes.min().date(),
            end_date=datetimes.max().date(),
        )
        if item.get("raw_path"):
            raw_frame = pd.read_parquet(item["raw_path"])
            _record_raw_file(
                session=session,
                task=task,
                path=Path(str(item["raw_path"])),
                symbol=PRODUCT,
                contract=str(item["contract"]),
                frequency=str(item["period"]),
                start_time=datetimes.min().to_pydatetime(),
                end_time=datetimes.max().to_pydatetime(),
                row_count=len(raw_frame),
                data_version=str(item["data_version"]),
            )
        market_file = _record_canonical_file_and_quality(
            session=session,
            task=task,
            path=Path(str(item["canonical_path"])),
            frame=frame,
            quality=quality,
            symbol=PRODUCT,
            contract=str(item["contract"]),
            frequency=str(item["period"]),
            data_version=str(item["data_version"]),
            data_role="primary",
        )
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task_id = str(materialized.get("task_id") or "JM-HISTORICAL-CATCHUP-S6-03")
        task.result = {
            "pipeline_task_id": task_id,
            "jm_historical_catchup_s6_03": task_id == "JM-HISTORICAL-CATCHUP-S6-03",
            "jm_after_market_archive_s6_06": task_id == "JM-AFTER-MARKET-ARCHIVE-S6-06",
            "batch_id": materialized["batch_id"],
            "source_role": item["source_role"],
            "canonical_path": item["canonical_path"],
            "checksum": item["checksum"],
        }
        session.flush()
        report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        if report is not None:
            report.details = {
                **(report.details or {}),
                "pipeline_task_id": task_id,
                "jm_historical_catchup_s6_03": task_id == "JM-HISTORICAL-CATCHUP-S6-03",
                "jm_after_market_archive_s6_06": task_id == "JM-AFTER-MARKET-ARCHIVE-S6-06",
                "batch_id": materialized["batch_id"],
                "source_role": item["source_role"],
                "checksum": item["checksum"],
            }
        row = {
            **{key: item[key] for key in ("contract", "period", "source_role", "data_version", "canonical_path", "raw_path", "row_count", "min_datetime", "max_datetime", "checksum")},
            "quality_status": "passed",
            "market_data_file_id": market_file.id,
            "data_quality_report_id": report.id if report else None,
        }
        rows.append(row)
        by_version[str(item["data_version"])] = row
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["contract", "period", "source_role"]).to_csv(manifest_path, index=False)
    return {"status": "passed", "rows": rows, "by_version": by_version, "manifest_path": str(manifest_path)}


def collect_active_binding_snapshot(session: Session) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(ProfileActiveBinding)
            .where(
                ProfileActiveBinding.instrument_symbol == PRODUCT,
                ProfileActiveBinding.binding_status == "active",
            )
            .order_by(
                ProfileActiveBinding.profile_id,
                ProfileActiveBinding.contract_code,
                ProfileActiveBinding.period,
                ProfileActiveBinding.id,
            )
        )
    )
    bindings = [
        {
            "id": row.id,
            "profile_id": row.profile_id,
            "instrument_symbol": row.instrument_symbol,
            "contract_code": row.contract_code,
            "contract_role": row.contract_role,
            "period": row.period,
            "data_version": row.data_version,
            "market_data_file_id": row.market_data_file_id,
        }
        for row in rows
    ]
    return {"product": PRODUCT, "bindings": bindings, "sha256": _stable_hash(bindings)}


def collect_database_state(session: Session, *, actual_contract: str) -> dict[str, Any]:
    actual = actual_contract.strip().upper()
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise S603ExecutionError("jm_actual_contract_required")
    binding_snapshot = collect_active_binding_snapshot(session)
    files = list(
        session.scalars(
            select(MarketDataFile)
            .where(
                MarketDataFile.provider == PROVIDER,
                MarketDataFile.instrument_symbol == PRODUCT,
                MarketDataFile.contract_code.in_((CONTINUOUS_CONTRACT, actual)),
                MarketDataFile.data_role == "primary",
                MarketDataFile.quality_status == "passed",
            )
            .order_by(MarketDataFile.contract_code, MarketDataFile.period, MarketDataFile.end_time.desc(), MarketDataFile.id)
        )
    )
    file_rows = [
        {
            "id": row.id,
            "contract": row.contract_code,
            "period": row.period,
            "start_time": row.start_time.isoformat(),
            "end_time": row.end_time.isoformat(),
            "data_version": row.data_version,
            "checksum": row.checksum,
            "file_path": row.file_path,
        }
        for row in files
    ]
    latest_calendar = session.scalar(select(TradingCalendar.trade_date).order_by(TradingCalendar.trade_date.desc()))
    latest_mapping = session.scalar(
        select(MainContractMap.trade_date)
        .where(
            MainContractMap.instrument_symbol == PRODUCT,
            MainContractMap.rank == 1,
            MainContractMap.provider == PROVIDER,
        )
        .order_by(MainContractMap.trade_date.desc())
    )
    latest_parameter = session.scalar(
        select(FuturesTradingParameter.trade_date)
        .where(
            FuturesTradingParameter.instrument_symbol == PRODUCT,
            FuturesTradingParameter.provider == PROVIDER,
        )
        .order_by(FuturesTradingParameter.trade_date.desc())
    )
    metadata = {
        "product": PRODUCT,
        "actual_contract": actual,
        "latest_calendar_date": latest_calendar.isoformat() if latest_calendar else None,
        "latest_rank1_mapping_date": latest_mapping.isoformat() if latest_mapping else None,
        "latest_trading_parameter_date": latest_parameter.isoformat() if latest_parameter else None,
        "active_binding_sha256": binding_snapshot["sha256"],
        "primary_files": file_rows,
    }
    return {
        "metadata": metadata,
        "metadata_sha256": _stable_hash(metadata),
        "binding_snapshot": binding_snapshot,
    }


def active_end_map(database_state: Mapping[str, Any]) -> dict[tuple[str, str, str], date]:
    latest: dict[tuple[str, str, str], date] = {}
    active_file_ids = {
        row["market_data_file_id"]
        for row in database_state["binding_snapshot"].get("bindings") or []
        if row.get("market_data_file_id") is not None
    }
    for row in database_state["metadata"].get("primary_files") or []:
        if row["id"] not in active_file_ids:
            continue
        contract = str(row["contract"])
        period = str(row["period"])
        roles = ("direct", "derived_from_1m") if period == "1d" and contract == CONTINUOUS_CONTRACT else (
            ("derived_from_1m",) if period in CONTINUOUS_DERIVED_PERIODS and period != "1d" else ("direct",)
        )
        end = pd.Timestamp(row["end_time"]).date()
        for role in roles:
            key = (contract, period, role)
            if key not in latest or end > latest[key]:
                latest[key] = end
    return latest


def active_baseline_start(session: Session, *, contract: str, periods: Iterable[str]) -> date:
    starts: list[date] = []
    for period in periods:
        statement = (
            select(MarketDataFile)
            .join(ProfileActiveBinding, ProfileActiveBinding.market_data_file_id == MarketDataFile.id)
            .where(
                ProfileActiveBinding.instrument_symbol == PRODUCT,
                ProfileActiveBinding.contract_code == contract,
                ProfileActiveBinding.period == period,
                ProfileActiveBinding.profile_id == _direct_profile_id(period),
                ProfileActiveBinding.binding_status == "active",
                MarketDataFile.provider == PROVIDER,
                MarketDataFile.data_role == "primary",
                MarketDataFile.quality_status == "passed",
            )
            .order_by(MarketDataFile.end_time.desc(), MarketDataFile.start_time.asc(), MarketDataFile.id.asc())
        )
        selected = session.scalar(statement)
        if selected is None:
            raise S603ExecutionError(f"active_baseline_missing:{contract}:{period}")
        starts.append(selected.start_time.date())
    return min(starts)


def apply_profile_binding_candidates(
    session: Session,
    *,
    artifact_plan: Mapping[str, Any],
    registration: Mapping[str, Any],
    expected_snapshot: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    current = collect_active_binding_snapshot(session)
    if current["sha256"] != expected_snapshot.get("sha256"):
        raise S603ExecutionError("active_binding_snapshot_drift")
    previous_by_identity = {
        (row["profile_id"], row["contract_code"], row["period"]): row
        for row in expected_snapshot.get("bindings") or []
    }
    registered = dict(registration.get("by_version") or {})
    results: list[dict[str, Any]] = []
    for candidate in build_profile_binding_plan(artifact_plan):
        target = registered.get(str(candidate["data_version"]))
        if target is None or target.get("quality_status") != "passed":
            raise S603ExecutionError(f"profile_candidate_not_registered:{candidate['data_version']}")
        identity = (candidate["profile_id"], candidate["contract"], candidate["period"])
        previous = previous_by_identity.get(identity)
        results.append(
            switch_profile_active_binding(
                session,
                profile_id=str(candidate["profile_id"]),
                instrument_symbol=PRODUCT,
                contract_code=str(candidate["contract"]),
                period=str(candidate["period"]),
                data_version=str(candidate["data_version"]),
                market_data_file_id=int(target["market_data_file_id"]),
                contract_role=str(candidate["contract_role"]),
                dry_run=False,
                commit=False,
                project_root=project_root,
                expected_previous_binding_id=previous.get("id") if previous else None,
                expected_previous_market_data_file_id=previous.get("market_data_file_id") if previous else None,
                expected_previous_data_version=str(previous.get("data_version") or "") if previous else "",
                enforce_expected_previous=True,
            )
        )
    return {"status": "passed", "count": len(results), "switches": results}


def build_execution_approval_packet(
    *,
    gap_plan: CatchupPlan,
    execution_plan: Mapping[str, Any],
    reference_snapshot: Mapping[str, Any],
    binding_snapshot: Mapping[str, Any],
    git_commit: str,
    git_branch: str,
    git_status_sha256: str,
    output_root: Path,
    output_root_identity: Mapping[str, Any],
    database_target: str,
    database_identity: Mapping[str, Any],
    metadata_snapshot_sha256: str,
    calendar_start: date,
    calendar_end: date,
) -> dict[str, Any]:
    if gap_plan.product != PRODUCT or execution_plan.get("product") != PRODUCT:
        raise S603ExecutionError("jm_only")
    paths = expected_execution_paths(
        output_root=output_root,
        batch_id=str(execution_plan["batch_id"]),
        target=_day(execution_plan["target"]),
        continuous_start=min(
            _day(row["output_start"])
            for row in execution_plan["bars"]
            if row["contract"] == CONTINUOUS_CONTRACT
        ),
        actual_contract=str(reference_snapshot["actual_contract"]),
        actual_start=min(
            _day(row["output_start"])
            for row in execution_plan["bars"]
            if row["contract"] != CONTINUOUS_CONTRACT
        ),
        weekly_target=_day(
            next(
                row["end"]
                for row in execution_plan["bars"]
                if row["contract"] == CONTINUOUS_CONTRACT and row["period"] == "1w"
            )
        ),
    )
    direct_count = sum(1 for row in execution_plan["bars"] if row["source_role"] == "direct")
    binding_candidates = build_profile_binding_plan(execution_plan)
    packet = build_approval_packet(
        git_commit=git_commit,
        git_branch=git_branch,
        git_status_sha256=git_status_sha256,
        output_root=output_root,
        output_root_identity=output_root_identity,
        database_target=database_target,
        database_identity=database_identity,
        binding_snapshot_sha256=str(binding_snapshot["sha256"]),
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        target=gap_plan.target,
        request_plan=build_rqdata_request_plan(
            gap_plan,
            calendar_start=calendar_start,
            calendar_end=calendar_end,
        ),
        expected_outputs=[Path(path) for path in paths["files"]],
        expected_versions=[str(row["data_version"]) for row in execution_plan["bars"]],
        expected_database_rows={
            "data_download_tasks": len(execution_plan["bars"]),
            "market_data_files": len(execution_plan["bars"]) + direct_count,
            "data_quality_reports": len(execution_plan["bars"]),
            "profile_binding_candidates": len(binding_candidates),
            "trading_calendar_upserts": len(reference_snapshot.get("calendar") or []),
            "rank1_mapping_candidates": len(reference_snapshot.get("rank1_mapping") or []),
            "trading_parameter_candidates": len(reference_snapshot.get("trading_parameters") or []),
        },
        rollback_plan={
            "existing_assets": "immutable",
            "active_binding": "database transaction rollback before commit; compare-and-switch blocks drift",
            "new_files": "remove only packet-listed paths after checksum verification",
            "new_database_rows": "single transaction rollback before commit",
            "failure_before_binding": "previous active binding remains unchanged",
        },
    )
    packet["execution_plan"] = dict(execution_plan)
    packet["reference_snapshot"] = dict(reference_snapshot)
    packet["binding_snapshot"] = dict(binding_snapshot)
    packet["bound_facts"]["reference_snapshot_sha256"] = _stable_hash(reference_snapshot)
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def execute_approved_catchup(
    *,
    session: Session,
    client: Any,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_facts: Mapping[str, Any],
    output_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    packet_hash = str(packet.get("packet_hash") or "")
    if not approval_hash or approval_hash != packet_hash:
        raise S603ExecutionError("approval_hash_mismatch")
    verify_approval_packet(packet, current_facts=current_facts)
    execution_plan = dict(packet.get("execution_plan") or {})
    reference_snapshot = dict(packet.get("reference_snapshot") or {})
    binding_snapshot = dict(packet.get("binding_snapshot") or {})
    if execution_plan.get("product") != PRODUCT or reference_snapshot.get("product") != PRODUCT:
        raise S603ExecutionError("jm_only")
    if str(output_root.resolve(strict=False)) != packet["bound_facts"]["output_root"]:
        raise S603ExecutionError("output_root_drift")

    quality_path = Path(str(execution_plan["audit_root"])) / "quality_gate.json"
    try:
        reference = apply_reference_snapshot(
            session,
            snapshot=reference_snapshot,
            batch_id=str(execution_plan["batch_id"]),
            target=_day(execution_plan["target"]),
        )
        materialized = materialize_execution_assets(
            session=session,
            client=client,
            plan=execution_plan,
            reference_snapshot=reference_snapshot,
            output_root=output_root,
        )
        registration = register_execution_assets(
            session=session,
            materialized=materialized,
            manifest_path=Path(str(execution_plan["manifest_path"])),
        )
        bindings = apply_profile_binding_candidates(
            session,
            artifact_plan=execution_plan,
            registration=registration,
            expected_snapshot=binding_snapshot,
            project_root=project_root,
        )
        quality_payload = {
            "status": "passed",
            "task_id": "JM-HISTORICAL-CATCHUP-S6-03",
            "packet_hash": packet_hash,
            "target": execution_plan["target"],
            "reference": reference,
            "assets": registration["rows"],
            "profile_switches": bindings["switches"],
        }
        _write_json_create_only(quality_path, quality_payload)
        session.commit()
    except Exception:
        session.rollback()
        if quality_path.is_file():
            quality_path.unlink()
        raise

    final_payload = {
        **quality_payload,
        "gates": [
            "JM_HISTORICAL_CATCHUP_READY",
            "JM_REFERENCE_METADATA_FRESH",
            "JM_LIVE_TARGET_FRESHNESS_READY",
        ],
        "database_committed": True,
    }
    _write_json_create_only(Path(str(execution_plan["audit_root"])) / "final_audit.json", final_payload)
    _write_json_create_only(
        Path(str(execution_plan["audit_root"])) / "completion_receipt.json",
        {
            "status": "completed",
            "task_id": "JM-HISTORICAL-CATCHUP-S6-03",
            "packet_hash": packet_hash,
            "target": execution_plan["target"],
            "manifest_path": registration["manifest_path"],
        },
    )
    return final_payload


def _reference_path_values(root: Path, batch: str) -> list[str]:
    reference_root = root / "raw" / "rqdata" / "jm_historical_catchup" / f"batch={batch}" / "reference"
    return [
        str(reference_root / name)
        for name in ("calendar.parquet", "rank1_mapping.parquet", "trading_parameters.parquet")
    ]


def _write_reference_raw(*, root: Path, batch: str, snapshot: Mapping[str, Any]) -> None:
    rows_by_path = (
        list(snapshot.get("calendar") or []),
        list(snapshot.get("rank1_mapping") or []),
        list(snapshot.get("trading_parameters") or []),
    )
    for path, rows in zip(_reference_path_values(root, batch), rows_by_path, strict=True):
        if not rows:
            raise S603ExecutionError(f"reference_rows_missing:{Path(path).stem}")
        write_parquet_atomic(pd.DataFrame(rows), Path(path))


def _load_active_continuous_baseline(session: Session, *, output_root: Path, period: str) -> pd.DataFrame:
    return _load_active_baseline(
        session,
        output_root=output_root,
        contract=CONTINUOUS_CONTRACT,
        period=period,
    )


def _load_active_baseline(
    session: Session,
    *,
    output_root: Path,
    contract: str,
    period: str,
) -> pd.DataFrame:
    statement = (
        select(MarketDataFile)
        .join(ProfileActiveBinding, ProfileActiveBinding.market_data_file_id == MarketDataFile.id)
        .where(
            ProfileActiveBinding.instrument_symbol == PRODUCT,
            ProfileActiveBinding.contract_code == contract,
            ProfileActiveBinding.period == period,
            ProfileActiveBinding.profile_id == _direct_profile_id(period),
            ProfileActiveBinding.binding_status == "active",
            MarketDataFile.provider == PROVIDER,
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
        )
        .order_by(MarketDataFile.end_time.desc(), MarketDataFile.start_time.asc(), MarketDataFile.id.asc())
    )
    candidates = list(session.scalars(statement).unique())
    if not candidates:
        raise S603ExecutionError(f"active_baseline_missing:{contract}:{period}")
    selected = candidates[0]
    raw_path = Path(selected.file_path)
    path = raw_path if raw_path.is_absolute() else output_root.parent / raw_path
    if not path.is_file():
        raise S603ExecutionError(f"active_baseline_file_missing:{contract}:{period}:{path}")
    frame = pd.read_parquet(path)
    if frame.empty:
        raise S603ExecutionError(f"active_baseline_empty:{contract}:{period}")
    return frame


def _require_passed_quality(status: str, *, contract: str, period: str) -> None:
    if status != "passed":
        raise S603ExecutionError(f"quality_not_passed:{contract}:{period}:{status}")


def _direct_profile_id(period: str) -> str:
    return "long_horizon_daily_v1" if period in {"1d", "1w"} else "intraday_research_v1"


def _materialized_row(
    row: Mapping[str, Any],
    *,
    frame: pd.DataFrame,
    raw_frame: pd.DataFrame | None,
    quality: Any,
) -> dict[str, Any]:
    datetimes = pd.to_datetime(frame["datetime"], errors="raise")
    canonical_path = Path(str(row["canonical_path"]))
    raw_path = Path(str(row["raw_path"])) if row.get("raw_path") else None
    return {
        **dict(row),
        "row_count": len(frame),
        "min_datetime": datetimes.min().isoformat(),
        "max_datetime": datetimes.max().isoformat(),
        "quality_status": str(quality.status),
        "quality_details": dict(quality.details),
        "checksum": sha256_file(canonical_path),
        "raw_row_count": len(raw_frame) if raw_frame is not None else None,
        "raw_checksum": sha256_file(raw_path) if raw_path is not None else None,
    }


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_bar_frame_hash(frame: pd.DataFrame) -> str:
    columns = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    normalized = frame.loc[:, columns].copy()
    normalized["datetime"] = pd.to_datetime(normalized["datetime"], errors="raise").map(lambda value: value.isoformat())
    for column in columns[1:]:
        normalized[column] = normalized[column].map(lambda value: "" if pd.isna(value) else str(value))
    rows = normalized.sort_values("datetime").to_dict("records")
    return _stable_hash(rows)


def _write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise S603ExecutionError(f"output_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise S603ExecutionError(f"temporary_output_already_exists:{temporary}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parameter_values(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "instrument_symbol": PRODUCT,
        "exchange_code": str(row.get("exchange_code") or "DCE"),
        "long_margin_ratio": _decimal(row.get("long_margin_ratio")),
        "short_margin_ratio": _decimal(row.get("short_margin_ratio")),
        "open_commission": _decimal(row.get("open_commission")),
        "close_commission": _decimal(row.get("close_commission")),
        "close_today_commission": _decimal(row.get("close_today_commission")),
        "commission_type": str(row.get("commission_type") or "") or None,
        "price_tick": _decimal(row.get("price_tick")),
        "contract_multiplier": int(row["contract_multiplier"]) if row.get("contract_multiplier") is not None else None,
        "min_order_quantity": int(row["min_order_quantity"]) if row.get("min_order_quantity") is not None else None,
        "max_order_quantity": int(row["max_order_quantity"]) if row.get("max_order_quantity") is not None else None,
    }


def _mapping_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        trade_value = next((raw.get(key) for key in ("date", "trade_date", "trading_date", "index") if raw.get(key) is not None), None)
        contract_value = next(
            (raw.get(key) for key in ("dominant", "contract", "order_book_id", "dominant_id") if raw.get(key)),
            None,
        )
        if trade_value is None or contract_value is None:
            continue
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_value).date().isoformat(),
                "contract_code": str(contract_value).upper(),
            }
        )
    return sorted(rows, key=lambda row: row["trade_date"])


def _parameter_records(
    frame: pd.DataFrame,
    *,
    contract: str,
    price_tick: Any,
    multiplier: Any,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict("records"):
        trade_value = next((raw.get(key) for key in ("trading_date", "trade_date", "date", "index") if not _missing(raw.get(key))), None)
        if trade_value is None:
            continue
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_value).date().isoformat(),
                "contract_code": contract,
                "exchange_code": "DCE",
                "price_tick": _clean_number(price_tick),
                "contract_multiplier": _clean_int(multiplier),
                "long_margin_ratio": _clean_number(raw.get("long_margin_ratio")),
                "short_margin_ratio": _clean_number(raw.get("short_margin_ratio")),
                "open_commission": _clean_number(raw.get("open_commission")),
                "close_commission": _clean_number(raw.get("close_commission")),
                "close_today_commission": _clean_number(
                    raw.get("close_commission_today", raw.get("close_today_commission"))
                ),
                "commission_type": None if _missing(raw.get("commission_type")) else str(raw.get("commission_type")),
                "min_order_quantity": _clean_int(raw.get("min_order_quantity")),
                "max_order_quantity": _clean_int(raw.get("max_order_quantity", raw.get("client_limit"))),
            }
        )
    return sorted(rows, key=lambda row: row["trade_date"])


def _artifact_row(
    *,
    root: Path,
    batch: str,
    contract: str,
    period: str,
    source_role: str,
    output_start: date,
    request_start: date | None,
    end: date,
    raw_path: Path | None,
) -> dict[str, Any]:
    role_code = "d" if source_role == "direct" else "d1m"
    data_version = (
        f"{batch}_{PRODUCT}_{contract.replace('.', '_')}_{period}_{role_code}_{end:%Y%m%d}_v1"
    )
    if len(data_version) > 64:
        raise S603ExecutionError(f"data_version_too_long:{data_version}")
    return {
        "product": PRODUCT,
        "contract": contract,
        "period": period,
        "source_role": source_role,
        "output_start": output_start.isoformat(),
        "request_start": request_start.isoformat() if request_start else None,
        "end": end.isoformat(),
        "data_version": data_version,
        "raw_path": str(raw_path) if raw_path else None,
        "canonical_path": str(
            _canonical_path(
                root,
                batch=batch,
                contract=contract,
                period=period,
                start=output_start,
                end=end,
                role=source_role,
            )
        ),
        "write_mode": "create_only",
    }


def _missing(value: Any) -> bool:
    return value is None or bool(pd.isna(value))


def _clean_number(value: Any) -> float | None:
    return None if _missing(value) else float(value)


def _clean_int(value: Any) -> int | None:
    return None if _missing(value) else int(float(value))


def _canonical_path(
    root: Path,
    *,
    batch: str,
    contract: str,
    period: str,
    start: date,
    end: date,
    role: str,
) -> Path:
    contract_file = contract.replace(".", "_")
    return (
        root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period}"
        / "exchange=DCE"
        / "symbol=jm"
        / f"contract={contract}"
        / f"batch={batch}"
        / f"{contract_file}_{period}_{start:%Y%m%d}_{end:%Y%m%d}_{role}_{batch}.parquet"
    )


def _paths(payload: Mapping[str, Any]) -> Iterable[Path]:
    for value in payload.get("files") or []:
        yield Path(str(value)).resolve(strict=False)


def _safe_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() else "_" for character in str(value).strip())
    slug = "_".join(part for part in slug.split("_") if part)
    if not slug:
        raise S603ExecutionError("empty_batch_id")
    return slug


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _decimal(value: Any) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


__all__ = [
    "S603ExecutionError",
    "active_baseline_start",
    "active_end_map",
    "apply_profile_binding_candidates",
    "apply_reference_snapshot",
    "build_execution_approval_packet",
    "build_execution_artifact_plan",
    "collect_provider_reference_snapshot",
    "collect_active_binding_snapshot",
    "collect_database_state",
    "expected_execution_paths",
    "execute_approved_catchup",
    "materialize_execution_assets",
    "register_execution_assets",
    "stable_bar_frame_hash",
    "validate_execution_paths_create_only",
]
