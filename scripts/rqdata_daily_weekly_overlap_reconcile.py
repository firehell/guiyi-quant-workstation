from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.daily_weekly_overlap_batch import (  # noqa: E402
    run_batch_overlap,
    run_contract_audit,
    run_jm_pilot_overlap,
)
from app.services.rqdata_ingest.schema_contract import (  # noqa: E402
    compare_daily_weekly_overlap,
    validate_canonical_bar_schema,
)


def _load_products(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only daily/weekly overlap reconcile and contract audit.")
    parser.add_argument(
        "--mode",
        choices=("pair", "jm-pilot", "batch", "contract-audit"),
        default="pair",
        help="pair: single aggregated vs direct paths; jm-pilot/batch/contract-audit: report modes",
    )
    parser.add_argument("--aggregated-path", type=Path)
    parser.add_argument("--direct-path", type=Path)
    parser.add_argument("--product", default="jm")
    parser.add_argument("--contract", default="jm.MAIN")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/active_products.txt")
    parser.add_argument(
        "--sealing-dir",
        type=Path,
        default=PROJECT_ROOT / "data/reports/data_sealing_audit_20260712_162941",
    )
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--limit-products", type=int)
    parser.add_argument("--limit-rows", type=int)
    args = parser.parse_args()

    output_dir = args.output_dir or args.output or (PROJECT_ROOT / "data/reports/daily_weekly_overlap_reconcile.json")
    if args.mode == "pair":
        if args.aggregated_path is None or args.direct_path is None:
            raise SystemExit("--aggregated-path and --direct-path are required for pair mode")
        result = {
            "mode": "pair",
            "aggregated_path": str(args.aggregated_path),
            "direct_path": str(args.direct_path),
            "aggregated_schema": validate_canonical_bar_schema(args.aggregated_path),
            "direct_schema": validate_canonical_bar_schema(args.direct_path),
            "overlap": compare_daily_weekly_overlap(aggregated_path=args.aggregated_path, direct_path=args.direct_path),
            "writes_database": False,
            "writes_parquet": False,
            "calls_rqdata": False,
        }
        output = output_dir
        if output.suffix != ".json":
            output = output / "overlap_result.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"output={output}")
        return

    if args.mode == "contract-audit":
        result = run_contract_audit(
            sealing_dir=args.sealing_dir,
            output_dir=output_dir,
            limit_rows=args.limit_rows,
        )
        print(json.dumps({"mode": result["mode"], "rows": len(result["rows"]), "outputs": {k: str(v) for k, v in result["outputs"].items()}}, indent=2, ensure_ascii=False))
        print(f"output_dir={output_dir}")
        return

    if args.mode == "jm-pilot":
        result = run_jm_pilot_overlap(
            sealing_dir=args.sealing_dir,
            output_dir=output_dir,
            product=args.product,
            contract=args.contract,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        print(f"output_dir={output_dir}")
        return

    products = _load_products(args.products_file)
    result = run_batch_overlap(
        sealing_dir=args.sealing_dir,
        output_dir=output_dir,
        products=products,
        max_workers=args.max_workers,
        limit_products=args.limit_products,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"output_dir={output_dir}")


if __name__ == "__main__":
    main()
