"""Tests for HistoricalUpdateTargetPlanner and shared identity expansion."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.contracts import BarFrequency, DatasetKind
from app.services.data_operations.contracts import HistoricalUpdateRequest
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
        if probe.frequency is BarFrequency.M1 and probe.dataset_kind is DatasetKind.CONTINUOUS:
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


DIRECT_SET = {BarFrequency.M1, BarFrequency.D1, BarFrequency.W1}
