from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.download_pending_inventory import (  # noqa: E402
    load_product_windows,
    run_download_pending_inventory,
    write_pending_inventory_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import DEFAULT_AUDIT_END  # noqa: E402


def _products_from_file(path: Path) -> list[str]:
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only download pending inventory for dominant main and roll segments.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "active_products.txt")
    parser.add_argument("--product-windows", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--audit-end", type=date.fromisoformat, default=DEFAULT_AUDIT_END)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "download_pending_inventory_20260713",
    )
    args = parser.parse_args()

    products = _products_from_file(args.products_file)
    product_windows = load_product_windows(args.product_windows, products=products)

    try:
        with SessionLocal() as session:
            result = run_download_pending_inventory(
                session=session,
                project_root=args.project_root,
                products=products,
                product_windows=product_windows,
                audit_end=args.audit_end,
            )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc), "fallback": "session_unavailable"}, ensure_ascii=False), file=sys.stderr)
        result = run_download_pending_inventory(
            session=None,
            project_root=args.project_root,
            products=products,
            product_windows=product_windows,
            audit_end=args.audit_end,
        )

    paths = write_pending_inventory_reports(result, output_dir=args.output_dir)
    payload = {
        "mode": result["mode"],
        "audit_end": result["audit_end"],
        "summary": result["summary"],
        "output_paths": {key: str(path) for key, path in paths.items()},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
