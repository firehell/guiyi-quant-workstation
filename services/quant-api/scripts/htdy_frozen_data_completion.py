"""Execute fixed-scope, read-only R4501B frozen-window completion evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
API = Path(__file__).resolve().parents[1]
for item in (API, ROOT / "packages/quant-core"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from app.backtest.htdy_frozen_data_completion import run_completion, write_outputs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    try:
        if not data_root.is_dir():
            raise ValueError("data-root must be an existing project directory")
        packets = run_completion(ROOT, data_root)
        write_outputs(ROOT, packets)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        print(f"R4501B fail-closed: {exc}", file=sys.stderr)
        return 2
    print(f"{packets['acceptance']['gate']} packet_hash={packets['acceptance']['packet_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
