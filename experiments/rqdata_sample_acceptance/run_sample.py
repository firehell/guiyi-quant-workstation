#!/usr/bin/env python3
"""RQData small sample acceptance runner.

This script intentionally keeps real market data under an ignored experiment
output directory. It does not accept account secrets as CLI arguments.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
QUANT_CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("output")

for path in (API_ROOT, QUANT_CORE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


DISCLAIMER = "RQData 小样本验收只用于链路验证，不是正式回测结论；回测结果不等于实盘结果。"
CREDENTIAL_MESSAGE = (
    "RQData credentials not configured. Set RQDATAC2_CONF, RQDATAC_CONF, "
    "RQDATA_LICENSE_KEY, or RQDATA_USERNAME/RQDATA_PASSWORD in environment variables."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RQData small sample acceptance chain.")
    parser.add_argument("--check-credentials", action="store_true", help="Check RQData credential environment variables and exit.")
    parser.add_argument("--jm-one-year-raw", action="store_true", help="Download one complete year of JM 1m dominant-contract raw bars.")
    parser.add_argument("--standardize-jm-raw", action="store_true", help="Convert JM raw parquet from P0-002 to standard parquet and quality reports.")
    parser.add_argument("--aggregate-jm-standard", action="store_true", help="Aggregate JM 1m standard parquet into 5m/15m/1d standard parquet.")
    parser.add_argument("--product", default="JM", help="RQData futures product for --jm-one-year-raw, default JM.")
    parser.add_argument("--year", type=int, default=None, help="Complete calendar year for --jm-one-year-raw. Defaults to latest complete year.")
    parser.add_argument("--raw-path", type=Path, default=None, help="Raw parquet path for --standardize-jm-raw. Defaults to rqdata_jm_raw_result.json raw.path.")
    parser.add_argument("--standard-path", type=Path, default=None, help="JM 1m standard parquet path for --aggregate-jm-standard. Defaults to rqdata_jm_standard_result.json standard.path.")
    parser.add_argument("--contract", default="RB2405", help="RQData futures contract, default RB2405.")
    parser.add_argument("--exchange", default="SHFE", help="Exchange code, default SHFE.")
    parser.add_argument("--symbol", default="rb", help="Product symbol, default rb.")
    parser.add_argument("--frequency", default="1m", choices=["1m", "60m", "1d"], help="Small sample bar frequency.")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 2), help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 1, 31), help="End date YYYY-MM-DD.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Ignored output directory.")
    parser.add_argument("--use-app-db", action="store_true", help="Write indexes to the configured app database instead of isolated SQLite.")
    parser.add_argument("--run-backtest", action="store_true", help="Optionally run vn.py smoke on the downloaded standard parquet if quality passed.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.check_credentials:
        return check_credentials(args.output_dir)
    if args.jm_one_year_raw:
        return run_jm_one_year_raw(args)
    if args.standardize_jm_raw:
        return run_standardize_jm_raw(args)
    if args.aggregate_jm_standard:
        return run_aggregate_jm_standard(args)

    try:
        credential_info = check_rqdata_credential_environment()
        from app.services.rqdata_ingest.client import RqDataClient

        client = RqDataClient(load_env_file=False)
    except Exception as exc:
        payload = error_payload("credentials", exc)
        write_json(args.output_dir / "rqdata_sample_result.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 2

    with session_scope(args.output_dir, args.use_app_db) as session:
        try:
            from app.services.rqdata_ingest.bar_sample import run_rqdata_bar_sample

            result = run_rqdata_bar_sample(
                session=session,
                client=client,
                output_root=args.output_dir,
                symbol=args.symbol,
                contract=args.contract,
                exchange=args.exchange,
                frequency=args.frequency,
                start_date=args.start,
                end_date=args.end,
            )
            session.commit()
            from app.services.market_data_reader import MarketDataReader

            reader_rows = MarketDataReader(session=session, project_root=PROJECT_ROOT).load_bars(
                symbol=args.symbol.lower(),
                contract=args.contract.lower(),
                period=args.frequency,
                start=_date_time_from_iso(result.duckdb_summary["start_time"]),
                end=_date_time_from_iso(result.duckdb_summary["end_time"]),
                provider="rqdata",
            )
        except Exception as exc:
            session.rollback()
            payload = error_payload("sample", exc)
            write_json(args.output_dir / "rqdata_sample_result.json", payload)
            print(payload["error"]["message"], file=sys.stderr)
            return 1

        from app.data_sources import MarketDataQuery, RQDataProvider

        provider_rows = RQDataProvider(session=session, project_root=PROJECT_ROOT).get_bars(
            MarketDataQuery(
                symbol=args.symbol.lower(),
                contract=args.contract.lower(),
                period=args.frequency,
                start=_date_time_from_iso(result.duckdb_summary["start_time"]),
                end=_date_time_from_iso(result.duckdb_summary["end_time"]),
            )
        )
        backtest_payload = run_optional_backtest(session, args, result) if args.run_backtest else {"requested": False}
        payload = {
            "mode": "rqdata-small-sample",
            "disclaimer": DISCLAIMER,
            "rqdata_account_required": True,
            "credential_sources": credential_info["credential_sources"],
            "live_trading_used": False,
            "database_mode": "app_db" if args.use_app_db else "isolated_sqlite",
            "sample": {
                "symbol": args.symbol.lower(),
                "contract": args.contract.lower(),
                "exchange": args.exchange.upper(),
                "frequency": args.frequency,
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
            },
            "files": {
                "raw_path": str(result.raw_path),
                "standard_path": str(result.canonical_path),
                "raw_rows": result.raw_rows,
                "standard_rows": result.canonical_rows,
                "data_version": result.data_version,
            },
            "quality": {
                "status": result.quality.status,
                "missing_bars": result.quality.missing_bars,
                "duplicated_bars": result.quality.duplicated_bars,
                "abnormal_price_count": result.quality.abnormal_price_count,
                "abnormal_volume_count": result.quality.abnormal_volume_count,
                "abnormal_open_interest_count": result.quality.abnormal_open_interest_count,
                "details": result.quality.details,
            },
            "database": {
                "task_no": result.task_no,
                "market_file_id": result.market_file_id,
            },
            "duckdb": result.duckdb_summary,
            "reader": {
                "rows": len(reader_rows),
                "provider_rows": len(provider_rows),
            },
            "backtest": backtest_payload,
            "output_note": "Generated under experiments/rqdata_sample_acceptance/output/ and ignored by git.",
        }
        write_json(args.output_dir / "rqdata_sample_result.json", payload)
        print(f"RQData sample written: {args.output_dir / 'rqdata_sample_result.json'}")
        print(f"standard_rows={result.canonical_rows} quality={result.quality.status}")
        return 0


def check_credentials(output_dir: Path) -> int:
    try:
        payload = {
            "mode": "check-credentials",
            "rqdata_account_required": True,
            "live_trading_used": False,
            **check_rqdata_credential_environment(),
        }
        from app.services.rqdata_ingest.client import RqDataClient

        RqDataClient(load_env_file=False)
        payload["rqdata_client_initialized"] = True
        write_json(output_dir / "rqdata_credentials_check.json", payload)
        print("RQData credential environment is configured and client initialized.")
        return 0
    except Exception as exc:
        payload = error_payload("credentials", exc)
        write_json(output_dir / "rqdata_credentials_check.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 2


def run_jm_one_year_raw(args: argparse.Namespace) -> int:
    year = args.year or latest_complete_year()
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)
    product = args.product.strip() or "JM"
    exchange = args.exchange.strip().upper()
    frequency = args.frequency.strip().lower()
    if frequency != "1m":
        payload = error_payload("jm-one-year-raw", ValueError("JM raw acceptance requires frequency=1m"))
        write_json(args.output_dir / "rqdata_jm_raw_result.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 1

    try:
        credential_info = check_rqdata_credential_environment()
        from app.services.rqdata_ingest.client import RqDataClient

        client = RqDataClient(load_env_file=False)
        result = download_dominant_product_raw(
            client=client,
            output_root=args.output_dir,
            product=product,
            exchange=exchange,
            frequency=frequency,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        payload = error_payload("jm-one-year-raw", exc)
        write_json(args.output_dir / "rqdata_jm_raw_result.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 2

    payload = {
        "mode": "jm-one-year-raw",
        "disclaimer": DISCLAIMER,
        "rqdata_account_required": True,
        "credential_sources": credential_info["credential_sources"],
        "live_trading_used": False,
        "product": result["product"],
        "exchange": result["exchange"],
        "frequency": result["frequency"],
        "year": year,
        "date_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "symbol_mapping": result["symbol_mapping"],
        "raw": {
            "path": result["raw_path"],
            "row_count": result["row_count"],
            "start_datetime": result["start_datetime"],
            "end_datetime": result["end_datetime"],
            "fields": result["fields"],
        },
        "segments": result["segments"],
        "output_note": "Generated under experiments/rqdata_sample_acceptance/output/ and ignored by git.",
    }
    write_json(args.output_dir / "rqdata_jm_raw_result.json", payload)
    print(f"JM raw parquet written: {payload['raw']['path']}")
    print(f"row_count={payload['raw']['row_count']}")
    print(f"start_datetime={payload['raw']['start_datetime']}")
    print(f"end_datetime={payload['raw']['end_datetime']}")
    print("fields=" + ",".join(payload["raw"]["fields"]))
    return 0


def run_standardize_jm_raw(args: argparse.Namespace) -> int:
    try:
        raw_path = args.raw_path or _raw_path_from_result(args.output_dir / "rqdata_jm_raw_result.json")
        with session_scope(args.output_dir, args.use_app_db) as session:
            result = standardize_jm_raw_parquet(
                session=session,
                output_root=args.output_dir,
                raw_path=raw_path,
                symbol=args.product.lower(),
                exchange=args.exchange.upper(),
                interval=args.frequency.lower(),
            )
            session.commit()
    except Exception as exc:
        payload = error_payload("standardize-jm-raw", exc)
        write_json(args.output_dir / "rqdata_jm_standard_result.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 1

    payload = {
        "mode": "jm-standard-parquet",
        "disclaimer": DISCLAIMER,
        "live_trading_used": False,
        "database_mode": "app_db" if args.use_app_db else "isolated_sqlite",
        **result,
        "output_note": "Generated under experiments/rqdata_sample_acceptance/output/ and ignored by git.",
    }
    write_json(args.output_dir / "rqdata_jm_standard_result.json", payload)
    print(f"JM standard parquet written: {payload['standard']['path']}")
    print(f"row_count={payload['standard']['row_count']}")
    print(f"quality_status={payload['quality']['status']}")
    print(f"duckdb_rows={payload['duckdb']['row_count']}")
    print(f"reader_rows={payload['reader']['rows']}")
    print(f"local_parquet_provider_rows={payload['local_parquet_provider']['rows']}")
    return 0


def run_aggregate_jm_standard(args: argparse.Namespace) -> int:
    try:
        standard_path = args.standard_path or _standard_path_from_result(args.output_dir / "rqdata_jm_standard_result.json")
        with session_scope(args.output_dir, args.use_app_db) as session:
            result = aggregate_jm_standard_parquet(
                session=session,
                output_root=args.output_dir,
                standard_path=standard_path,
                target_intervals=("5m", "15m", "1d"),
            )
            session.commit()
    except Exception as exc:
        payload = error_payload("aggregate-jm-standard", exc)
        write_json(args.output_dir / "rqdata_jm_aggregate_result.json", payload)
        print(payload["error"]["message"], file=sys.stderr)
        return 1

    payload = {
        "mode": "jm-standard-aggregation",
        "disclaimer": DISCLAIMER,
        "live_trading_used": False,
        "database_mode": "app_db" if args.use_app_db else "isolated_sqlite",
        **result,
        "output_note": "Generated under experiments/rqdata_sample_acceptance/output/ and ignored by git.",
    }
    write_json(args.output_dir / "rqdata_jm_aggregate_result.json", payload)
    print(f"JM 1m standard source: {payload['source_1m']['path']}")
    for interval, summary in payload["aggregates"].items():
        print(f"{interval}_path={summary['path']}")
        print(f"{interval}_row_count={summary['row_count']}")
        print(f"{interval}_start_datetime={summary['start_datetime']}")
        print(f"{interval}_end_datetime={summary['end_datetime']}")
    return 0


def standardize_jm_raw_parquet(
    *,
    session: Session,
    output_root: Path,
    raw_path: Path,
    symbol: str,
    exchange: str,
    interval: str,
) -> dict[str, Any]:
    import pandas as pd

    from app.data_sources import LocalParquetProvider, MarketDataQuery
    from app.models.data_center import utc_now
    from app.models.data_center import DataQualityReport
    from app.services.market_data_reader import MarketDataReader
    from app.services.rqdata_ingest.bar_sample import (
        _ensure_reference_rows,
        _record_canonical_file_and_quality,
        _start_task,
        duckdb_bar_summary,
    )
    from app.services.rqdata_ingest.parquet import write_parquet_atomic

    if not raw_path.exists():
        raise FileNotFoundError(f"JM raw parquet not found: {raw_path}")
    raw_frame = pd.read_parquet(raw_path)
    if raw_frame.empty:
        raise ValueError(f"JM raw parquet is empty: {raw_path}")

    normalized_symbol = symbol.strip().lower()
    exchange_code = exchange.strip().upper()
    normalized_interval = interval.strip().lower()
    if normalized_interval != "1m":
        raise ValueError("JM standard acceptance requires interval/frequency=1m")

    standard_frame = normalize_jm_dominant_raw_frame(
        raw_frame,
        symbol=normalized_symbol,
        exchange=exchange_code,
        interval=normalized_interval,
        data_version=_standard_data_version(raw_frame, normalized_interval),
    )
    quality = evaluate_standard_dominant_quality(standard_frame, normalized_interval)
    standard_frame["quality_status"] = quality.status
    start_date = pd.to_datetime(standard_frame["datetime"].min()).date()
    end_date = pd.to_datetime(standard_frame["datetime"].max()).date()
    contract = f"{normalized_symbol}.MAIN"
    standard_path = _jm_standard_path(
        output_root,
        symbol=normalized_symbol,
        contract=contract,
        exchange=exchange_code,
        interval=normalized_interval,
        start_date=start_date,
        end_date=end_date,
    )
    write_parquet_atomic(standard_frame, standard_path)

    task = _start_task(
        session=session,
        symbol=normalized_symbol,
        contract=contract,
        frequency=normalized_interval,
        start_date=start_date,
        end_date=end_date,
    )
    _ensure_reference_rows(session, symbol=normalized_symbol, contract=contract, exchange=exchange_code)
    market_file = _record_canonical_file_and_quality(
        session=session,
        task=task,
        path=standard_path,
        frame=standard_frame,
        quality=quality,
        symbol=normalized_symbol,
        contract=contract,
        frequency=normalized_interval,
        data_version=str(standard_frame["data_version"].iloc[0]),
    )
    task.status = "success" if quality.status != "failed" else "failed"
    task.progress = 100
    task.finished_at = utc_now()
    task.result = {
        "raw_file": str(raw_path),
        "canonical_file": str(standard_path),
        "row_count": len(standard_frame),
        "quality_status": quality.status,
    }
    session.flush()

    duckdb_summary = duckdb_bar_summary(standard_path)
    query_start = datetime.min
    query_end = datetime.max
    reader_rows = MarketDataReader(session=session, project_root=PROJECT_ROOT).load_bars(
        symbol=normalized_symbol,
        contract=contract,
        period=normalized_interval,
        start=query_start,
        end=query_end,
        provider="rqdata",
    )
    provider_rows = LocalParquetProvider(session=session, project_root=PROJECT_ROOT).get_bars(
        MarketDataQuery(
            symbol=normalized_symbol,
            contract=contract,
            period=normalized_interval,
            start=query_start,
            end=query_end,
        )
    )
    quality_report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
    return {
        "raw": {
            "path": str(raw_path),
            "row_count": len(raw_frame),
        },
        "standard": {
            "path": str(standard_path),
            "row_count": len(standard_frame),
            "start_datetime": standard_frame["datetime"].min().isoformat(),
            "end_datetime": standard_frame["datetime"].max().isoformat(),
            "fields": list(standard_frame.columns),
            "contracts": sorted(standard_frame["source_symbol"].dropna().unique().tolist()),
        },
        "quality": {
            "status": quality.status,
            "missing_bars": quality.missing_bars,
            "duplicated_bars": quality.duplicated_bars,
            "abnormal_price_count": quality.abnormal_price_count,
            "abnormal_volume_count": quality.abnormal_volume_count,
            "abnormal_open_interest_count": quality.abnormal_open_interest_count,
            "details": quality.details,
        },
        "data_quality_report": {
            "id": None if quality_report is None else quality_report.id,
            "status": None if quality_report is None else quality_report.status,
            "missing_bars": None if quality_report is None else quality_report.missing_bars,
            "duplicated_bars": None if quality_report is None else quality_report.duplicated_bars,
            "abnormal_price_count": None if quality_report is None else quality_report.abnormal_price_count,
            "abnormal_volume_count": None if quality_report is None else quality_report.abnormal_volume_count,
        },
        "duckdb": duckdb_summary,
        "reader": {
            "rows": len(reader_rows),
        },
        "local_parquet_provider": {
            "rows": len(provider_rows),
        },
        "formal_backtest_allowed": quality.status == "passed",
        "failed_data_blocked_from_formal_backtest": quality.status != "failed",
    }


def aggregate_jm_standard_parquet(
    *,
    session: Session,
    output_root: Path,
    standard_path: Path,
    target_intervals: tuple[str, ...],
) -> dict[str, Any]:
    import pandas as pd

    from app.data_sources import LocalParquetProvider, MarketDataQuery
    from app.models.data_center import DataQualityReport, utc_now
    from app.services.market_data_reader import MarketDataReader
    from app.services.rqdata_ingest.bar_sample import (
        _ensure_reference_rows,
        _record_canonical_file_and_quality,
        _start_task,
        duckdb_bar_summary,
    )
    from app.services.rqdata_ingest.parquet import write_parquet_atomic

    if not standard_path.exists():
        raise FileNotFoundError(f"JM 1m standard parquet not found: {standard_path}")
    source_frame = pd.read_parquet(standard_path)
    if source_frame.empty:
        raise ValueError(f"JM 1m standard parquet is empty: {standard_path}")
    _validate_standard_1m_source(source_frame, standard_path)

    normalized_symbol = str(source_frame["symbol"].iloc[0]).strip().lower()
    contract = str(source_frame["contract"].iloc[0]).strip()
    exchange_code = str(source_frame["exchange"].iloc[0]).strip().upper()
    query_start = datetime.min
    query_end = datetime.max
    reader = MarketDataReader(session=session, project_root=PROJECT_ROOT)
    provider = LocalParquetProvider(session=session, project_root=PROJECT_ROOT)
    aggregates: dict[str, Any] = {}

    for interval in target_intervals:
        aggregate_frame = aggregate_standard_bars(source_frame, interval)
        if aggregate_frame.empty:
            raise ValueError(f"JM aggregation produced empty {interval} frame from {standard_path}")
        quality = evaluate_standard_dominant_quality(aggregate_frame, interval)
        aggregate_frame["quality_status"] = quality.status
        start_date = pd.to_datetime(aggregate_frame["datetime"].min()).date()
        end_date = pd.to_datetime(aggregate_frame["datetime"].max()).date()
        aggregate_path = _jm_standard_path(
            output_root,
            symbol=normalized_symbol,
            contract=contract,
            exchange=exchange_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        write_parquet_atomic(aggregate_frame, aggregate_path)

        task = _start_task(
            session=session,
            symbol=normalized_symbol,
            contract=contract,
            frequency=interval,
            start_date=start_date,
            end_date=end_date,
        )
        _ensure_reference_rows(session, symbol=normalized_symbol, contract=contract, exchange=exchange_code)
        market_file = _record_canonical_file_and_quality(
            session=session,
            task=task,
            path=aggregate_path,
            frame=aggregate_frame,
            quality=quality,
            symbol=normalized_symbol,
            contract=contract,
            frequency=interval,
            data_version=str(aggregate_frame["data_version"].iloc[0]),
        )
        task.status = "success" if quality.status != "failed" else "failed"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "source_1m_file": str(standard_path),
            "canonical_file": str(aggregate_path),
            "row_count": len(aggregate_frame),
            "quality_status": quality.status,
        }
        session.flush()

        duckdb_summary = duckdb_bar_summary(aggregate_path)
        reader_rows = reader.load_bars(
            symbol=normalized_symbol,
            contract=contract,
            period=interval,
            start=query_start,
            end=query_end,
            provider="rqdata",
        )
        provider_rows = provider.get_bars(
            MarketDataQuery(
                symbol=normalized_symbol,
                contract=contract,
                period=interval,
                start=query_start,
                end=query_end,
            )
        )
        quality_report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        aggregates[interval] = {
            "path": str(aggregate_path),
            "row_count": len(aggregate_frame),
            "start_datetime": aggregate_frame["datetime"].min().isoformat(),
            "end_datetime": aggregate_frame["datetime"].max().isoformat(),
            "fields": list(aggregate_frame.columns),
            "quality": {
                "status": quality.status,
                "missing_bars": quality.missing_bars,
                "duplicated_bars": quality.duplicated_bars,
                "abnormal_price_count": quality.abnormal_price_count,
                "abnormal_volume_count": quality.abnormal_volume_count,
                "abnormal_open_interest_count": quality.abnormal_open_interest_count,
                "details": quality.details,
            },
            "data_quality_report": {
                "id": None if quality_report is None else quality_report.id,
                "status": None if quality_report is None else quality_report.status,
            },
            "duckdb": duckdb_summary,
            "reader": {"rows": len(reader_rows)},
            "local_parquet_provider": {"rows": len(provider_rows)},
            "formal_backtest_allowed": quality.status == "passed",
        }

    return {
        "source_1m": {
            "path": str(standard_path),
            "row_count": len(source_frame),
            "start_datetime": pd.to_datetime(source_frame["datetime"]).min().isoformat(),
            "end_datetime": pd.to_datetime(source_frame["datetime"]).max().isoformat(),
        },
        "symbol_mapping": {
            "symbol": normalized_symbol,
            "contract": contract,
            "exchange": exchange_code,
            "project_vt_symbol": f"{contract}.{exchange_code}",
            "source_contracts": sorted(source_frame["source_symbol"].dropna().astype(str).unique().tolist()),
        },
        "aggregation_rule": {
            "source_interval": "1m",
            "target_intervals": list(target_intervals),
            "minute_grouping": "source_symbol + trading_day + time_gap_session_block + sequential_completed_1m_bucket",
            "daily_grouping": "trading_day, not natural calendar day",
            "ohlcv": {
                "open": "first 1m open",
                "high": "max high",
                "low": "min low",
                "close": "last 1m close",
                "volume": "sum",
                "turnover": "sum",
                "open_interest": "last",
            },
            "future_function_guard": "Aggregated bar datetime is the last included 1m bar datetime; no bar uses rows after its own close.",
        },
        "aggregates": aggregates,
    }


def aggregate_standard_bars(frame: Any, interval: str) -> Any:
    import pandas as pd

    normalized_interval = interval.strip().lower()
    required = {
        "symbol",
        "contract",
        "exchange",
        "vt_symbol",
        "datetime",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "open_interest",
        "source",
        "provider",
        "source_symbol",
        "data_role",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"JM standard frame missing required columns for aggregation: {missing}")
    if normalized_interval not in {"5m", "15m", "1d"}:
        raise ValueError(f"unsupported JM aggregation interval: {interval}")

    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data["trading_day"] = pd.to_datetime(data["trading_day"], errors="coerce").dt.date
    data = data.dropna(subset=["datetime", "trading_day", "open", "high", "low", "close"])
    data = data.sort_values(["source_symbol", "trading_day", "datetime"]).reset_index(drop=True)
    if data.empty:
        return data

    if normalized_interval == "1d":
        group_keys = ["symbol", "contract", "exchange", "vt_symbol", "trading_day"]
        group_values = data[group_keys].astype({"trading_day": "object"})
        data["_bucket"] = group_values.apply(lambda row: tuple(row), axis=1)
    else:
        minutes = int(normalized_interval.removesuffix("m"))
        previous_datetime = data.groupby(["source_symbol", "trading_day"])["datetime"].shift()
        gap_seconds = (data["datetime"] - previous_datetime).dt.total_seconds()
        data["_block"] = gap_seconds.isna() | (gap_seconds > 90)
        data["_block"] = data.groupby(["source_symbol", "trading_day"])["_block"].cumsum()
        data["_offset"] = data.groupby(["source_symbol", "trading_day", "_block"]).cumcount()
        data["_bucket_index"] = data["_offset"] // minutes
        data["_bucket"] = list(zip(data["source_symbol"], data["trading_day"], data["_block"], data["_bucket_index"], strict=False))

    grouped = data.groupby("_bucket", sort=False, dropna=False)
    first = grouped.head(1).set_index("_bucket")
    last = grouped.tail(1).set_index("_bucket")
    result = pd.DataFrame(
        {
            "symbol": first["symbol"],
            "contract": first["contract"],
            "exchange": first["exchange"],
            "vt_symbol": first["vt_symbol"],
            "datetime": last["datetime"],
            "trading_day": first["trading_day"],
            "interval": normalized_interval,
            "period": normalized_interval,
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
            "turnover": grouped["turnover"].sum(),
            "open_interest": grouped["open_interest"].last(),
            "source": first["source"],
            "provider": first["provider"],
            "source_symbol": last["source_symbol"],
            "data_role": first["data_role"],
            "quality_status": "unchecked",
            "data_version": _aggregated_data_version(data, normalized_interval),
            "created_at": first["created_at"] if "created_at" in first.columns else pd.Timestamp.utcnow().to_pydatetime(),
            "source_interval": "1m",
            "source_bar_count": grouped.size(),
        }
    )
    result = result.sort_values("datetime").reset_index(drop=True)
    return result[
        [
            "symbol",
            "contract",
            "exchange",
            "vt_symbol",
            "datetime",
            "trading_day",
            "interval",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "source",
            "provider",
            "source_symbol",
            "data_role",
            "quality_status",
            "data_version",
            "created_at",
            "source_interval",
            "source_bar_count",
        ]
    ]


def _validate_standard_1m_source(frame: Any, path: Path) -> None:
    periods = set(frame.get("period", frame.get("interval", [])).dropna().astype(str).str.lower())
    intervals = set(frame.get("interval", frame.get("period", [])).dropna().astype(str).str.lower())
    if periods and periods != {"1m"}:
        raise ValueError(f"JM standard source must be period=1m: {path}")
    if intervals and intervals != {"1m"}:
        raise ValueError(f"JM standard source must be interval=1m: {path}")


def _aggregated_data_version(frame: Any, interval: str) -> str:
    import pandas as pd

    start = pd.to_datetime(frame["datetime"]).min().date()
    end = pd.to_datetime(frame["datetime"]).max().date()
    return f"rqdata_jm_standard_{interval}_{start:%Y%m%d}_{end:%Y%m%d}_v1"


def normalize_jm_dominant_raw_frame(
    raw_frame: Any,
    *,
    symbol: str,
    exchange: str,
    interval: str,
    data_version: str,
) -> Any:
    import pandas as pd

    from app.models.data_center import utc_now

    raw = raw_frame.copy()
    datetimes = _raw_datetime_series(raw)
    source_symbol = raw.get("rqdata_order_book_id", raw.get("order_book_id", raw.get("project_contract")))
    if source_symbol is None:
        raise ValueError("JM raw frame missing source contract column")
    source_symbol = source_symbol.astype(str).str.lower()
    contract = f"{symbol}.MAIN"
    frame = pd.DataFrame(
        {
            "symbol": symbol,
            "contract": contract,
            "exchange": exchange,
            "vt_symbol": f"{contract}.{exchange}",
            "datetime": datetimes,
            "trading_day": _trading_day_series(raw, datetimes),
            "interval": interval,
            "period": interval,
            "open": _numeric_series(raw, "open"),
            "high": _numeric_series(raw, "high"),
            "low": _numeric_series(raw, "low"),
            "close": _numeric_series(raw, "close"),
            "volume": _numeric_series(raw, "volume", default=0.0),
            "turnover": _numeric_series(raw, "turnover", "total_turnover", "amount", default=0.0),
            "open_interest": _numeric_series(raw, "open_interest", "open_oi", "close_oi", default=0.0),
            "source": "rqdata",
            "provider": "rqdata",
            "source_symbol": source_symbol,
            "data_role": "primary",
            "quality_status": "unchecked",
            "data_version": data_version,
            "created_at": utc_now(),
        }
    )
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return frame[
        [
            "symbol",
            "contract",
            "exchange",
            "vt_symbol",
            "datetime",
            "trading_day",
            "interval",
            "period",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "source",
            "provider",
            "source_symbol",
            "data_role",
            "quality_status",
            "data_version",
            "created_at",
        ]
    ]


def evaluate_standard_dominant_quality(frame: Any, interval: str) -> Any:
    from app.services.rqdata_ingest.bar_sample import BarQuality
    from app.services.trader_future_importer import CHECK_RULE_VERSION

    sorted_frame = frame.sort_values("datetime")
    duplicate_subset = ["datetime"]
    duplicated_mask = sorted_frame.duplicated(subset=duplicate_subset)
    abnormal_price_mask = (sorted_frame["high"] < sorted_frame[["open", "close", "low"]].max(axis=1)) | (
        sorted_frame["low"] > sorted_frame[["open", "close", "high"]].min(axis=1)
    )
    abnormal_volume_mask = sorted_frame["volume"] < 0
    abnormal_open_interest_mask = sorted_frame["open_interest"].notna() & (sorted_frame["open_interest"] < 0)
    gap_samples = _gap_samples(sorted_frame, interval)
    abnormal_price_count = int(abnormal_price_mask.sum())
    abnormal_volume_count = int(abnormal_volume_mask.sum())
    abnormal_open_interest_count = int(abnormal_open_interest_mask.sum())
    duplicate_count = int(duplicated_mask.sum())
    failed_count = abnormal_price_count + abnormal_volume_count + abnormal_open_interest_count + duplicate_count
    status = "failed" if failed_count > 0 else "passed"
    return BarQuality(
        status=status,
        missing_bars=0,
        duplicated_bars=duplicate_count,
        abnormal_price_count=abnormal_price_count,
        abnormal_volume_count=abnormal_volume_count,
        abnormal_open_interest_count=abnormal_open_interest_count,
        details={
            "check_rule_version": CHECK_RULE_VERSION,
            "check_mode": "dominant_1m_raw_to_standard_without_session_calendar",
            "empty": bool(sorted_frame.empty),
            "missing_bars": 0,
            "missing_bar_note": "Trading-session calendar is not applied in P0-003; natural lunch, night, holiday and weekend gaps are reported as gap_samples only.",
            "gap_count": len(gap_samples),
            "gap_samples": gap_samples[:20],
            "duplicate_samples": _datetime_samples(sorted_frame.loc[duplicated_mask, "datetime"]),
            "abnormal_price_samples": _datetime_samples(sorted_frame.loc[abnormal_price_mask, "datetime"]),
            "abnormal_volume_samples": _datetime_samples(sorted_frame.loc[abnormal_volume_mask, "datetime"]),
            "abnormal_open_interest_count": abnormal_open_interest_count,
            "abnormal_open_interest_samples": _datetime_samples(sorted_frame.loc[abnormal_open_interest_mask, "datetime"]),
            "datetime_timezone": "naive_local_exchange_time",
            "trading_day_source": "rqdata_trading_date_or_exchange_day_roll",
            "source_contracts": sorted(sorted_frame["source_symbol"].dropna().unique().tolist()),
        },
    )


def _raw_path_from_result(result_path: Path) -> Path:
    if not result_path.exists():
        raise FileNotFoundError(f"JM raw result JSON not found: {result_path}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    raw_path = ((payload.get("raw") or {}).get("path") or "").strip()
    if not raw_path:
        raise ValueError(f"JM raw result JSON does not include raw.path: {result_path}")
    return Path(raw_path)


def _standard_path_from_result(result_path: Path) -> Path:
    if not result_path.exists():
        raise FileNotFoundError(f"JM standard result JSON not found: {result_path}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    standard_path = ((payload.get("standard") or {}).get("path") or "").strip()
    if not standard_path:
        raise ValueError(f"JM standard result JSON does not include standard.path: {result_path}")
    return Path(standard_path)


def _standard_data_version(frame: Any, interval: str) -> str:
    import pandas as pd

    datetimes = _raw_datetime_series(frame)
    start = pd.to_datetime(datetimes.min()).date()
    end = pd.to_datetime(datetimes.max()).date()
    return f"rqdata_jm_standard_{interval}_{start:%Y%m%d}_{end:%Y%m%d}_v1"


def _jm_standard_path(
    output_root: Path,
    *,
    symbol: str,
    contract: str,
    exchange: str,
    interval: str,
    start_date: date,
    end_date: date,
) -> Path:
    safe_contract = contract.replace(".", "_")
    return (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={interval}"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"contract={contract}"
        / f"{safe_contract}_{interval}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )


def _trading_day_series(raw: Any, datetimes: Any):
    import pandas as pd

    if "trading_date" in raw.columns:
        values = pd.to_datetime(raw["trading_date"], errors="coerce")
        if values.notna().any():
            return values.dt.date
    return pd.to_datetime(datetimes, errors="coerce").map(lambda value: (value + pd.Timedelta(days=1)).date() if value.hour >= 21 else value.date())


def _numeric_series(frame: Any, *columns: str, default: float | None = None):
    import pandas as pd

    for column in columns:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").astype("float64")
    if default is not None:
        return pd.Series([default] * len(frame), index=frame.index, dtype="float64")
    raise ValueError(f"JM raw frame missing required numeric column; tried {list(columns)}")


def _gap_samples(frame: Any, interval: str) -> list[dict[str, Any]]:
    import pandas as pd

    expected_delta = _frequency_delta(interval)
    unique_times = list(pd.to_datetime(frame["datetime"]).drop_duplicates().sort_values())
    samples: list[dict[str, Any]] = []
    for previous, current in zip(unique_times, unique_times[1:], strict=False):
        diff = current.to_pydatetime() - previous.to_pydatetime()
        if diff <= expected_delta:
            continue
        if len(samples) < 50:
            samples.append(
                {
                    "from": previous.isoformat(),
                    "to": current.isoformat(),
                    "gap_seconds": int(diff.total_seconds()),
                    "expected_seconds": int(expected_delta.total_seconds()),
                }
            )
    return samples


def _frequency_delta(interval: str) -> timedelta:
    normalized = interval.strip().lower()
    if normalized == "1m":
        return timedelta(minutes=1)
    if normalized == "5m":
        return timedelta(minutes=5)
    if normalized == "15m":
        return timedelta(minutes=15)
    if normalized == "60m":
        return timedelta(minutes=60)
    if normalized == "1d":
        return timedelta(days=1)
    raise ValueError(f"unsupported interval: {interval}")


def _datetime_samples(values: Any) -> list[str]:
    return [value.isoformat() for value in values.head(10)]


def download_dominant_product_raw(
    *,
    client: Any,
    output_root: Path,
    product: str,
    exchange: str,
    frequency: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    import pandas as pd

    from app.services.rqdata_ingest.parquet import write_parquet_atomic
    from app.vnpy_integration.symbol_mapper import to_vt_symbol

    rq_product = client.underlying_symbol(product)
    dominant = client.dominant_contracts(rq_product, start_date, end_date, rank=1)
    dominant_records = _dominant_contract_records(dominant)
    if not dominant_records:
        raise ValueError(f"RQData returned no dominant contract mapping for product={rq_product} {start_date}..{end_date}")

    frames: list[pd.DataFrame] = []
    segments: list[dict[str, Any]] = []
    for segment in _contract_segments(dominant_records, start_date=start_date, end_date=end_date):
        frame = client.contract_bars(segment["rqdata_order_book_id"], segment["start_date"], segment["end_date"], frequency)
        if frame.empty:
            segments.append({**segment, "row_count": 0, "status": "empty"})
            continue
        raw = frame.copy()
        if not any(column in raw.columns for column in ("datetime", "date", "trading_date", "index")):
            raw["index"] = raw.index
        raw["rqdata_product"] = rq_product
        raw["rqdata_order_book_id"] = segment["rqdata_order_book_id"]
        raw["project_contract"] = segment["project_contract"]
        raw["exchange"] = exchange
        raw["frequency"] = frequency
        raw["segment_start"] = segment["start_date"].isoformat()
        raw["segment_end"] = segment["end_date"].isoformat()
        frames.append(raw)
        segments.append({**segment, "row_count": len(raw), "status": "downloaded"})

    if not frames:
        raise ValueError(f"RQData returned no raw 1m rows for product={rq_product} {start_date}..{end_date}")

    output = pd.concat(frames, ignore_index=True)
    datetimes = _raw_datetime_series(output)
    output["datetime"] = datetimes
    output = output.sort_values(["datetime", "rqdata_order_book_id"]).reset_index(drop=True)

    product_key = rq_product.lower()
    raw_path = (
        output_root
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / f"product={product_key}"
        / f"frequency={frequency}"
        / f"year={start_date:%Y}"
        / f"{product_key}_{frequency}_dominant_raw_{start_date:%Y%m%d}_{end_date:%Y%m%d}.parquet"
    )
    write_parquet_atomic(output, raw_path)

    project_contracts = sorted({str(value) for value in output["project_contract"].dropna().unique()})
    rqdata_contracts = sorted({str(value) for value in output["rqdata_order_book_id"].dropna().unique()})
    return {
        "product": product_key,
        "exchange": exchange,
        "frequency": frequency,
        "raw_path": str(raw_path),
        "row_count": len(output),
        "start_datetime": output["datetime"].min().isoformat(),
        "end_datetime": output["datetime"].max().isoformat(),
        "fields": list(output.columns),
        "segments": segments,
        "symbol_mapping": {
            "rqdata_product": rq_product,
            "rqdata_order_book_ids": rqdata_contracts,
            "project_contracts": project_contracts,
            "project_vt_symbols": [to_vt_symbol(contract, exchange) for contract in project_contracts],
            "vnpy_vt_symbols_by_current_symbol_mapper": [to_vt_symbol(contract, exchange) for contract in project_contracts],
        },
    }


def latest_complete_year(today: date | None = None) -> int:
    today = today or date.today()
    return today.year - 1


def _dominant_contract_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    records: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        trade_date = _record_date(record)
        contract = _record_contract(record)
        if trade_date is None or not contract:
            continue
        records.append({"trade_date": trade_date, "rqdata_order_book_id": contract})
    return sorted(records, key=lambda item: item["trade_date"])


def _raw_datetime_series(frame: Any):
    import pandas as pd

    for column in ("datetime", "date", "trading_date", "index"):
        if column in frame.columns:
            values = pd.to_datetime(frame[column], errors="coerce")
            if values.notna().any():
                return values
    values = pd.to_datetime(frame.index, errors="coerce")
    if values.notna().any():
        return pd.Series(values, index=frame.index)
    raise ValueError("RQData raw frame does not contain a datetime-like column or index")


def _record_date(record: dict[str, Any]) -> date | None:
    import pandas as pd

    for key in ("date", "trade_date", "trading_date", "datetime", "index"):
        value = record.get(key)
        if value is None or pd.isna(value):
            continue
        try:
            return pd.to_datetime(value).date()
        except Exception:
            continue
    return None


def _record_contract(record: dict[str, Any]) -> str:
    import pandas as pd

    for key in ("contract", "order_book_id", "dominant_id", "dominant", "symbol", "underlying_order_book_id"):
        value = record.get(key)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip().upper()
    for value in record.values():
        if value is not None and not pd.isna(value) and str(value).strip().upper().startswith("JM"):
            return str(value).strip().upper()
    return ""


def _contract_segments(records: list[dict[str, Any]], *, start_date: date, end_date: date) -> list[dict[str, Any]]:
    if not records:
        return []
    segments: list[dict[str, Any]] = []
    current_contract = records[0]["rqdata_order_book_id"]
    current_start = max(records[0]["trade_date"], start_date)
    previous_date = records[0]["trade_date"]
    for record in records[1:]:
        trade_date = record["trade_date"]
        contract = record["rqdata_order_book_id"]
        if contract != current_contract:
            segments.append(_segment(current_contract, current_start, min(previous_date, end_date)))
            current_contract = contract
            current_start = max(trade_date, start_date)
        previous_date = trade_date
    segments.append(_segment(current_contract, current_start, min(previous_date, end_date)))
    return [item for item in segments if item["start_date"] <= item["end_date"]]


def _segment(contract: str, start_date: date, end_date: date) -> dict[str, Any]:
    return {
        "rqdata_order_book_id": contract,
        "project_contract": contract.lower(),
        "start_date": start_date,
        "end_date": end_date,
    }


def run_optional_backtest(session: Session, args: argparse.Namespace, result: Any) -> dict[str, Any]:
    if result.quality.status != "passed":
        return {
            "requested": True,
            "executed": False,
            "skipped_reason": "vn.py runner accepts only quality_status=passed standard bars",
        }
    try:
        from app.backtest.runner import BacktestTaskRunner
        from app.backtest.service import BacktestService
        from app.schemas.backtest import BacktestTaskConfig

        config = BacktestTaskConfig(
            engine_type="vnpy",
            task_type="single",
            symbol=args.contract.lower(),
            exchange=args.exchange.upper(),
            interval=args.frequency,
            start=_date_time_from_iso(result.duckdb_summary["start_time"]),
            end=_date_time_from_iso(result.duckdb_summary["end_time"]),
            strategy_class_path="guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy",
            strategy_code="su_bing_ema21",
            strategy_version="rqdata-sample-smoke",
            strategy_parameters={},
            rate=0.0001,
            slippage=1,
            size=10,
            pricetick=1,
            capital=100000,
            data_source="rqdata",
            data_role="primary",
            data_version=result.data_version,
            research_only=False,
            quality_status=result.quality.status,
            bar_data_path=str(result.canonical_path),
        )
        task = BacktestService(session).create_task(config)
        session.commit()
        runner_result = BacktestTaskRunner(session).run(task.id)
        session.commit()
        return {
            "requested": True,
            "executed": runner_result.get("status") == "success",
            "task_id": task.id,
            "task_no": task.task_no,
            "report_id": task.reports[0].id if task.reports else None,
            "status": runner_result.get("status"),
        }
    except Exception as exc:
        session.rollback()
        return {"requested": True, "executed": False, "error": str(exc)}


@contextmanager
def session_scope(output_dir: Path, use_app_db: bool):
    if use_app_db:
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            yield session
        return

    import app.models  # noqa: F401
    from app.db.base import Base

    db_path = output_dir / "rqdata_sample.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        yield session


def error_payload(stage: str, exc: Exception) -> dict[str, Any]:
    message = str(exc) or CREDENTIAL_MESSAGE
    if isinstance(exc, MissingRqDataCredentials):
        message = CREDENTIAL_MESSAGE
    return {
        "mode": "rqdata-small-sample",
        "stage": stage,
        "rqdata_account_required": True,
        "live_trading_used": False,
        "error": {
            "type": exc.__class__.__name__,
            "message": message,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _date_time_from_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


class MissingRqDataCredentials(RuntimeError):
    """Raised when no RQData credential environment variables are present."""


def check_rqdata_credential_environment() -> dict[str, Any]:
    import os

    has_uri = bool(os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF"))
    has_license = bool(os.getenv("RQDATA_LICENSE_KEY"))
    has_username_password = bool(os.getenv("RQDATA_USERNAME") and os.getenv("RQDATA_PASSWORD"))
    configured = has_uri or has_license or has_username_password
    if not configured:
        raise MissingRqDataCredentials(CREDENTIAL_MESSAGE)
    return {
        "configured": True,
        "credential_sources": {
            "uri": has_uri,
            "license_key": has_license,
            "username_password": has_username_password,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
