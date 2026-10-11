from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.market_data.newow.page_performance_adapter import project_page_performance
from app.market_data.newow.product_reader import ResolvedPerformanceWindow
from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
from app.reference_trading.persisted_newow import PersistedNewowReference
from app.schemas.market_newow_product import PagePerformanceOut, ProductMetaOut, ReferenceValueOut
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_adapters import label_calculation_segments
from guiyi_quant.newow.product_contracts import ActionKind, ProductStrategy, StrategyAction, TradeEligibility


def test_typed_page_payload_and_terminal_does_not_mutate_reference(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    service = NewowProductService(lambda *_: reader, now=lambda: fake.as_of)
    result = service.query(ProductServiceQuery("rb", "oscillation", "60m", section="reference",
        performance_since=query.performance_since, performance_through=query.performance_through,
        as_of=fake.as_of))
    value = result.reference.value
    PagePerformanceOut.model_validate(value.page_performance)
    before = value.projection
    # The independent page estimate can contain terminal valuation; strategy
    # projection and OPEN/CLOSED facts remain exactly the original object.
    assert before is value.projection
    assert result.meta.schema_version == "newow_product_detail_v4"
    assert value.page_performance["ordinary"]["dates"][-1].endswith("+08:00")
    assert value.page_performance["input_sha256"]


def test_adapter_window_uses_exit_membership_and_full_prefix(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    identity = build_product_identity("rb", "oscillation", "60m")
    through = read.replay_bars[-1].bar.trading_day
    full_window = ResolvedPerformanceWindow(query.performance_since, through, through, fake.as_of)
    narrow_window = replace(full_window, requested_since=through)
    full = project_page_performance(read, identity, full_window)
    narrow = project_page_performance(read, identity, narrow_window)
    assert full["input_sha256"] == narrow["input_sha256"]
    assert all(trade["sellDate"] >= through.isoformat() for trade in narrow["ordinary"]["trades"])
    assert all(day == through.isoformat() for day in narrow["ordinary"]["trading_days"])


def test_persisted_empty_scope_decodes_cached_full_prefix_after_source_proof(product_cases, monkeypatch):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    calls = []
    native_load = reader.load
    reader.load = lambda request, cutoff: (calls.append(request), native_load(request, cutoff))[1]
    reader.historical_source_evidence = lambda **_: {"verified": "source"}
    proofs = []
    monkeypatch.setattr("app.reference_trading.persisted_newow.verify_saved_compact_source",
        lambda manifest, evidence: proofs.append((manifest, evidence)))
    manifest = {"reader": "newow_product_reader_intraday_v3",
        "query_since": query.since.isoformat(), "query_through": query.through.isoformat(),
        "query_as_of": fake.as_of.isoformat()}
    resolved = ResolvedPerformanceWindow(query.since, query.through, query.through, fake.as_of)
    request = ProductServiceQuery("rb", "trend", "60m", section="reference")
    saved = PersistedNewowReference(lambda: None)
    full = saved._page_read(request, reader, manifest, resolved)
    cached = saved._page_read(request, reader, manifest, resolved)
    assert full is cached and full.replay_bars == read.replay_bars
    assert len(calls) == 1 and len(proofs) == 3
    assert calls[0].performance_since == query.since
    assert full.reference_source_evidence_sha256


def test_required_page_contract_and_old_schema_rejected():
    assert ReferenceValueOut.model_fields["page_performance"].is_required()
    with pytest.raises(ValidationError):
        PagePerformanceOut.model_validate({"version": "newow_page_performance_v3379_v2"})
    with pytest.raises(ValidationError):
        ProductMetaOut.model_validate({"schema_version": "newow_product_detail_v3"})


def test_page_contract_rejects_misaligned_curve(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    resolved = ResolvedPerformanceWindow(query.since, query.through, query.through, fake.as_of)
    result = project_page_performance(read, build_product_identity("rb", "trend", "60m"), resolved)
    result["ordinary"]["equity"] = []
    with pytest.raises(ValidationError, match="misaligned"):
        PagePerformanceOut.model_validate(result)


def test_verified_trend_initial_clear_exits_oscillation_fusion_entry(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=80, frequency="60m")
    read = reader.load(query, fake.as_of)
    identity = build_product_identity("rb", "trend", "60m")
    bars = label_calculation_segments(identity, read.replay_bars)
    first_owner = bars[0].bar.segment_id
    owned = [bar for bar in bars if bar.bar.segment_id == first_owner and bar.bar.observation_eligible]
    buy_bar, sell_bar = owned[10], owned[11]
    oscillation = build_product_identity("rb", "oscillation", "60m")
    def action(source_identity, bar, kind, price, eligibility, marker=None):
        return StrategyAction(source_identity, bar.bar.physical_contract, bar.bar.segment_id,
            bar.bar.bar_end, bar.bar.trading_day, kind, price,
            trade_eligibility=eligibility, source_marker_id=marker,
            calculation_segment_id=bar.calculation_segment_id)
    buy = action(oscillation, buy_bar, ActionKind.BUILD, buy_bar.bar.close, TradeEligibility.ELIGIBLE)
    clear = action(identity, sell_bar, ActionKind.CLEAR, sell_bar.bar.close,
        TradeEligibility.INITIAL_CLEAR_NO_ENTRY, "public:first-d1")
    resolved = ResolvedPerformanceWindow(query.since, query.through, query.through, fake.as_of)
    result = project_page_performance(read, identity, resolved, fusion=True, replays={
        ProductStrategy.OSCILLATION: SimpleNamespace(actions=(buy,)),
        ProductStrategy.TREND: SimpleNamespace(actions=(clear,)),
    })
    assert clear.related_build_id is None
    assert result["ordinary"]["summary"]["tradeCount"] == 1
    assert result["ordinary"]["trades"][0]["forceClose"] is False
    assert result["ordinary"]["trades"][0]["sellDate"].startswith(sell_bar.bar.trading_day.isoformat())


def test_terminal_page_close_leaves_strategy_open_fact(product_cases):
    from newow.test_product_service import _service
    service, _reader, build, clear = _service(product_cases, "1d")
    result = service.query(ProductServiceQuery("rb", "trend", "1d", section="reference",
        performance_since=build.trading_day, performance_through=build.trading_day,
        as_of=clear.bar_end))
    value = result.reference.value
    assert value.summary.open_count == 1
    assert value.summary.closed_count == 0
    assert value.items[0].status.value == "OPEN"
    page = value.page_performance["ordinary"]
    assert page["trades"][-1]["forceClose"] is True
    assert page["trades"][-1]["sellDate"].startswith(build.trading_day.isoformat())
    assert value.items[0].exit_bar_end is None


@pytest.mark.parametrize("terminal_kind", ("rollover", "tail_gap"))
def test_interrupted_terminal_never_force_closes(product_cases, terminal_kind):
    from datetime import timedelta
    from newow.test_product_service import _service
    from app.market_data.newow.product_query import NewowProductQuery
    from guiyi_quant.newow.product_contracts import DataInterruption, OwnerBoundary
    service, reader, build, clear = _service(product_cases, "1d")
    cutoff = build.bar_end + timedelta(microseconds=2)
    read = reader.load(NewowProductQuery("rb", "trend", "1d", build.trading_day,
        build.trading_day, build.trading_day, build.trading_day, cutoff), cutoff)
    last = read.replay_bars[-1].bar
    if terminal_kind == "rollover":
        boundary = OwnerBoundary("rb", last.physical_contract, "RB2901", last.segment_id,
            "rb-next-owner", last.trading_day, last.bar_end + timedelta(microseconds=1), "owned:rollover")
        read = replace(read, boundaries=(boundary,))
    else:
        gap = DataInterruption("rb", read.frequency, last.physical_contract, last.segment_id,
            last.trading_day, last.bar_end + timedelta(microseconds=1), "owned:tail-gap")
        read = replace(read, data_interruptions_by_frequency={read.frequency: (gap,)})
    resolved = ResolvedPerformanceWindow(build.trading_day, build.trading_day, build.trading_day, cutoff)
    result = project_page_performance(read, build.identity, resolved)
    assert result["ordinary_interrupted_count"] == 1
    assert all(not trade["forceClose"] for trade in result["ordinary"]["trades"])
