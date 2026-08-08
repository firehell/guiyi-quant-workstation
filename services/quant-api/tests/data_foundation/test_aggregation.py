from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import (
    AggregationError,
    SessionWindow,
    aggregate_from_1m,
    session_digest,
)
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


def test_session_digest_is_ordered_and_stable() -> None:
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    sessions = (
        SessionWindow(start, start + timedelta(hours=1)),
        SessionWindow(start + timedelta(hours=2), start + timedelta(hours=3)),
    )

    assert session_digest(sessions) == session_digest(sessions)
    assert session_digest(sessions) != session_digest(tuple(reversed(sessions)))
