from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


SENSITIVE_ENV_NAMES = (
    "RQDATAC2_CONF",
    "RQDATAC_CONF",
    "RQDATA_LICENSE_KEY",
    "RQDATA_USERNAME",
    "RQDATA_PASSWORD",
    "RQDATA_ADDR",
    "QYWX_WEBHOOK_URL",
)

DEFAULT_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 8.5-6 JM actual-contract historical bars pilot. Defaults to dry-run.")
    parser.add_argument("--product", default="jm")
    parser.add_argument("--trade-date", type=date.fromisoformat, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--periods", default=",".join(DEFAULT_PERIODS))
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--dry-run", action="store_true", help="Print the non-mutating plan. This is also the default when --run-write is absent.")
    parser.add_argument("--run-write", action="store_true", help="Explicitly run the pilot write path. Requires DB and RQData access.")
    return parser.parse_args(argv)


def credential_presence(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = environ if environ is not None else os.environ
    return {name: "present" if source.get(name) else "missing" for name in SENSITIVE_ENV_NAMES}


def redact_message(message: Any, environ: Mapping[str, str] | None = None) -> str:
    text = "" if message is None else str(message)
    source = environ if environ is not None else os.environ
    for name in SENSITIVE_ENV_NAMES:
        value = source.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    periods = _parse_periods(args.periods)
    try:
        if args.dry_run or not args.run_write:
            payload = _dry_run_payload(
                product=args.product,
                trade_date=args.trade_date,
                start_date=args.start_date,
                end_date=args.end_date,
                periods=periods,
                output_root=args.output_root,
            )
            payload["credential_presence"] = credential_presence(source_env)
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return 0

        from app.services.rqdata_ingest.actual_contract_bars_pilot import (
            run_actual_contract_bars_pilot_write,
        )

        from app.db.session import SessionLocal
        from app.services.rqdata_ingest.client import RqDataClient

        client = RqDataClient(load_env_file=True)
        with SessionLocal() as session:
            result = run_actual_contract_bars_pilot_write(
                session=session,
                client=client,
                output_root=args.output_root,
                product=args.product,
                trade_date=args.trade_date,
                start_date=args.start_date,
                end_date=args.end_date,
                periods=periods,
            )
            session.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI should provide structured, redacted failure for GPT handoff.
        print(
            json.dumps(
                {
                    "mode": "write" if args.run_write and not args.dry_run else "dry-run",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": redact_message(exc, source_env),
                    "credential_presence": credential_presence(source_env),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


def _parse_periods(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _dry_run_payload(
    *,
    product: str,
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
    output_root: Path,
) -> dict[str, Any]:
    normalized_product = product.strip().lower()
    return {
        "mode": "dry-run",
        "stage": "DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-WRITE",
        "provider": "rqdata",
        "product": normalized_product,
        "continuous_contract": f"{normalized_product}.MAIN",
        "actual_contract": None,
        "trade_date": trade_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": list(periods),
        "output_root": str(output_root),
        "would_construct_rqdata_client": False,
        "would_open_database_session": False,
        "would_call_rqdata": False,
        "would_write_parquet": False,
        "would_write_manifest": False,
        "would_write_database": False,
        "would_register_primary": False,
        "would_send_wechat": False,
        "would_trigger_strategy": False,
        "would_run_backtest": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
