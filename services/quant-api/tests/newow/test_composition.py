"""Shared assembly retains consumer-selected Newow policies and resources."""

from datetime import timedelta

import pytest

from guiyi_quant.newow.product_identity import InputQualityPolicy
from guiyi_quant.newow.product_contracts import ProductFrequency
from app.market_data.newow.composition import NewowComposition
from app.market_data.newow.product_reader import NewowProductReadCancelled
from app.market_data.newow.product_service import ProductServiceQuery
from app.market_data.newow.resource_gate import HeavyResourceGate
from app.market_data.newow.snapshot_cache import SnapshotCache
from app.market_data.newow.inflight import InFlightCoordinator


def test_shared_composition_matches_existing_reader_and_service_outputs(product_cases):
    reader, query, facts = product_cases.paged_reader(prefix_bars=50, frequency="1d")

    def now():
        return facts.as_of

    composition = NewowComposition(
        facts, facts.coverage, ("rb",), InputQualityPolicy.V1, now=now
    )
    shared = composition.reader()
    assert shared.load(query, facts.as_of) == reader.load(query, facts.as_of)

    from app.market_data.newow.product_service import NewowProductService

    direct = NewowProductService(lambda _context, _cancelled: reader, now=now)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of)
    expected = direct.query(request)
    actual = composition.service(cancelled=None).query(request)
    assert actual.chart == expected.chart
    assert actual.meta.input_content_sha256 == expected.meta.input_content_sha256


def test_context_policy_and_quality_are_explicit_and_do_not_leak(product_cases):
    _, _, facts = product_cases.paged_reader(prefix_bars=3, frequency="1d")

    def context_policy(_product, _frequency):
        return InputQualityPolicy.WEEKLY_V2

    http = NewowComposition(
        facts,
        facts.coverage,
        ("rb",),
        InputQualityPolicy.DAILY_V2,
        now=lambda: facts.as_of,
        context_quality_policy=context_policy,
    )
    snapshot = NewowComposition(
        facts,
        facts.coverage,
        ("rb",),
        InputQualityPolicy.V1,
        now=lambda: facts.as_of - timedelta(seconds=1),
    )
    assert http.reader()._context_quality_policy is None
    context_reader = http.reader((ProductFrequency.WEEKLY,))
    assert context_reader._context_quality_policy is context_policy
    assert context_reader._input_quality_policy is InputQualityPolicy.DAILY_V2
    assert snapshot.reader((ProductFrequency.WEEKLY,))._context_quality_policy is None
    assert snapshot.reader()._input_quality_policy is InputQualityPolicy.V1
    assert snapshot.reader()._now() != context_reader._now()


def test_budget_and_consumer_cancellation_remain_independent(product_cases):
    _, query, facts = product_cases.paged_reader(prefix_bars=3, frequency="1d")
    budget, consumer = [False], [False]
    composition = NewowComposition(
        facts,
        facts.coverage,
        ("rb",),
        InputQualityPolicy.V1,
        now=lambda: facts.as_of,
        budget_cancelled=lambda: budget[0],
    )
    reader = composition.reader(cancelled=lambda: consumer[0])
    reader.load(query, facts.as_of)
    for budget[0], consumer[0] in ((True, False), (False, True)):
        with pytest.raises(NewowProductReadCancelled):
            reader.load(query, facts.as_of)


def test_explicit_resources_and_reference_authority_survive_assembly(product_cases):
    _, _, facts = product_cases.paged_reader(prefix_bars=3, frequency="1d")

    def clock():
        return facts.as_of

    composition = NewowComposition(
        facts, facts.coverage, ("rb",), InputQualityPolicy.V1, now=clock
    )
    cache, gate, reference_gate, inflight = (
        SnapshotCache(),
        HeavyResourceGate(),
        HeavyResourceGate(),
        InFlightCoordinator(),
    )

    def reference(*_args):
        return None

    service = composition.service(
        cancelled=None,
        cache=cache,
        heavy_gate=gate,
        persisted_reference_gate=reference_gate,
        inflight=inflight,
        persisted_reference=reference,
        reuse_read_inputs=True,
    )
    assert service._cache is cache
    assert service._gate is gate
    assert service._reference_gate is reference_gate
    assert service._inflight is inflight
    assert service._persisted_reference is reference
    assert service._now is clock
    assert service._reuse_read_inputs is True
    assert composition.service(cancelled=None)._persisted_reference is None


def test_http_and_snapshot_assembly_keep_outputs_and_distinct_context_policy(
    product_cases, monkeypatch
):
    from app.api import market_newow

    _, _, facts = product_cases.paged_reader(prefix_bars=50, frequency="1d")
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE", "legacy")
    monkeypatch.setattr(
        market_newow, "build_market_data_service", lambda _session: facts
    )
    monkeypatch.setattr(
        market_newow,
        "build_database_coverage_source",
        lambda _session, **_options: facts.coverage,
    )
    monkeypatch.setattr(market_newow, "load_active_products", lambda: ("rb",))
    http = market_newow._build_product_service(object())
    reader, factory = market_newow._build_snapshot_inputs(
        object(), lambda: False, lambda: facts.as_of
    )
    snapshot = factory(lambda: False)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of)
    http_result, snapshot_result = http.query(request), snapshot.query(request)
    assert http_result.chart == snapshot_result.chart
    assert (
        http_result.meta.input_content_sha256
        == snapshot_result.meta.input_content_sha256
    )
    assert (
        http._reader_factory((ProductFrequency.WEEKLY,), None)._context_quality_policy
        is not None
    )
    assert (
        snapshot._reader_factory(
            (ProductFrequency.WEEKLY,), None
        )._context_quality_policy
        is None
    )
    assert reader._now() == facts.as_of
    assert http._cache is snapshot._cache is market_newow._PRODUCT_CACHE
    assert http._reference_gate is market_newow._PERSISTED_REFERENCE_GATE
    assert snapshot._reference_gate is market_newow._PRODUCT_GATE
