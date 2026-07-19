"""Execute read-only R45-00 baseline and R45-01 frozen-window equivalence."""

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

from app.backtest.htdy_stage45_closeout import (  # noqa: E402
    BLOCKED_DATA_GATE,
    build_baseline,
    build_data_equivalence,
    packet_hash,
    write_evidence,
)


OUTPUT_ROOT = REPO_ROOT / "data/reports/htdy_stage45_closeout_r45"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Read-only project root containing the declared canonical Parquet assets.",
    )
    return parser


def source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    args = build_parser().parse_args()
    data_root = args.data_root.expanduser().resolve()
    if not data_root.is_dir():
        raise ValueError("data-root must be an existing project directory")
    baseline = build_baseline(REPO_ROOT, source_commit=source_commit())
    write_evidence(
        OUTPUT_ROOT / "baseline",
        stem="BASELINE",
        title="HTDY Stage 4/5 Closeout Baseline R45-00",
        packet=baseline,
    )
    try:
        equivalence = build_data_equivalence(REPO_ROOT, data_root=data_root, baseline=baseline)
    except (FileNotFoundError, ValueError) as exc:
        reason = str(exc)
        for marker in (str(data_root), str(REPO_ROOT), "/Users/", "/Volumes/", "/private/"):
            reason = reason.replace(marker, "[redacted-path]")
        equivalence = {
            "schema_version": "htdy_frozen_data_window_equivalence_r4501_v1",
            "task_id": "HTDY-STAGE45-CONTRACT-CLOSEOUT-R45",
            "gate": BLOCKED_DATA_GATE,
            "comparison_result": "blocked_data_identity_drift",
            "blocked_reason": reason,
            "baseline_packet_hash": baseline["packet_hash"],
            "boundaries": baseline["boundaries"],
        }
        equivalence["packet_hash"] = packet_hash(equivalence)
    write_evidence(
        OUTPUT_ROOT / "data_equivalence",
        stem="DATA_EQUIVALENCE",
        title="HTDY Frozen Data Window Equivalence R45-01",
        packet=equivalence,
    )
    print(
        f"{baseline['gate']} baseline_packet_hash={baseline['packet_hash']}\n"
        f"{equivalence['gate']} packet_hash={equivalence['packet_hash']}"
    )
    return 2 if equivalence["gate"] == BLOCKED_DATA_GATE else 0


if __name__ == "__main__":
    raise SystemExit(main())
