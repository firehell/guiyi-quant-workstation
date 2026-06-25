from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import sys

import pandas as pd
import pyarrow.parquet as pq
from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from rqdata_sync_common import DEFAULT_END, DEFAULT_RESEARCH_PRODUCTS  # noqa: E402


PRODUCT_DATASETS = [
    ("get_dominant_rank1", "main_contract_map", "main_contract_map", "rank = 1"),
    ("get_dominant_rank2", "main_contract_map", "main_contract_map", "rank = 2"),
    ("get_ex_factor", "futures_ex_factors", "futures_ex_factors", None),
    ("get_warehouse_stocks", "futures_warehouse_stocks", "futures_warehouse_stocks", None),
    ("get_contracts", "futures_contract_universe", "contract_universe", None),
    ("get_continuous_contracts", "futures_continuous_contract_map", "continuous_contracts", None),
]

FILE_ONLY_DATASETS = [
    ("get_dominant_price_1d", "dominant_daily_baseline"),
    ("get_dominant_price_samples", "market_sample"),
]


def _product_key(value: str) -> str:
    return value.lower()


def _table_exists(session, table: str) -> bool:
    return bool(session.execute(text("select to_regclass(:table)"), {"table": table}).scalar())


def _raw_counts(raw_root: Path) -> tuple[Counter[str], Counter[str]]:
    files: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    if not raw_root.exists():
        return files, rows
    for path in raw_root.rglob("*.parquet"):
        data_type = path.relative_to(raw_root).parts[0]
        files[data_type] += 1
        rows[data_type] += pq.ParquetFile(path).metadata.num_rows
    return files, rows


def _db_product_count(session, table: str, product: str, where: str | None) -> tuple[int, str, str]:
    if not _table_exists(session, table):
        return 0, "", ""
    extra = f" and {where}" if where else ""
    row = session.execute(
        text(
            f"""
            select count(*) rows, min(trade_date) start_date, max(trade_date) end_date
            from {table}
            where lower(instrument_symbol) = :product
            {extra}
            """
        ),
        {"product": product},
    ).one()
    return int(row.rows or 0), "" if row.start_date is None else str(row.start_date), "" if row.end_date is None else str(row.end_date)


def _file_product_count(session, data_type: str, product: str) -> tuple[int, int, str, str]:
    row = session.execute(
        text(
            """
            select count(*) files, coalesce(sum(row_count), 0) rows, min(start_time) start_time, max(end_time) end_time
            from market_data_files
            where provider = 'rqdata' and data_type = :data_type and lower(coalesce(instrument_symbol, '')) = :product
            """
        ),
        {"data_type": data_type, "product": product},
    ).one()
    return int(row.files or 0), int(row.rows or 0), "" if row.start_time is None else str(row.start_time.date()), "" if row.end_time is None else str(row.end_time.date())


def _status(rows: int, files: int, table_exists: bool = True) -> str:
    if not table_exists:
        return "missing_table"
    if rows > 0:
        return "ok"
    if files > 0:
        return "needs_rerun"
    return "missing_download"


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for record in frame.astype(str).to_dict("records"):
        lines.append("| " + " | ".join(record[column].replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit RQData structured coverage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--interface", dest="interface_name")
    args = parser.parse_args()

    products = [_product_key(item) for item in (args.products or DEFAULT_RESEARCH_PRODUCTS)]
    raw_files, raw_rows = _raw_counts(PROJECT_ROOT / "data/raw/rqdata")
    rows: list[dict[str, object]] = []
    with SessionLocal() as session:
        for product in products:
            for interface_name, table, data_type, where in PRODUCT_DATASETS:
                if args.interface_name and args.interface_name != interface_name:
                    continue
                db_rows, start_date, end_date = _db_product_count(session, table, product, where)
                files, file_rows, file_start, file_end = _file_product_count(session, data_type, product)
                rows.append(
                    {
                        "product": product,
                        "interface_name": interface_name,
                        "dataset_name": data_type,
                        "start_date": start_date or file_start,
                        "end_date": end_date or file_end,
                        "expected_end": str(DEFAULT_END),
                        "raw_files_count": raw_files[data_type],
                        "raw_rows": raw_rows[data_type],
                        "indexed_files": files,
                        "indexed_rows": file_rows,
                        "db_rows": db_rows,
                        "status": _status(db_rows, files, _table_exists(session, table)),
                    }
                )
            for interface_name, data_type in FILE_ONLY_DATASETS:
                if args.interface_name and args.interface_name != interface_name:
                    continue
                files, file_rows, start_date, end_date = _file_product_count(session, data_type, product)
                rows.append(
                    {
                        "product": product,
                        "interface_name": interface_name,
                        "dataset_name": data_type,
                        "start_date": start_date,
                        "end_date": end_date,
                        "expected_end": str(DEFAULT_END),
                        "raw_files_count": raw_files[data_type],
                        "raw_rows": raw_rows[data_type],
                        "indexed_files": files,
                        "indexed_rows": file_rows,
                        "db_rows": "",
                        "status": "ok" if file_rows > 0 else "missing_download",
                    }
                )

    reports = PROJECT_ROOT / "data/reports"
    reports.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    matrix_path = reports / "rqdata_coverage_matrix.csv"
    missing_path = reports / "rqdata_missing_items.csv"
    summary_path = reports / "rqdata_product_coverage_summary.md"
    frame.to_csv(matrix_path, index=False)
    frame[frame["status"] != "ok"].to_csv(missing_path, index=False)
    status_counts = frame.groupby(["dataset_name", "status"]).size().reset_index(name="count") if not frame.empty else pd.DataFrame()
    summary_path.write_text(
        "# RQData Product Coverage Summary\n\n"
        + _markdown_table(status_counts)
        + "\n\n## Missing Items\n\n"
        + _markdown_table(frame[frame["status"] != "ok"].head(100))
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {matrix_path}")
    print(f"wrote {missing_path}")
    print(f"wrote {summary_path}")
    print(status_counts.to_string(index=False))


if __name__ == "__main__":
    main()
