"""Stage 8.6 全宇宙 active gate 只读审计。

写入边界：只读查库 + 写报告文件；**不写** DB / parquet，**不调** RQData。
逻辑在 ``app.services.rqdata_ingest.full_universe_active_gate``。
"""

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
    """按 profile 审计 active 宇宙覆盖，并落盘 Stage 8.6 报告。"""
    parser = argparse.ArgumentParser(description="Stage 8.6 read-only full-universe active gate audit.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--product", action="append", dest="products", help="Limit audit to one or more products.")
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=("stage8_6_1d_first", "jm_six_period_reference", "jm_main_six_period_latest"),
    )
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
    """CLI 显式品种优先，否则读品种文件（跳过空行与 #）。"""
    if products:
        return [product.strip().lower() for product in products if product.strip()]
    return [
        line.strip().lower()
        for line in products_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    main()
