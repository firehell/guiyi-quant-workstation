"""Execute the file-only HTDY X5-04 frozen OOS window."""

from __future__ import annotations

import argparse
import json
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

from app.backtest.htdy_oos_validation import (  # noqa: E402
    DEFAULT_CANDIDATE_PACKET_RELATIVE_PATH,
    OOSPrerequisiteError,
    assert_selection_unchanged,
    build_sanitized_failure_packet,
    generate_oos_bundle,
    load_candidate_prerequisite,
    load_x502_packet,
    write_oos_artifacts,
)
from app.backtest.htdy_trusted_report import freeze_profile_selection  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_oos_validation_x5_04"
DEFAULT_CANDIDATE_PACKET = REPO_ROOT / DEFAULT_CANDIDATE_PACKET_RELATIVE_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute HTDY X5-04 frozen oos_fixed to file-only artifacts.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-packet", type=Path, default=DEFAULT_CANDIDATE_PACKET)
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
        raise ValueError("X5-04 output-dir must stay under data/reports")
    if resolved.name != "htdy_oos_validation_x5_04":
        raise ValueError("X5-04 output-dir must end with htdy_oos_validation_x5_04")
    return resolved


def _write_failure(output_dir: Path, *, source_commit: str, reason: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "OOS_VALIDATION_RESULT.json"
    if target.exists():
        raise RuntimeError("refusing to overwrite existing X5-04 failure evidence")
    packet = build_sanitized_failure_packet(source_commit=source_commit, reason=reason)
    target.write_text(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = build_parser().parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    source_commit = _source_commit()
    try:
        candidate_packet = load_candidate_prerequisite(args.candidate_packet.expanduser().resolve())
        x502_packet = load_x502_packet(REPO_ROOT)
        if output_dir.exists() and any(output_dir.iterdir()):
            raise OOSPrerequisiteError("X5-04 output directory is non-empty; immutable evidence cannot be overwritten")
    except OOSPrerequisiteError as exc:
        print(f"X5-04 NOT RUN: {exc}", file=sys.stderr)
        return 2

    try:
        with SessionLocal() as session:
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            bundle = generate_oos_bundle(
                session,
                repo_root=REPO_ROOT,
                candidate_packet=candidate_packet,
                x502_packet=x502_packet,
            )
            session.rollback()
        with SessionLocal() as verification_session:
            if verification_session.bind is not None and verification_session.bind.dialect.name == "postgresql":
                verification_session.execute(text("SET TRANSACTION READ ONLY"))
            after = freeze_profile_selection(verification_session, project_root=REPO_ROOT)
            verification_session.rollback()
        assert_selection_unchanged(bundle["execution_snapshot"], after)
        packet = write_oos_artifacts(output_dir, source_commit=source_commit, bundle=bundle)
    except Exception as exc:
        _write_failure(output_dir, source_commit=source_commit, reason=str(exc))
        print(f"OOS_HARD_REJECT_TRIGGERED error={type(exc).__name__}", file=sys.stderr)
        return 1

    print(f"{packet['gate']} packet_hash={packet['packet_hash']}")
    return 1 if packet["gate"] == "OOS_HARD_REJECT_TRIGGERED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
