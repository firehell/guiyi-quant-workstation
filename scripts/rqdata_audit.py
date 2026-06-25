from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

import pyarrow.parquet as pq
from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402


STRUCTURED_TABLES = [
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "futures_ex_factors",
    "futures_trading_parameters",
    "fee_margin_rules",
    "futures_warehouse_stocks",
    "futures_roll_yields",
    "futures_basis",
]


def main() -> None:
    raw_root = PROJECT_ROOT / "data" / "raw" / "rqdata"
    raw_files = sorted(raw_root.rglob("*.parquet")) if raw_root.exists() else []
    raw_by_type = Counter(path.relative_to(raw_root).parts[0] for path in raw_files)
    raw_rows_by_type: Counter[str] = Counter()
    for path in raw_files:
        raw_rows_by_type[path.relative_to(raw_root).parts[0]] += pq.ParquetFile(path).metadata.num_rows

    with SessionLocal() as session:
        print("## structured table counts")
        for table in STRUCTURED_TABLES:
            exists = session.execute(text("select to_regclass(:table)"), {"table": table}).scalar()
            if not exists:
                print(f"{table}: MISSING")
                continue
            count = session.execute(text(f"select count(*) from {table}")).scalar()
            print(f"{table}: {count}")

        print("\n## raw parquet by type")
        for data_type in sorted(raw_by_type):
            print(f"{data_type}: files={raw_by_type[data_type]} rows={raw_rows_by_type[data_type]}")

        print("\n## manifest status")
        for manifest in sorted((PROJECT_ROOT / "data" / "manifests").glob("rqdata_*.csv")):
            print(f"{manifest.name}:")
            query = f"select status, count(*) as row_count from read_csv_auto('{manifest}') group by status order by status"
            try:
                import duckdb

                for status, row_count in duckdb.sql(query).fetchall():
                    print(f"  {status}: {row_count}")
            except Exception as exc:
                print(f"  unable to read manifest: {exc}")

        print("\n## market_data_files by type and quality")
        for row in session.execute(
            text(
                """
                select data_type, quality_status, count(*) files, coalesce(sum(row_count),0) rows
                from market_data_files
                where provider = 'rqdata'
                group by data_type, quality_status
                order by data_type, quality_status
                """
            )
        ):
            print(dict(row._mapping))

        print("\n## quality reports by type and status")
        for row in session.execute(
            text(
                """
                select data_type, status, count(*) reports
                from data_quality_reports
                where provider = 'rqdata'
                group by data_type, status
                order by data_type, status
                """
            )
        ):
            print(dict(row._mapping))

        print("\n## raw/index consistency")
        indexed = set()
        for (file_path,) in session.execute(text("select file_path from market_data_files where provider = 'rqdata'")):
            path = Path(file_path)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            indexed.add(path.resolve())
        raw_set = {path.resolve() for path in raw_files}
        raw_not_indexed = raw_set - indexed
        indexed_not_raw = indexed - raw_set
        print(f"raw_files={len(raw_set)} indexed_files={len(indexed)} raw_not_indexed={len(raw_not_indexed)} indexed_not_raw={len(indexed_not_raw)}")
        if raw_not_indexed:
            print("raw_not_indexed_by_type:", dict(Counter(path.relative_to(raw_root).parts[0] for path in raw_not_indexed)))
        if indexed_not_raw:
            print("indexed_not_raw_sample:", [str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path) for path in sorted(indexed_not_raw)[:10]])


if __name__ == "__main__":
    main()
