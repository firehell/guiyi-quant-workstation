from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from app.services.rqdata_ingest.dominant_v2_incremental import (
    CanonicalBaseline,
    append_dominant_v2_tail,
    compute_delta_start,
    find_latest_main_canonical,
    is_up_to_date,
    merge_dominant_frames,
)
from app.services.rqdata_ingest.dominant_v2_parquet import _standard_path


def _write_main_parquet(
    tmp_path,
    *,
    symbol: str,
    period: str,
    start: date,
    end: date,
    datetimes: list[datetime],
    close_values: list[float] | None = None,
) -> None:
    path = _standard_path(
        tmp_path,
        symbol=symbol,
        exchange="DCE",
        contract=f"{symbol}.MAIN",
        period=period,
        start_date=start,
        end_date=end,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    close_values = close_values or [100.0 + index for index in range(len(datetimes))]
    frame = pd.DataFrame(
        {
            "symbol": [symbol] * len(datetimes),
            "contract": [f"{symbol}.MAIN"] * len(datetimes),
            "exchange": ["DCE"] * len(datetimes),
            "vt_symbol": [f"{symbol}.MAIN.DCE"] * len(datetimes),
            "datetime": datetimes,
            "trading_day": [dt.date() for dt in datetimes],
            "interval": [period] * len(datetimes),
            "period": [period] * len(datetimes),
            "open": close_values,
            "high": [value + 1 for value in close_values],
            "low": [value - 1 for value in close_values],
            "close": close_values,
            "volume": [10.0] * len(datetimes),
            "turnover": [1000.0] * len(datetimes),
            "open_interest": [100.0] * len(datetimes),
            "source": ["rqdata"] * len(datetimes),
            "provider": ["rqdata"] * len(datetimes),
            "source_symbol": ["JM2609"] * len(datetimes),
            "data_role": ["primary"] * len(datetimes),
            "quality_status": ["passed"] * len(datetimes),
            "data_version": [f"rqdata_{symbol}_standard_{period}_{start:%Y%m%d}_{end:%Y%m%d}_v2"] * len(datetimes),
            "created_at": [pd.Timestamp("2026-07-10")] * len(datetimes),
        }
    )
    frame.to_parquet(path, index=False)


def test_find_latest_main_canonical_picks_max_datetime(tmp_path) -> None:
    _write_main_parquet(
        tmp_path,
        symbol="jm",
        period="1d",
        start=date(2023, 1, 3),
        end=date(2026, 7, 7),
        datetimes=[datetime(2026, 7, 6)],
    )
    _write_main_parquet(
        tmp_path,
        symbol="jm",
        period="1d",
        start=date(2023, 1, 3),
        end=date(2026, 7, 10),
        datetimes=[datetime(2026, 7, 9)],
    )
    baseline = find_latest_main_canonical(tmp_path, "jm", "1d")
    assert baseline is not None
    assert baseline.last_datetime == pd.Timestamp("2026-07-09")
    assert baseline.end_date_token == date(2026, 7, 10)


def test_compute_delta_start_lookback() -> None:
    last = pd.Timestamp("2026-07-09 23:00:00")
    assert compute_delta_start(last, "1m") == date(2026, 7, 7)
    assert compute_delta_start(last, "1d") == date(2026, 7, 4)
    assert compute_delta_start(last, "1w") == date(2026, 6, 25)


def test_merge_dominant_frames_dedupes_overlap() -> None:
    baseline = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-09 09:01:00"), pd.Timestamp("2026-07-09 09:02:00")],
            "close": [100.0, 101.0],
        }
    )
    delta = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-09 09:02:00"), pd.Timestamp("2026-07-09 09:03:00")],
            "close": [201.0, 202.0],
        }
    )
    merged = merge_dominant_frames(baseline, delta)
    assert len(merged) == 3
    assert merged.iloc[-2]["close"] == 201.0
    assert merged.iloc[-1]["close"] == 202.0


def test_is_up_to_date_for_1m_requires_session_end() -> None:
    assert is_up_to_date(pd.Timestamp("2026-07-09 23:00:00"), date(2026, 7, 11), "1m") is False
    assert is_up_to_date(pd.Timestamp("2026-07-11 15:00:00"), date(2026, 7, 11), "1m") is True


class FakeClient:
    def underlying_symbol(self, product: str) -> str:
        return product.upper()

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range(start_date, end_date, freq="D"),
                "dominant": ["JM2609"] * len(pd.date_range(start_date, end_date, freq="D")),
            }
        )

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        if frequency == "1d":
            stamps = pd.date_range(start_date, end_date, freq="D")
        else:
            stamps = pd.date_range("2026-07-10 09:01:00", periods=3, freq="min")
        return pd.DataFrame(
            {
                "datetime": stamps,
                "open": [100.0] * len(stamps),
                "high": [101.0] * len(stamps),
                "low": [99.0] * len(stamps),
                "close": [100.5] * len(stamps),
                "volume": [10.0] * len(stamps),
                "turnover": [1000.0] * len(stamps),
                "open_interest": [100.0] * len(stamps),
            }
        )


def test_append_dominant_v2_tail_updates_from_baseline(tmp_path) -> None:
    _write_main_parquet(
        tmp_path,
        symbol="jm",
        period="1d",
        start=date(2023, 1, 3),
        end=date(2026, 7, 10),
        datetimes=[datetime(2026, 7, 9)],
    )
    result = append_dominant_v2_tail(
        client=FakeClient(),
        output_root=tmp_path,
        product="jm",
        exchange="DCE",
        period="1d",
        target_end=date(2026, 7, 11),
        dry_run=False,
        register=False,
    )
    assert result.status == "updated"
    assert result.output_path is not None
    assert Path(result.output_path).exists()
    merged = pd.read_parquet(result.output_path)
    assert merged["datetime"].max() >= pd.Timestamp("2026-07-10")
