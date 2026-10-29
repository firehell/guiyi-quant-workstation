"""Read per-product execution checks; no broker, credential, or write operations."""

import argparse
from datetime import datetime, UTC
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/quant-core"))


def main():
    from guiyi_quant.simnow_execution.input_evidence import read_input_checks

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                read_input_checks(args.status, datetime.now(UTC)), sort_keys=True
            )
        )
        return 0
    except Exception:
        print("INPUT_CHECK_READBACK_UNAVAILABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
