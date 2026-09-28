from dataclasses import replace
from decimal import Decimal
import pytest

from guiyi_quant.newow.fusion_reference import fusion_reference_comparison
from guiyi_quant.newow.reference_statistics import PerformanceWindow
from app.reference_trading.inputs import HistoricalInputBar
from app.reference_trading.service import _advance_batch, _seed_checkpoint


@pytest.mark.parametrize("frequency", ("5m", "15m", "30m", "60m"))
@pytest.mark.parametrize("same_bar_reentry", (False, True))
def test_fusion_saved_source_driver_matches_accepted_core_and_restart(
    frequency, same_bar_reentry
):
    from newow.product_fixtures import ProductCases
    from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
    from app.reference_trading.newow_fusion import FusionHistoricalPayload

    cases = ProductCases()
    trend = cases.closed(frequency=frequency)
    osc = cases.closed(strategy="oscillation", frequency=frequency)
    from guiyi_quant.newow.product_adapters import build_product_identity

    def canonical(case):
        identity = build_product_identity(
            "rb", case.identity.strategy, case.identity.frequency
        )
        entry = replace(case.entry, identity=identity)
        return replace(
            case,
            identity=identity,
            entry=entry,
            exit=replace(
                case.exit, identity=identity, related_build_id=entry.signal_id
            ),
        )

    trend, osc = canonical(trend), canonical(osc)
    t = cases.replay(trend.identity, trend.bars, (trend.entry,), ("BUILD", "HOLD"))
    from guiyi_quant.newow.product_contracts import TradeEligibility

    witness = replace(osc.entry, trade_eligibility=TradeEligibility.WARMUP_ONLY)
    o = cases.replay(
        osc.identity,
        trend.bars,
        (
            witness,
            replace(
                osc.exit,
                trade_eligibility=TradeEligibility.NO_ELIGIBLE_ENTRY,
                related_build_id=witness.signal_id,
            ),
        ),
        ("FLAT", "CLEAR"),
    )
    if same_bar_reentry:
        t = cases.replay(
            trend.identity, trend.bars, (trend.entry, trend.exit), ("BUILD", "CLEAR")
        )
        new_entry = replace(
            osc.entry,
            bar_end=trend.exit.bar_end,
            trading_day=trend.exit.trading_day,
            reference_price=Decimal("105"),
            sequence=1,
        )
        o = cases.replay(osc.identity, trend.bars, (new_entry,), ("FLAT", "BUILD"))
    expected = fusion_reference_comparison(
        t,
        o,
        (),
        (),
        PerformanceWindow(
            trend.bars[0].bar.trading_day,
            trend.bars[-1].bar.trading_day,
            trend.as_of,
        ),
    )
    stream = build_fusion_stream_identity("rb", frequency)
    checkpoint, schema = _seed_checkpoint(stream)
    bars = tuple(
        HistoricalInputBar(
            item.bar.bar_end,
            item.bar.trading_day,
            item.bar.physical_contract,
            item.bar.segment_id,
            item.calculation_segment_id,
            item.bar.close,
            str(index + 1) * 64,
            FusionHistoricalPayload(
                item,
                tuple(
                    action
                    for action in (*t.actions, *o.actions)
                    if action.bar_end == item.bar.bar_end
                ),
            ),
        )
        for index, item in enumerate(trend.bars)
    )
    points = []
    final, sources, transitions, schema = _advance_batch(
        stream, checkpoint, bars, points
    )
    closed = [
        trade
        for transition in transitions
        for trade in transition.changed_trades
        if trade.status.value == "CLOSED"
    ]
    assert len(closed) == 1
    assert closed[0].reference_return == Decimal(
        next(item["reference_return_pct"] for item in expected["items"] if item["status"]=="CLOSED")
    )
    public = [
        point["value"]["public_trade_id"]
        for point in points
        if point["kind"] == "trade_identity"
    ]
    assert set(public) == {item["reference_trade_id"] for item in expected["items"]}
    assert closed[0].holding_bars == next(
        item["holding_bars"] for item in expected["items"] if item["status"] == "CLOSED"
    )
    assert (
        final.reference_state.open_trade is not None
        if same_bar_reentry
        else final.reference_state.open_trade is None
    )
    from guiyi_quant.reference_trading.strategy_checkpoint import (
        adapter_checkpoint_to_json,
        adapter_checkpoint_from_json,
    )

    first, _, _, schema = _advance_batch(stream, checkpoint, bars[:1], [])
    restored = adapter_checkpoint_from_json(
        adapter_checkpoint_to_json(first, strategy_schema=schema),
        expected_stream=stream,
        expected_strategy_schema=schema,
    )
    resumed, _, _, _ = _advance_batch(stream, restored, bars[1:], [])
    assert resumed == final


def test_saved_fusion_source_action_roundtrip_rejects_tampered_identity():
    from newow.product_fixtures import ProductCases
    from guiyi_quant.newow.product_adapters import build_product_identity
    from app.reference_trading.newow_fusion import decode_source_action
    from app.reference_trading.presentation import _wire

    case = ProductCases().closed(frequency="60m")
    identity = build_product_identity(
        "rb", case.identity.strategy, case.identity.frequency
    )
    action = replace(case.entry, identity=identity)
    value = _wire(action)
    assert decode_source_action(value, identity) == action
    with pytest.raises(ValueError, match="REFERENCE_FUSION_SOURCE_ACTION_CORRUPT"):
        decode_source_action({**value, "signal_id": "wrong"}, identity)
    with pytest.raises(ValueError, match="REFERENCE_FUSION_SOURCE_IDENTITY_CONFLICT"):
        decode_source_action(
            {**value, "identity": {**value["identity"], "profile_id": "wrong"}},
            identity,
        )


@pytest.mark.parametrize('changed', (False, True))
def test_cached_base_fusion_requires_exact_saved_generation(monkeypatch, changed):
    from types import SimpleNamespace
    from datetime import UTC, date, datetime
    from app.reference_trading.persisted_newow import PersistedNewowReference
    from app.reference_trading.newow_fusion import PersistedFusionComparison
    from app.reference_trading.query import QueryConflict
    from app.market_data.newow.product_service import SectionDelivery, PersistedReferenceSectionValue
    saved = PersistedNewowReference(lambda: None)
    saved._query = SimpleNamespace(summary=lambda *a, **kw: {'revision_id': 'revision', 'seq': 8 if changed else 7})
    monkeypatch.setattr(PersistedFusionComparison, 'comparison', lambda *_a, **_kw: {'reference_input_sha256': 'fusion-source', 'items': []})
    payload = {'items': [{'reference_trade_id': 'base'}]}
    delivery = SectionDelivery('delivered', None, PersistedReferenceSectionValue(payload, ("stream", "revision", 7)))
    request = SimpleNamespace(product='rb', frequency=SimpleNamespace(value='1m'), strategy=SimpleNamespace(value='trend'), history_limit=50, fusion_before=None)
    window = SimpleNamespace(requested_since=date(2023,1,1), actual_through=date(2026,9,24), requested_through=date(2026,9,24), cutoff=datetime(2026,9,24,7,tzinfo=UTC))
    if changed:
        with pytest.raises(QueryConflict, match='SOURCE_GENERATION_CONFLICT'):
            saved.attach_cached_fusion(request, delivery, None, 'page-proof', window)
    else:
        result = saved.attach_cached_fusion(request, delivery, None, 'page-proof', window)
        assert result.value.payload['items'] == payload['items']
        assert result.value.payload['fusion_comparison']['fusion_input_sha256'] == 'fusion-source'
        assert result.value.payload['fusion_comparison']['reference_input_sha256'] == 'page-proof'
        assert 'fusion_comparison' not in payload


@pytest.mark.parametrize('current_seq', (7, 8))
def test_hot_reference_cache_rechecks_generation(current_seq):
    from types import SimpleNamespace
    from app.reference_trading.persisted_newow import PersistedNewowReference
    from app.reference_trading.query import QueryConflict
    from app.market_data.newow.product_service import SectionDelivery, PersistedReferenceSectionValue
    saved = PersistedNewowReference(lambda: None)
    saved._query = SimpleNamespace(summary=lambda *_a, **_kw: {'revision_id':'revision', 'seq':current_seq})
    delivery = SectionDelivery('delivered', None, PersistedReferenceSectionValue({'performance_since':'2023-01-01','performance_through':'2026-09-24','reference_cutoff':'2026-09-24T07:00:00+00:00'}, ('stream','revision',7)))
    if current_seq == 7:
        saved.validate_cached_generation(delivery)
    else:
        with pytest.raises(QueryConflict, match='SOURCE_GENERATION_CONFLICT'):
            saved.validate_cached_generation(delivery)


@pytest.mark.parametrize('changed', (None, 'oscillation', 'fusion'))
def test_hot_fusion_cache_validates_real_payload_shape_and_all_generations(changed):
    from types import SimpleNamespace
    from app.reference_trading.persisted_newow import PersistedNewowReference
    from app.reference_trading.contracts import manifest_sha256
    from app.reference_trading.query import QueryConflict
    from app.market_data.newow.product_service import SectionDelivery, PersistedReferenceSectionValue
    saved = PersistedNewowReference(lambda: None)
    dependencies = [{'stream_id':s, 'revision_id':'revision', 'seq':7} for s in ('trend','oscillation')]
    def streams(*, strategy, product, frequency):
        assert (product, frequency) == ('rb','1m')
        name = 'fusion' if strategy == 'newow_dual_fusion' else strategy.removeprefix('newow_')
        return [{'stream_id':name,'active_revision_id':'revision','latest_seq':8 if changed==name else 7}]
    def summary(stream, **kw):
        return {'revision_id':'revision','seq':8 if changed==stream else 7,'snapshot':'fusion-new' if changed=='fusion' and stream=='fusion' else 'fusion-snapshot'}
    saved._query = SimpleNamespace(streams=streams, summary=summary)
    saved._manifest = lambda *_: (None, {'source_dependencies':dependencies})
    revision = manifest_sha256({'snapshot':'fusion-snapshot','dependencies':dependencies,'record_since':'2025-09-25','record_through':'2026-09-24'})
    payload = {'performance_since':'2023-01-01','performance_through':'2026-09-24','reference_cutoff':'2026-09-24T07:00:00+00:00','fusion_comparison':{'product':'rb','frequency':'1m','reference_revision':revision}}
    delivery = SectionDelivery('delivered',None,PersistedReferenceSectionValue(payload,('trend','revision',7)))
    if changed is None:
        saved.validate_cached_generation(delivery)
    else:
        with pytest.raises(QueryConflict, match='SOURCE_GENERATION_CONFLICT'):
            saved.validate_cached_generation(delivery)
