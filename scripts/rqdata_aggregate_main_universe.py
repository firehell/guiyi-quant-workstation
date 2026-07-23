"""从本地已通过的 MAIN 1m 聚合生成 5m/15m/30m/60m（不调用 RQData）。

CLI：``run`` → 比对 1m 与聚合周期尾部 → 过期则 ``build_dominant_v2_parquet_assets`` → 可选注册。
依赖 ``dominant_v2_incremental.find_latest_main_canonical`` 与 ``dominant_v2_parquet``。
``--dry-run`` 只报告 needs_update / skipped；写入需显式非 dry-run。
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import Instrument  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_incremental import find_latest_main_canonical  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_parquet import build_dominant_v2_parquet_assets  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality  # noqa: E402
from rqdata_sync_common import products_from_file  # noqa: E402


DEFAULT_AGG_PERIODS = ("5m", "15m", "30m", "60m")


def resolve_exchange(product: str, override: str | None) -> str:
    """交易所覆盖 → Instrument → DCE。"""
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


def aggregate_needs_update(output_root: Path, product: str, periods: tuple[str, ...]) -> tuple[str, dict[str, Any] | None]:
    """判断聚合周期是否落后于最新 canonical 1m。

    返回 ``(skipped_no_1m|skipped_up_to_date|needs_update, 详情)``。
    """
    baseline_1m = find_latest_main_canonical(output_root, product, "1m")
    if baseline_1m is None:
        return "skipped_no_1m", None
    stale_periods: list[str] = []
    for period in periods:
        baseline_agg = find_latest_main_canonical(output_root, product, period)
        if baseline_agg is None or baseline_agg.end_date_token < baseline_1m.end_date_token:
            stale_periods.append(period)
    if not stale_periods:
        return "skipped_up_to_date", {
            "product": product,
            "start_date": baseline_1m.start_date.isoformat(),
            "end_date": baseline_1m.end_date_token.isoformat(),
            "baseline_1m": str(baseline_1m.path),
        }
    return "needs_update", {
        "product": product,
        "start_date": baseline_1m.start_date.isoformat(),
        "end_date": baseline_1m.end_date_token.isoformat(),
        "baseline_1m": str(baseline_1m.path),
        "stale_periods": stale_periods,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate MAIN 5m/15m/30m/60m from local passed 1m for universe products (no RQData)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--end-date", type=date.fromisoformat, default=None, help="Optional cap; default follows latest 1m window.")
    run.add_argument("--start-date", type=date.fromisoformat, default=None, help="Optional override; default follows latest 1m window.")
    run.add_argument("--period", action="append", choices=DEFAULT_AGG_PERIODS, dest="periods")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/full_products_90.txt")
    run.add_argument("--exchange", default=None)
    run.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true", help="Re-aggregate even when aggregate end token already matches 1m.")
    run.add_argument("--no-register", action="store_true")
    run.add_argument(
        "--allow-quality-failed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Register bars even when OHLC quality checks fail (stored as warning).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command != "run":
        raise SystemExit(f"unsupported command: {args.command}")

    products = args.products or products_from_file(args.products_file)
    periods = tuple(args.periods or DEFAULT_AGG_PERIODS)
    output_root = args.output_root.resolve()

    summary: dict[str, Any] = {
        "mode": "dominant-v2-aggregate-main-universe",
        "periods": list(periods),
        "updated": 0,
        "skipped_up_to_date": 0,
        "skipped_no_1m": 0,
        "dry_run": 0,
        "failed": 0,
        "results": [],
    }

    with SessionLocal() as session:
        for product in products:
            symbol = product.strip().lower()
            exchange = resolve_exchange(symbol, args.exchange)
            status, plan = aggregate_needs_update(output_root, symbol, periods)
            if args.force and plan is not None:
                status = "needs_update"
                plan = plan or {}
                plan["stale_periods"] = list(periods)

            if status == "skipped_no_1m":
                summary["skipped_no_1m"] += 1
                summary["results"].append({"product": symbol, "status": status})
                print(f"skip {symbol}: no local 1m baseline")
                continue

            if status == "skipped_up_to_date" and not args.force:
                summary["skipped_up_to_date"] += 1
                summary["results"].append({"product": symbol, "status": status, **(plan or {})})
                print(f"skip {symbol}: aggregate up to date ({plan['end_date'] if plan else '?'})")
                continue

            assert plan is not None
            start_date = date.fromisoformat(plan["start_date"]) if args.start_date is None else args.start_date
            end_date = date.fromisoformat(plan["end_date"]) if args.end_date is None else args.end_date
            if args.end_date is not None and end_date < start_date:
                summary["failed"] += 1
                summary["results"].append(
                    {"product": symbol, "status": "failed", "error": "end_date before start_date"}
                )
                print(f"failed {symbol}: end_date before start_date")
                continue

            if args.dry_run:
                summary["dry_run"] += 1
                summary["results"].append(
                    {
                        "product": symbol,
                        "status": "dry_run",
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "baseline_1m": plan.get("baseline_1m"),
                        "periods": list(periods),
                    }
                )
                print(f"dry-run {symbol}: aggregate {','.join(periods)} {start_date}..{end_date}")
                continue

            try:
                build_summary = build_dominant_v2_parquet_assets(
                    client=None,
                    output_root=output_root,
                    product=symbol,
                    exchange=exchange,
                    start_date=start_date,
                    end_date=end_date,
                    periods=periods,
                    force=True,
                )
                summary_path = (
                    output_root
                    / "processed"
                    / "v1b"
                    / symbol
                    / f"{symbol}_v2_parquet_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"
                )
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(
                    json.dumps(build_summary, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )

                if not args.no_register:
                    register_dominant_v2_quality(
                        session=session,
                        summary_path=summary_path,
                        allow_quality_failed=args.allow_quality_failed,
                    )
                    session.commit()

                summary["updated"] += 1
                summary["results"].append(
                    {
                        "product": symbol,
                        "status": "updated",
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "summary_path": str(summary_path),
                        "periods": {
                            period: build_summary["periods"][period]["quality_status"]
                            for period in periods
                            if period in build_summary.get("periods", {})
                        },
                    }
                )
                print(f"updated {symbol}: {','.join(periods)} -> {end_date}")
            except Exception as exc:
                session.rollback()
                summary["failed"] += 1
                summary["results"].append(
                    {"product": symbol, "status": "failed", "error": str(exc), "end_date": end_date.isoformat()}
                )
                print(f"failed {symbol}: {exc}")

    report_path = output_root / "reports" / "aggregate_main_universe_latest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("updated", "skipped_up_to_date", "skipped_no_1m", "dry_run", "failed")}, ensure_ascii=False))
    print(f"report: {report_path}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
