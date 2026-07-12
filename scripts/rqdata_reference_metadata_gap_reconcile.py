from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.reference_metadata_gap_reconcile import (  # noqa: E402
    reconcile_reference_metadata_gaps,
    write_reference_metadata_gap_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only reconcile for reference metadata target coverage gaps.")
    parser.add_argument(
        "--metadata-matrix",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "target_coverage_audit_20260712_after_lpv_reconcile" / "metadata_consistency_matrix.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--audit-end", type=date.fromisoformat, default=date(2026, 7, 10))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_reconcile_20260712",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = reconcile_reference_metadata_gaps(
            session=session,
            project_root=args.project_root,
            metadata_matrix=_input_path(args.metadata_matrix),
            audit_end=args.audit_end,
        )
    output_paths = write_reference_metadata_gap_reports(result, output_dir=args.output_dir)
    print("Reference metadata gap reconcile completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"input_gap_rows={result['input_gap_rows']}")
    for name, count in result["classification_counts"].items():
        print(f"{name}={count}")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


def _input_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
