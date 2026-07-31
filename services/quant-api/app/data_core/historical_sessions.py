from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Sequence

from sqlalchemy.orm import Session

from app.data_core.aggregation import AggregationSession
from app.data_core.contracts import BarFrequency, ContractValidationError, DatasetKey
from app.data_core.rqdata_adapter import TradingSessionCoverage


def jm_provider_sessions(
    session: Session,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
) -> tuple[TradingSessionCoverage, ...]:
    from app.services.canonical_market_data import jm_sessions

    padding = (
        timedelta(days=7)
        if dataset.frequency in {BarFrequency.D1, BarFrequency.W1}
        else timedelta(0)
    )
    sessions = jm_sessions(
        session,
        symbol=dataset.symbol,
        start=start - padding,
        end=end + padding,
    )
    return build_provider_sessions(
        dataset,
        start=start,
        end=end,
        sessions=sessions,
    )


def build_provider_sessions(
    dataset: DatasetKey,
    *,
    start: datetime,
    end: datetime,
    sessions: Sequence[AggregationSession],
) -> tuple[TradingSessionCoverage, ...]:
    if not isinstance(dataset, DatasetKey):
        raise ContractValidationError(
            facts={"field": "dataset", "reason": "invalid"}
        )
    window_start, window_end = _window(start, end)
    ordered = tuple(sorted(sessions, key=lambda item: (item.start, item.end)))
    if dataset.frequency is BarFrequency.M1:
        return _minute_sessions(ordered, window_start, window_end)
    trading_days = sorted({item.trading_day for item in ordered})
    if dataset.frequency is BarFrequency.D1:
        selected_days = trading_days
    elif dataset.frequency is BarFrequency.W1:
        by_week: dict[tuple[int, int], list[object]] = defaultdict(list)
        for trading_day in trading_days:
            iso = trading_day.isocalendar()
            by_week[(iso.year, iso.week)].append(trading_day)
        selected_days = [max(days) for _, days in sorted(by_week.items())]
    else:
        raise ContractValidationError(
            facts={"field": "frequency", "reason": "direct_required"}
        )
    result: list[TradingSessionCoverage] = []
    for trading_day in selected_days:
        bar_end = datetime.combine(trading_day, time.min, tzinfo=UTC)
        if not window_start < bar_end <= window_end:
            continue
        result.append(
            TradingSessionCoverage(
                trading_day=trading_day,
                start=bar_end - timedelta(microseconds=1),
                end=bar_end,
                expected_bar_ends=(bar_end,),
            )
        )
    return tuple(result)


def _minute_sessions(
    sessions: Sequence[AggregationSession],
    start: datetime,
    end: datetime,
) -> tuple[TradingSessionCoverage, ...]:
    result: list[TradingSessionCoverage] = []
    step = timedelta(minutes=1)
    for session in sessions:
        expected: list[datetime] = []
        bar_end = session.start + step
        while bar_end <= session.end:
            if start < bar_end <= end:
                expected.append(bar_end)
            bar_end += step
        if not expected:
            continue
        result.append(
            TradingSessionCoverage(
                trading_day=session.trading_day,
                start=max(session.start, start),
                end=min(session.end, end),
                expected_bar_ends=tuple(expected),
            )
        )
    return tuple(result)


def _window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if (
        not isinstance(start, datetime)
        or start.tzinfo is None
        or start.utcoffset() is None
        or not isinstance(end, datetime)
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise ContractValidationError(
            facts={"field": "window", "reason": "invalid"}
        )
    return start.astimezone(UTC), end.astimezone(UTC)
