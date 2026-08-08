from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil

from app.market_data.domain import BarFrequency, CanonicalBar, DERIVED_FREQUENCIES


class AggregationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if (
            self.start.tzinfo is None
            or self.start.utcoffset() is None
            or self.end.tzinfo is None
            or self.end.utcoffset() is None
        ):
            raise AggregationError("SESSION_TIMEZONE_REQUIRED")
        start = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        if start >= end:
            raise AggregationError("SESSION_WINDOW_INVALID")
        if (end - start).total_seconds() % 60:
            raise AggregationError("SESSION_MINUTE_BOUNDARY_REQUIRED")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


_MINUTES = {
    BarFrequency.M5: 5,
    BarFrequency.M15: 15,
    BarFrequency.M30: 30,
    BarFrequency.H1: 60,
}


def aggregate_from_1m(
    bars: tuple[CanonicalBar, ...],
    *,
    target_frequency: BarFrequency | str,
    sessions: tuple[SessionWindow, ...],
) -> tuple[CanonicalBar, ...]:
    try:
        frequency = BarFrequency(target_frequency)
    except ValueError as exc:
        raise AggregationError("TARGET_FREQUENCY_INVALID") from exc
    if frequency not in DERIVED_FREQUENCIES:
        raise AggregationError("TARGET_FREQUENCY_NOT_DERIVED")
    _validate_sessions(sessions)
    source = tuple(bars)
    if any(
        previous.bar_end >= current.bar_end
        for previous, current in zip(source, source[1:])
    ):
        raise AggregationError("SOURCE_1M_NOT_ORDERED")

    assigned: set[datetime] = set()
    output: list[CanonicalBar] = []
    width = _MINUTES[frequency]
    for session in sessions:
        session_bars = tuple(bar for bar in source if session.start < bar.bar_end <= session.end)
        expected_count = int((session.end - session.start).total_seconds() // 60)
        expected_ends = tuple(
            session.start + timedelta(minutes=minute)
            for minute in range(1, expected_count + 1)
        )
        if tuple(bar.bar_end for bar in session_bars) != expected_ends:
            raise AggregationError("SOURCE_1M_INCOMPLETE")
        assigned.update(expected_ends)
        buckets: dict[datetime, list[CanonicalBar]] = {}
        for bar in session_bars:
            elapsed = int((bar.bar_end - session.start).total_seconds() // 60)
            bucket_minutes = min(ceil(elapsed / width) * width, expected_count)
            bucket_end = session.start + timedelta(minutes=bucket_minutes)
            buckets.setdefault(bucket_end, []).append(bar)
        for bucket_end in sorted(buckets):
            output.append(_aggregate_bucket(tuple(buckets[bucket_end]), bucket_end=bucket_end))
    if {bar.bar_end for bar in source} != assigned:
        raise AggregationError("SOURCE_1M_OUTSIDE_SESSION")
    return tuple(output)


def _validate_sessions(sessions: tuple[SessionWindow, ...]) -> None:
    if not sessions:
        raise AggregationError("SESSIONS_REQUIRED")
    for previous, current in zip(sessions, sessions[1:]):
        if previous.end > current.start:
            raise AggregationError("SESSIONS_OVERLAP_OR_UNORDERED")


def _aggregate_bucket(
    bars: tuple[CanonicalBar, ...],
    *,
    bucket_end: datetime,
) -> CanonicalBar:
    first = bars[0]
    last = bars[-1]
    turnovers = tuple(bar.turnover for bar in bars)
    return CanonicalBar(
        bar_end=bucket_end,
        trading_day=last.trading_day,
        open=first.open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=last.close,
        volume=sum((bar.volume for bar in bars), start=Decimal(0)),
        turnover=(
            None
            if all(value is None for value in turnovers)
            else sum((value or Decimal(0) for value in turnovers), start=Decimal(0))
        ),
        open_interest=last.open_interest,
    )
