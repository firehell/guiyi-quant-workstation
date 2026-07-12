from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.actual_contract_registration_reconcile import (  # noqa: E402
    reconcile_actual_contract_registrations,
    write_actual_contract_registration_reconcile_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only reconcile for LPV actual-contract market_data_files registrations.")
    parser.add_argument(
        "--candidate-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "target_coverage_gap_triage_20260711" / "missing_db_registration_candidates.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "lpv_actual_contract_registration_dry_run_20260712",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = reconcile_actual_contract_registrations(
            session=session,
            project_root=PROJECT_ROOT,
            candidate_file=args.candidate_file,
        )
    output_paths = write_actual_contract_registration_reconcile_reports(result, output_dir=args.output_dir)
    print("LPV actual-contract registration reconcile completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"candidate_target_rows={result['candidate_target_row_count']}")
    print(f"unique_paths={result['unique_path_count']}")
    for name, count in result["classification_counts"].items():
        print(f"{name}={count}")
    print(f"database_counts_unchanged={result['database_counts_unchanged']}")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
