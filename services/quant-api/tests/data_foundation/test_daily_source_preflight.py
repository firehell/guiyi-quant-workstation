from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
import pytest
from app.market_data.historical_data_manager import (
    HistoricalDataManager,
    BarBatch,
    BarFetchRequest,
)
from app.market_data.domain import DatasetKey, DatasetKind, BarFrequency, CanonicalBar
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.errors import InfrastructureError


def setup_manager(tmp_path, missing=False):
    end = datetime(2026, 9, 30, 7, tzinfo=UTC)
    bar = CanonicalBar(
        end, date(2026, 9, 30), *[Decimal(10)] * 4, Decimal(1), Decimal(10), Decimal(1)
    )
    targets = [
        SimpleNamespace(
            key=DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1),
            year=2026,
            month=9,
            expected=(end,),
            missing=(end,),
            existing=(),
        )
        for symbol, contract in (("a", "A2611"), ("rs", "RS2611"))
    ]
    calls = []

    def fetch(requests):
        calls.append(requests)
        return tuple(
            BarBatch(
                () if missing and request.key.symbol == "rs" else (bar,),
                source_key=request.key,
                requested_ends=request.expected,
            )
            for request in requests
        )

    manager = HistoricalDataManager(
        catalog=SimpleNamespace(all_partitions=lambda key: ()),
        store=CanonicalMonthlyStore(tmp_path),
        coverage=None,
        metadata=None,
        provider=SimpleNamespace(fetch_many=fetch),
    )
    plan = SimpleNamespace(
        groups=(SimpleNamespace(fetch_groups=tuple((target,) for target in targets)),)
    )
    return manager, plan, targets, calls


def test_missing_last_contract_prevents_any_publication(tmp_path):
    manager, plan, targets, calls = setup_manager(tmp_path, True)
    with pytest.raises(InfrastructureError) as exc:
        manager._prepare_daily_sources(plan)
    assert exc.value.code == "RQDATA_NOT_READY"
    assert manager._ready_batches is None
    assert not list(tmp_path.rglob("*.parquet"))


def test_validated_frozen_responses_are_reused_without_refetch(tmp_path):
    manager, plan, targets, calls = setup_manager(tmp_path)
    manager._prepare_daily_sources(plan)
    for target in targets:
        assert (
            len(
                manager._fetch_many((BarFetchRequest(target.key, target.missing),))[
                    0
                ].bars
            )
            == 1
        )
    assert len(calls) == 2
    assert not list(tmp_path.rglob("*.parquet"))


@pytest.mark.parametrize(
    "day,next_day",
    [(date(2026, 9, 24), date(2026, 9, 28)), (date(2026, 9, 30), date(2026, 10, 8))],
)
def test_next_session_crosses_holiday_using_provider_dates(day, next_day):
    from app.market_data.rqdata_adapter import RQDataClient

    calls = []
    client = object.__new__(RQDataClient)
    client.api = SimpleNamespace(get_trading_dates=lambda **kw: (day, next_day))
    client.metadata_snapshot = lambda products, through, starts, **kw: calls.append(
        (products, through, starts, kw)
    )
    client.current_day_metadata_snapshot(("rs",), day)
    assert calls == [(("rs",), next_day, {"rs": day}, {"current_day_only": True})]


@pytest.mark.parametrize(
    "dates",
    [
        (),
        (date(2026, 10, 8), date(2026, 9, 30)),
        (date(2026, 9, 30), date(2026, 9, 30)),
        (date(2026, 10, 8),),
    ],
)
def test_invalid_provider_calendar_never_infers_next_session(dates):
    from app.market_data.rqdata_adapter import RQDataClient

    client = object.__new__(RQDataClient)
    client.api = SimpleNamespace(get_trading_dates=lambda **kw: dates)
    client.metadata_snapshot = lambda *args, **kw: pytest.fail("invalid calendar")
    with pytest.raises(InfrastructureError):
        client.current_day_metadata_snapshot(("rs",), date(2026, 9, 30))


def test_short_week_daily_companion_and_weekly_reuse_exact_frozen_requests(tmp_path):
    from app.market_data.historical_data_manager import _Target

    day_ends = tuple(datetime(2026, 9, day, 7, tzinfo=UTC) for day in (28, 29, 30))
    daily = DatasetKey(DatasetKind.CONTRACT, "a", "A2611", BarFrequency.D1)
    weekly = DatasetKey(DatasetKind.CONTRACT, "a", "A2611", BarFrequency.W1)
    targets = (
        _Target(daily, 2026, 9, day_ends, day_ends, ()),
        _Target(weekly, 2026, 9, (day_ends[-1],), (day_ends[-1],), ()),
    )
    calls = []

    def fetch(requests):
        calls.append(requests)
        return tuple(
            BarBatch(
                tuple(
                    CanonicalBar(
                        end,
                        end.date(),
                        *[Decimal(10)] * 4,
                        Decimal(1),
                        Decimal(10),
                        Decimal(1),
                    )
                    for end in request.expected
                ),
                source_key=request.key,
                requested_ends=request.expected,
            )
            for request in requests
        )

    manager = HistoricalDataManager(
        catalog=SimpleNamespace(all_partitions=lambda key: ()),
        store=CanonicalMonthlyStore(tmp_path),
        coverage=None,
        metadata=None,
        provider=SimpleNamespace(fetch_many=fetch),
    )
    plan = SimpleNamespace(
        groups=(SimpleNamespace(fetch_groups=((targets[0],), targets)),)
    )
    manager._prepare_daily_sources(plan)
    frozen = manager._fetch_many(
        tuple(BarFetchRequest(target.key, target.missing) for target in targets)
    )
    assert len(calls) == 2
    assert len(frozen[0].bars) == 3 and frozen[1].bars[0].bar_end == day_ends[-1]
    # Real immutable storage can publish and read the frozen snapshots; no second
    # provider request occurs and no Oct-1/2 synthetic Bars have been inserted.
    from app.market_data.storage import PublishRequest

    for target, batch in zip(targets, frozen, strict=True):
        partition = manager.store.publish(
            PublishRequest(target.key, 2026, 9, batch.bars, target.expected)
        )
        from app.market_data.catalog import CatalogPartition

        pointer = CatalogPartition(
            target.key,
            2026,
            9,
            partition.coverage_start,
            partition.coverage_end,
            partition.parquet_path,
            partition.row_count,
            partition.source_coverage_start,
            partition.source_coverage_end,
            partition.source_quality,
            partition.source_quality_sha256,
        )
        assert manager.store.read_catalog_partition(pointer) == batch.bars
