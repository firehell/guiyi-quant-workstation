"""Build the read-only R45-03 rolling OOS decision-semantics evidence."""

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

from app.backtest.htdy_rolling_decision_recheck import (  # noqa: E402
    BLOCKED_DECISION,
    CURRENT_REJECTION_GATE,
    READY_GATE,
    RollingDecisionEvidenceError,
    build_rolling_decision_recheck,
    immutable_input_hashes,
    render_markdown,
)


OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_stage45_closeout_r45/rolling_decision_recheck"
JSON_OUTPUT = OUTPUT_DIR / "ROLLING_DECISION_RECHECK.json"
MARKDOWN_OUTPUT = OUTPUT_DIR / "ROLLING_DECISION_RECHECK.md"


def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_once(packet: dict) -> None:
    markdown = render_markdown(packet)
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        if JSON_OUTPUT.is_file() and MARKDOWN_OUTPUT.is_file():
            existing = json.loads(JSON_OUTPUT.read_text(encoding="utf-8"))
            if existing == packet and MARKDOWN_OUTPUT.read_text(encoding="utf-8") == markdown:
                return
        raise RollingDecisionEvidenceError(
            "rolling_decision_recheck evidence directory is non-empty; refusing overwrite"
        )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    MARKDOWN_OUTPUT.write_text(markdown, encoding="utf-8")


def main() -> int:
    try:
        hashes_before = immutable_input_hashes(REPO_ROOT)
        packet = build_rolling_decision_recheck(
            REPO_ROOT,
            source_commit=_source_commit(),
            immutable_hashes_before=hashes_before,
            immutable_hashes_after=immutable_input_hashes(REPO_ROOT),
        )
        _write_once(packet)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"{BLOCKED_DECISION}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if packet["status"] != "completed":
        print(
            f"{BLOCKED_DECISION}: {packet.get('blocked_reason') or 'unknown evidence error'}",
            file=sys.stderr,
        )
        return 1
    if packet.get("gates") != [READY_GATE, CURRENT_REJECTION_GATE]:
        print(f"{BLOCKED_DECISION}: success gates are incomplete", file=sys.stderr)
        return 1
    print(f"{READY_GATE} packet_hash={packet['packet_hash']}")
    print(CURRENT_REJECTION_GATE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
