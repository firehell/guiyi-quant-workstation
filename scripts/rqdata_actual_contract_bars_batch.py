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

from rqdata_sync_common import (  # noqa: E402
    run_with_manifest,
    selected_products,
)

DEFAULT_PERIODS = ("1m", "5m", "15m", "30m", "60m")
MANIFEST_NAME = "rqdata_actual_contract_bars_batch"
SENSITIVE_ENV_NAMES = (
    "RQDATAC2_CONF",
    "RQDATAC_CONF",
    "RQDATA_LICENSE_KEY",
    "RQDATA_USERNAME",
    "RQDATA_PASSWORD",
    "RQDATA_ADDR",
    "QYWX_WEBHOOK_URL",
)


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch sync actual-contract historical bars. Defaults to dry-run.")
    parser.add_argument("--trade-date", type=date.fromisoformat, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--product", action="append", dest="products")
    parser.add_argument("--all-products", action="store_true")
    parser.add_argument("--periods", default=",".join(DEFAULT_PERIODS))
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--roll-segments", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the non-mutating plan. Default when --run-write is absent.")
    parser.add_argument("--run-write", action="store_true", help="Explicitly run the batch write path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    periods = _parse_periods(args.periods)
    try:
        from app.db.session import SessionLocal
        from app.services.rqdata_ingest.actual_contract_bars_batch import run_actual_contract_bars_batch

        with SessionLocal() as session:
            products = selected_products(session, args.products, all_products=args.all_products, limit=args.limit)
            if args.limit is not None:
                products = products[: args.limit]

            if args.dry_run or not args.run_write:
                payload = run_actual_contract_bars_batch(
                    session=session,
                    client=None,
                    output_root=args.output_root,
                    products=products,
                    trade_date=args.trade_date,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    periods=periods,
                    dry_run=True,
                    roll_segments=args.roll_segments,
                )
                payload["credential_presence"] = credential_presence(source_env)
                print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
                return 0

            from app.services.rqdata_ingest.client import RqDataClient

            client = RqDataClient(load_env_file=True)

            def run_product(product: str) -> str:
                normalized = product.strip().lower()
                try:
                    result = run_actual_contract_bars_batch(
                        session=session,
                        client=client,
                        output_root=args.output_root,
                        products=[normalized],
                        trade_date=args.trade_date,
                        start_date=args.start_date,
                        end_date=args.end_date,
                        periods=periods,
                        dry_run=False,
                        roll_segments=args.roll_segments,
                    )
                    session.commit()
                    if result["failure_count"]:
                        raise RuntimeError(result["failures"].get(normalized) or "batch write failed")
                    actual = result["results"][normalized]["actual_contract"]
                    return f"actual_contract={actual} periods={len(periods)}"
                except Exception:
                    session.rollback()
                    raise

            run_with_manifest(
                argparse.Namespace(
                    dry_run=False,
                    resume=args.resume,
                    retry_failed=True,
                    limit=args.limit,
                ),
                MANIFEST_NAME,
                products,
                run_product,
            )
            print(json.dumps({"mode": "write", "status": "completed", "products": products}, ensure_ascii=False, indent=2))
            return 0
    except Exception as exc:  # noqa: BLE001
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


if __name__ == "__main__":
    raise SystemExit(main())
