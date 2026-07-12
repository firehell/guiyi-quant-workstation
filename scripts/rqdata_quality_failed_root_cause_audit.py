from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.quality_failed_root_cause_audit import (  # noqa: E402
    audit_quality_failed_root_causes,
    write_quality_failed_root_cause_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only root-cause audit for target coverage quality_failed rows.")
    parser.add_argument(
        "--target-coverage-matrix",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "target_coverage_audit_20260712_after_lpv_reconcile" / "target_coverage_matrix.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "quality_failed_root_cause_audit_20260712",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = audit_quality_failed_root_causes(
            session=session,
            project_root=args.project_root,
            target_coverage_matrix=_input_path(args.target_coverage_matrix),
        )
    output_paths = write_quality_failed_root_cause_reports(result, output_dir=args.output_dir)
    print("Quality failed root-cause audit completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"candidate_target_rows={result['candidate_target_row_count']}")
    print(f"unique_paths={result['unique_path_count']}")
    for name, count in result["classification_counts"].items():
        print(f"{name}={count}")
    print(f"database_counts_unchanged={result['database_counts_unchanged']}")
    for name, path in output_paths.items():
        print(f"{name}: {path}")


def _input_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
