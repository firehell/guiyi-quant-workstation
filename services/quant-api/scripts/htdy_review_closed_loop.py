"""Execute and finalize the real HTDY X5-06B Review/Web closed loop."""

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

from app.backtest.htdy_trusted_report import file_sha256, packet_hash  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.backtest import BacktestReportModel  # noqa: E402
from app.services.backtest_validation_context import build_backtest_validation_context  # noqa: E402
from app.services.htdy_review_closed_loop import (  # noqa: E402
    build_closed_loop_packet,
    execute_review_note,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_strategy_review_x5_06b"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute/finalize HTDY X5-06B closed-loop evidence.")
    parser.add_argument("--phase", choices=("execute", "finalize"), required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    if args.phase == "execute":
        return _execute(output_dir)
    return _finalize(output_dir)


def _execute(output_dir: Path) -> int:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("X5-06B output directory must be empty for execute")
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = execute_review_note(SessionLocal, repo_root=REPO_ROOT)
    evidence["execution_source_commit"] = _source_commit()
    with SessionLocal() as session:
        report = session.get(BacktestReportModel, 15)
        if report is None:
            raise ValueError("candidate report disappeared after ReviewNote commit")
        context = build_backtest_validation_context(
            REPO_ROOT,
            report_identity={
                "id": report.id,
                "report_no": report.report_no,
                "task_id": report.task_id,
                "task_no": report.task_no,
                "profile_id": report.profile_id,
                "market_data_file_id": report.market_data_file_id,
            },
        )
        session.rollback()
    _write_json(output_dir / "review_db_evidence.json", evidence)
    _write_json(output_dir / "validation_context.json", context)
    (output_dir / "X506B_EXECUTION_PENDING_BROWSER.md").write_text(
        "# HTDY X5-06B\n\nReviewNote / exact-bars / trust audits passed. Browser smoke remains required.\n",
        encoding="utf-8",
    )
    print(
        "X5-06B_DB_AND_API_EVIDENCE_READY "
        f"review_id={evidence['review_note']['id']} trade_id={evidence['selected_trade']['id']}"
    )
    return 0


def _finalize(output_dir: Path) -> int:
    db_path = output_dir / "review_db_evidence.json"
    browser_path = output_dir / "BROWSER_SMOKE_EVIDENCE.json"
    context_path = output_dir / "validation_context.json"
    if not db_path.is_file() or not browser_path.is_file() or not context_path.is_file():
        raise ValueError("X5-06B finalize prerequisites are missing")
    db_evidence = _read_json(db_path)
    browser = _read_json(browser_path)
    context = _read_json(context_path)
    if db_evidence.get("validation_context_hash") != context.get("context_hash"):
        raise ValueError("X5-06B validation context hash drifted")
    screenshot_name = str(browser.get("screenshot") or "")
    if not screenshot_name or Path(screenshot_name).name != screenshot_name:
        raise ValueError("browser screenshot path must be a fixed basename")
    screenshot = output_dir / screenshot_name
    if not screenshot.is_file() or file_sha256(screenshot) != browser.get("screenshot_sha256"):
        raise ValueError("browser screenshot hash is invalid")
    packet = build_closed_loop_packet(
        source_commit=_source_commit(),
        db_evidence=db_evidence,
        browser_smoke=browser,
    )
    packet["artifacts"] = {
        "review_db_evidence": file_sha256(db_path),
        "validation_context": file_sha256(context_path),
        "browser_smoke": file_sha256(browser_path),
        "screenshot": file_sha256(screenshot),
    }
    packet_without_hash = dict(packet)
    packet_without_hash.pop("packet_hash", None)
    packet["packet_hash"] = packet_hash(packet_without_hash)
    _write_json(output_dir / "STRATEGY_REVIEW_CLOSED_LOOP_READY.json", packet)
    (output_dir / "STRATEGY_REVIEW_CLOSED_LOOP_READY.md").write_text(
        "# HTDY X5-06B\n\n"
        f"Gate: `{packet['gate']}`\n\n"
        f"Review: `{packet['review_note'].get('deep_link')}`\n\n"
        f"Packet hash: `{packet['packet_hash']}`\n",
        encoding="utf-8",
    )
    print(f"{packet['gate']} packet_hash={packet['packet_hash']}")
    return 0


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
        raise ValueError("X5-06B output-dir must stay under data/reports")
    if resolved.name != "htdy_strategy_review_x5_06b":
        raise ValueError("X5-06B output-dir must end with htdy_strategy_review_x5_06b")
    return resolved


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path.name}")
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
