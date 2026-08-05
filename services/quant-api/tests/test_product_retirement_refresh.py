from __future__ import annotations

from datetime import UTC, date, datetime

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

    executor.sync_direct(("jm",), ("1m", "1d", "1w"))
    executor.aggregate(("jm",), ("5m", "15m", "30m", "60m"))

    assert calls[0] == ("fetch", "jm", date(2026, 8, 3), date(2026, 8, 3))
    assert calls[1][0] == "replace"
    assert {call[0] for call in calls[2:8]} == {"direct"}
    assert {call[0] for call in calls[8:]} == {"aggregate"}
