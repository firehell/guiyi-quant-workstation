"""主力 MAIN 1d 前缀回填到 listed_date（pre-2020 日线覆盖）。

CLI：加载适用品种 → 建计划 → dry-run 或 ``run_daily_pre2020_backfill_batch``。
算法在 ``app.services.rqdata_ingest.daily_pre2020_backfill``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import Instrument  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.daily_pre2020_backfill import (  # noqa: E402
    build_daily_pre2020_backfill_plan,
    load_pre2020_applicable_products,
    run_daily_pre2020_backfill_batch,
)
from app.services.rqdata_ingest.target_coverage_audit import load_product_windows  # noqa: E402


def resolve_exchange(product: str) -> str:
    """从 Instrument 读交易所，失败回退 DCE。"""
    try:
        with SessionLocal() as session:
            instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.strip().lower()))
            if instrument is not None and instrument.exchange_code:
                return str(instrument.exchange_code).upper()
    except Exception:
        pass
    return "DCE"


def load_products(args: argparse.Namespace, product_windows: dict) -> list[str]:
    return load_pre2020_applicable_products(
        products_file=args.products_file,
        product_windows=product_windows,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill dominant MAIN 1d prefix to listed_date for pre-2020 daily coverage.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "active_products.txt")
    parser.add_argument("--product-windows", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument(
        "--weekly-history-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_final_audit_phase3_20260712" / "weekly_history_audit.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "daily_pre2020_backfill_20260713",
    )
    parser.add_argument("--batch-size", type=int, default=21, help="Number of actionable products per batch; 0 means all pending")
    parser.add_argument("--batch-offset", type=int, default=0, help="Skip first N pending actionable products")
    parser.add_argument("--no-resume", action="store_true", help="Do not skip products already marked success in batch_results.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-write", action="store_true")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--allow-quality-failed", action="store_true")
    args = parser.parse_args()

    all_products = [
        line.strip().lower()
        for line in args.products_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    product_windows = load_product_windows(args.product_windows, products=all_products)
    products = load_products(args, product_windows)

    if args.dry_run or not args.run_write:
        result = build_daily_pre2020_backfill_plan(
            project_root=args.project_root,
            products=products,
            product_windows=product_windows,
            output_dir=args.output_dir,
        )
        print(json.dumps(result["summary"], indent=2))
        return 0

    client = RqDataClient()
    result = run_daily_pre2020_backfill_batch(
        client=client,
        project_root=args.project_root,
        products=products,
        product_windows=product_windows,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        batch_offset=args.batch_offset,
        resume=not args.no_resume,
        register=args.register,
        allow_quality_failed=args.allow_quality_failed,
        resolve_exchange=resolve_exchange,
    )
    print(json.dumps(result, indent=2, default=str))
    failed_count = sum(1 for item in result["batch_results"] if item.get("status") in {"failed", "register_failed"})
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
