from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.models.data_center import utc_now
from app.services.rqdata_ingest.bar_aggregation import aggregate_standard_bars


def _one_minute_frame() -> pd.DataFrame:
    stamps = list(pd.date_range("2026-07-06 09:01:00", periods=10, freq="min"))
    return pd.DataFrame(
        {
            "symbol": ["jm"] * 10,
            "contract": ["JM2609"] * 10,
            "exchange": ["DCE"] * 10,
            "vt_symbol": ["JM2609.DCE"] * 10,
            "datetime": stamps,
            "trading_day": [date(2026, 7, 6)] * 10,
            "open": [100.0 + index for index in range(10)],
            "high": [101.0 + index for index in range(10)],
            "low": [99.0 + index for index in range(10)],
            "close": [100.5 + index for index in range(10)],
            "volume": [10] * 10,
            "turnover": [1000.0] * 10,
            "open_interest": [500.0] * 10,
            "source": ["rqdata"] * 10,
            "provider": ["rqdata"] * 10,
            "data_role": ["primary"] * 10,
            "quality_status": ["unchecked"] * 10,
            "data_version": ["test-v1"] * 10,
            "created_at": [utc_now()] * 10,
        }
    )


def test_aggregate_standard_bars_builds_5m_from_1m() -> None:
    result = aggregate_standard_bars(_one_minute_frame(), "5m")

    assert len(result) == 2
    assert result["period"].unique().tolist() == ["5m"]
    assert result["source_interval"].unique().tolist() == ["1m"]
    assert result["source_bar_count"].tolist() == [5, 5]
    assert float(result.iloc[0]["open"]) == 100.0
    assert float(result.iloc[0]["close"]) == 104.5


def test_aggregate_standard_bars_builds_1d_by_trading_day() -> None:
    frame = _one_minute_frame()
    frame.loc[0, "datetime"] = pd.Timestamp("2026-07-05 21:01:00")

    result = aggregate_standard_bars(frame, "1d")

    assert len(result) == 1
    assert result.iloc[0]["period"] == "1d"
    assert result.iloc[0]["datetime"] == pd.Timestamp("2026-07-06")
    assert result.iloc[0]["source_interval"] == "1m"
    assert int(result.iloc[0]["source_bar_count"]) == 10
    assert float(result.iloc[0]["open"]) == 100.0
    assert float(result.iloc[0]["close"]) == 109.5


def test_aggregate_standard_bars_rejects_unsupported_period() -> None:
    with pytest.raises(ValueError, match="unsupported aggregation period"):
        aggregate_standard_bars(_one_minute_frame(), "2h")
