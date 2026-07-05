from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.jm_update_plan import CURRENT_FORMAL_END, build_jm_history_update_plan  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only RQData JM history update plan.")
    parser.add_argument("--current-end", type=date.fromisoformat, default=CURRENT_FORMAL_END)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = RqDataClient(load_env_file=True)
    plan = build_jm_history_update_plan(client, current_end=args.current_end, as_of=args.as_of)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
