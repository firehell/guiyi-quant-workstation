from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from app.models.data_center import utc_now
from app.services.rqdata_ingest.bar_aggregation import (
    aggregate_standard_bars,
    aggregate_standard_bars_strict,
)
from app.services.trading_session_clock import SessionWindow


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


def test_strict_aggregation_keeps_night_and_day_sessions_on_trading_day() -> None:
    frame = _one_minute_frame().iloc[:6].copy()
    frame["datetime"] = pd.to_datetime(
        [
            "2026-07-05 21:01:00",
            "2026-07-05 21:02:00",
            "2026-07-05 21:03:00",
            "2026-07-06 09:01:00",
            "2026-07-06 09:02:00",
            "2026-07-06 09:03:00",
        ]
    )
    windows = (
        SessionWindow(date(2026, 7, 6), "night", datetime(2026, 7, 5, 21, 0), datetime(2026, 7, 5, 21, 3)),
        SessionWindow(date(2026, 7, 6), "day", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 3)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [pd.Timestamp("2026-07-05 21:03:00"), pd.Timestamp("2026-07-06 09:03:00")]
    assert result.frame["source_bar_count"].tolist() == [3, 3]
    assert result.diagnostics.source_gap_count == 0
    assert result.diagnostics.incomplete_bucket_count == 0


def test_strict_aggregation_treats_lunch_as_session_boundary() -> None:
    frame = _one_minute_frame().iloc[:10].copy()
    frame["datetime"] = pd.to_datetime(
        [f"2026-07-06 11:{minute:02d}:00" for minute in range(26, 31)]
        + [f"2026-07-06 13:{minute:02d}:00" for minute in range(31, 36)]
    )
    windows = (
        SessionWindow(date(2026, 7, 6), "morning", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 11, 30)),
        SessionWindow(date(2026, 7, 6), "afternoon", datetime(2026, 7, 6, 13, 30), datetime(2026, 7, 6, 15, 0)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [pd.Timestamp("2026-07-06 11:30:00"), pd.Timestamp("2026-07-06 13:35:00")]
    assert result.diagnostics.source_gap_count == 0


def test_strict_aggregation_excludes_first_and_last_partial_buckets() -> None:
    frame = _one_minute_frame().iloc[:6].copy()
    frame["datetime"] = pd.date_range("2026-07-06 09:03:00", periods=6, freq="min")
    windows = (
        SessionWindow(date(2026, 7, 6), "morning", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 10)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame.empty
    assert result.diagnostics.excluded_partial_bucket_count == 2
    assert result.diagnostics.source_gap_count == 0


def test_strict_aggregation_reports_interior_source_gap_without_reanchoring() -> None:
    frame = _one_minute_frame().iloc[:9].copy()
    frame["datetime"] = pd.to_datetime(
        ["2026-07-06 09:01:00", "2026-07-06 09:02:00", "2026-07-06 09:04:00", "2026-07-06 09:05:00"]
        + [f"2026-07-06 09:{minute:02d}:00" for minute in range(6, 11)]
    )
    windows = (
        SessionWindow(date(2026, 7, 6), "morning", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 10)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [pd.Timestamp("2026-07-06 09:10:00")]
    assert result.diagnostics.source_gap_count == 1
    assert result.diagnostics.incomplete_bucket_count == 1


def test_strict_aggregation_reports_wholly_missing_interior_bucket() -> None:
    frame = _one_minute_frame().copy()
    frame["datetime"] = pd.to_datetime(
        [f"2026-07-06 09:{minute:02d}:00" for minute in range(1, 6)]
        + [f"2026-07-06 09:{minute:02d}:00" for minute in range(11, 16)]
    )
    windows = (
        SessionWindow(date(2026, 7, 6), "morning", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 15)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [
        pd.Timestamp("2026-07-06 09:05:00"),
        pd.Timestamp("2026-07-06 09:15:00"),
    ]
    assert result.diagnostics.source_gap_count == 5
    assert result.diagnostics.incomplete_bucket_count == 1


def test_strict_aggregation_accepts_complete_short_session_tail() -> None:
    frame = _one_minute_frame().iloc[:7].copy()
    frame["datetime"] = pd.date_range("2026-07-06 09:01:00", periods=7, freq="min")
    windows = (
        SessionWindow(date(2026, 7, 6), "short", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 7)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [pd.Timestamp("2026-07-06 09:05:00"), pd.Timestamp("2026-07-06 09:07:00")]
    assert result.frame["source_bar_count"].tolist() == [5, 2]
    assert result.diagnostics.incomplete_bucket_count == 0


def test_strict_daily_aggregation_inherits_minute_source_gap_diagnostics() -> None:
    frame = _one_minute_frame().drop(index=[4]).reset_index(drop=True)
    windows = (
        SessionWindow(date(2026, 7, 6), "day", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 10)),
    )

    result = aggregate_standard_bars_strict(frame, "1d", session_windows=windows)

    assert len(result.frame) == 1
    assert result.diagnostics.source_gap_count == 1
    assert result.diagnostics.incomplete_bucket_count == 1


def test_strict_aggregation_reports_entirely_absent_expected_session() -> None:
    frame = _one_minute_frame().iloc[:3].copy()
    frame["datetime"] = pd.date_range("2026-07-06 09:01:00", periods=3, freq="min")
    windows = (
        SessionWindow(date(2026, 7, 6), "night", datetime(2026, 7, 5, 21, 0), datetime(2026, 7, 5, 21, 3)),
        SessionWindow(date(2026, 7, 6), "day", datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 9, 3)),
    )

    result = aggregate_standard_bars_strict(frame, "5m", session_windows=windows)

    assert result.frame["datetime"].tolist() == [pd.Timestamp("2026-07-06 09:03:00")]
    assert result.diagnostics.source_gap_count == 3
    assert result.diagnostics.incomplete_bucket_count == 1
