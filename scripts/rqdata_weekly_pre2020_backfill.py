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
from app.services.rqdata_ingest.target_coverage_audit import load_product_windows  # noqa: E402
from app.services.rqdata_ingest.weekly_pre2020_backfill import (  # noqa: E402
    build_weekly_pre2020_backfill_plan,
    load_pre2020_gap_products,
    run_weekly_pre2020_backfill_batch,
)


def resolve_exchange(product: str) -> str:
    try:
        with SessionLocal() as session:
            instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.strip().lower()))
            if instrument is not None and instrument.exchange_code:
                return str(instrument.exchange_code).upper()
    except Exception:
        pass
    return "DCE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill dominant MAIN 1w prefix to listed_date for pre-2020 weekly coverage.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--product-windows", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument(
        "--weekly-history-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_final_audit_20260712" / "weekly_history_audit.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_phase2_weekly_pre2020_20260712",
    )
    parser.add_argument("--batch-size", type=int, default=0, help="0 means all actionable products")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-write", action="store_true")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--allow-quality-failed", action="store_true")
    args = parser.parse_args()

    products = load_pre2020_gap_products(weekly_history_csv=args.weekly_history_csv)
    if not products:
        products = [
            line.strip().lower()
            for line in args.products_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    product_windows = load_product_windows(args.product_windows, products=products)

    if args.dry_run or not args.run_write:
        result = build_weekly_pre2020_backfill_plan(
            project_root=args.project_root,
            products=products,
            product_windows=product_windows,
            output_dir=args.output_dir,
        )
        print(json.dumps(result["summary"], indent=2))
        return 0

    client = RqDataClient()
    result = run_weekly_pre2020_backfill_batch(
        client=client,
        project_root=args.project_root,
        products=products,
        product_windows=product_windows,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        register=args.register,
        allow_quality_failed=args.allow_quality_failed,
        resolve_exchange=resolve_exchange,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
