from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.reference_metadata_gap_apply import (  # noqa: E402
    run_reference_metadata_gap_apply,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reference metadata gaps with a metadata-only safety boundary.")
    parser.add_argument(
        "--candidate-rows",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_apply_plan_20260712" / "apply_candidate_rows.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_apply_20260712",
    )
    parser.add_argument("--batch-id")
    parser.add_argument("--dataset", choices=["contract_universe", "continuous_contract_map"])
    parser.add_argument("--year", type=int)
    parser.add_argument("--product")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--continuous-type", action="append", dest="continuous_types")
    parser.add_argument(
        "--derive-continuous-from-universe",
        action="store_true",
        help="Derive front/next continuous maps from futures_contract_universe sort_order without calling RQData.",
    )
    parser.add_argument("--apply", action="store_true", help="Call RQData and write only reference metadata tables.")
    parser.add_argument("--confirm-metadata-only", action="store_true", help="Required with --apply.")
    args = parser.parse_args()

    client = RqDataClient() if args.apply else None
    with SessionLocal() as session:
        result = run_reference_metadata_gap_apply(
            session=session,
            client=client,
            candidate_rows_csv=_resolve(args.candidate_rows),
            output_dir=_resolve(args.output_dir),
            apply=args.apply,
            confirm_metadata_only=args.confirm_metadata_only,
            batch_id=args.batch_id,
            dataset=args.dataset,
            year=args.year,
            product=args.product,
            limit=args.limit,
            continuous_types=args.continuous_types,
            derive_continuous_from_universe=args.derive_continuous_from_universe,
        )

    print("Reference metadata gap apply completed")
    print(f"apply={result['apply']}")
    print(f"candidate_count={result['candidate_count']}")
    print(f"status_counts={result['status_counts']}")
    print(f"writes_database={result['writes_database']}")
    print("writes_parquet=False")
    print("writes_market_data_files=False")
    print("writes_quality_status=False")
    print(f"calls_rqdata={result['calls_rqdata']}")
    print(f"ledger: {result['ledger_path']}")
    print(f"summary: {result['summary_path']}")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
