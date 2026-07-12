from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.schema_contract import compare_daily_weekly_overlap, validate_canonical_bar_schema  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only 1m-aggregated vs RQData-direct daily/weekly overlap reconcile.")
    parser.add_argument("--aggregated-path", type=Path, required=True)
    parser.add_argument("--direct-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/reports/daily_weekly_overlap_reconcile.json")
    args = parser.parse_args()

    result = {
        "aggregated_path": str(args.aggregated_path),
        "direct_path": str(args.direct_path),
        "aggregated_schema": validate_canonical_bar_schema(args.aggregated_path),
        "direct_schema": validate_canonical_bar_schema(args.direct_path),
        "overlap": compare_daily_weekly_overlap(aggregated_path=args.aggregated_path, direct_path=args.direct_path),
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
