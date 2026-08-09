from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

import app.market_data.aggregation as aggregation
from app.market_data.aggregation import (
    AggregationError,
    SessionWindow,
    aggregate_from_1m,
)
from app.market_data.domain import BarFrequency
from app.market_data.domain import CanonicalBar


def _bars(start: datetime, count: int) -> tuple[CanonicalBar, ...]:
    result = []
    for offset in range(1, count + 1):
        price = Decimal(100 + offset)
        result.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=offset),
                trading_day=date(2025, 1, 2),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=offset,
                turnover=offset * 10,
                open_interest=200 + offset,
            )
        )
    return tuple(result)


def test_aggregate_5m_uses_session_buckets_and_canonical_values() -> None:
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    bars = _bars(start, 10)

    result = aggregate_from_1m(
        bars,
        target_frequency="5m",
        sessions=(SessionWindow(start=start, end=start + timedelta(minutes=10)),),
    )

    assert [bar.bar_end for bar in result] == [
        start + timedelta(minutes=5),
        start + timedelta(minutes=10),
    ]
    assert result[0].open == Decimal("101")
    assert result[0].high == Decimal("106")
    assert result[0].low == Decimal("100")
    assert result[0].close == Decimal("105")
    assert result[0].volume == Decimal("15")
    assert result[0].turnover == Decimal("150")
    assert result[0].open_interest == Decimal("205")


def test_aggregate_never_bridges_session_break() -> None:
    first_start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    second_start = datetime(2025, 1, 2, 2, 0, tzinfo=UTC)

    result = aggregate_from_1m(
        _bars(first_start, 3) + _bars(second_start, 3),
        target_frequency="5m",
        sessions=(
            SessionWindow(first_start, first_start + timedelta(minutes=3)),
            SessionWindow(second_start, second_start + timedelta(minutes=3)),
        ),
    )

    assert [bar.bar_end for bar in result] == [
        first_start + timedelta(minutes=3),
        second_start + timedelta(minutes=3),
    ]


def test_aggregate_rejects_missing_1m_inside_session() -> None:
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    bars = _bars(start, 5)

    with pytest.raises(AggregationError, match="SOURCE_1M_INCOMPLETE"):
        aggregate_from_1m(
            bars[:2] + bars[3:],
            target_frequency="5m",
            sessions=(SessionWindow(start, start + timedelta(minutes=5)),),
        )


def test_bucket_window_aligns_first_5m_bar_to_session_start() -> None:
    """Catches a bucket calculation that aligns to the clock instead of its session."""
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    session = SessionWindow(start=start, end=start + timedelta(minutes=15))

    result = aggregation.bucket_window_for_bar(
        session,
        BarFrequency.M5,
        start + timedelta(minutes=1),
    )

    assert result == SessionWindow(start=start, end=start + timedelta(minutes=5))


def test_bucket_window_keeps_break_boundary_in_its_own_session() -> None:
    """Catches a bucket that extends the final bar at 10:15 across a session break."""
    start = datetime(2025, 1, 2, 9, 0, tzinfo=UTC)
    session = SessionWindow(start=start, end=datetime(2025, 1, 2, 10, 15, tzinfo=UTC))

    result = aggregation.bucket_window_for_bar(
        session,
        "5m",
        session.end,
    )

    assert result == SessionWindow(start=datetime(2025, 1, 2, 10, 10, tzinfo=UTC), end=session.end)


def test_bucket_window_uses_session_end_for_partial_tail() -> None:
    """Catches a partial final bucket that is rounded beyond the session end."""
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    session = SessionWindow(start=start, end=start + timedelta(minutes=7))

    result = aggregation.bucket_window_for_bar(
        session,
        "5m",
        start + timedelta(minutes=6),
    )

    assert result == SessionWindow(start=start + timedelta(minutes=5), end=start + timedelta(minutes=7))


def test_bucket_window_rejects_bar_outside_session() -> None:
    """Catches accidental aggregation of a bar from a break or undeclared session."""
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    session = SessionWindow(start=start, end=start + timedelta(minutes=5))

    with pytest.raises(AggregationError, match="BAR_OUTSIDE_SESSION"):
        aggregation.bucket_window_for_bar(
            session,
            "5m",
            start,
        )


def test_aggregate_bucket_preserves_canonical_ohlcv_semantics() -> None:
    """Catches a shared aggregate primitive that changes historical OHLCV semantics."""
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    bars = _bars(start, 2)

    result = aggregation.aggregate_bucket(
        bars,
        bucket_end=start + timedelta(minutes=5),
    )

    assert result.bar_end == start + timedelta(minutes=5)
    assert result.open == Decimal("101")
    assert result.high == Decimal("103")
    assert result.low == Decimal("100")
    assert result.close == Decimal("102")
    assert result.volume == Decimal("3")
    assert result.turnover == Decimal("30")
    assert result.open_interest == Decimal("202")
