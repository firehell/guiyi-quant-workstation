from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.models.data_center import DataQualityReport, MarketDataFile, utc_now  # noqa: E402
from app.services.market_data_reader import MarketDataReader  # noqa: E402
from app.services.rqdata_ingest.bar_sample import (  # noqa: E402
    _ensure_reference_rows,
    _record_canonical_file_and_quality,
    _start_task,
    duckdb_bar_summary,
)
from app.services.rqdata_ingest.parquet import write_parquet_atomic  # noqa: E402
from experiments.rqdata_sample_acceptance.run_sample import (  # noqa: E402
    aggregate_standard_bars,
    download_dominant_product_raw,
    evaluate_standard_dominant_quality,
    normalize_jm_dominant_raw_frame,
)


SYMBOL = "jm"
EXCHANGE = "DCE"
CONTRACT = "jm.MAIN"
SOURCE_PERIOD = "1m"
TARGET_PERIODS = ("5m", "15m", "1d")
DEFAULT_START = date(2023, 1, 1)
DEFAULT_END = date(2025, 12, 31)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and register V1-B JM RQData sample assets.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--raw-path", type=Path, default=None, help="Existing raw dominant 1m parquet. If omitted, download or reuse formal raw.")
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Allow replacing formal parquet outputs.")
    parser.add_argument("--skip-download", action="store_true", help="Do not call RQData; require an existing raw parquet.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify registered 1d/15m/5m rows are readable.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        if args.verify_only:
            summary = verify_registered_periods(session=session)
        else:
            summary = build_v1b_jm_asset(
                session=session,
                output_root=args.output_root,
                raw_path=args.raw_path,
                start_date=args.start_date,
                end_date=args.end_date,
                force=args.force,
                skip_download=args.skip_download,
            )
            session.commit()
        summary_path = args.summary_path or (
            _default_verify_path(args.output_root, args.start_date, args.end_date)
            if args.verify_only
            else _default_summary_path(args.output_root, args.start_date, args.end_date)
        )
        write_summary(summary, summary_path)
        print(json.dumps(_public_summary(summary), ensure_ascii=False, indent=2))
    return 0


def build_v1b_jm_asset(
    *,
    session: Session,
    output_root: Path,
    raw_path: Path | None = None,
    start_date: date = DEFAULT_START,
    end_date: date = DEFAULT_END,
    force: bool = False,
    skip_download: bool = False,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    raw_file = raw_path.resolve() if raw_path is not None else _formal_raw_path(output_root, start_date, end_date)
    if not raw_file.exists():
        if skip_download:
            raise FileNotFoundError(f"JM raw parquet not found and --skip-download was set: {raw_file}")
        _download_raw_to_formal_path(output_root=output_root, start_date=start_date, end_date=end_date, force=force)
    elif force and not skip_download and raw_path is None:
        _download_raw_to_formal_path(output_root=output_root, start_date=start_date, end_date=end_date, force=True)

    raw_frame = pd.read_parquet(raw_file)
    if raw_frame.empty:
        raise ValueError(f"JM raw parquet is empty: {raw_file}")

    standard_frame = normalize_jm_dominant_raw_frame(
        raw_frame,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=SOURCE_PERIOD,
        data_version=_data_version(SOURCE_PERIOD, raw_frame),
    )
    standard_frame = _filter_by_datetime(standard_frame, start_date=start_date, end_date=end_date)
    if standard_frame.empty:
        raise ValueError(f"JM standard frame is empty after date filtering: {start_date}..{end_date}")
    standard_frame["quality_status"] = evaluate_standard_dominant_quality(standard_frame, SOURCE_PERIOD).status

    period_frames: dict[str, pd.DataFrame] = {SOURCE_PERIOD: standard_frame}
    for period in TARGET_PERIODS:
        aggregate_frame = aggregate_standard_bars(standard_frame, period)
        aggregate_frame["quality_status"] = evaluate_standard_dominant_quality(aggregate_frame, period).status
        period_frames[period] = aggregate_frame

    _demote_non_v1b_primary_files(session=session, keep_root=output_root)

    summaries: dict[str, dict[str, Any]] = {}
    for period, frame in period_frames.items():
        path = _canonical_path(output_root, period=period, frame=frame)
        if path.exists() and not force:
            frame = pd.read_parquet(path)
        else:
            if path.exists() and not force:
                raise FileExistsError(f"Refusing to overwrite existing JM parquet: {path}")
            write_parquet_atomic(frame, path)
        summaries[period] = register_period(session=session, path=path, frame=frame, period=period)

    verification = verify_registered_periods(session=session)
    return {
        "mode": "v1b-jm-asset",
        "symbol": SYMBOL,
        "contract": CONTRACT,
        "exchange": EXCHANGE,
        "requested_start_date": start_date.isoformat(),
        "requested_end_date": end_date.isoformat(),
        "raw_path": str(raw_file),
        "periods": summaries,
        "verification": verification["periods"],
    }


def register_period(*, session: Session, path: Path, frame: pd.DataFrame, period: str) -> dict[str, Any]:
    quality = evaluate_standard_dominant_quality(frame, period)
    if quality.status != "passed":
        raise ValueError(f"JM {period} quality must be passed before registration, got {quality.status}")
    start = pd.to_datetime(frame["datetime"].min()).date()
    end = pd.to_datetime(frame["datetime"].max()).date()
    task = _start_task(session=session, symbol=SYMBOL, contract=CONTRACT, frequency=period, start_date=start, end_date=end)
    _ensure_reference_rows(session, symbol=SYMBOL, contract=CONTRACT, exchange=EXCHANGE)
    market_file = _record_canonical_file_and_quality(
        session=session,
        task=task,
        path=path,
        frame=frame,
        quality=quality,
        symbol=SYMBOL,
        contract=CONTRACT,
        frequency=period,
        data_version=str(frame["data_version"].iloc[0]),
    )
    task.status = "success"
    task.progress = 100
    task.finished_at = utc_now()
    null_count = _null_count(frame)
    task.result = {
        "v1b_jm_asset": True,
        "canonical_file": str(path),
        "row_count": len(frame),
        "quality_status": quality.status,
        "null_count": null_count,
    }
    report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
    if report is not None:
        report.details = {
            **(report.details or {}),
            "v1b_jm_asset": True,
            "symbol": SYMBOL,
            "interval": period,
            "start_datetime": _iso(frame["datetime"].min()),
            "end_datetime": _iso(frame["datetime"].max()),
            "row_count": len(frame),
            "missing_count": quality.missing_bars,
            "duplicate_count": quality.duplicated_bars,
            "null_count": null_count,
            "file_path": str(path),
            "quality_status": quality.status,
        }
    session.flush()
    reader_rows = MarketDataReader(session=session, project_root=PROJECT_ROOT).load_bars(
        symbol=SYMBOL,
        contract=CONTRACT,
        period=period,
        start=datetime.min,
        end=datetime.max,
        provider="rqdata",
        data_role="primary",
    )
    return {
        "symbol": SYMBOL,
        "interval": period,
        "start_datetime": _iso(frame["datetime"].min()),
        "end_datetime": _iso(frame["datetime"].max()),
        "row_count": len(frame),
        "missing_count": quality.missing_bars,
        "duplicate_count": quality.duplicated_bars,
        "null_count": null_count,
        "file_path": str(path),
        "quality_status": quality.status,
        "market_data_file_id": market_file.id,
        "data_quality_report_id": None if report is None else report.id,
        "reader_rows": len(reader_rows),
        "duckdb": duckdb_bar_summary(path),
    }


def verify_registered_periods(*, session: Session) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    for period in TARGET_PERIODS:
        rows = MarketDataReader(session=session, project_root=PROJECT_ROOT).load_bars(
            symbol=SYMBOL,
            contract=CONTRACT,
            period=period,
            start=datetime.min,
            end=datetime.max,
            provider="rqdata",
            data_role="primary",
        )
        if not rows:
            raise ValueError(f"JM {period} has no readable registered bars")
        periods[period] = {
            "symbol": SYMBOL,
            "interval": period,
            "start_datetime": rows[0]["datetime"].isoformat(),
            "end_datetime": rows[-1]["datetime"].isoformat(),
            "row_count": len(rows),
            "quality_status": "readable",
        }
    return {"mode": "v1b-jm-verify", "periods": periods}


def _demote_non_v1b_primary_files(*, session: Session, keep_root: Path) -> int:
    keep_root = keep_root.resolve()
    query = select(MarketDataFile).where(
        MarketDataFile.provider == "rqdata",
        MarketDataFile.instrument_symbol == SYMBOL,
        MarketDataFile.contract_code == CONTRACT,
        MarketDataFile.period.in_([SOURCE_PERIOD, *TARGET_PERIODS]),
        MarketDataFile.data_role == "primary",
    )
    changed = 0
    for market_file in session.scalars(query):
        path = Path(market_file.file_path)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if _is_relative_to(resolved, keep_root):
            continue
        market_file.data_role = "candidate"
        changed += 1
    session.flush()
    return changed


def write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _download_raw_to_formal_path(*, output_root: Path, start_date: date, end_date: date, force: bool) -> None:
    target = _formal_raw_path(output_root, start_date, end_date)
    if target.exists() and not force:
        return
    from app.services.rqdata_ingest.client import RqDataClient

    client = RqDataClient(load_env_file=False)
    result = download_dominant_product_raw(
        client=client,
        output_root=output_root,
        product="JM",
        exchange=EXCHANGE,
        frequency=SOURCE_PERIOD,
        start_date=start_date,
        end_date=end_date,
    )
    written = Path(result["raw_path"])
    if written != target:
        raise ValueError(f"Unexpected JM raw path: {written}; expected {target}")


def _formal_raw_path(output_root: Path, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / "product=jm"
        / "frequency=1m"
        / f"year={start_date:%Y}"
        / f"jm_1m_dominant_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _canonical_path(output_root: Path, *, period: str, frame: pd.DataFrame) -> Path:
    start = pd.to_datetime(frame["datetime"]).min().date()
    end = pd.to_datetime(frame["datetime"]).max().date()
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period}"
        / "exchange=DCE"
        / "symbol=jm"
        / "contract=jm.MAIN"
        / f"jm_MAIN_{period}_{start:%Y%m%d}_{end:%Y%m%d}.parquet"
    )


def _filter_by_datetime(frame: pd.DataFrame, *, start_date: date, end_date: date) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    return data[(data["datetime"] >= start) & (data["datetime"] <= end)].reset_index(drop=True)


def _data_version(period: str, frame: pd.DataFrame) -> str:
    datetimes = pd.to_datetime(frame["datetime"], errors="coerce")
    start = datetimes.min().date()
    end = datetimes.max().date()
    return f"rqdata_v1b_jm_{period}_{start:%Y%m%d}_{end:%Y%m%d}_v1"


def _null_count(frame: pd.DataFrame) -> int:
    required = ["datetime", "trading_day", "open", "high", "low", "close", "volume", "open_interest"]
    return int(frame[[column for column in required if column in frame.columns]].isna().sum().sum())


def _iso(value: Any) -> str:
    return pd.Timestamp(value).to_pydatetime().isoformat()


def _default_summary_path(output_root: Path, start_date: date, end_date: date) -> Path:
    return output_root / "processed" / "v1b" / "jm" / f"v1b_jm_quality_report_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"


def _default_verify_path(output_root: Path, start_date: date, end_date: date) -> Path:
    return output_root / "processed" / "v1b" / "jm" / f"v1b_jm_verify_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"


def _public_summary(summary: dict[str, Any]) -> dict[str, Any]:
    periods = summary.get("periods", {})
    return {
        "mode": summary.get("mode"),
        "symbol": summary.get("symbol"),
        "contract": summary.get("contract"),
        "raw_path": summary.get("raw_path"),
        "periods": {period: periods[period] for period in ("1d", "15m", "5m") if period in periods},
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
