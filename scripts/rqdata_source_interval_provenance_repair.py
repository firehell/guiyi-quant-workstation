from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.source_interval_provenance_repair import (  # noqa: E402
    CONFIRM_FLAG,
    DEFAULT_ISSUE_REGISTER,
    DEFAULT_TRIAGE_REPORT,
    run_source_interval_provenance_repair_apply,
    run_source_interval_provenance_repair_dry_run,
)
from app.db.session import SessionLocal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run or apply source_interval provenance repair candidates for RQData derived assets.")
    parser.add_argument("--triage-report", type=Path, default=PROJECT_ROOT / DEFAULT_TRIAGE_REPORT)
    parser.add_argument("--issue-register", type=Path, default=PROJECT_ROOT / DEFAULT_ISSUE_REGISTER)
    parser.add_argument("--candidate-files", type=Path, default=None, help="Dry-run candidate_files.csv to apply.")
    parser.add_argument("--candidate-id", action="append", dest="candidate_ids", help="Limit apply to one or more candidate ids.")
    parser.add_argument("--limit", type=int, default=None, help="Limit selected candidates, used for pilot apply.")
    parser.add_argument("--apply", action="store_true", help=f"Apply the controlled repair. Requires {CONFIRM_FLAG}.")
    parser.add_argument(
        "--confirm-source-interval-provenance-repair",
        action="store_true",
        help="Required confirmation for controlled Parquet/manifest/DB checksum writes.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "source_interval_provenance_repair_dry_run_20260712",
    )
    args = parser.parse_args()

    if args.apply or args.candidate_files:
        candidate_files = args.candidate_files or PROJECT_ROOT / "data" / "reports" / "source_interval_provenance_repair_dry_run_20260712" / "candidate_files.csv"
        with SessionLocal() as session:
            result = run_source_interval_provenance_repair_apply(
                project_root=PROJECT_ROOT,
                session=session,
                candidate_files=candidate_files,
                output_dir=args.output_dir,
                apply=args.apply,
                confirm=args.confirm_source_interval_provenance_repair,
                candidate_ids=args.candidate_ids,
                limit=args.limit,
            )
        print("Source interval provenance repair apply completed")
        print(f"operation={result['operation']}")
        print(
            "writes_database={writes_database} writes_parquet={writes_parquet} writes_manifest={writes_manifest} "
            "writes_processed_summary={writes_processed_summary} calls_rqdata=False".format(**result)
        )
        print(f"selected_candidate_count={result['selected_candidate_count']}")
        print(f"applied_candidate_count={result['applied_candidate_count']}")
        print(f"skipped_candidate_count={result['skipped_candidate_count']}")
        print(f"blocked_candidate_count={result['blocked_candidate_count']}")
        if result["blocked_reasons"]:
            print(f"blocked_reasons={','.join(result['blocked_reasons'])}")
    else:
        result = run_source_interval_provenance_repair_dry_run(
            project_root=PROJECT_ROOT,
            triage_report=args.triage_report,
            issue_register=args.issue_register,
            output_dir=args.output_dir,
        )
        print("Source interval provenance repair dry-run completed")
        print("writes_database=False writes_parquet=False writes_manifest=False writes_processed_summary=False calls_rqdata=False")
        print(f"candidate_files={len(result['candidate_files'])}")
        print(f"affected_coverage_rows={len(result['affected_coverage_rows'])}")
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
