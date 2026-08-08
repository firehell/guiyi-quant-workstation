"""Tests for HistoricalUpdateTargetPlanner and shared identity expansion."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.contracts import BarFrequency, DatasetKind
from app.services.data_operations.contracts import HistoricalUpdateRequest
from app.services.data_operations.contracts import CliArgumentInvalid
from app.services.data_operations.target_planner import (
    HistoricalUpdateTargetPlanner,
    build_identity_targets,
    inclusive_trading_days_to_half_open,
)


def test_identity_targets_cover_continuous_and_actual_dominant_direct_periods() -> None:
    targets = build_identity_targets(
        products=("jm",),
        mappings=(
            CanonicalMainContractMapping(
                id=1,
                symbol="jm",
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="rqdata-rank1",
                created_at=None,
            ),
        ),
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    assert {
        (item.dataset_kind.value, item.contract_or_series, item.frequency.value)
        for item in targets
    } == {
        ("continuous", "JM.MAIN", "1m"),
        ("continuous", "JM.MAIN", "1d"),
        ("continuous", "JM.MAIN", "1w"),
        ("actual_dominant", "JM2609", "1m"),
        ("actual_dominant", "JM2609", "1d"),
        ("actual_dominant", "JM2609", "1w"),
    }


def test_inclusive_trading_days_materialize_to_half_open_shanghai_window() -> None:
    start, end = inclusive_trading_days_to_half_open(date(2026, 8, 3), date(2026, 8, 5))
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert start < end
    assert (end - start) == timedelta(days=3)


def test_planner_uses_catalog_gaps_not_fixed_ten_day_window() -> None:
    mappings = (
        CanonicalMainContractMapping(
            id=1,
            symbol="jm",
            trading_day=date(2026, 7, 1),
            actual_contract="JM2609",
            data_version="v",
            created_at=None,
        ),
        CanonicalMainContractMapping(
            id=2,
            symbol="jm",
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            data_version="v",
            created_at=None,
        ),
    )

    def list_mappings(symbol: str, start_day: date, end_day: date):
        return tuple(
            item
            for item in mappings
            if item.symbol == symbol and start_day <= item.trading_day <= end_day
        )

    # Covered only through early July; long backlog must not be truncated to 10 days.
    covered_end = datetime(2026, 7, 10, tzinfo=UTC)

    def covered_windows(probe):
        if probe.dataset_kind is DatasetKind.CONTINUOUS:
            # Mirror 1m coverage onto derived so catch-up since is driven by 1m hole.
            return (
                (
                    datetime(2026, 3, 1, tzinfo=UTC),
                    covered_end,
                ),
            )
        return ()

    planner = HistoricalUpdateTargetPlanner(
        list_mappings=list_mappings,
        covered_windows=covered_windows,
        latest_completed_day=lambda _symbol: date(2026, 8, 3),
        mapping_overlap_trading_days=5,
    )
    plan = planner.plan(
        HistoricalUpdateRequest(products=("jm",), through=date(2026, 8, 3), apply=False)
    )
    assert plan.windows
    since = plan.windows[0].since_day
    assert since <= date(2026, 7, 10)
    assert (date(2026, 8, 3) - since).days > 10
    assert plan.direct_targets
    assert all(item.frequency in DIRECT_SET for item in plan.direct_targets)


def test_planner_uses_earliest_catalog_coverage_not_a_fixed_lookback() -> None:
    mappings = tuple(
        CanonicalMainContractMapping(
            id=index,
            symbol="jm",
            trading_day=day,
            actual_contract="JM2609",
            data_version="v",
            created_at=None,
        )
        for index, day in enumerate((date(2024, 3, 1), date(2026, 8, 3)), start=1)
    )
    planner = HistoricalUpdateTargetPlanner(
        list_mappings=lambda _symbol, _start, _end: mappings,
        covered_windows=lambda probe: (
            (datetime(2020, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)),
            (datetime(2024, 3, 2, tzinfo=UTC), datetime(2026, 8, 4, tzinfo=UTC)),
        )
        if probe.dataset_kind is DatasetKind.CONTINUOUS
        else (),
        latest_completed_day=lambda _symbol: date(2026, 8, 3),
        mapping_overlap_trading_days=0,
    )

    plan = planner.plan(HistoricalUpdateRequest(products=("jm",), apply=False))

    assert plan.windows[0].since_day == date(2024, 3, 1)


def test_actual_dominant_targets_are_limited_to_rank_one_validity_windows() -> None:
    start = datetime(2026, 8, 3, tzinfo=UTC)
    end = datetime(2026, 8, 7, tzinfo=UTC)
    targets = build_identity_targets(
        products=("jm",),
        mappings=(
            CanonicalMainContractMapping(1, "jm", date(2026, 8, 3), "JM2609", "v", None),
            CanonicalMainContractMapping(2, "jm", date(2026, 8, 5), "JM2701", "v", None),
        ),
        start=start,
        end=end,
    )

    actual_m1 = [
        item
        for item in targets
        if item.dataset_kind is DatasetKind.ACTUAL_DOMINANT and item.frequency is BarFrequency.M1
    ]
    assert [(item.contract_or_series, item.start, item.end) for item in actual_m1] == [
        ("JM2609", start, datetime(2026, 8, 4, 16, tzinfo=UTC)),
        ("JM2701", datetime(2026, 8, 4, 16, tzinfo=UTC), end),
    ]


def test_planner_schedules_derived_when_direct_complete_but_aggregate_missing() -> None:
    """1m covered but 15m hole must still plan aggregate-only repair."""
    start, end = inclusive_trading_days_to_half_open(date(2026, 8, 3), date(2026, 8, 3))
    covered_direct = (start, end)

    def covered_windows(probe):
        if probe.frequency in {
            BarFrequency.M5,
            BarFrequency.M15,
            BarFrequency.M30,
            BarFrequency.H1,
        }:
            return ()
        return (covered_direct,)

    planner = HistoricalUpdateTargetPlanner(
        list_mappings=lambda *_args: (
            CanonicalMainContractMapping(
                id=1,
                symbol="jm",
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="v",
                created_at=None,
            ),
        ),
        covered_windows=covered_windows,
        latest_completed_day=lambda _symbol: date(2026, 8, 3),
        mapping_overlap_trading_days=0,
    )
    plan = planner.plan(
        HistoricalUpdateRequest(
            products=("jm",),
            since=date(2026, 8, 3),
            through=date(2026, 8, 3),
            apply=False,
        )
    )

    assert plan.direct_targets == ()
    assert plan.aggregate_targets
    assert all(item.frequency in DERIVED_SET for item in plan.aggregate_targets)
    assert {
        (item.dataset_kind.value, item.contract_or_series, item.frequency.value)
        for item in plan.aggregate_targets
    } >= {
        ("continuous", "JM.MAIN", "5m"),
        ("continuous", "JM.MAIN", "15m"),
        ("actual_dominant", "JM2609", "5m"),
        ("actual_dominant", "JM2609", "15m"),
    }


def test_empty_dataset_requires_explicit_since() -> None:
    planner = HistoricalUpdateTargetPlanner(
        list_mappings=lambda *_args: (
            CanonicalMainContractMapping(
                id=1,
                symbol="jm",
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="v",
                created_at=None,
            ),
        ),
        covered_windows=lambda _probe: (),
        latest_completed_day=lambda _symbol: date(2026, 8, 3),
    )

    with pytest.raises(CliArgumentInvalid) as exc_info:
        planner.plan(HistoricalUpdateRequest(products=("jm",)))

    assert exc_info.value.code == "HISTORICAL_UPDATE_START_REQUIRED"


def test_planner_blocks_any_target_window_with_catalog_gap() -> None:
    start = datetime(2026, 8, 3, tzinfo=UTC)
    planner = HistoricalUpdateTargetPlanner(
        list_mappings=lambda *_args: (
            CanonicalMainContractMapping(
                id=1,
                symbol="jm",
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="v",
                created_at=None,
            ),
        ),
        covered_windows=lambda _probe: (),
        latest_completed_day=lambda _symbol: date(2026, 8, 3),
    )
    planner._list_gaps = lambda _probe: (  # type: ignore[attr-defined]
        type("Gap", (), {"gap_start": start, "gap_end": start + timedelta(hours=1)})(),
    )

    with pytest.raises(CliArgumentInvalid) as exc_info:
        planner.plan(
            HistoricalUpdateRequest(
                products=("jm",),
                since=date(2026, 8, 3),
                through=date(2026, 8, 3),
            )
        )

    assert exc_info.value.code == "HISTORICAL_UPDATE_DATA_GAP"


DIRECT_SET = {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
DERIVED_SET = {BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1}
