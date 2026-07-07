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
from app.services.rqdata_ingest.jm_v2_parquet import FORMAL_START, PERIODS, build_jm_v2_parquet_assets  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write JM v2 raw and standard parquet assets without DB registration.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=FORMAL_START)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--period", action="append", choices=PERIODS, dest="periods")
    parser.add_argument("--force", action="store_true", help="Allow replacing existing JM v2 parquet outputs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    periods = tuple(args.periods) if args.periods else PERIODS
    client = RqDataClient(load_env_file=True)
    summary = build_jm_v2_parquet_assets(
        client=client,
        output_root=args.output_root,
        start_date=args.start_date,
        end_date=args.end_date,
        periods=periods,
        force=args.force,
    )
    summary_path = args.summary_path or args.output_root / "processed" / "v1b" / "jm" / f"jm_v2_parquet_{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(_public_summary(summary), ensure_ascii=False, indent=2, default=str))
    return 0


def _public_summary(summary: dict) -> dict:
    return {
        "mode": summary.get("mode"),
        "symbol": summary.get("symbol"),
        "contract": summary.get("contract"),
        "start_date": summary.get("start_date"),
        "end_date": summary.get("end_date"),
        "writes_database": summary.get("writes_database"),
        "periods": {
            period: {
                "data_version": payload.get("data_version"),
                "quality_status": payload.get("quality_status"),
                "raw": payload.get("raw"),
                "standard": payload.get("standard"),
            }
            for period, payload in (summary.get("periods") or {}).items()
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
