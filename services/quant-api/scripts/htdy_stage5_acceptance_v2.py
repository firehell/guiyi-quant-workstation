"""Build the read-only R45-04 HTDY Stage 5 Acceptance V2 packet."""

from __future__ import annotations

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
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.backtest.htdy_sample_end_audit import build_report_snapshot  # noqa: E402
from app.backtest.htdy_trusted_report import freeze_profile_selection  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.htdy_stage5_acceptance_v2 import (  # noqa: E402
    BLOCKED_GATE,
    CLOSEOUT_GATE,
    PIPELINE_READY_GATE,
    REJECTED_OUTCOME,
    X503_PATH,
    Stage5AcceptanceV2Error,
    build_blocked_packet,
    build_stage5_acceptance_v2,
    collect_immutable_input_hashes,
    collect_strategy_source_invariance,
    write_evidence_once,
)


OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_stage5_acceptance_r45_v2"


def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _x503_source_commit() -> str:
    value = json.loads((REPO_ROOT / X503_PATH).read_text(encoding="utf-8"))
    source_commit = str(value.get("source_commit") or "")
    if len(source_commit) != 40:
        raise Stage5AcceptanceV2Error("X5-03 source commit is invalid")
    return source_commit


def _database_state() -> tuple[dict, dict]:
    with SessionLocal() as session:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            raise Stage5AcceptanceV2Error(
                "R45-04 requires canonical PostgreSQL read-only verification"
            )
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        report_snapshot = build_report_snapshot(session)
        binding_snapshot = freeze_profile_selection(
            session,
            project_root=REPO_ROOT,
        ).payload()
        session.rollback()
    return report_snapshot, binding_snapshot


def main() -> int:
    try:
        source_commit = _source_commit()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"{BLOCKED_GATE}: {type(exc).__name__}: source commit unavailable", file=sys.stderr)
        return 1

    try:
        immutable_before = collect_immutable_input_hashes(REPO_ROOT)
        strategy_invariance = collect_strategy_source_invariance(
            REPO_ROOT,
            baseline_commit=_x503_source_commit(),
        )
        db_before, binding_before = _database_state()
        db_after, binding_after = _database_state()
        immutable_after = collect_immutable_input_hashes(REPO_ROOT)
        packet = build_stage5_acceptance_v2(
            REPO_ROOT,
            source_commit=source_commit,
            db_before=db_before,
            db_after=db_after,
            binding_before=binding_before,
            binding_after=binding_after,
            immutable_hashes_before=immutable_before,
            immutable_hashes_after=immutable_after,
            strategy_source_invariance=strategy_invariance,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        SQLAlchemyError,
        subprocess.SubprocessError,
    ) as exc:
        packet = build_blocked_packet(
            source_commit=source_commit,
            reason=f"{type(exc).__name__}: {exc}",
        )

    try:
        write_evidence_once(OUTPUT_DIR, packet)
    except (OSError, ValueError) as exc:
        print(f"{BLOCKED_GATE}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if packet.get("markers") != [PIPELINE_READY_GATE, REJECTED_OUTCOME, CLOSEOUT_GATE]:
        print(
            f"{BLOCKED_GATE}: {packet.get('blocked_reason') or 'V2 hard checks incomplete'}",
            file=sys.stderr,
        )
        return 1
    print(PIPELINE_READY_GATE)
    print(REJECTED_OUTCOME)
    print(f"{CLOSEOUT_GATE} packet_hash={packet['packet_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
