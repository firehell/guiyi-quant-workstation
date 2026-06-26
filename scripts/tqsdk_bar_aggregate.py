from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
import argparse
import sys
from uuid import uuid4

import duckdb
import pandas as pd
from sqlalchemy import delete, select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import DataDownloadTask, DataQualityReport, MarketDataFile  # noqa: E402
from app.services.tqsdk_ingest.aggregate import aggregate_bars  # noqa: E402
from app.services.tqsdk_ingest.manifest import TqSdkCsvManifest  # noqa: E402
from app.services.tqsdk_ingest.parquet import sha256_file, write_parquet_atomic  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate TqSdk 1m canonical bars into higher periods")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--provider", default="tqsdk")
    run.add_argument("--data-type", default="main_continuous")
    run.add_argument("--periods", nargs="+", required=True)
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--start-date", type=_parse_date)
    run.add_argument("--end-date", type=_parse_date)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest = TqSdkCsvManifest(PROJECT_ROOT / "data/manifests/tqsdk_bar_aggregate_manifest.csv")
    with SessionLocal() as session:
        files = _input_files(session, provider=args.provider, data_type=args.data_type, products=args.products, start=args.start_date, end=args.end_date)
        for market_file in files:
            bars = _read_bars([Path(market_file.file_path)])
            for period in args.periods:
                key = f"{market_file.instrument_symbol}:{args.data_type}:{period}:{market_file.start_time:%Y-%m}"
                if not manifest.should_run(key, resume=args.resume, retry_failed=False, force=args.force):
                    print(f"skip {key}")
                    continue
                aggregated, warnings = aggregate_bars(bars, period)
                if aggregated.empty:
                    manifest.mark(key=key, status="empty", error="no rows")
                    print(f"empty {key}")
                    continue
                output = _output_path(market_file, args.data_type, period)
                enriched = _enrich(aggregated, market_file, args.data_type, period)
                write_parquet_atomic(enriched, output)
                indexed = _record_aggregate(session, market_file, output, enriched, args.data_type, period, warnings)
                session.commit()
                manifest.mark(
                    key=key,
                    provider=args.provider,
                    data_type=args.data_type,
                    product=market_file.instrument_symbol or "",
                    exchange=_value_from_path(output, "exchange"),
                    contract=market_file.contract_code or "",
                    source_symbol=market_file.contract_code or "",
                    period=period,
                    chunk_start=indexed.start_time.date(),
                    chunk_end=indexed.end_time.date(),
                    canonical_path=output,
                    rows=len(enriched),
                    checksum=sha256_file(output),
                    status="success",
                    error="; ".join(warnings),
                )
                print(f"success {key}: rows={len(enriched)} warnings={len(warnings)}")


def _input_files(session, *, provider: str, data_type: str, products: list[str] | None, start: date | None, end: date | None) -> list[MarketDataFile]:
    query = select(MarketDataFile).where(MarketDataFile.provider == provider, MarketDataFile.data_type == data_type, MarketDataFile.period == "1m", MarketDataFile.quality_status != "failed")
    if products:
        query = query.where(MarketDataFile.instrument_symbol.in_(products))
    if start:
        query = query.where(MarketDataFile.end_time >= datetime.combine(start, datetime.min.time(), tzinfo=UTC))
    if end:
        query = query.where(MarketDataFile.start_time <= datetime.combine(end, datetime.max.time(), tzinfo=UTC))
    return list(session.scalars(query.order_by(MarketDataFile.start_time)))


def _read_bars(paths: list[Path]) -> pd.DataFrame:
    literal = "[" + ", ".join(f"'{str((path if path.is_absolute() else PROJECT_ROOT / path)).replace(chr(39), chr(39) + chr(39))}'" for path in paths) + "]"
    with duckdb.connect(database=":memory:") as connection:
        return connection.execute(f"select * from read_parquet({literal}, union_by_name = true) order by datetime").fetchdf()


def _output_path(market_file: MarketDataFile, data_type: str, period: str) -> Path:
    source = Path(market_file.file_path)
    parts = source.parts
    exchange = _part(parts, "exchange")
    symbol = market_file.instrument_symbol or _part(parts, "symbol")
    contract = market_file.contract_code or _part(parts, "contract")
    year = f"{market_file.start_time:%Y}"
    month = f"{market_file.start_time:%m}"
    return PROJECT_ROOT / "data/parquet/canonical/bars" / "provider=tqsdk" / f"data_type={data_type}" / f"period={period}" / f"exchange={exchange}" / f"symbol={symbol}" / f"contract={contract}" / f"year={year}" / f"month={month}" / "part-000.parquet"


def _enrich(frame: pd.DataFrame, market_file: MarketDataFile, data_type: str, period: str) -> pd.DataFrame:
    output = frame.copy()
    output["symbol"] = market_file.instrument_symbol
    output["contract"] = market_file.contract_code
    output["provider"] = "tqsdk"
    output["data_type"] = data_type
    output["period"] = period
    output["source_period"] = "1m"
    output["data_version"] = "tq_aggregate_v1"
    output["created_at"] = datetime.now(UTC)
    return output


def _record_aggregate(session, source_file: MarketDataFile, path: Path, frame: pd.DataFrame, data_type: str, period: str, warnings: list[str]) -> MarketDataFile:
    start_time = frame["datetime"].min().to_pydatetime()
    end_time = frame["datetime"].max().to_pydatetime()
    task = DataDownloadTask(
        task_no=f"tqsdk-aggregate-{uuid4().hex[:12]}",
        provider="tqsdk",
        data_type=data_type,
        instrument_symbol=source_file.instrument_symbol,
        contract_code=source_file.contract_code,
        period=period,
        start_time=start_time,
        end_time=end_time,
        status="success",
        progress=100,
        result={"source_file_id": source_file.id, "warnings": warnings},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    session.add(task)
    session.flush()
    market_file = session.scalar(
        select(MarketDataFile).where(
            MarketDataFile.provider == "tqsdk",
            MarketDataFile.data_type == data_type,
            MarketDataFile.instrument_symbol == source_file.instrument_symbol,
            MarketDataFile.contract_code == source_file.contract_code,
            MarketDataFile.period == period,
            MarketDataFile.start_time == start_time,
            MarketDataFile.end_time == end_time,
            MarketDataFile.data_version == "tq_aggregate_v1",
        )
    )
    if market_file is None:
        market_file = MarketDataFile(provider="tqsdk", data_type=data_type, instrument_symbol=source_file.instrument_symbol, contract_code=source_file.contract_code, period=period, start_time=start_time, end_time=end_time, data_version="tq_aggregate_v1")
        session.add(market_file)
    market_file.task_id = task.id
    market_file.file_path = str(path)
    market_file.row_count = len(frame)
    market_file.file_size_bytes = path.stat().st_size
    market_file.checksum = sha256_file(path)
    market_file.quality_status = "warning" if warnings else "passed"
    session.flush()
    session.execute(delete(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
    session.add(DataQualityReport(file_id=market_file.id, task_id=task.id, provider="tqsdk", data_type=data_type, instrument_symbol=source_file.instrument_symbol, contract_code=source_file.contract_code, period=period, start_time=start_time, end_time=end_time, status=market_file.quality_status, details={"check_rule_version": "tqsdk_aggregate_v1", "warnings": warnings, "source_file_id": source_file.id}))
    return market_file


def _value_from_path(path: Path, key: str) -> str:
    return _part(path.parts, key)


def _part(parts, key: str) -> str:
    prefix = f"{key}="
    return next((part.split("=", 1)[1] for part in parts if part.startswith(prefix)), "")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
