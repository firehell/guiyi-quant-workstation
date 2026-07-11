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

from app.models.data_center import Instrument  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_backfill import (  # noqa: E402
    BACKFILL_PERIODS,
    DEFAULT_GLOBAL_END,
    build_dominant_backfill_summary,
    load_product_starts,
    persist_backfill_summary,
    plan_dominant_period_backfill,
    run_dominant_period_backfill,
    summary_path_for_product,
    write_backfill_report,
)
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill dominant MAIN 1d/1w prefix data toward 2020 without re-downloading existing tail.")
    parser.add_argument("--product", action="append", dest="products")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--starts-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument("--periods", default="1d,1w")
    parser.add_argument("--global-end", type=date.fromisoformat, default=DEFAULT_GLOBAL_END)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--report-path", type=Path, default=PROJECT_ROOT / "data" / "reports" / "dominant_v2_backfill_plan.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-write", action="store_true")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--allow-quality-failed", action="store_true")
    return parser.parse_args(argv)


def load_products(args: argparse.Namespace) -> list[str]:
    if args.products:
        return [item.strip().lower() for item in args.products if item.strip()]
    return [
        line.strip().lower()
        for line in args.products_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def resolve_exchange(product: str) -> str:
    try:
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.strip().lower()))
            if instrument is not None and instrument.exchange_code:
                return str(instrument.exchange_code).upper()
    except Exception:
        pass
    return "DCE"


def parse_periods(value: str) -> tuple[str, ...]:
    periods = tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))
    unsupported = sorted(set(periods) - set(BACKFILL_PERIODS))
    if unsupported:
        raise SystemExit(f"unsupported periods: {unsupported}; allowed: {BACKFILL_PERIODS}")
    return periods


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    products = load_products(args)
    periods = parse_periods(args.periods)
    starts = load_product_starts(args.starts_file)
    report_rows: list[dict[str, object]] = []
    results: list[dict[str, object]] = []

    client = None if args.dry_run else RqDataClient(load_env_file=True)

    for product in products:
        target_start = starts.get(product, date(2020, 1, 2))
        exchange = resolve_exchange(product)
        period_results: dict[str, object] = {}
        summary_start: date | None = None
        summary_end: date | None = None

        for period in periods:
            plan = plan_dominant_period_backfill(
                output_root=args.output_root,
                product=product,
                period=period,
                target_start=target_start,
                global_end=args.global_end,
                exchange=exchange,
            )
            report_rows.append(
                {
                    "product": product,
                    "period": period,
                    "layer": "layer1",
                    "mode": plan.mode,
                    "status": "planned",
                    "detail": plan.reason,
                    "gap_start": plan.gap_start.isoformat() if plan.gap_start else "",
                    "gap_end": plan.gap_end.isoformat() if plan.gap_end else "",
                }
            )
            if plan.mode == "skip":
                period_results[period] = {"mode": "skip", "reason": plan.reason}
                continue

            if args.dry_run:
                period_results[period] = {
                    "mode": plan.mode,
                    "gap_start": plan.gap_start.isoformat() if plan.gap_start else "",
                    "gap_end": plan.gap_end.isoformat() if plan.gap_end else "",
                    "output_start": plan.output_start.isoformat(),
                    "output_end": plan.output_end.isoformat(),
                    "superseded_paths": list(plan.superseded_paths),
                }
                summary_start = plan.output_start if summary_start is None else min(summary_start, plan.output_start)
                summary_end = plan.output_end if summary_end is None else max(summary_end, plan.output_end)
                continue

            if not args.run_write:
                raise SystemExit("Use --run-write to mutate parquet assets, or --dry-run for planning only")

            try:
                payload = run_dominant_period_backfill(
                    client=client,
                    output_root=args.output_root,
                    plan=plan,
                    exchange=exchange,
                )
            except Exception as exc:  # noqa: BLE001 - batch backfill should continue on single product failure
                period_results[period] = {"mode": "failed", "error": str(exc), "plan_mode": plan.mode}
                report_rows[-1]["status"] = "failed"
                report_rows[-1]["detail"] = str(exc)
                continue

            period_results[period] = payload
            summary_start = plan.output_start if summary_start is None else min(summary_start, plan.output_start)
            summary_end = plan.output_end if summary_end is None else max(summary_end, plan.output_end)
            report_rows[-1]["status"] = "success"

        if args.dry_run or not args.run_write or not period_results:
            results.append({"product": product, "periods": period_results})
            continue

        written = {period: payload for period, payload in period_results.items() if payload.get("standard")}
        if not written:
            results.append({"product": product, "periods": period_results, "register": None})
            continue

        assert summary_start is not None and summary_end is not None
        summary = build_dominant_backfill_summary(
            product=product,
            exchange=exchange,
            start_date=summary_start,
            end_date=summary_end,
            period_results=written,
        )
        summary_path = summary_path_for_product(args.output_root, product, summary_start, summary_end)
        persist_backfill_summary(summary, summary_path)
        register_payload = None
        if args.register:
            from app.db.session import SessionLocal

            try:
                with SessionLocal() as session:
                    register_payload = register_dominant_v2_quality(
                        session=session,
                        summary_path=summary_path,
                        allow_quality_failed=args.allow_quality_failed,
                    )
                    session.commit()
            except Exception as exc:  # noqa: BLE001 - keep parquet even if DB registration fails
                register_payload = {"mode": "register_failed", "error": str(exc), "summary_path": str(summary_path)}
                report_rows.append(
                    {
                        "product": product,
                        "period": "register",
                        "layer": "layer1",
                        "mode": "register",
                        "status": "failed",
                        "detail": str(exc),
                        "gap_start": "",
                        "gap_end": "",
                    }
                )
        results.append(
            {
                "product": product,
                "summary_path": str(summary_path),
                "register": register_payload,
                "periods": period_results,
            }
        )

    write_backfill_report(args.report_path, report_rows)
    failed_count = sum(1 for row in report_rows if row.get("status") == "failed")
    print(
        json.dumps(
            {
                "products": len(products),
                "failed_periods": failed_count,
                "report_path": str(args.report_path),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
