"""Build the read-only R45-02 sample-end accounting-liquidation evidence."""

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

from app.backtest.htdy_sample_end_audit import (  # noqa: E402
    BASELINE_PATH,
    BLOCKED_GATE,
    R4501_PATH,
    X504_PACKET_PATH,
    X504_RESULT_PATH,
    EvidenceDriftError,
    build_closeout_packet,
    build_report_snapshot,
    immutable_file_hashes,
    load_verified_packet,
    render_markdown,
)
from app.db.session import SessionLocal  # noqa: E402


OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_stage45_closeout_r45/sample_end_audit"
JSON_OUTPUT = OUTPUT_DIR / "SAMPLE_END_AUDIT.json"
MARKDOWN_OUTPUT = OUTPUT_DIR / "SAMPLE_END_AUDIT.md"


def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _read_result() -> dict:
    path = REPO_ROOT / X504_RESULT_PATH
    if not path.is_file():
        raise EvidenceDriftError("X5-04 window result is missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceDriftError("X5-04 window result is not an object")
    return value


def _database_snapshot() -> dict:
    with SessionLocal() as session:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            raise EvidenceDriftError("R45-02 requires canonical PostgreSQL read-only verification")
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        snapshot = build_report_snapshot(session)
        session.rollback()
    return snapshot


def _write_once(packet: dict) -> None:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        if JSON_OUTPUT.is_file():
            existing = json.loads(JSON_OUTPUT.read_text(encoding="utf-8"))
            if existing == packet and MARKDOWN_OUTPUT.is_file():
                return
        raise EvidenceDriftError("sample_end_audit evidence directory is non-empty; refusing overwrite")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    MARKDOWN_OUTPUT.write_text(render_markdown(packet), encoding="utf-8")


def main() -> int:
    try:
        hashes_before = immutable_file_hashes(REPO_ROOT)
        baseline = load_verified_packet(REPO_ROOT / BASELINE_PATH)
        r4501 = load_verified_packet(REPO_ROOT / R4501_PATH)
        x504 = load_verified_packet(REPO_ROOT / X504_PACKET_PATH)
        result = _read_result()
        db_before = _database_snapshot()
        db_after = _database_snapshot()
        hashes_after = immutable_file_hashes(REPO_ROOT)
        packet = build_closeout_packet(
            result=result,
            x504_packet=x504,
            baseline_packet=baseline,
            r4501_acceptance=r4501,
            immutable_hashes_before=hashes_before,
            immutable_hashes_after=hashes_after,
            db_before=db_before,
            db_after=db_after,
            source_commit=_source_commit(),
        )
        _write_once(packet)
    except SQLAlchemyError as exc:
        print(f"{BLOCKED_GATE}: {type(exc).__name__}: database read-only verification failed", file=sys.stderr)
        return 1
    except (EvidenceDriftError, OSError, ValueError) as exc:
        print(f"{BLOCKED_GATE}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"{packet['structural_gate']} packet_hash={packet['packet_hash']}")
    print(packet["numeric_gate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
