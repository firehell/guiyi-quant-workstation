from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import sys

import duckdb
import pandas as pd
from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import DataQualityReport, MainContractMap, MarketDataFile  # noqa: E402
from app.services.tqsdk_ingest.aggregate import aggregate_bars  # noqa: E402
from app.services.tqsdk_ingest.products import product_spec, selected_product_specs  # noqa: E402


COMPARE_PERIODS = ["5m", "15m", "30m", "60m"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit TqSdk download coverage, quality, and cross-source diffs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--product", action="append", dest="product_items")
    run.add_argument("--products", nargs="+")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    args = parser.parse_args()

    products = [spec.product for spec in selected_product_specs((args.product_items or []) + (args.products or []) or None)]
    reports = PROJECT_ROOT / "data/reports"
    reports.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        coverage = _coverage(session, products, args.start_date, args.end_date)
        quality = _quality(session, products, args.start_date, args.end_date)
        diff = _cross_source_diff(session, products)
        gap = _mapping_gap(session, products, args.start_date, args.end_date)

    coverage.to_csv(reports / "tqsdk_download_coverage.csv", index=False)
    quality.to_csv(reports / "tqsdk_quality_report.csv", index=False)
    diff.to_csv(reports / "tqsdk_cross_source_diff.csv", index=False)
    summary = _summary(coverage, quality, diff, gap)
    (reports / "tqsdk_audit_summary.md").write_text(summary, encoding="utf-8")
    print(f"wrote {reports / 'tqsdk_download_coverage.csv'}")
    print(f"wrote {reports / 'tqsdk_quality_report.csv'}")
    print(f"wrote {reports / 'tqsdk_cross_source_diff.csv'}")
    print(f"wrote {reports / 'tqsdk_audit_summary.md'}")


def _coverage(session, products: list[str], start: date | None, end: date | None) -> pd.DataFrame:
    query = select(MarketDataFile).where(MarketDataFile.provider == "tqsdk", MarketDataFile.instrument_symbol.in_(products))
    if start:
        query = query.where(MarketDataFile.end_time >= pd.Timestamp(start).to_pydatetime())
    if end:
        query = query.where(MarketDataFile.start_time <= pd.Timestamp(end).to_pydatetime())
    rows = []
    for item in session.scalars(query.order_by(MarketDataFile.instrument_symbol, MarketDataFile.data_type, MarketDataFile.period, MarketDataFile.start_time)):
        path = Path(item.file_path)
        exists = path.exists() or (PROJECT_ROOT / path).exists()
        rows.append(
            {
                "provider": item.provider,
                "data_type": item.data_type,
                "product": item.instrument_symbol,
                "contract": item.contract_code,
                "period": item.period,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "rows": item.row_count,
                "quality_status": item.quality_status,
                "file_path": item.file_path,
                "file_exists": exists,
                "status": "ok" if exists and item.quality_status != "failed" else "problem",
            }
        )
    return pd.DataFrame(rows)


def _quality(session, products: list[str], start: date | None, end: date | None) -> pd.DataFrame:
    query = select(DataQualityReport).where(DataQualityReport.provider == "tqsdk", DataQualityReport.instrument_symbol.in_(products))
    if start:
        query = query.where(DataQualityReport.end_time >= pd.Timestamp(start).to_pydatetime())
    if end:
        query = query.where(DataQualityReport.start_time <= pd.Timestamp(end).to_pydatetime())
    return pd.DataFrame(
        [
            {
                "data_type": item.data_type,
                "product": item.instrument_symbol,
                "contract": item.contract_code,
                "period": item.period,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "status": item.status,
                "missing_bars": item.missing_bars,
                "duplicated_bars": item.duplicated_bars,
                "abnormal_price_count": item.abnormal_price_count,
                "abnormal_volume_count": item.abnormal_volume_count,
                "details": item.details,
            }
            for item in session.scalars(query.order_by(DataQualityReport.start_time))
        ]
    )


def _cross_source_diff(session, products: list[str]) -> pd.DataFrame:
    rows = []
    for product in products:
        spec = product_spec(product)
        tqsdk_files = _paths(session, "tqsdk", "main_continuous", spec.product, spec.contract_code, "1m")
        if not tqsdk_files:
            continue
        tqsdk_1m = _read_bars(tqsdk_files)
        for period in COMPARE_PERIODS:
            trader_files = _paths(session, "trader_future_data", "main_continuous_kline", spec.product, spec.contract_code, period)
            if not trader_files:
                rows.append(_diff_row(spec.product, period, "missing_trader_future"))
                continue
            aggregated, warnings = aggregate_bars(tqsdk_1m, period)
            trader = _read_bars(trader_files)
            rows.append(_compare(spec.product, period, aggregated, trader, warnings))
    return pd.DataFrame(rows)


def _mapping_gap(session, products: list[str], start: date | None, end: date | None) -> pd.DataFrame:
    query = select(MainContractMap).where(MainContractMap.instrument_symbol.in_(products), MainContractMap.rank == 1)
    if start:
        query = query.where(MainContractMap.trade_date >= start)
    if end:
        query = query.where(MainContractMap.trade_date <= end)
    rows = []
    for item in session.scalars(query.limit(5000)):
        spec = product_spec(item.instrument_symbol)
        contract = f"{spec.exchange}.{spec.product.lower()}{''.join(ch for ch in item.contract_code if ch.isdigit())}"
        has_file = bool(_paths(session, "tqsdk", "contract", spec.product, contract, "1m"))
        if not has_file:
            rows.append({"product": spec.product, "trade_date": item.trade_date, "contract": contract, "status": "missing_contract_1m"})
    return pd.DataFrame(rows)


def _paths(session, provider: str, data_type: str, symbol: str, contract: str, period: str) -> list[Path]:
    query = select(MarketDataFile).where(MarketDataFile.provider == provider, MarketDataFile.data_type == data_type, MarketDataFile.instrument_symbol == symbol, MarketDataFile.contract_code == contract, MarketDataFile.period == period, MarketDataFile.quality_status != "failed")
    result = []
    for item in session.scalars(query.order_by(MarketDataFile.start_time)):
        path = Path(item.file_path)
        result.append(path if path.is_absolute() else PROJECT_ROOT / path)
    return result


def _read_bars(paths: list[Path]) -> pd.DataFrame:
    literal = "[" + ", ".join(f"'{str(path).replace(chr(39), chr(39) + chr(39))}'" for path in paths) + "]"
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(f"select * from read_parquet({literal}, union_by_name = true) order by datetime").fetchdf()


def _compare(product: str, period: str, left: pd.DataFrame, right: pd.DataFrame, warnings: list[str]) -> dict[str, object]:
    if left.empty:
        return _diff_row(product, period, "missing_tqsdk_aggregate", warnings=warnings)
    merged = left.merge(right, on="datetime", suffixes=("_tqsdk", "_trader"))
    if merged.empty:
        return _diff_row(product, period, "no_overlap", len(left), len(right), warnings)
    price_cols = ["open", "high", "low", "close"]
    return {
        "product": product,
        "period": period,
        "status": "ok",
        "tqsdk_rows": len(left),
        "trader_rows": len(right),
        "overlap_rows": len(merged),
        "overlap_ratio": round(len(merged) / max(len(right), 1), 6),
        "max_price_diff": max(float((merged[f"{col}_tqsdk"] - merged[f"{col}_trader"]).abs().max()) for col in price_cols),
        "max_volume_diff": float((merged["volume_tqsdk"] - merged["volume_trader"]).abs().max()),
        "warnings": "; ".join(warnings),
    }


def _diff_row(product: str, period: str, status: str, tqsdk_rows: int = 0, trader_rows: int = 0, warnings: list[str] | None = None) -> dict[str, object]:
    return {"product": product, "period": period, "status": status, "tqsdk_rows": tqsdk_rows, "trader_rows": trader_rows, "overlap_rows": 0, "overlap_ratio": 0, "max_price_diff": "", "max_volume_diff": "", "warnings": "; ".join(warnings or [])}


def _summary(coverage: pd.DataFrame, quality: pd.DataFrame, diff: pd.DataFrame, gap: pd.DataFrame) -> str:
    return (
        "# TqSdk Audit Summary\n\n"
        "## Coverage\n\n"
        + _counts(coverage, "status")
        + "\n## Quality\n\n"
        + _counts(quality, "status")
        + "\n## Cross Source Diff\n\n"
        + _counts(diff, "status")
        + "\n## Mapping Gaps\n\n"
        + _counts(gap, "status")
    )


def _counts(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return "_No rows._\n"
    counts = frame.groupby(column).size().reset_index(name="count")
    columns = list(counts.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for record in counts.astype(str).to_dict("records"):
        lines.append("| " + " | ".join(record[column].replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines) + "\n"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
