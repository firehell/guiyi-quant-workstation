from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.market_data.newow.product_query import NewowProductQuery
from app.reference_trading.history_input_cache import HistoricalMarketReadCache

NOW = datetime(2026, 10, 8, 8, tzinfo=UTC)


def query(strategy="trend", frequency="1d"):
    return NewowProductQuery(
        "rb", strategy, frequency, date(2026, 9, 1), date(2026, 10, 8), as_of=NOW
    )


def fixture():
    events = []

    @contextmanager
    def lease():
        events.append("acquire")
        try:
            yield
        finally:
            events.append("release")

    reads = []

    class Reader:
        def load(self, q, at):
            reads.append((q, at))
            return SimpleNamespace(bars=(len(reads),))

        def historical_metadata_evidence(self, **kwargs):
            reads.append(kwargs)
            return {"fact": ["original"]}

        def historical_input_bound(self, **kwargs):
            reads.append(kwargs)
            return (12, 4096)

    cache = HistoricalMarketReadCache(lease)
    return cache, Reader(), events, reads


def test_only_pure_market_read_shared_across_strategies_inside_lease():
    cache, reader, events, reads = fixture()
    proxy = cache.reader(reader, policy_key=("daily_v2", ()))
    proxy.load(query(), NOW)
    proxy.load(query(), NOW)
    assert len(reads) == 2 and events == []
    with cache.scope("rb"):
        first = proxy.load(query(), NOW)
        with cache.guard():
            assert proxy.load(query("oscillation"), NOW) is first
        assert proxy.load(query("main_rise"), NOW) is first
        assert events == ["acquire"] and len(reads) == 3
    assert events == ["acquire", "release"]
    with cache.scope("rb"):
        assert proxy.load(query(), NOW) is not first
    assert len(reads) == 4


def test_quality_frequency_asof_and_windows_never_alias():
    cache, reader, events, reads = fixture()
    with cache.scope("rb"):
        a = cache.reader(reader, policy_key=("daily_v2", ()))
        b = cache.reader(reader, policy_key=("v1", ()))
        a.load(query(), NOW)
        b.load(query(), NOW)
        a.load(query(frequency="1w"), NOW)
        a.load(query(), NOW.replace(hour=9))
    assert len(reads) == 4


def test_failure_releases_lease_and_never_retains_market_evidence():
    cache, reader, events, reads = fixture()
    proxy = cache.reader(reader, policy_key="v1")
    with pytest.raises(RuntimeError):
        with cache.scope("rb"):
            proxy.load(query(), NOW)
            raise RuntimeError("cancelled")
    with cache.scope("rb"):
        proxy.load(query(), NOW)
    assert len(reads) == 2 and events == ["acquire", "release", "acquire", "release"]


def test_mutable_proof_is_copied_and_nested_scope_rejected():
    cache, reader, events, reads = fixture()
    proxy = cache.reader(reader, policy_key="v1")
    with cache.scope("rb"):
        proof = proxy.historical_metadata_evidence(
            product="rb", through=date(2026, 10, 8)
        )
        proof["fact"].append("modified")
        assert proxy.historical_metadata_evidence(
            product="rb", through=date(2026, 10, 8)
        ) == {"fact": ["original"]}
        with pytest.raises(ValueError, match="REFERENCE_INPUT_LEASE_ALREADY_HELD"):
            with cache.scope("cu"):
                pass
    assert len(reads) == 1


def test_outer_scope_binds_one_product_and_rejects_cross_product():
    from dataclasses import replace

    cache, reader, events, reads = fixture()
    proxy = cache.reader(reader, policy_key="v1")
    with cache.scope():
        proxy.load(query(), NOW)
        with pytest.raises(ValueError, match="REFERENCE_INPUT_LEASE_PRODUCT_CONFLICT"):
            proxy.load(replace(query(), product="cu"), NOW)
    assert len(reads) == 1 and events == ["acquire", "release"]


def test_cancelled_cache_hit_still_fails_and_releases():
    cache, reader, events, reads = fixture()
    stopped = [False]
    cache._cancelled = lambda: stopped[0]
    proxy = cache.reader(reader, policy_key="v1")
    with pytest.raises(RuntimeError, match="NEWOW_READ_CANCELLED"):
        with cache.scope("rb"):
            proxy.load(query(), NOW)
            stopped[0] = True
            proxy.load(query("oscillation"), NOW)
    assert len(reads) == 1 and events == ["acquire", "release"]


def test_opt_in_composition_holds_one_real_lease_and_keeps_refresh_default(monkeypatch):
    from contextlib import nullcontext
    from app.reference_trading.composition import open_historical_reference_components

    events, reads = [], []

    class Catalog:
        def __init__(self, *args):
            pass

        def acquire_maintenance_lock(self):
            events.append("acquire")
            return SimpleNamespace(release=lambda: events.append("release"))

    class ProductReader:
        def __init__(self, *args, **kwargs):
            pass

        def load(self, query, as_of):
            reads.append(query)
            return SimpleNamespace(bars=())

    monkeypatch.setattr("app.market_data.catalog.MarketCatalog", Catalog)
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service", lambda _: object()
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_database_coverage_source", lambda _: object()
    )
    monkeypatch.setattr(
        "app.market_data.newow.product_reader.NewowProductReader", ProductReader
    )
    identity = SimpleNamespace(product="rb", frequency="1d")

    def factory():
        return nullcontext(object())

    with open_historical_reference_components(
        session_factory=factory, reuse_market_inputs=True
    ) as (planner, _):
        a = planner._reader._newow_for(identity)
        b = planner._reader._newow_for(identity)
        assert a.load(query(), NOW) is b.load(query("oscillation"), NOW)
        assert events == ["acquire"]
    assert events == ["acquire", "release"] and len(reads) == 1
    with open_historical_reference_components(session_factory=factory) as (planner, _):
        a = planner._reader._newow_for(identity)
        a.load(query(), NOW)
        a.load(query("oscillation"), NOW)
    assert len(reads) == 3 and events == ["acquire", "release"]


def test_pure_preflight_bound_reuses_exact_parameters_inside_lease():
    cache, reader, events, reads = fixture()
    proxy = cache.reader(reader, policy_key="v1")
    args = dict(
        product="rb",
        frequency="60m",
        since=date(2025, 9, 25),
        through=date(2026, 10, 8),
        as_of=NOW,
    )
    with cache.scope("rb"):
        assert proxy.historical_input_bound(**args) == (12, 4096)
        assert proxy.historical_input_bound(**args) == (12, 4096)
    assert len(reads) == 1
