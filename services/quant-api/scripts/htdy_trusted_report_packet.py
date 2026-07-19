"""Generate the read-only HTDY X5-02 full-window apply packet."""

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

from sqlalchemy import text  # noqa: E402

from app.backtest.htdy_trusted_report import (  # noqa: E402
    assert_profile_selection_unchanged,
    freeze_profile_selection,
    generate_trusted_report_bundle,
    write_artifact_bundle,
)
from app.db.session import SessionLocal  # noqa: E402

DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_trusted_report_x5_02"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the read-only HTDY X5-02 trusted-report apply packet."
    )
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
        raise ValueError("X5-02 output-dir must stay under data/reports")
    if resolved.name != "htdy_trusted_report_x5_02":
        raise ValueError("X5-02 output-dir must end with htdy_trusted_report_x5_02")
    return resolved


def main() -> int:
    args = build_parser().parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    with SessionLocal() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        bundle = generate_trusted_report_bundle(session, repo_root=REPO_ROOT)
        session.rollback()
    with SessionLocal() as verification_session:
        if verification_session.bind is not None and verification_session.bind.dialect.name == "postgresql":
            verification_session.execute(text("SET TRANSACTION READ ONLY"))
        after = freeze_profile_selection(verification_session, project_root=REPO_ROOT)
        verification_session.rollback()
    assert_profile_selection_unchanged(bundle["execution_snapshot"], after)
    packet = write_artifact_bundle(
        output_dir,
        source_commit=_source_commit(),
        protocol_hash=bundle["protocol_hash"],
        parameter_hash=bundle["parameter_hash"],
        execution_snapshot=bundle["execution_snapshot"],
        cost_payload=bundle["cost_payload"],
        dry_run=bundle["dry_run"],
        preapply_audit=bundle["preapply_audit"],
    )
    print(f"{packet['gate']} packet_hash={packet['packet_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
