from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.stage8_6_pending_reconcile import (  # noqa: E402
    reconcile_stage8_6_pending,
    write_stage8_6_pending_reconcile_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 8.6 pending rows read-only reconcile.")
    parser.add_argument(
        "--matrix-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "stage8_6_active_gate_matrix.csv",
    )
    parser.add_argument(
        "--lpv-summary",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "lpv_actual_contract_registration_dry_run_20260712" / "LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "stage8_6_pending_reconcile_20260712",
    )
    args = parser.parse_args()

    result = reconcile_stage8_6_pending(
        matrix_file=args.matrix_file,
        lpv_reconcile_summary=args.lpv_summary if args.lpv_summary.exists() else None,
    )
    output_paths = write_stage8_6_pending_reconcile_reports(result, output_dir=args.output_dir)
    print("Stage 8.6 pending reconcile completed")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
