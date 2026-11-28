"""Export an existing published Backtest Center Run to standard output."""

import argparse
from pathlib import Path
import sqlite3

from app.backtest_center.codec import encode
from app.backtest_center.contracts import BacktestError
from app.backtest_center.store import RunStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        print(encode(RunStore.open_reader(args.store).research_publication(args.run_id)))
    except BacktestError as exc:
        parser.exit(1, f"{exc.code}\n")
    except (OSError, sqlite3.Error):
        parser.exit(1, "BACKTEST_PUBLICATION_STORE_UNAVAILABLE\n")


if __name__ == "__main__":
    main()
