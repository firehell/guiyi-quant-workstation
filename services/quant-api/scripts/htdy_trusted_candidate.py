"""Apply the approved X5-03 HTDY candidate in one audited transaction."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
for import_root in (SERVICE_ROOT, QUANT_CORE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.backtest.htdy_trusted_candidate import (  # noqa: E402
    CandidateApplyError,
    FAILURE_GATE,
    SUCCESS_GATE,
    apply_candidate_transaction,
    build_failure_packet,
    load_x502_bundle,
    write_candidate_artifacts,
    write_failure_artifact,
)
from app.db.session import SessionLocal  # noqa: E402


APPROVAL_GATE = "HTDY_X503_CANONICAL_WRITE_APPROVED"
X502_DIR = REPO_ROOT / "data/reports/htdy_trusted_report_x5_02"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_trusted_backtest_candidate_x5_03"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create exactly one approved HTDY X5-03 canonical candidate with atomic dual trust audit."
    )
    parser.add_argument("--approval-gate", required=True, choices=(APPROVAL_GATE,))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validated_output_dir(value: Path) -> Path:
    resolved = value.expanduser().resolve()
    reports_root = (REPO_ROOT / "data/reports").resolve()
    if not resolved.is_relative_to(reports_root):
        raise ValueError("X5-03 output-dir must stay under data/reports")
    if resolved.name != "htdy_trusted_backtest_candidate_x5_03":
        raise ValueError("X5-03 output-dir must end with htdy_trusted_backtest_candidate_x5_03")
    return resolved


def main() -> int:
    args = build_parser().parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    source_commit = _source_commit()
    if output_dir.exists() and any(output_dir.iterdir()):
        print("X5-03 NOT RUN: immutable output directory is non-empty", file=sys.stderr)
        return 2

    try:
        bundle = load_x502_bundle(X502_DIR)
        result = apply_candidate_transaction(
            SessionLocal,
            repo_root=REPO_ROOT,
            bundle=bundle,
            source_commit=source_commit,
        )
    except CandidateApplyError as exc:
        packet = build_failure_packet(
            source_commit=source_commit,
            reason=str(exc),
            failure=exc.failure,
        )
        write_failure_artifact(output_dir, packet)
        print(f"{FAILURE_GATE} packet_hash={packet['packet_hash']}", file=sys.stderr)
        return 1

    packet = write_candidate_artifacts(
        output_dir,
        result=result,
        bundle=bundle,
        source_commit=source_commit,
    )
    print(f"{SUCCESS_GATE} packet_hash={packet['packet_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
