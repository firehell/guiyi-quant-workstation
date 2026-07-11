from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled JM after-market archive")
    parser.add_argument("--trading-day", type=date.fromisoformat, required=True)
    parser.add_argument("--product", default="jm", choices=("jm",))
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--run-write", action="store_true")
    parser.add_argument("--confirm-after-market-archive", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    enabled = str(source_env.get("GUIYI_AFTER_MARKET_ARCHIVE_ENABLED") or "").lower() in {"1", "true", "yes", "on"}
    if not args.run_write:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "product": args.product,
                    "trading_day": args.trading_day.isoformat(),
                    "output_root": str(args.output_root),
                    "enabled": enabled,
                    "would_construct_rqdata_client": False,
                    "would_open_database": False,
                    "would_write_database": False,
                    "would_write_parquet": False,
                    "would_register_primary": False,
                    "would_send_notification": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not enabled or not args.confirm_after_market_archive:
        print(json.dumps({"status": "blocked", "enabled": enabled, "confirmation": args.confirm_after_market_archive}, ensure_ascii=False))
        return 2

    try:
        from app.db.session import SessionLocal
        from app.services.after_market_archive import AfterMarketArchiveService
        from app.services.rqdata_ingest.client import RqDataClient

        client = RqDataClient(load_env_file=True)
        with SessionLocal() as session:
            result = AfterMarketArchiveService(
                session=session,
                client=client,
                output_root=args.output_root,
            ).archive_once(
                trading_day=args.trading_day,
                enabled=True,
                confirmed=True,
                product=args.product,
            )
            session.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] in {"success", "already_archived"} else 1
    except Exception as exc:  # noqa: BLE001 - CLI must return a bounded failure.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
