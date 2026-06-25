from __future__ import annotations

from collections import defaultdict
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
from app.models.data_center import DataDownloadTask, MarketDataFile  # noqa: E402
from app.services.tqsdk_ingest.products import selected_product_specs  # noqa: E402
from app.services.tqsdk_ingest.transformer import CANONICAL_DATA_TYPE, PERIOD, PROVIDER, RAW_DATA_TYPE, build_month_chunks, month_key  # noqa: E402


VALIDATION_PERIODS = ["5m", "15m", "30m", "60m"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit TqSdk 1m coverage and trader_future aggregation validation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    args = parser.parse_args()

    specs = selected_product_specs(args.products)
    reports_dir = PROJECT_ROOT / "data/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    coverage = _coverage_frame(specs=specs, start_date=args.start_date, end_date=args.end_date)
    coverage_path = reports_dir / "tqsdk_1m_coverage_matrix.csv"
    coverage.to_csv(coverage_path, index=False)
    summary_path = reports_dir / "tqsdk_1m_coverage_summary.md"
    summary_path.write_text(_coverage_summary(coverage), encoding="utf-8")

    diff = _validation_frame(specs=specs)
    diff_path = reports_dir / "tqsdk_trader_future_bar_diff.csv"
    diff.to_csv(diff_path, index=False)
    diff_summary_path = reports_dir / "tqsdk_trader_future_bar_diff.md"
    diff_summary_path.write_text(_validation_summary(diff), encoding="utf-8")

    print(f"wrote {coverage_path}")
    print(f"wrote {summary_path}")
    print(f"wrote {diff_path}")
    print(f"wrote {diff_summary_path}")


def _coverage_frame(*, specs, start_date: date | None, end_date: date | None) -> pd.DataFrame:
    rows = []
    with SessionLocal() as session:
        canonical_files = _files_by_key(session, CANONICAL_DATA_TYPE)
        raw_files = _files_by_key(session, RAW_DATA_TYPE)
        failed_tasks = _failed_tasks_by_key(session)
        if start_date is None or end_date is None:
            keys = set(canonical_files) | set(raw_files) | set(failed_tasks)
            if not keys:
                start_date = start_date or date.today()
                end_date = end_date or start_date
        if start_date is not None and end_date is not None:
            expected_keys = {
                month_key(spec, chunk)
                for spec in specs
                for chunk in build_month_chunks(start_date, end_date)
            }
        else:
            expected_keys = set(canonical_files) | set(raw_files) | set(failed_tasks)
        for key in sorted(expected_keys):
            product, _, month = key.split(":", 2)
            raw = raw_files.get(key, [])
            canonical = canonical_files.get(key, [])
            failed = failed_tasks.get(key, [])
            rows.append(
                {
                    "key": key,
                    "product": product,
                    "month": month,
                    "raw_files": len(raw),
                    "canonical_files": len(canonical),
                    "canonical_rows": sum(item.row_count or 0 for item in canonical),
                    "start_time": _min_time(canonical),
                    "end_time": _max_time(canonical),
                    "quality_status": _aggregate_status([item.quality_status for item in canonical]),
                    "failed_tasks": len(failed),
                    "last_error": failed[-1].error_message if failed else "",
                    "status": "ok" if canonical else "failed" if failed else "missing",
                }
            )
    return pd.DataFrame(rows)


def _validation_frame(*, specs) -> pd.DataFrame:
    rows = []
    with SessionLocal() as session:
        for spec in specs:
            tqsdk_files = _market_file_paths(
                session,
                provider=PROVIDER,
                data_type=CANONICAL_DATA_TYPE,
                symbol=spec.product,
                contract=spec.contract_code,
                period=PERIOD,
            )
            if not tqsdk_files:
                continue
            tqsdk_1m = _read_bars(tqsdk_files)
            for period in VALIDATION_PERIODS:
                trader_files = _market_file_paths(
                    session,
                    provider="trader_future_data",
                    data_type="main_continuous_kline",
                    symbol=spec.product,
                    contract=spec.contract_code,
                    period=period,
                )
                if not trader_files:
                    rows.append(_empty_validation_row(spec.product, period, "missing_trader_future"))
                    continue
                trader = _read_bars(trader_files)
                aggregated = _aggregate_1m(tqsdk_1m, period)
                rows.append(_compare_frames(spec.product, period, aggregated, trader))
    return pd.DataFrame(rows)


def _files_by_key(session, data_type: str) -> dict[str, list[MarketDataFile]]:
    result: dict[str, list[MarketDataFile]] = defaultdict(list)
    query = select(MarketDataFile).where(MarketDataFile.provider == PROVIDER, MarketDataFile.data_type == data_type, MarketDataFile.period == PERIOD)
    for item in session.scalars(query):
        key = f"{item.instrument_symbol}:{PERIOD}:{item.start_time:%Y-%m}"
        result[key].append(item)
    return result


def _failed_tasks_by_key(session) -> dict[str, list[DataDownloadTask]]:
    result: dict[str, list[DataDownloadTask]] = defaultdict(list)
    query = select(DataDownloadTask).where(DataDownloadTask.provider == PROVIDER, DataDownloadTask.period == PERIOD, DataDownloadTask.status == "failed")
    for task in session.scalars(query.order_by(DataDownloadTask.finished_at)):
        key = f"{task.instrument_symbol}:{PERIOD}:{task.start_time:%Y-%m}"
        result[key].append(task)
    return result


def _market_file_paths(session, *, provider: str, data_type: str, symbol: str, contract: str, period: str) -> list[Path]:
    query = select(MarketDataFile).where(
        MarketDataFile.provider == provider,
        MarketDataFile.data_type == data_type,
        MarketDataFile.instrument_symbol == symbol,
        MarketDataFile.contract_code == contract,
        MarketDataFile.period == period,
        MarketDataFile.quality_status != "failed",
    )
    paths = []
    for item in session.scalars(query.order_by(MarketDataFile.start_time)):
        path = Path(item.file_path)
        paths.append(path if path.is_absolute() else PROJECT_ROOT / path)
    return paths


def _read_bars(paths: list[Path]) -> pd.DataFrame:
    literal = "[" + ", ".join(f"'{str(path).replace(chr(39), chr(39) + chr(39))}'" for path in paths) + "]"
    sql = f"""
        select datetime, open, high, low, close, volume, open_interest, turnover
        from read_parquet({literal}, union_by_name = true)
        order by datetime
    """
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(sql).fetchdf()


def _aggregate_1m(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    minutes = int(period.removesuffix("m"))
    if frame.empty:
        return frame
    data = frame.copy()
    data["datetime"] = pd.to_datetime(data["datetime"])
    data["bucket"] = data["datetime"].map(lambda value: _period_end(value, minutes))
    grouped = data.groupby("bucket", as_index=False)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        open_interest=("open_interest", "last"),
        turnover=("turnover", "sum"),
    )
    result = result.rename(columns={"bucket": "datetime"})
    return result


def _period_end(value: pd.Timestamp, minutes: int) -> pd.Timestamp:
    minute_of_day = value.hour * 60 + value.minute
    end_minute = ((minute_of_day + minutes - 1) // minutes) * minutes
    return value.normalize() + pd.Timedelta(minutes=end_minute)


def _compare_frames(product: str, period: str, left: pd.DataFrame, right: pd.DataFrame) -> dict[str, object]:
    if left.empty:
        return _empty_validation_row(product, period, "missing_tqsdk")
    merged = left.merge(right, on="datetime", suffixes=("_tqsdk", "_trader"))
    if merged.empty:
        return _empty_validation_row(product, period, "no_overlap", tqsdk_rows=len(left), trader_rows=len(right))
    price_cols = ["open", "high", "low", "close"]
    max_price_diff = max(float((merged[f"{col}_tqsdk"] - merged[f"{col}_trader"]).abs().max()) for col in price_cols)
    volume_diff = float((merged["volume_tqsdk"] - merged["volume_trader"]).abs().max())
    return {
        "product": product,
        "period": period,
        "status": "ok",
        "tqsdk_rows": len(left),
        "trader_rows": len(right),
        "overlap_rows": len(merged),
        "overlap_ratio": round(len(merged) / max(len(right), 1), 6),
        "max_price_diff": max_price_diff,
        "max_volume_diff": volume_diff,
        "start_time": str(merged["datetime"].min()),
        "end_time": str(merged["datetime"].max()),
    }


def _empty_validation_row(product: str, period: str, status: str, tqsdk_rows: int = 0, trader_rows: int = 0) -> dict[str, object]:
    return {
        "product": product,
        "period": period,
        "status": status,
        "tqsdk_rows": tqsdk_rows,
        "trader_rows": trader_rows,
        "overlap_rows": 0,
        "overlap_ratio": 0,
        "max_price_diff": "",
        "max_volume_diff": "",
        "start_time": "",
        "end_time": "",
    }


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "missing"
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    return "passed"


def _min_time(files: list[MarketDataFile]) -> str:
    return "" if not files else str(min(item.start_time for item in files))


def _max_time(files: list[MarketDataFile]) -> str:
    return "" if not files else str(max(item.end_time for item in files))


def _coverage_summary(frame: pd.DataFrame) -> str:
    counts = frame.groupby("status").size().reset_index(name="count") if not frame.empty else pd.DataFrame()
    return "# TqSdk 1m Coverage Summary\n\n" + _markdown_table(counts) + "\n\n## Non-OK Items\n\n" + _markdown_table(frame[frame["status"] != "ok"].head(100))


def _validation_summary(frame: pd.DataFrame) -> str:
    counts = frame.groupby(["period", "status"]).size().reset_index(name="count") if not frame.empty else pd.DataFrame()
    return "# TqSdk vs Trader Future Bar Diff\n\n" + _markdown_table(counts) + "\n\n## Samples\n\n" + _markdown_table(frame.head(100))


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._\n"
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for record in frame.astype(str).to_dict("records"):
        lines.append("| " + " | ".join(record[column].replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines) + "\n"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
