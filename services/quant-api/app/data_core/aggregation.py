from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from app.data_core.bar_schema import (
    CanonicalBar,
    CanonicalBarConflictError,
)
from app.data_core.contracts import (
    DERIVED_FREQUENCIES,
    BarFrequency,
    DataGapError,
    DatasetAmbiguousError,
)


_TARGET_MINUTES = {
    BarFrequency.M5: 5,
    BarFrequency.M15: 15,
    BarFrequency.M30: 30,
    BarFrequency.H1: 60,
}


@dataclass(frozen=True, slots=True)
class AggregationSession:
    trading_day: date
    name: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.trading_day, date) or isinstance(
            self.trading_day,
            datetime,
        ):
            raise DataGapError(
                facts={
                    "reason": "invalid_session_trading_day",
                    "value_type": type(self.trading_day).__name__,
                }
            )
        if not isinstance(self.name, str) or not self.name.strip():
            raise DataGapError(
                facts={"reason": "invalid_session_name"}
            )
        if not _is_aware_datetime(self.start) or not _is_aware_datetime(self.end):
            raise DataGapError(
                facts={"reason": "invalid_session_window"}
            )
        start = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        if start >= end:
            raise DataGapError(
                facts={"reason": "invalid_session_window"}
            )
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


def aggregate_bars(
    bars: Iterable[CanonicalBar],
    *,
    target_frequency: BarFrequency,
    sessions: Iterable[AggregationSession],
    requested_window: tuple[datetime, datetime],
) -> tuple[CanonicalBar, ...]:
    target = _normalize_target_frequency(target_frequency)
    request_start, request_end = _normalize_requested_window(requested_window)
    source_bars = _normalize_source_bars(bars)
    normalized_sessions = _normalize_sessions(sessions)
    identities = {_source_identity(bar) for bar in source_bars}
    if len(identities) > 1:
        raise DatasetAmbiguousError(
            facts={
                "reason": "multiple_source_identities",
                "identity_count": len(identities),
            }
        )
    deduplicated = _deduplicate(source_bars)
    session_bars = _assign_to_sessions(deduplicated, normalized_sessions)

    output: list[CanonicalBar] = []
    selected_bucket_count = 0
    for session in normalized_sessions:
        expected = _expected_minute_ends(session)
        actual = {bar.bar_end: bar for bar in session_bars[session]}
        minutes = _TARGET_MINUTES[target]
        for offset in range(0, len(expected), minutes):
            bucket_times = expected[offset : offset + minutes]
            bucket_end = bucket_times[-1]
            if not request_start < bucket_end <= request_end:
                continue
            selected_bucket_count += 1
            bucket_start = session.start + timedelta(minutes=offset)
            bucket_time_set = set(bucket_times)
            missing = tuple(item for item in bucket_times if item not in actual)
            unexpected = tuple(
                bar_end
                for bar_end in actual
                if bucket_start < bar_end <= bucket_end
                and bar_end not in bucket_time_set
            )
            if missing or unexpected:
                raise DataGapError(
                    facts={
                        "reason": "missing_source_minutes",
                        "session": session.name,
                        "trading_day": session.trading_day.isoformat(),
                        "missing_count": len(missing),
                        "missing_bar_ends": tuple(
                            item.isoformat() for item in missing[:10]
                        ),
                        "unexpected_bar_ends": tuple(
                            item.isoformat()
                            for item in sorted(unexpected)[:10]
                        ),
                    }
                )
            bucket = tuple(actual[item] for item in bucket_times)
            output.append(_aggregate_bucket(bucket, target, bucket_end))
    if not selected_bucket_count:
        raise DataGapError(facts={"reason": "no_requested_bucket"})
    return tuple(output)


def _normalize_requested_window(
    value: object,
) -> tuple[datetime, datetime]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise DataGapError(facts={"reason": "invalid_requested_window"})
    start, end = value
    if not _is_aware_datetime(start) or not _is_aware_datetime(end):
        raise DataGapError(facts={"reason": "invalid_requested_window"})
    normalized_start = start.astimezone(UTC)
    normalized_end = end.astimezone(UTC)
    if normalized_start >= normalized_end:
        raise DataGapError(facts={"reason": "invalid_requested_window"})
    return normalized_start, normalized_end


def _normalize_target_frequency(value: object) -> BarFrequency:
    try:
        frequency = BarFrequency(value)
    except (TypeError, ValueError) as exc:
        raise DataGapError(
            facts={
                "reason": "unsupported_target_frequency",
                "value": str(value),
            }
        ) from exc
    if frequency not in DERIVED_FREQUENCIES:
        raise DataGapError(
            facts={
                "reason": "unsupported_target_frequency",
                "value": frequency.value,
            }
        )
    return frequency


def _normalize_source_bars(
    bars: Iterable[CanonicalBar],
) -> tuple[CanonicalBar, ...]:
    try:
        normalized = tuple(bars)
    except TypeError as exc:
        raise DataGapError(
            facts={"reason": "invalid_source_bars"}
        ) from exc
    for bar in normalized:
        if not isinstance(bar, CanonicalBar):
            raise DataGapError(
                facts={
                    "reason": "invalid_source_bar",
                    "value_type": type(bar).__name__,
                }
            )
        if bar.frequency is not BarFrequency.M1:
            raise DataGapError(
                facts={
                    "reason": "source_frequency_must_be_1m",
                    "value": bar.frequency.value,
                }
            )
    return normalized


def _normalize_sessions(
    sessions: Iterable[AggregationSession],
) -> tuple[AggregationSession, ...]:
    try:
        normalized = tuple(sessions)
    except TypeError as exc:
        raise DataGapError(
            facts={"reason": "invalid_sessions"}
        ) from exc
    if not all(isinstance(item, AggregationSession) for item in normalized):
        raise DataGapError(
            facts={"reason": "invalid_session"}
        )
    if len(set(normalized)) != len(normalized):
        raise DatasetAmbiguousError(
            facts={"reason": "duplicate_sessions"}
        )
    ordered = tuple(
        sorted(
            normalized,
            key=lambda item: (
                item.start,
                item.end,
                item.trading_day,
                item.name,
            ),
        )
    )
    for session in ordered:
        duration_seconds = (session.end - session.start).total_seconds()
        if (
            session.start.second
            or session.start.microsecond
            or session.end.second
            or session.end.microsecond
            or duration_seconds % 60
        ):
            raise DataGapError(
                facts={
                    "reason": "session_not_minute_aligned",
                    "session": session.name,
                }
            )
    active = ordered[0] if ordered else None
    for current in ordered[1:]:
        if active is not None and current.start < active.end:
            raise DatasetAmbiguousError(
                facts={
                    "reason": "overlapping_sessions",
                    "previous_session": active.name,
                    "current_session": current.name,
                }
            )
        if active is None or current.end > active.end:
            active = current
    return ordered


def _deduplicate(
    bars: tuple[CanonicalBar, ...],
) -> tuple[CanonicalBar, ...]:
    grouped: dict[tuple[object, ...], list[CanonicalBar]] = {}
    for bar in bars:
        key = (*_source_identity(bar), bar.bar_end)
        grouped.setdefault(key, []).append(bar)

    deduplicated: list[CanonicalBar] = []
    for key in sorted(grouped, key=_duplicate_key_sort_key):
        versions = grouped[key]
        unique_versions = set(versions)
        if len(unique_versions) == 1:
            deduplicated.append(versions[0])
            continue
        differing_fields = tuple(
            sorted(
                field.name
                for field in fields(CanonicalBar)
                if len(
                    {
                        getattr(version, field.name)
                        for version in unique_versions
                    }
                )
                > 1
            )
        )
        raise CanonicalBarConflictError(
            facts={
                "symbol": versions[0].symbol,
                "contract_or_series": versions[0].contract_or_series,
                "bar_end": versions[0].bar_end.isoformat(),
                "differing_fields": differing_fields,
            }
        )
    return tuple(sorted(deduplicated, key=lambda item: item.bar_end))


def _duplicate_key_sort_key(key: tuple[object, ...]) -> tuple[object, ...]:
    return (
        str(key[0]),
        str(key[1]),
        str(key[2]),
        str(key[3]),
        str(key[4]),
        str(key[5]),
        str(key[6]),
        key[7],
    )


def _assign_to_sessions(
    bars: tuple[CanonicalBar, ...],
    sessions: tuple[AggregationSession, ...],
) -> dict[AggregationSession, tuple[CanonicalBar, ...]]:
    assigned: dict[AggregationSession, list[CanonicalBar]] = {
        session: [] for session in sessions
    }
    for bar in bars:
        matches = tuple(
            session
            for session in sessions
            if session.trading_day == bar.trading_day
            and session.start < bar.bar_end <= session.end
        )
        if not matches:
            raise DataGapError(
                facts={
                    "reason": "unmatched_session",
                    "bar_end": bar.bar_end.isoformat(),
                    "trading_day": bar.trading_day.isoformat(),
                }
            )
        if len(matches) > 1:
            raise DatasetAmbiguousError(
                facts={
                    "reason": "overlapping_sessions",
                    "bar_end": bar.bar_end.isoformat(),
                    "session_names": tuple(item.name for item in matches),
                }
            )
        assigned[matches[0]].append(bar)
    return {
        session: tuple(sorted(values, key=lambda item: item.bar_end))
        for session, values in assigned.items()
    }


def _expected_minute_ends(
    session: AggregationSession,
) -> tuple[datetime, ...]:
    count = int((session.end - session.start).total_seconds() // 60)
    return tuple(
        session.start + timedelta(minutes=index)
        for index in range(1, count + 1)
    )


def _aggregate_bucket(
    bars: tuple[CanonicalBar, ...],
    target: BarFrequency,
    bucket_end: datetime,
) -> CanonicalBar:
    first = bars[0]
    last = bars[-1]
    turnover = _aggregate_optional(
        bars,
        field="turnover",
        bucket_end=bucket_end,
        take_last=False,
    )
    open_interest = _aggregate_optional(
        bars,
        field="open_interest",
        bucket_end=bucket_end,
        take_last=True,
    )
    return CanonicalBar(
        provider=first.provider,
        dataset_kind=first.dataset_kind,
        symbol=first.symbol,
        contract_or_series=first.contract_or_series,
        frequency=target,
        bar_end=bucket_end,
        trading_day=first.trading_day,
        open=first.open,
        high=max(bar.high for bar in bars),
        low=min(bar.low for bar in bars),
        close=last.close,
        volume=sum((bar.volume for bar in bars), Decimal(0)),
        turnover=turnover,
        open_interest=open_interest,
        adjustment=first.adjustment,
        schema_version=first.schema_version,
    )


def _aggregate_optional(
    bars: tuple[CanonicalBar, ...],
    *,
    field: str,
    bucket_end: datetime,
    take_last: bool,
) -> Decimal | None:
    values = tuple(getattr(bar, field) for bar in bars)
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    if len(present) != len(values):
        raise DataGapError(
            facts={
                "reason": "mixed_optional_field",
                "field": field,
                "bucket_end": bucket_end.isoformat(),
            }
        )
    if take_last:
        return present[-1]
    return sum(present, Decimal(0))


def _source_identity(bar: CanonicalBar) -> tuple[object, ...]:
    return (
        bar.provider,
        bar.dataset_kind,
        bar.symbol,
        bar.contract_or_series,
        bar.frequency,
        bar.adjustment,
        bar.schema_version,
    )


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
