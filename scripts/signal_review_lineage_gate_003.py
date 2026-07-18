#!/usr/bin/env python3
"""Close SIGNAL_REVIEW_LINEAGE_READY by deriving JM2609 actual 5m/15m and binding Profile lineage.

This script is intentionally fixed-scope and fail-closed:
- product=jm, contract=JM2609, trading days 2026-07-08..2026-07-10
- source is the canonical passed actual-contract 1m asset from ACTUAL-DOMINANT-ROLL-V2-006
- no RQData, no live runtime, no notification/order/signal/review history writes
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import DataProfile, MainContractMap, MarketDataFile  # noqa: E402
from app.models.review import ReviewNote  # noqa: E402
from app.models.signal import SignalEvent  # noqa: E402
from app.services.data_profile_registry import DataProfileRegistry  # noqa: E402
from app.services.market_data_reader import MarketDataReader  # noqa: E402
from app.services.profile_lineage import ProfileLineageResolver  # noqa: E402
from app.services.review_lineage import load_review_bars  # noqa: E402
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars_strict  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality  # noqa: E402
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality  # noqa: E402
from app.services.rqdata_ingest.parquet import sha256_file, write_parquet_atomic  # noqa: E402
from app.services.signal_lineage import SignalFormalLineageResolver  # noqa: E402
from app.services.trading_session_clock import TradingSessionClock  # noqa: E402
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate  # noqa: E402

TASK_ID = "SIGNAL-REVIEW-PROFILE-LINEAGE-003"
GATE_ID = "signal_review_lineage_gate_003"
EXPECTED_ALEMBIC = "20260718_0024"
PRODUCT = "jm"
CONTRACT = "JM2609"
EXCHANGE = "DCE"
START_DATE = date(2026, 7, 8)
END_DATE = date(2026, 7, 10)
PERIODS = ("5m", "15m")
PROFILES = ("intraday_research_v1", "live_observation_v1")
SOURCE_FILE_ID = 103923
SOURCE_VERSION = "actual_dominant_roll_006_JM2609_1m_20260708_20260710_v1"
SOURCE_PATH = Path(
    "/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/canonical/bars/provider=rqdata/period=1m/"
    "exchange=DCE/symbol=jm/contract=JM2609/JM2609_1m_20260708_20260710_actual_roll_006_v1.parquet"
)
DATA_ROOT_DEFAULT = Path("/Volumes/扩展盘/guiyi-quant-workstation")
EVIDENCE_REL = Path("data/reports/full_history_audit_v2_20260710") / GATE_ID
OUTPUT_REL = Path("data/parquet/canonical/bars/provider=rqdata")
SUMMARY_REL = Path("data/processed/v1b/jm") / f"jm_{GATE_ID}.json"
MANIFEST_REL = Path("data/manifests") / f"rqdata_actual_contract_bars_jm_JM2609_20260708_20260710_{GATE_ID}.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT_DEFAULT)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.preflight == args.apply:
        parser.error("choose exactly one of --preflight or --apply")
    data_root = args.data_root.resolve()
    evidence_dir = data_root / EVIDENCE_REL
    with SessionLocal() as session:
        preflight = build_preflight(session=session, data_root=data_root)
        if args.preflight:
            print(json.dumps(preflight, ensure_ascii=False, indent=2, default=str))
            return 0
        evidence_dir.mkdir(parents=True, exist_ok=False)
        write_json(evidence_dir / "preflight.json", preflight)
        before = snapshot_no_touch(session)
        write_json(evidence_dir / "no_touch_hashes.json", {"before": before})
        binding_before = collect_bindings(session)
        result = apply_gate(session=session, data_root=data_root, evidence_dir=evidence_dir)
        binding_after = collect_bindings(session)
        write_csv(evidence_dir / "binding_before_after.csv", binding_before + binding_after)
        verify = verify_gate(session=session, data_root=data_root, registrations=result["registrations"])
        write_json(evidence_dir / "resolver_verify.json", verify["resolver_verify"])
        write_json(evidence_dir / "stage9_verify.json", verify["stage9_verify"])
        after = snapshot_no_touch(session)
        write_json(evidence_dir / "no_touch_hashes.json", {"before": before, "after": after, "status": compare_no_touch(before, after)})
        rollback = {
            "status": "PREPARED_AFTER_COMMIT",
            "gate_id": GATE_ID,
            "market_data_file_ids": result["market_data_file_ids"],
            "data_quality_report_ids": result["data_quality_report_ids"],
            "data_download_task_ids": result["data_download_task_ids"],
            "binding_ids": result["binding_ids"],
            "created_files": result["created_files"],
            "method": "Supersede listed bindings, delete listed new metadata rows, and move listed files to quarantine only if post-commit verification fails.",
        }
        write_json(evidence_dir / "rollback_evidence.json", rollback)
        if verify["status"] != "passed" or compare_no_touch(before, after)["status"] != "passed":
            raise GateError("post-commit verification failed")
        session.commit()
        print(json.dumps({"status": "SIGNAL_REVIEW_LINEAGE_READY", **result, "verification": verify}, ensure_ascii=False, indent=2, default=str))
        return 0


class GateError(RuntimeError):
    pass


def build_preflight(*, session: Any, data_root: Path) -> dict[str, Any]:
    alembic = [row[0] for row in session.execute(text("select version_num from alembic_version order by version_num"))]
    if alembic != [EXPECTED_ALEMBIC]:
        raise GateError(f"unexpected alembic revision: {alembic}")
    if not SOURCE_PATH.is_file():
        raise GateError(f"source 1m parquet missing: {SOURCE_PATH}")
    source_sha = sha256_file(SOURCE_PATH)
    source = session.get(MarketDataFile, SOURCE_FILE_ID)
    if source is None:
        raise GateError(f"source MarketDataFile missing: {SOURCE_FILE_ID}")
    expected_source = {
        "provider": "rqdata",
        "data_type": "bars",
        "instrument_symbol": PRODUCT,
        "contract_code": CONTRACT,
        "period": "1m",
        "data_version": SOURCE_VERSION,
        "data_role": "primary",
        "quality_status": "passed",
        "checksum": source_sha,
        "file_path": str(SOURCE_PATH),
    }
    actual_source = {key: getattr(source, key) for key in expected_source}
    if actual_source != expected_source:
        raise GateError(f"source MarketDataFile drifted: {actual_source}")
    rank_rows = list(
        session.scalars(
            select(MainContractMap)
            .where(
                MainContractMap.instrument_symbol == PRODUCT,
                MainContractMap.trade_date >= START_DATE,
                MainContractMap.trade_date <= END_DATE,
                MainContractMap.provider == "rqdata",
                MainContractMap.rule == "volume_open_interest",
                MainContractMap.rank == 1,
            )
            .order_by(MainContractMap.trade_date.asc())
        )
    )
    if [row.trade_date for row in rank_rows] != [START_DATE, date(2026, 7, 9), END_DATE]:
        raise GateError("rank=1 mapping dates missing")
    if any(row.contract_code != CONTRACT for row in rank_rows):
        raise GateError("rank=1 mapping is not JM2609 for all target days")
    existing_outputs = [str(path_for_period(data_root, period)) for period in PERIODS if path_for_period(data_root, period).exists()]
    if existing_outputs:
        raise GateError(f"target output already exists: {existing_outputs}")
    active_actual = collect_active_actual_bindings(session)
    if active_actual:
        raise GateError(f"actual active bindings already exist: {active_actual}")
    clock = TradingSessionClock(session)
    trading_days, calendar_complete = clock.trading_days_between(START_DATE, END_DATE, exchange=EXCHANGE)
    if trading_days != [START_DATE, date(2026, 7, 9), END_DATE] or not calendar_complete:
        raise GateError("trading calendar incomplete for JM2609 target range")
    windows = clock.windows_for_trading_days(trading_days, product=PRODUCT, exchange=EXCHANGE)
    if not windows:
        raise GateError("trading session windows missing")
    return {
        "status": "passed",
        "gate_id": GATE_ID,
        "alembic": alembic,
        "source_file_id": SOURCE_FILE_ID,
        "source_path": str(SOURCE_PATH),
        "source_sha256": source_sha,
        "source_start": source.start_time.isoformat(),
        "source_end": source.end_time.isoformat(),
        "rank1": [model_dict(row, fields=("id", "trade_date", "contract_code", "data_version")) for row in rank_rows],
        "calendar_complete": calendar_complete,
        "trading_days": [item.isoformat() for item in trading_days],
        "session_window_count": len(windows),
        "existing_target_files": existing_outputs,
        "active_actual_bindings": active_actual,
        "no_touch_before": snapshot_no_touch(session),
    }


def apply_gate(*, session: Any, data_root: Path, evidence_dir: Path) -> dict[str, Any]:
    source = session.get(MarketDataFile, SOURCE_FILE_ID)
    if source is None:
        raise GateError("source missing during apply")
    frame_1m = pd.read_parquet(SOURCE_PATH)
    frame_1m["trading_day"] = pd.to_datetime(frame_1m["trading_day"], errors="coerce").dt.date
    frame_1m = frame_1m[(frame_1m["trading_day"] >= START_DATE) & (frame_1m["trading_day"] <= END_DATE)].copy()
    if frame_1m.empty:
        raise GateError("source window empty")
    clock = TradingSessionClock(session)
    trading_days, calendar_complete = clock.trading_days_between(START_DATE, END_DATE, exchange=EXCHANGE)
    if not calendar_complete:
        raise GateError("calendar incomplete during apply")
    windows = clock.windows_for_trading_days(trading_days, product=PRODUCT, exchange=EXCHANGE)
    periods_payload: dict[str, Any] = {}
    derived_rows: list[dict[str, Any]] = []
    created_files: list[str] = []
    for period in PERIODS:
        aggregate = aggregate_standard_bars_strict(frame_1m, period, session_windows=tuple(windows))
        diagnostics = dataclass_dict(aggregate.diagnostics)
        if diagnostics.get("source_gap_count") or diagnostics.get("unmatched_source_row_count"):
            raise GateError(f"strict aggregation diagnostics failed for {period}: {diagnostics}")
        derived = aggregate.frame.copy()
        if derived.empty:
            raise GateError(f"derived frame empty for {period}")
        version = f"signal_review_lineage_003_jm_JM2609_{period}_20260708_20260710_v1"
        derived["data_role"] = "primary"
        derived["quality_status"] = "passed"
        derived["data_version"] = version
        derived["source_market_data_file_id"] = SOURCE_FILE_ID
        derived["source_path"] = str(SOURCE_PATH)
        derived["source_data_version"] = SOURCE_VERSION
        derived["source_checksum"] = source.checksum
        derived["source_interval"] = "1m"
        derived["source_profile_id"] = GATE_ID
        quality = evaluate_standard_dominant_quality(derived, period)
        if quality.status != "passed":
            raise GateError(f"derived quality failed for {period}: {dataclass_dict(quality)}")
        output_path = path_for_period(data_root, period)
        if output_path.exists():
            raise GateError(f"output already exists: {output_path}")
        write_parquet_atomic(derived, output_path)
        checksum = sha256_file(output_path)
        created_files.append(str(output_path))
        readable = duckdb_count(output_path)
        if readable != len(derived):
            raise GateError(f"DuckDB row count mismatch for {period}: {readable} != {len(derived)}")
        periods_payload[period] = {
            "data_version": version,
            "raw": {"path": str(SOURCE_PATH)},
            "standard": {
                "path": str(output_path),
                "row_count": len(derived),
                "min_datetime": pd.to_datetime(derived["datetime"]).min().isoformat(),
                "max_datetime": pd.to_datetime(derived["datetime"]).max().isoformat(),
                "checksum": checksum,
            },
            "lineage": {
                "source_market_data_file_id": SOURCE_FILE_ID,
                "source_path": str(SOURCE_PATH),
                "source_data_version": SOURCE_VERSION,
                "source_checksum": source.checksum,
                "source_interval": "1m",
                "gate_id": GATE_ID,
            },
        }
        derived_rows.append(
            {
                "period": period,
                "data_version": version,
                "path": str(output_path),
                "row_count": len(derived),
                "checksum": checksum,
                "min_datetime": periods_payload[period]["standard"]["min_datetime"],
                "max_datetime": periods_payload[period]["standard"]["max_datetime"],
                "diagnostics": json.dumps(diagnostics, ensure_ascii=False),
            }
        )
    summary_path = data_root / SUMMARY_REL
    manifest_path = data_root / MANIFEST_REL
    if summary_path.exists() or manifest_path.exists():
        raise GateError("summary or manifest already exists")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        summary_path,
        {
            "symbol": PRODUCT,
            "contract": CONTRACT,
            "exchange": EXCHANGE,
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "data_role": "primary",
            "gate_id": GATE_ID,
            "periods": periods_payload,
        },
    )
    created_files.append(str(summary_path))
    registration = register_dominant_v2_quality(
        session=session,
        summary_path=summary_path,
        manifest_path=manifest_path,
        data_role="primary",
    )
    created_files.append(str(manifest_path))
    write_csv(evidence_dir / "derived_manifest.csv", derived_rows)
    registry = DataProfileRegistry(session)
    sync_profile_contract_roles(session)
    binding_ids: list[int] = []
    for profile_id in PROFILES:
        for period in PERIODS:
            item = registration["periods"][period]
            binding = registry.switch_active_binding(
                profile_id=profile_id,
                instrument_symbol=PRODUCT,
                contract_code=CONTRACT,
                period=period,
                data_version=str(item["data_version"]),
                market_data_file_id=int(item["market_data_file_id"]),
                contract_role="actual_contract",
            )
            binding_ids.append(int(binding.id))
    session.flush()
    return {
        "status": "applied",
        "registrations": registration,
        "market_data_file_ids": [int(item["market_data_file_id"]) for item in registration["periods"].values()],
        "data_quality_report_ids": [int(item["data_quality_report_id"]) for item in registration["periods"].values() if item.get("data_quality_report_id") is not None],
        "data_download_task_ids": collect_task_ids_for_versions(session, [str(item["data_version"]) for item in registration["periods"].values()]),
        "binding_ids": binding_ids,
        "created_files": created_files,
    }


def verify_gate(*, session: Any, data_root: Path, registrations: dict[str, Any]) -> dict[str, Any]:
    resolver = ProfileLineageResolver(session)
    signal_resolver = SignalFormalLineageResolver(session, project_root=data_root)
    reader = MarketDataReader(session, project_root=data_root)
    resolver_rows: list[dict[str, Any]] = []
    stage9_rows: list[dict[str, Any]] = []
    for profile_id in PROFILES:
        for period in PERIODS:
            lineage = resolver.resolve(consumer="signal", symbol=PRODUCT, contract=CONTRACT, period=period, profile_id=profile_id)
            if lineage.blocked or lineage.market_file is None:
                raise GateError(f"ProfileLineageResolver blocked {profile_id}:{period}: {lineage.blocked_reason}")
            market_file = lineage.market_file
            frame = pd.read_parquet(Path(market_file.file_path))
            frame = frame.sort_values("datetime")
            row = frame.iloc[-1]
            bar_end = pd.Timestamp(row["datetime"]).to_pydatetime()
            bar_start = bar_end - timedelta(minutes=int(period.removesuffix("m")))
            trigger_price = float(row["close"])
            signal_lineage = signal_resolver.resolve(
                profile_id=profile_id,
                symbol=PRODUCT,
                continuous_contract="jm.MAIN",
                actual_contract=CONTRACT,
                period=period,
                dominant_mapping_date=END_DATE,
                bar_start=bar_start,
                bar_end=bar_end,
                trigger_price=trigger_price,
                source_mode="historical_scan",
                confirmation={"confirmation_mode": "historical_canonical"},
            )
            if signal_lineage.blocked or not signal_lineage.snapshot:
                raise GateError(f"SignalFormalLineageResolver blocked {profile_id}:{period}: {signal_lineage.blocked_code}")
            event = build_preview_event(
                profile_id=profile_id,
                market_data_file_id=int(signal_lineage.market_data_file_id or 0),
                period=period,
                bar_start=bar_start,
                bar_end=bar_end,
                trigger_price=trigger_price,
                snapshot=signal_lineage.snapshot,
            )
            gate = evaluate_stage9_signal_event_gate(event)
            if not gate["allowed"]:
                raise GateError(f"Stage9 blocked {profile_id}:{period}: {gate['blocked_reasons']}")
            note = ReviewNote(
                source_type="signal_event",
                source_id=0,
                symbol=PRODUCT,
                contract=CONTRACT,
                period=period,
                direction="long",
                strategy_name="gate_verify",
                strategy_version="signal_review_lineage_003",
                open_time=bar_start,
                close_time=bar_end,
                open_price=trigger_price,
                close_price=trigger_price,
                volume=0,
                extra={"formal_lineage": deepcopy(signal_lineage.snapshot)},
            )
            review_bars = load_review_bars(session, note, project_root=data_root)
            exact_rows = reader.load_bars_from_market_file(
                market_data_file_id=market_file.id,
                symbol=PRODUCT,
                contract=CONTRACT,
                period=period,
                start=bar_end,
                end=bar_end,
                expected_provider="rqdata",
                expected_data_role="primary",
                expected_quality_status="passed",
                expected_data_version=str(market_file.data_version),
                expected_checksum=str(market_file.checksum),
            )
            if len(exact_rows) != 1 or not review_bars["bars"]:
                raise GateError(f"exact bar verification failed {profile_id}:{period}")
            resolver_rows.append(
                {
                    "profile_id": profile_id,
                    "period": period,
                    "market_data_file_id": market_file.id,
                    "data_version": market_file.data_version,
                    "coverage_start": market_file.start_time.isoformat(),
                    "coverage_end": market_file.end_time.isoformat(),
                    "quality_status": market_file.quality_status,
                    "data_role": market_file.data_role,
                }
            )
            stage9_rows.append({"profile_id": profile_id, "period": period, "allowed": gate["allowed"], "bar_end": bar_end.isoformat()})
    return {"status": "passed", "resolver_verify": resolver_rows, "stage9_verify": stage9_rows}


def build_preview_event(*, profile_id: str, market_data_file_id: int, period: str, bar_start: datetime, bar_end: datetime, trigger_price: float, snapshot: dict[str, Any]) -> SignalEvent:
    return SignalEvent(
        event_key=f"gate003:{profile_id}:{period}:{bar_end.isoformat()}",
        event_type="signal_created",
        signal_id=0,
        task_no="gate003",
        source_mode="historical_scan",
        strategy_name="gate_verify",
        strategy_version="signal_review_lineage_003",
        watchlist_code="jm_gate003",
        symbol=PRODUCT,
        contract="jm.MAIN",
        product=PRODUCT,
        continuous_contract="jm.MAIN",
        actual_contract=CONTRACT,
        dominant_mapping_date=END_DATE,
        exchange=EXCHANGE,
        period=period,
        signal_time=bar_end,
        bar_start=bar_start,
        bar_end=bar_end,
        trigger_price=trigger_price,
        provider="rqdata",
        source="historical_canonical",
        direction="long",
        signal_status="entry_signal",
        lifecycle_status="new",
        score_bucket=1,
        data_role="primary",
        quality_status={"status": "passed"},
        profile_id=profile_id,
        market_data_file_id=market_data_file_id,
        payload={"formal_lineage": snapshot},
    )


def sync_profile_contract_roles(session: Any) -> None:
    for profile_id in PROFILES:
        profile = session.scalar(select(DataProfile).where(DataProfile.profile_id == profile_id))
        if profile is None:
            raise GateError(f"profile missing: {profile_id}")
        roles = list(profile.contract_roles or [])
        if "actual_contract" not in roles:
            profile.contract_roles = [*roles, "actual_contract"]


def collect_active_actual_bindings(session: Any) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select profile_id, instrument_symbol, contract_code, contract_role, period, market_data_file_id, data_version, binding_status
            from profile_active_bindings
            where profile_id in ('intraday_research_v1','live_observation_v1')
              and instrument_symbol='jm' and contract_code='JM2609' and period in ('5m','15m')
              and binding_status='active'
            order by profile_id, period
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def collect_bindings(session: Any) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select profile_id, instrument_symbol, contract_code, contract_role, period, market_data_file_id, data_version, binding_status, activated_at, superseded_at
            from profile_active_bindings
            where profile_id in ('intraday_research_v1','live_observation_v1')
              and instrument_symbol='jm' and contract_code='JM2609' and period in ('5m','15m')
            order by profile_id, period, binding_status, id
            """
        )
    ).mappings()
    return [json_ready({"snapshot_phase": "binding", **dict(row)}) for row in rows]


def snapshot_no_touch(session: Any) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            select
              (select count(*) from signal_scan_tasks) as signal_scan_tasks,
              (select count(*) from strategy_signals) as strategy_signals,
              (select count(*) from signal_events) as signal_events,
              (select count(*) from review_notes) as review_notes,
              (select count(*) from signal_events where profile_id is not null or market_data_file_id is not null or payload::jsonb ? 'formal_lineage') as lineage_events,
              (select count(*) from review_notes where extra::jsonb ? 'formal_lineage') as lineage_reviews,
              (select count(*) from live_minute_bars) as live_minute_bars,
              (select count(*) from live_aggregated_bars) as live_aggregated_bars,
              (select md5(to_jsonb(t)::text) from backtest_reports t where id=14) as report14_md5
            """
        )
    ).mappings().one()
    return dict(row)


def compare_no_touch(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    diffs = {key: {"before": before.get(key), "after": after.get(key)} for key in sorted(before) if before.get(key) != after.get(key)}
    return {"status": "passed" if not diffs else "failed", "diffs": diffs}


def collect_task_ids_for_versions(session: Any, versions: list[str]) -> list[int]:
    rows = session.execute(
        text(
            """
            select distinct task_id from market_data_files
            where data_version = any(:versions) and task_id is not null
            order by task_id
            """
        ),
        {"versions": versions},
    ).fetchall()
    return [int(row[0]) for row in rows]


def path_for_period(data_root: Path, period: str) -> Path:
    return data_root / OUTPUT_REL / f"period={period}" / "exchange=DCE" / "symbol=jm" / "contract=JM2609" / f"JM2609_{period}_20260708_20260710_signal_review_lineage_003.parquet"


def duckdb_count(path: Path) -> int:
    with duckdb.connect(database=":memory:") as connection:
        return int(connection.execute("select count(*) from read_parquet(?)", [str(path)]).fetchone()[0])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_ready(payload), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(json_ready(row))


def model_dict(obj: Any, *, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


def dataclass_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj) if is_dataclass(obj) else dict(obj)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_ready(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
