from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.target_coverage_audit import (  # noqa: E402
    DEFAULT_AUDIT_END,
    audit_target_coverage,
    load_product_windows,
    write_target_coverage_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only target coverage matrix audit for RQData assets.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--product-windows", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--product", action="append", dest="products", help="Limit audit to one or more products.")
    parser.add_argument("--audit-end", type=date.fromisoformat, default=DEFAULT_AUDIT_END)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000/api/v1/data")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "reports" / "target_coverage_audit_20260711")
    args = parser.parse_args()

    products = _products_from_args(args.products, args.products_file)
    product_windows = load_product_windows(args.product_windows, products=products)
    db_error = ""
    db_snapshot_source = "database"
    result = None

    try:
        from app.db.session import SessionLocal  # noqa: PLC0415

        with SessionLocal() as session:
            result = audit_target_coverage(
                session=session,
                project_root=args.project_root,
                product_windows=product_windows,
                audit_end=args.audit_end,
                db_snapshot_source=db_snapshot_source,
            )
    except Exception as exc:  # noqa: BLE001 - CLI must still produce readonly evidence when DB is gated.
        db_error = f"{type(exc).__name__}: {exc}"
        api_coverage, api_quality_reports, api_error = _load_api_snapshot(args.api_base_url)
        if api_error:
            db_snapshot_source = "manifest_only"
            db_error = f"{db_error}; api_snapshot_error={api_error}"
        else:
            db_snapshot_source = args.api_base_url
        result = audit_target_coverage(
            session=None,
            project_root=args.project_root,
            product_windows=product_windows,
            audit_end=args.audit_end,
            api_coverage=api_coverage,
            api_quality_reports=api_quality_reports,
            db_snapshot_source=db_snapshot_source,
            db_error=db_error,
        )

    output_paths = write_target_coverage_reports(result, output_dir=args.output_dir)
    print("Target coverage audit completed")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    print(f"db_snapshot_source={result['db_snapshot_source']}")
    if result["db_error"]:
        print(f"db_error={result['db_error']}")
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


def _load_api_snapshot(api_base_url: str) -> tuple[list[dict], list[dict], str]:
    try:
        coverage = _get_json(f"{api_base_url.rstrip('/')}/coverage")
        quality_reports = _get_json(f"{api_base_url.rstrip('/')}/quality-reports")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [], [], f"{type(exc).__name__}: {exc}"
    return coverage, quality_reports, ""


def _get_json(url: str) -> list[dict]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - localhost readonly API snapshot.
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise json.JSONDecodeError("expected list payload", payload, 0)
    return data


if __name__ == "__main__":
    main()
