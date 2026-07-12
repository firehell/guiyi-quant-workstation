from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import MarketDataFile  # noqa: E402
from app.services.rqdata_ingest.weekly_row_count_reconcile import (  # noqa: E402
    DbMarketFileSnapshot,
    reconcile_weekly_row_counts,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only weekly row-count reconcile for selected dominant-main assets.")
    parser.add_argument("--products", nargs="+", default=["ad", "ec", "op"])
    parser.add_argument("--period", default="1w")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "reports" / "ad_ec_op_weekly_row_count_reconcile_20260711")
    args = parser.parse_args()

    db_status, db_error_type, db_rows = _load_db_rows(products=args.products, period=args.period)
    result = reconcile_weekly_row_counts(
        project_root=PROJECT_ROOT,
        products=args.products,
        period=args.period,
        output_dir=args.output_dir,
        db_status=db_status,
        db_error_type=db_error_type,
        db_rows=db_rows,
    )
    print("Weekly row-count reconcile completed")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    print(f"db_status={result['db_status']}")
    if result["db_error_type"]:
        print(f"db_error_type={result['db_error_type']}")
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")


def _load_db_rows(*, products: list[str], period: str) -> tuple[str, str, list[DbMarketFileSnapshot]]:
    try:
        with SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(MarketDataFile).where(
                        MarketDataFile.provider == "rqdata",
                        MarketDataFile.data_type == "bars",
                        MarketDataFile.period == period,
                        MarketDataFile.instrument_symbol.in_([product.lower() for product in products]),
                    )
                )
            )
    except Exception as exc:  # noqa: BLE001 - readonly CLI must still emit partial evidence.
        return "unavailable", type(exc).__name__, []
    return "available", "", [_snapshot(row) for row in rows]


def _snapshot(row: MarketDataFile) -> DbMarketFileSnapshot:
    return DbMarketFileSnapshot(
        id=row.id,
        file_path=row.file_path,
        row_count=row.row_count,
        start_time="" if row.start_time is None else row.start_time.isoformat(),
        end_time="" if row.end_time is None else row.end_time.isoformat(),
        checksum=row.checksum or "",
        data_role=row.data_role,
        quality_status=row.quality_status,
        data_version=row.data_version or "",
    )


if __name__ == "__main__":
    main()
