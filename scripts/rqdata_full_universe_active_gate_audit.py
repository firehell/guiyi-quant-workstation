from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.full_universe_active_gate import (  # noqa: E402
    DEFAULT_PROFILE,
    audit_full_universe_active_gate,
    write_stage8_6_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 8.6 read-only full-universe active gate audit.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--product", action="append", dest="products", help="Limit audit to one or more products.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, choices=("stage8_6_1d_first", "jm_six_period_reference"))
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "reports")
    args = parser.parse_args()

    products = _products_from_args(args.products, args.products_file)
    with SessionLocal() as session:
        result = audit_full_universe_active_gate(
            session=session,
            project_root=PROJECT_ROOT,
            products=products,
            profile=args.profile,
        )
    output_paths = write_stage8_6_reports(result, output_dir=args.output_dir)
    print("Stage 8.6 active gate audit completed")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


def _products_from_args(products: list[str] | None, products_file: Path) -> list[str]:
    if products:
        return [product.strip().lower() for product in products if product.strip()]
    return [
        line.strip().lower()
        for line in products_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    main()
