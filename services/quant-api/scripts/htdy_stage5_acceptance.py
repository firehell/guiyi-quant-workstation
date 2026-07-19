"""Build the file-only HTDY Stage 5 acceptance packet."""

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

from app.services.htdy_stage5_acceptance import (  # noqa: E402
    BLOCKED_GATE,
    build_stage5_acceptance,
)


OUTPUT_DIR = REPO_ROOT / "data/reports/htdy_stage5_acceptance_x5_07"


def main() -> int:
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise ValueError("X5-07 output directory is immutable and already populated")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    packet = build_stage5_acceptance(REPO_ROOT, source_commit=_source_commit())
    _write_json(OUTPUT_DIR / "STAGE5_ACCEPTANCE_PACKET.json", packet)
    (OUTPUT_DIR / "STAGE5_ACCEPTANCE_SUMMARY.md").write_text(
        "# HTDY Stage 5 Acceptance\n\n"
        f"Pipeline Gate: `{packet['gate']}`\n\n"
        f"Research Outcome: `{packet.get('research_outcome') or 'N/A'}`\n\n"
        f"Packet hash: `{packet['packet_hash']}`\n\n"
        "A rejected research candidate is a valid terminal research result and does not authorize tuning or rerun.\n",
        encoding="utf-8",
    )
    print(
        f"{packet['gate']}"
        f" outcome={packet.get('research_outcome') or 'none'}"
        f" packet_hash={packet['packet_hash']}"
    )
    return 2 if packet["gate"] == BLOCKED_GATE else 0


def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
