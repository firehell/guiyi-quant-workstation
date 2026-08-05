"""主力 dominant v2 bars 增量追加到目标结束日（默认 1m/1d/1w）。

CLI：``run`` → 对每个品种×周期调用 ``append_dominant_v2_tail``；成功可注册质量并 commit。
真实合并逻辑在 ``app.services.rqdata_ingest.dominant_v2_incremental``。
``--dry-run`` 不创建 client；``--no-register`` 只写文件不写 DB。
"""

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
from rqdata_sync_common import products_from_file  # noqa: E402


DEFAULT_PERIODS = ("1m", "1d", "1w")


def resolve_exchange(product: str, override: str | None) -> str:
    """优先 CLI ``--exchange``，否则查 Instrument，最后回退 DCE。"""
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
    """解析增量尾部参数；默认允许 quality_failed 以 warning 注册。"""
    parser = argparse.ArgumentParser(description="Incrementally append MAIN dominant v2 bars to target end date.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    run.add_argument("--period", action="append", choices=DEFAULT_PERIODS, dest="periods")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/active_products.txt")
    run.add_argument("--exchange", default=None)
    run.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-register", action="store_true")
    run.add_argument(
        "--allow-quality-failed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Register bars even when OHLC quality checks fail (stored as warning).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """批量追加；按状态计数；任一批 failed 则进程退出码为 1。"""
    args = parse_args(argv)
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
