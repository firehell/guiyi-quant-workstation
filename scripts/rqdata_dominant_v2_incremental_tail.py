from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import Instrument  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_incremental import append_dominant_v2_tail  # noqa: E402
from app.services.rqdata_ingest.profile_aware_incremental import (  # noqa: E402
    audit_profile_incremental_orphans,
    rollback_profile_aware_incremental_closure,
    run_profile_aware_incremental_closure,
)
from rqdata_sync_common import products_from_file  # noqa: E402


DEFAULT_PERIODS = ("1m", "1d", "1w")
DEFAULT_PROFILES = ("intraday_research_v1", "long_horizon_daily_v1", "live_observation_v1")


def resolve_exchange(product: str, override: str | None) -> str:
    if override:
        return override.upper()
    try:
        with SessionLocal() as session:
            instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.strip().lower()))
            if instrument is not None and instrument.exchange_code:
                return str(instrument.exchange_code).upper()
    except Exception:
        pass
    return "DCE"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally append MAIN dominant v2 bars to target end date.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    run.add_argument("--period", action="append", choices=DEFAULT_PERIODS, dest="periods")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/full_products_90.txt")
    run.add_argument("--exchange", default=None)
    run.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-register", action="store_true")
    run.add_argument(
        "--allow-quality-failed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Register bars even when OHLC quality checks fail (stored as warning).",
    )
    closure = subparsers.add_parser("closure", help="Profile-aware incremental closure dry-run/apply/rollback.")
    closure.add_argument("--mode", choices=["dry-run", "pilot", "apply", "rollback", "orphan-report"], required=True)
    closure.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    closure.add_argument("--period", action="append", choices=DEFAULT_PERIODS, dest="periods")
    closure.add_argument("--product", action="append", dest="products")
    closure.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/full_products_90.txt")
    closure.add_argument("--profile", action="append", choices=DEFAULT_PROFILES, dest="profiles")
    closure.add_argument("--profiles", choices=["all"], default=None)
    closure.add_argument("--exchange", default=None)
    closure.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    closure.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/reports/profile_incremental_closure_latest")
    closure.add_argument("--batch-id", default="")
    closure.add_argument("--commit", action="store_true", help="Commit DB writes for apply/pilot/rollback.")
    return parser.parse_args(argv)


def _profiles_from_args(args: argparse.Namespace) -> list[str]:
    if getattr(args, "profiles", None) == "all":
        return list(DEFAULT_PROFILES)
    return list(args.profiles or DEFAULT_PROFILES)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "closure":
        products = args.products or products_from_file(args.products_file)
        periods = tuple(args.periods or DEFAULT_PERIODS)
        exchange = resolve_exchange(products[0], args.exchange) if products else (args.exchange or "DCE")
        with SessionLocal() as session:
            if args.mode == "rollback":
                if not args.batch_id:
                    raise SystemExit("--batch-id is required for closure rollback")
                result = rollback_profile_aware_incremental_closure(
                    session=session,
                    output_dir=args.output_dir,
                    batch_id=args.batch_id,
                    dry_run=not args.commit,
                    commit=args.commit,
                )
            elif args.mode == "orphan-report":
                if not args.batch_id:
                    raise SystemExit("--batch-id is required for closure orphan-report")
                result = audit_profile_incremental_orphans(session=session, output_dir=args.output_dir, batch_id=args.batch_id)
            else:
                if args.mode in {"pilot", "apply"}:
                    if not args.batch_id:
                        raise SystemExit("--batch-id is required for closure pilot/apply")
                    if not args.commit:
                        raise SystemExit("--commit is required for closure pilot/apply; use --mode dry-run for no-write checks")
                dry_run = args.mode == "dry-run"
                client = None if dry_run else RqDataClient(load_env_file=True)
                result = run_profile_aware_incremental_closure(
                    session=session,
                    client=client,
                    output_root=args.output_root,
                    products=products,
                    periods=periods,
                    target_end=args.end_date,
                    profile_ids=_profiles_from_args(args),
                    exchange=exchange,
                    dry_run=dry_run,
                    commit=args.commit,
                    batch_id=args.batch_id or None,
                    output_dir=args.output_dir,
                    allow_quality_failed=False,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if result.get("failure_count") or result.get("errors") else 0
    if args.command != "run":
        raise SystemExit(f"unsupported command: {args.command}")
    products = args.products or products_from_file(args.products_file)
    periods = tuple(args.periods or DEFAULT_PERIODS)
    client = None if args.dry_run else RqDataClient(load_env_file=True)
    summary = {
        "updated": 0,
        "skipped_up_to_date": 0,
        "skipped_no_baseline": 0,
        "dry_run": 0,
        "failed": 0,
        "results": [],
    }

    with SessionLocal() as session:
        for product in products:
            exchange = resolve_exchange(product, args.exchange)
            for period in periods:
                try:
                    result = append_dominant_v2_tail(
                        client=client,
                        output_root=args.output_root,
                        product=product,
                        exchange=exchange,
                        period=period,
                        target_end=args.end_date,
                        dry_run=args.dry_run,
                        register=not args.no_register and not args.dry_run,
                        allow_quality_failed=args.allow_quality_failed,
                        session=session if not args.no_register and not args.dry_run else None,
                    )
                    if not args.dry_run and not args.no_register and result.status == "updated":
                        session.commit()
                    elif result.status == "failed":
                        session.rollback()
                except Exception as exc:
                    session.rollback()
                    result_payload = {
                        "status": "failed",
                        "product": product.strip().lower(),
                        "period": period,
                        "target_end": args.end_date.isoformat(),
                        "error": str(exc),
                    }
                    summary["failed"] += 1
                    summary["results"].append(result_payload)
                    print(json.dumps(result_payload, ensure_ascii=False))
                    continue

                payload = {
                    "status": result.status,
                    "product": result.product,
                    "period": result.period,
                    "target_end": result.target_end.isoformat(),
                    "baseline_path": result.baseline_path,
                    "output_path": result.output_path,
                    "summary_path": result.summary_path,
                    "delta_start": result.delta_start,
                    "delta_end": result.delta_end,
                    "baseline_last": result.baseline_last,
                    "merged_last": result.merged_last,
                    "row_count": result.row_count,
                    "quality_status": result.quality_status,
                    "error": result.error,
                }
                if result.status == "updated":
                    summary["updated"] += 1
                elif result.status == "skipped_up_to_date":
                    summary["skipped_up_to_date"] += 1
                elif result.status == "skipped_no_baseline":
                    summary["skipped_no_baseline"] += 1
                elif result.status == "dry_run":
                    summary["dry_run"] += 1
                elif result.status == "failed":
                    summary["failed"] += 1
                summary["results"].append(payload)
                print(json.dumps(payload, ensure_ascii=False))

    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
