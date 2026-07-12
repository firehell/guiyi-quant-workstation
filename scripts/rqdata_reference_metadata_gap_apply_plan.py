from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.reference_metadata_gap_apply_plan import (  # noqa: E402
    build_reference_metadata_gap_apply_plan,
    write_reference_metadata_gap_apply_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a no-write apply plan for reference metadata gaps.")
    parser.add_argument(
        "--gap-ledger",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_reconcile_20260712" / "reference_metadata_gap_ledger.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_apply_plan_20260712",
    )
    args = parser.parse_args()

    result = build_reference_metadata_gap_apply_plan(
        project_root=args.project_root,
        gap_ledger=_input_path(args.gap_ledger),
    )
    output_paths = write_reference_metadata_gap_apply_plan(result, output_dir=args.output_dir)
    print("Reference metadata gap apply plan completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"candidate_rows={result['candidate_row_count']}")
    print(f"batch_count={result['batch_count']}")
    for name, count in result["classification_counts"].items():
        print(f"{name}={count}")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


def _input_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
