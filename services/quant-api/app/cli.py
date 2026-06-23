from pathlib import Path
import argparse

from app.db.session import PROJECT_ROOT, SessionLocal
from app.services.trader_future_importer import TraderFutureCsvImporter


def main() -> None:
    parser = argparse.ArgumentParser(prog="guiyi-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-trader-future")
    import_parser.add_argument("--raw-root", default=str(PROJECT_ROOT / "data/raw/trader_Future_data"))
    import_parser.add_argument("--parquet-root", default=str(PROJECT_ROOT / "data/parquet"))
    import_parser.add_argument("--instrument", action="append", dest="instruments")
    import_parser.add_argument("--period", action="append", dest="periods")

    args = parser.parse_args()

    if args.command == "import-trader-future":
        with SessionLocal() as session:
            importer = TraderFutureCsvImporter(
                session=session,
                raw_root=Path(args.raw_root),
                parquet_root=Path(args.parquet_root),
            )
            summary = importer.import_files(instrument_names=args.instruments, periods=args.periods)
            session.commit()
            print(
                f"imported_files={summary.imported_files} "
                f"imported_rows={summary.imported_rows} "
                f"failed_files={summary.failed_files}"
            )


if __name__ == "__main__":
    main()
