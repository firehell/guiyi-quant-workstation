#!/usr/bin/env python3
"""RQData small sample acceptance runner.

This script intentionally keeps real market data under an ignored experiment
output directory. It does not accept account secrets as CLI arguments.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import create_engine
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
