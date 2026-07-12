from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.duplicate_path_version_reconcile import (  # noqa: E402
    reconcile_duplicate_path_versions,
    write_duplicate_path_version_reports,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only reconcile for duplicate market_data_files versions sharing one path.")
    parser.add_argument(
        "--lpv-ledger",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "lpv_actual_contract_registration_dry_run_20260712" / "registration_reconcile_ledger.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "duplicate_path_version_reconcile_20260712",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = reconcile_duplicate_path_versions(
            session=session,
            project_root=args.project_root,
            lpv_ledger=_input_path(args.lpv_ledger),
        )
    output_paths = write_duplicate_path_version_reports(result, output_dir=args.output_dir)
    print("Duplicate path version reconcile completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"input_duplicate_rows={result['input_duplicate_rows']}")
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
