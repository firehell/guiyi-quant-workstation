from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.tqsdk_ingest.contract_plan import build_contract_download_plan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TqSdk real-contract 1m download plan from main_contract_map")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--products", nargs="+", required=True)
    run.add_argument("--start-date", type=_parse_date, required=True)
    run.add_argument("--end-date", type=_parse_date, required=True)
    run.add_argument("--ranks", nargs="+", type=int, default=[1])
    run.add_argument("--include-rank2", action="store_true")
    run.add_argument("--buffer-days", type=int, default=10)
    run.add_argument("--output", default="data/manifests/tqsdk_contract_1m_download_plan.csv")
    args = parser.parse_args()
    ranks = sorted(set(args.ranks + ([2] if args.include_rank2 else [])))
    with SessionLocal() as session:
        plan = build_contract_download_plan(
            session,
            products=args.products,
            start_date=args.start_date,
            end_date=args.end_date,
            ranks=ranks,
            buffer_days=args.buffer_days,
        )
    output = PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    plan.to_csv(output, index=False)
    print(f"wrote {output} rows={len(plan)}")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
