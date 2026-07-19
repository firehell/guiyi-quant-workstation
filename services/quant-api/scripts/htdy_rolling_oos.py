"""Execute HTDY X5-05 rolling OOS stability and deterministic diagnostics."""

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

from app.backtest.htdy_rolling_oos import (  # noqa: E402
    generate_rolling_bundle,
    load_x504_packet,
    write_rolling_artifacts,
)
from app.backtest.htdy_trusted_report import (  # noqa: E402
    assert_profile_selection_unchanged,
    freeze_profile_selection,
)
from app.db.session import SessionLocal  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_rolling_oos_x5_05"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute HTDY X5-05 rolling_oos_stability file-only diagnostics.")
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
        raise ValueError("X5-05 output-dir must stay under data/reports")
    if resolved.name != "htdy_rolling_oos_x5_05":
        raise ValueError("X5-05 output-dir must end with htdy_rolling_oos_x5_05")
    return resolved


def main() -> int:
    args = build_parser().parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        print("X5-05 NOT RUN: immutable output directory is non-empty", file=sys.stderr)
        return 2
    x504_packet = load_x504_packet(REPO_ROOT)
    with SessionLocal() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        bundle = generate_rolling_bundle(session, repo_root=REPO_ROOT, x504_packet=x504_packet)
        session.rollback()
    with SessionLocal() as verification:
        if verification.bind is not None and verification.bind.dialect.name == "postgresql":
            verification.execute(text("SET TRANSACTION READ ONLY"))
        after = freeze_profile_selection(verification, project_root=REPO_ROOT)
        verification.rollback()
    assert_profile_selection_unchanged(bundle["execution_snapshot"], after)
    packet = write_rolling_artifacts(output_dir, source_commit=_source_commit(), bundle=bundle)
    print(f"{packet['proposal_label']} packet_hash={packet['packet_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
