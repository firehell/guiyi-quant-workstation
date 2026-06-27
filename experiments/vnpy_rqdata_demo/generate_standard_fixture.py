#!/usr/bin/env python3
"""Generate a deterministic standard Parquet fixture for V1 backtest tests."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_PATH = (
    PROJECT_ROOT
    / "services"
    / "quant-api"
    / "tests"
    / "fixtures"
    / "standard_parquet"
    / "canonical"
    / "bars"
    / "provider=local_parquet"
    / "interval=60m"
    / "exchange=SHFE"
    / "symbol=rb"
    / "contract=rb2405"
    / "rb2405_60m.parquet"
)

ROW_COUNT = 96
DATA_VERSION = "sample_standard_parquet_v1"


def build_sample_frame(row_count: int = ROW_COUNT) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = datetime(2024, 1, 2, 9, 0)
    previous_close = 3500.0

    for index in range(row_count):
        moment = start + timedelta(hours=index)
        drift = index * 1.75
        wave = ((index % 12) - 6) * 2.4
        close = round(3500.0 + drift + wave, 2)
        open_price = round(previous_close, 2)
        high = round(max(open_price, close) + 8.0 + (index % 5), 2)
        low = round(min(open_price, close) - 7.0 - (index % 3), 2)
        volume = 1000 + index * 13
        turnover = round(close * volume * 10, 2)

        rows.append(
            {
                "symbol": "rb",
                "contract": "rb2405",
                "exchange": "SHFE",
                "vt_symbol": "rb2405.SHFE",
                "datetime": moment,
                "trading_day": date(2024, 1, 2) + timedelta(days=index // 8),
                "interval": "60m",
                "period": "60m",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
                "open_interest": 120000 + index * 21,
                "source": "sample",
                "provider": "local_parquet",
                "data_role": "primary",
                "quality_status": "passed",
                "data_version": DATA_VERSION,
            }
        )
        previous_close = close

    return pd.DataFrame(rows)


def write_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> Path:
    frame = build_sample_frame()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the V1 standard Parquet sample fixture.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help="Output parquet path. Defaults to the quant-api test fixture path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = write_fixture(args.output)
    frame = pd.read_parquet(path)
    print(f"standard parquet fixture written: {path}")
    print(
        f"rows={len(frame)} "
        f"symbol={frame['symbol'].iloc[0]} "
        f"contract={frame['contract'].iloc[0]} "
        f"interval={frame['interval'].iloc[0]}"
    )
    print(f"start={frame['datetime'].min()} end={frame['datetime'].max()}")


if __name__ == "__main__":
    main()
