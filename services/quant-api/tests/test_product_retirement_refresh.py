from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.rqdata_adapter import MainMapRow
from app.services.product_retirement_refresh import (
    RefreshWindow,
    RetainedUniverseRefreshExecutor,
    build_refresh_targets,
)


def test_refresh_targets_cover_continuous_and_actual_dominant_direct_periods() -> None:
    targets = build_refresh_targets(
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
        (item.dataset_kind, item.contract_or_series, item.frequency) for item in targets
    } == {
        ("continuous", "JM.MAIN", "1m"),
        ("continuous", "JM.MAIN", "1d"),
        ("continuous", "JM.MAIN", "1w"),
        ("actual_dominant", "JM2609", "1m"),
        ("actual_dominant", "JM2609", "1d"),
        ("actual_dominant", "JM2609", "1w"),
    }


def test_actual_dominant_weekly_targets_use_only_complete_week_end_mapping() -> None:
    mappings = tuple(
        CanonicalMainContractMapping(
            id=index,
            symbol="br",
            trading_day=trading_day,
            actual_contract=contract,
            data_version="rqdata-rank1",
            created_at=None,
        )
        for index, (trading_day, contract) in enumerate(
            (
                (date(2026, 7, 31), "BR2609"),
                (date(2026, 8, 3), "BR2610"),
                (date(2026, 8, 4), "BR2610"),
            ),
            start=1,
        )
    )

    targets = build_refresh_targets(
        products=("br",),
        mappings=mappings,
        start=datetime(2026, 7, 31, tzinfo=UTC),
        end=datetime(2026, 8, 5, tzinfo=UTC),
        weekly_end_day=date(2026, 7, 31),
    )

    actual = {
        (item.contract_or_series, item.frequency)
        for item in targets
        if item.dataset_kind == "actual_dominant"
    }
    assert actual == {
        ("BR2609", "1m"),
        ("BR2609", "1d"),
        ("BR2609", "1w"),
        ("BR2610", "1m"),
        ("BR2610", "1d"),
    }


def test_refresh_executor_replaces_rank1_window_then_syncs_and_aggregates() -> None:
    calls: list[tuple[object, ...]] = []
    window = RefreshWindow(
        start_day=date(2026, 8, 3),
        end_day=date(2026, 8, 3),
        start=datetime(2026, 8, 3, tzinfo=UTC),
        end=datetime(2026, 8, 4, tzinfo=UTC),
    )

    class Adapter:
        def fetch_rank1_map(self, request):
            calls.append(("fetch", request.symbol, request.start_day, request.end_day))
            return (
                MainMapRow(
                    symbol=request.symbol,
                    trading_day=date(2026, 8, 3),
                    actual_contract="JM2609",
                    rank=1,
                    data_version="rqdata-rank1",
                ),
            )

    def mappings(symbol, _start_day, _end_day):
        return (
            CanonicalMainContractMapping(
                id=1,
                symbol=symbol,
                trading_day=date(2026, 8, 3),
                actual_contract="JM2609",
                data_version="rqdata-rank1",
                created_at=None,
            ),
        )

    executor = RetainedUniverseRefreshExecutor(
        mapping_window=lambda symbol: window if symbol == "jm" else None,
        mapping_adapter=Adapter(),
        replace_mapping=lambda symbol, start, end, rows: calls.append(
            ("replace", symbol, start, end, tuple(rows))
        ),
        list_mappings=mappings,
        sync_direct_target=lambda target: calls.append(
            ("direct", target.dataset_kind, target.contract_or_series, target.frequency)
        ),
        aggregate_target=lambda target: calls.append(
            (
                "aggregate",
                target.dataset_kind,
                target.contract_or_series,
                target.frequency,
            )
        ),
    )

    direct_receipt = executor.sync_direct(("jm",), ("1m", "1d", "1w"))
    aggregate_receipt = executor.aggregate(("jm",), ("5m", "15m", "30m", "60m"))

    assert calls[0] == ("fetch", "jm", date(2026, 8, 3), date(2026, 8, 3))
    assert calls[1][0] == "replace"
    assert {call[0] for call in calls[2:8]} == {"direct"}
    assert {call[0] for call in calls[8:]} == {"aggregate"}
    aggregate_calls = tuple(call for call in calls if call[0] == "aggregate")
    assert len(aggregate_calls) == 8
    assert {(call[1], call[2], call[3]) for call in aggregate_calls} == {
        ("continuous", "JM.MAIN", "5m"),
        ("continuous", "JM.MAIN", "15m"),
        ("continuous", "JM.MAIN", "30m"),
        ("continuous", "JM.MAIN", "60m"),
        ("actual_dominant", "JM2609", "5m"),
        ("actual_dominant", "JM2609", "15m"),
        ("actual_dominant", "JM2609", "30m"),
        ("actual_dominant", "JM2609", "60m"),
    }
    assert direct_receipt == {
        "status": "passed",
        "product_count": 1,
        "target_count": 6,
        "frequencies": ["1m", "1d", "1w"],
    }
    assert aggregate_receipt == {
        "status": "passed",
        "product_count": 1,
        "target_count": 8,
        "source_frequency": "1m",
        "frequencies": ["5m", "15m", "30m", "60m"],
    }


def test_production_refresh_selects_ten_days_and_excludes_partial_week() -> None:
    from app.services.product_retirement_production import select_refresh_days

    trading_days = tuple(
        date(2026, 7, 20) + timedelta(days=offset) for offset in range(17)
    )

    selected, weekly_end = select_refresh_days(
        trading_days=trading_days,
        latest_completed=date(2026, 8, 5),
        today=date(2026, 8, 5),
    )

    assert selected == tuple(
        date(2026, 7, 27) + timedelta(days=offset) for offset in range(10)
    )
    assert weekly_end == date(2026, 8, 2)


def test_calendar_refresh_bounds_include_nontrading_current_date() -> None:
    from app.services.product_retirement_production import calendar_refresh_bounds

    assert calendar_refresh_bounds(
        provider_days=(date(2026, 7, 31), date(2026, 8, 3)),
        today=date(2026, 8, 5),
    ) == (date(2026, 7, 31), date(2026, 8, 5))
