from __future__ import annotations

from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.recovery import backfill_ex_factors_from_raw  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover structured RQData tables from existing raw Parquet files")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ex_factor = subparsers.add_parser("backfill-ex-factor", help="Backfill futures_ex_factors from raw ex-factor Parquet")
    ex_factor.add_argument("--product", action="append", dest="products")
    ex_factor.add_argument("--limit", type=int)
    ex_factor.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "backfill-ex-factor":
            rows, files = backfill_ex_factors_from_raw(
                session,
                PROJECT_ROOT,
                products=args.products,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                session.commit()
            print(f"backfill-ex-factor rows={rows} files={files} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
