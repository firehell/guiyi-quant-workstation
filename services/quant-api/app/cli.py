from pathlib import Path
import argparse
from datetime import date, datetime, time

from app.db.session import PROJECT_ROOT, SessionLocal
from app.services.market_data_reader import MarketDataReader
from app.services.trader_future_importer import TraderFutureCsvImporter


def main() -> None:
    parser = argparse.ArgumentParser(prog="guiyi-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_standardize_parser(subparsers, "import-trader-future")
    _add_standardize_parser(subparsers, "standardize-trader-future")

    check_parser = subparsers.add_parser("check-bars")
    check_parser.add_argument("--symbol", required=True)
    check_parser.add_argument("--contract", required=True)
    check_parser.add_argument("--period", required=True)
    check_parser.add_argument("--start")
    check_parser.add_argument("--end")
    check_parser.add_argument("--provider")

    args = parser.parse_args()

    if args.command in {"import-trader-future", "standardize-trader-future"}:
        with SessionLocal() as session:
            importer = TraderFutureCsvImporter(
                session=session,
                raw_root=Path(args.raw_root),
                parquet_root=Path(args.parquet_root),
            )
            summary = importer.import_files(
                instrument_names=args.instruments,
                periods=args.periods,
                start=_parse_cli_datetime(args.start, end_of_day=False) if args.start else None,
                end=_parse_cli_datetime(args.end, end_of_day=True) if args.end else None,
            )
            session.commit()
            print(
                f"imported_files={summary.imported_files} "
                f"imported_rows={summary.imported_rows} "
                f"failed_files={summary.failed_files}"
            )
    elif args.command == "check-bars":
        with SessionLocal() as session:
            status = MarketDataReader(session).get_quality_status(
                symbol=args.symbol,
                contract=args.contract,
                period=args.period,
                start=_parse_cli_datetime(args.start, end_of_day=False) if args.start else datetime.min,
                end=_parse_cli_datetime(args.end, end_of_day=True) if args.end else datetime.max,
                provider=args.provider,
            )
            print(
                f"status={status['status']} "
                f"missing_bars={status['missing_bars']} "
                f"duplicated_bars={status['duplicated_bars']} "
                f"abnormal_price_count={status['abnormal_price_count']} "
                f"abnormal_volume_count={status['abnormal_volume_count']} "
                f"report_count={status['report_count']}"
            )


def _add_standardize_parser(subparsers: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name)
    parser.add_argument("--raw-root", default=str(PROJECT_ROOT / "data/raw/trader_Future_data"))
    parser.add_argument("--parquet-root", default=str(PROJECT_ROOT / "data/parquet"))
    parser.add_argument("--instrument", action="append", dest="instruments")
    parser.add_argument("--period", action="append", dest="periods")
    parser.add_argument("--start")
    parser.add_argument("--end")
    return parser


def _parse_cli_datetime(value: str, end_of_day: bool) -> datetime:
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.max if end_of_day else time.min)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


if __name__ == "__main__":
    main()
