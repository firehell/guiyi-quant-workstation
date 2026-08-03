from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.data_core.aggregation import AggregationSession, aggregate_bars
from app.data_core.bar_schema import CanonicalBar, CanonicalBarConflictError
from app.data_core.contracts import (
    BarFrequency,
    DataGapError,
    DatasetAmbiguousError,
    DatasetKind,
)


GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_golden(name: str) -> dict[str, Any]:
    with (GOLDEN_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def _bar_from_json(identity: dict[str, str], item: dict[str, Any]) -> CanonicalBar:
    return CanonicalBar(
        provider=identity["provider"],
        dataset_kind=identity["dataset_kind"],
        symbol=identity["symbol"],
        contract_or_series=identity["contract_or_series"],
        frequency=identity["frequency"],
        bar_end=datetime.fromisoformat(item["bar_end"]),
        trading_day=date.fromisoformat(item["trading_day"]),
        open=item["open"],
        high=item["high"],
        low=item["low"],
        close=item["close"],
        volume=item["volume"],
        turnover=item.get("turnover"),
        open_interest=item.get("open_interest"),
        adjustment=identity["adjustment"],
        schema_version=identity["schema_version"],
    )


def _load_case(
    name: str,
) -> tuple[
    dict[str, Any],
    tuple[CanonicalBar, ...],
    tuple[AggregationSession, ...],
]:
    case = _load_golden(name)
    bars = tuple(_bar_from_json(case["identity"], item) for item in case["bars"])
    sessions = tuple(
        AggregationSession(
            trading_day=date.fromisoformat(item["trading_day"]),
            name=item["name"],
            start=datetime.fromisoformat(item["start"]),
            end=datetime.fromisoformat(item["end"]),
        )
        for item in case["sessions"]
    )
    return case, bars, sessions


def _full_window(
    sessions: tuple[AggregationSession, ...],
) -> tuple[datetime, datetime]:
    return (
        min(session.start for session in sessions),
        max(session.end for session in sessions),
    )


def _serialize(bars: tuple[CanonicalBar, ...]) -> list[dict[str, str | None]]:
    return [
        {
            "bar_end": bar.bar_end.isoformat(),
            "trading_day": bar.trading_day.isoformat(),
            "open": format(bar.open, "f"),
            "high": format(bar.high, "f"),
            "low": format(bar.low, "f"),
            "close": format(bar.close, "f"),
            "volume": format(bar.volume, "f"),
            "turnover": None if bar.turnover is None else format(bar.turnover, "f"),
            "open_interest": (
                None
                if bar.open_interest is None
                else format(bar.open_interest, "f")
            ),
        }
        for bar in bars
    ]


def test_night_session_uses_next_trading_day_without_crossing_identity() -> None:
    case, bars, sessions = _load_case("night_trading_day.json")

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency(case["target_frequency"]),
        sessions=sessions,
        requested_window=_full_window(sessions),
    )

    assert _serialize(result) == case["expected"]
    assert result[0].bar_end == datetime(2026, 7, 29, 13, 5, tzinfo=UTC)
    assert result[0].trading_day == date(2026, 7, 30)


def test_lunch_boundary_creates_separate_session_tail_buckets() -> None:
    case, bars, sessions = _load_case("lunch_boundary.json")

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency(case["target_frequency"]),
        sessions=sessions,
        requested_window=_full_window(sessions),
    )

    assert _serialize(result) == case["expected"]
    assert len(result) == 2
    assert result[0].bar_end < result[1].bar_end


def test_session_close_allows_only_a_complete_short_tail_bucket() -> None:
    case, bars, sessions = _load_case("session_close_tail.json")

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency(case["target_frequency"]),
        sessions=sessions,
        requested_window=_full_window(sessions),
    )

    assert _serialize(result) == case["expected"]
    assert [bar.bar_end for bar in result] == [
        datetime(2026, 7, 30, 6, 57, tzinfo=UTC),
        datetime(2026, 7, 30, 7, 0, tzinfo=UTC),
    ]


def test_exact_duplicates_are_idempotent_and_input_order_is_irrelevant() -> None:
    case, bars, sessions = _load_case("duplicate_reorder.json")

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency(case["target_frequency"]),
        sessions=sessions,
        requested_window=_full_window(sessions),
    )
    reversed_result = aggregate_bars(
        tuple(reversed(bars)),
        target_frequency=BarFrequency(case["target_frequency"]),
        sessions=tuple(reversed(sessions)),
        requested_window=_full_window(sessions),
    )

    assert _serialize(result) == case["expected"]
    assert result == reversed_result


def test_same_identity_and_bar_end_with_different_values_conflicts() -> None:
    case, bars, sessions = _load_case("same_key_conflict.json")
    diagnostics: list[dict[str, object]] = []

    for candidate in (bars, tuple(reversed(bars))):
        with pytest.raises(CanonicalBarConflictError) as error:
            aggregate_bars(
                candidate,
                target_frequency=BarFrequency(case["target_frequency"]),
                sessions=sessions,
                requested_window=_full_window(sessions),
            )
        diagnostics.append(dict(error.value.facts))

    assert error.value.code == "CANONICAL_BAR_CONFLICT"
    assert diagnostics[0] == diagnostics[1]
    assert diagnostics[0]["symbol"] == "jm"
    assert diagnostics[0]["differing_fields"] == ("close", "high")


@pytest.mark.parametrize(
    ("target", "expected_count"),
    [
        (BarFrequency.M5, 12),
        (BarFrequency.M15, 4),
        (BarFrequency.M30, 2),
        (BarFrequency.H1, 1),
    ],
)
def test_all_supported_intraday_targets_use_session_start_anchor(
    target: BarFrequency,
    expected_count: int,
) -> None:
    start = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
    trading_day = date(2026, 7, 30)
    bars = tuple(
        CanonicalBar(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            bar_end=start + timedelta(minutes=index),
            trading_day=trading_day,
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1,
            turnover=None,
            open_interest=None,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for index in range(1, 61)
    )
    sessions = (
        AggregationSession(
            trading_day=trading_day,
            name="morning",
            start=start,
            end=start + timedelta(hours=1),
        ),
    )

    result = aggregate_bars(
        bars,
        target_frequency=target,
        sessions=sessions,
        requested_window=_full_window(sessions),
    )

    assert len(result) == expected_count
    assert result[-1].bar_end == sessions[0].end
    assert all(bar.frequency is target for bar in result)


def test_requested_window_selects_only_complete_bucket_ends() -> None:
    start = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
    trading_day = date(2026, 7, 30)
    bars = tuple(
        CanonicalBar(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            bar_end=start + timedelta(minutes=index),
            trading_day=trading_day,
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100 + index,
            volume=1,
            turnover=None,
            open_interest=None,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for index in range(1, 11)
    )
    sessions = (
        AggregationSession(
            trading_day=trading_day,
            name="morning",
            start=start,
            end=start + timedelta(minutes=10),
        ),
    )

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency.M5,
        sessions=sessions,
        requested_window=(
            start + timedelta(minutes=5),
            start + timedelta(minutes=10),
        ),
    )

    assert len(result) == 1
    assert result[0].bar_end == start + timedelta(minutes=10)
    assert result[0].open == bars[5].open
    assert result[0].close == bars[-1].close


def test_empty_session_outside_requested_window_does_not_block() -> None:
    case, bars, sessions = _load_case("night_trading_day.json")
    unrelated = AggregationSession(
        trading_day=sessions[0].trading_day,
        name="unrelated",
        start=sessions[0].start - timedelta(hours=2),
        end=sessions[0].start - timedelta(hours=1, minutes=55),
    )

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency.M5,
        sessions=(unrelated, *sessions),
        requested_window=_full_window(sessions),
    )

    assert _serialize(result) == case["expected"]


def test_empty_session_with_requested_bucket_reports_missing_minutes() -> None:
    _, _, sessions = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            (),
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=_full_window(sessions),
        )

    assert error.value.facts["reason"] == "missing_source_minutes"
    assert error.value.facts["missing_count"] == 5


def test_requested_window_without_any_bucket_fails_visible() -> None:
    _, bars, sessions = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            bars,
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=(
                sessions[0].start - timedelta(hours=1),
                sessions[0].start - timedelta(minutes=30),
            ),
        )

    assert error.value.facts == {"reason": "no_requested_bucket"}


@pytest.mark.parametrize(
    "requested_window",
    [
        (
            datetime(2026, 7, 29, 12, 0),
            datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
        ),
        (
            datetime(2026, 7, 29, 14, 0, tzinfo=UTC),
            datetime(2026, 7, 29, 13, 0, tzinfo=UTC),
        ),
    ],
)
def test_requested_window_requires_aware_ascending_datetimes(
    requested_window: tuple[datetime, datetime],
) -> None:
    _, bars, sessions = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            bars,
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=requested_window,
        )

    assert error.value.facts == {"reason": "invalid_requested_window"}


@pytest.mark.parametrize(
    "target",
    [BarFrequency.M1, BarFrequency.D1, BarFrequency.W1],
)
def test_aggregator_rejects_direct_daily_and_weekly_targets(
    target: BarFrequency,
) -> None:
    _, bars, sessions = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            bars,
            target_frequency=target,
            sessions=sessions,
            requested_window=_full_window(sessions),
        )

    assert error.value.facts["reason"] == "unsupported_target_frequency"


def test_missing_minute_fails_instead_of_returning_a_partial_bucket() -> None:
    _, bars, sessions = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            bars[:-1],
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=_full_window(sessions),
        )

    assert error.value.facts["reason"] == "missing_source_minutes"
    assert error.value.facts["missing_bar_ends"] == (
        "2026-07-29T13:05:00+00:00",
    )


def test_bar_without_matching_session_including_holiday_fails_visible() -> None:
    _, bars, _ = _load_case("night_trading_day.json")

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            (replace(bars[0], trading_day=date(2026, 8, 1)),),
            target_frequency=BarFrequency.M5,
            sessions=(),
            requested_window=(
                bars[0].bar_end - timedelta(minutes=1),
                bars[0].bar_end,
            ),
        )

    assert error.value.facts["reason"] == "unmatched_session"


def test_multiple_source_identities_are_rejected_not_combined() -> None:
    _, bars, sessions = _load_case("night_trading_day.json")
    mixed = bars + (replace(bars[0], symbol="i", contract_or_series="I2609"),)

    with pytest.raises(DatasetAmbiguousError) as error:
        aggregate_bars(
            mixed,
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=_full_window(sessions),
        )

    assert error.value.facts["reason"] == "multiple_source_identities"


@pytest.mark.parametrize("field", ["turnover", "open_interest"])
def test_optional_numeric_fields_cannot_be_partially_missing(
    field: str,
) -> None:
    _, bars, sessions = _load_case("night_trading_day.json")
    mixed = (replace(bars[0], **{field: None}),) + bars[1:]

    with pytest.raises(DataGapError) as error:
        aggregate_bars(
            mixed,
            target_frequency=BarFrequency.M5,
            sessions=sessions,
            requested_window=_full_window(sessions),
        )

    assert error.value.facts == {
        "reason": "mixed_optional_field",
        "field": field,
        "bucket_end": "2026-07-29T13:05:00+00:00",
    }


def test_aggregation_session_requires_aware_ascending_window() -> None:
    with pytest.raises(DataGapError) as error:
        AggregationSession(
            trading_day=date(2026, 7, 30),
            name="night",
            start=datetime(2026, 7, 29, 21, 0),
            end=datetime(2026, 7, 29, 21, 5),
        )

    assert error.value.facts["reason"] == "invalid_session_window"


def test_geometrically_overlapping_sessions_fail_without_overlap_bar() -> None:
    _, bars, sessions = _load_case("night_trading_day.json")
    overlap = AggregationSession(
        trading_day=sessions[0].trading_day,
        name="overlap",
        start=sessions[0].start + timedelta(minutes=4),
        end=sessions[0].end + timedelta(minutes=5),
    )

    with pytest.raises(DatasetAmbiguousError) as error:
        aggregate_bars(
            (bars[0],),
            target_frequency=BarFrequency.M5,
            sessions=(sessions[0], overlap),
            requested_window=(
                sessions[0].start,
                sessions[0].start + timedelta(minutes=1),
            ),
        )

    assert error.value.facts == {
        "reason": "overlapping_sessions",
        "previous_session": "night",
        "current_session": "overlap",
    }


def test_adjacent_sessions_share_boundary_without_overlap() -> None:
    start = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
    trading_day = date(2026, 7, 30)
    sessions = (
        AggregationSession(
            trading_day=trading_day,
            name="first",
            start=start,
            end=start + timedelta(minutes=1),
        ),
        AggregationSession(
            trading_day=trading_day,
            name="second",
            start=start + timedelta(minutes=1),
            end=start + timedelta(minutes=2),
        ),
    )
    bars = tuple(
        CanonicalBar(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            bar_end=start + timedelta(minutes=index),
            trading_day=trading_day,
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
            turnover=None,
            open_interest=None,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for index in (1, 2)
    )

    result = aggregate_bars(
        bars,
        target_frequency=BarFrequency.M5,
        sessions=sessions,
        requested_window=(start, start + timedelta(minutes=2)),
    )

    assert tuple(bar.bar_end for bar in result) == (
        start + timedelta(minutes=1),
        start + timedelta(minutes=2),
    )
