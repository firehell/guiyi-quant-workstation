from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.core_cli import (  # noqa: E402
    format_reference_metadata_plan_legacy,
    run_reference_metadata_gap_plan,
)


def main(
    argv: list[str] | None = None,
    *,
    plan_runner: Callable[..., dict] = run_reference_metadata_gap_plan,
    stdout: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description="Build a no-write apply plan for reference metadata gaps.")
    parser.add_argument(
        "--gap-ledger",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_reconcile_20260712" / "reference_metadata_gap_ledger.csv",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "reference_metadata_gap_apply_plan_20260712",
    )
    args = parser.parse_args(argv)

    payload = plan_runner(
        project_root=args.project_root,
        gap_ledger=args.gap_ledger,
        output_dir=args.output_dir,
    )
    print(format_reference_metadata_plan_legacy(payload), end="", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
