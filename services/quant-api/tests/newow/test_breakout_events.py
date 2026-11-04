"""Synthetic display witnesses, not market or strategy acceptance evidence."""
from dataclasses import replace
from decimal import Decimal as D

import pytest
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import ProductFrequency
from app.market_data.newow.breakout_events import project_breakout_events
from app.schemas.market_newow_product import BreakoutEventOut
from .test_experiments import make_bar


def sample():
    bars = [replace(make_bar(i), bar=replace(make_bar(i).bar, high=D('101'), low=D('99'))) for i in range(15)]
    bars[11] = replace(bars[11], bar=replace(bars[11].bar, high=D('104'), low=D('100'), close=D('103')))
    bars[12] = replace(bars[12], bar=replace(bars[12].bar, high=D('105'), low=D('100'), close=D('104')))
    return tuple(bars)


def test_pending_confirmation_identity_cutoff_and_prefix_evidence():
    bars = sample()
    pending = next(e for e in project_breakout_events(bars[:12]) if e['kind'] == 'pending')
    confirmed = next(e for e in project_breakout_events(bars) if e['occur_bar_end'] == pending['occur_bar_end'] and e['kind'] == 'true_up')
    assert pending['event_id'] == confirmed['event_id']
    assert pending['confirmed_at'] is pending['confirm_close'] is pending['bar_gap'] is None
    assert pending['known_at'] == pending['occur_bar_end']
    assert confirmed['known_at'] == bars[12].bar.bar_end.isoformat()
    assert confirmed['confirm_close'] == '104' and confirmed['bar_gap'] == 1
    assert project_breakout_events(bars, as_of=bars[11].bar.bar_end) == project_breakout_events(bars[:12])
    assert confirmed in project_breakout_events(bars[:13])
    changed_future = bars[:13] + tuple(replace(b, bar=replace(b.bar, volume=999)) for b in bars[13:])
    assert confirmed in project_breakout_events(changed_future)
    assert pending['input_sha256'] != confirmed['input_sha256']
    for event in (pending, confirmed):
        assert BreakoutEventOut.model_validate(event).executable is False


def test_full_prefix_then_visible_owner_filter_and_replay_api():
    bars = sample()
    full = project_breakout_events(bars)
    assert project_breakout_events(bars, visible_bars=bars[12:13]) == tuple(e for e in full if e['bar_end'] == bars[12].bar.bar_end.isoformat())
    assert project_breakout_events(bars[12:13]) == ()
    wrong_owner = (replace(bars[12], calculation_segment_id='different'),)
    assert project_breakout_events(bars, visible_bars=wrong_owner) == ()
    identity = build_product_identity('rb', 'oscillation', ProductFrequency.DAILY)
    replay = replay_strategy(identity, bars)
    assert project_breakout_events(replay) == project_breakout_events(tuple(f.bar for f in replay.frames))


@pytest.mark.parametrize('field', ['physical', 'segment', 'calculation'])
def test_owner_boundary_never_confirms_with_other_owner(field):
    bars = sample()
    if field == 'physical':
        tail = tuple(replace(b, bar=replace(b.bar, physical_contract='RB2705')) for b in bars[12:])
    elif field == 'segment':
        tail = tuple(replace(b, bar=replace(b.bar, segment_id='new')) for b in bars[12:])
    else:
        tail = tuple(replace(b, calculation_segment_id='new') for b in bars[12:])
    events = project_breakout_events(bars[:12] + tail)
    assert any(e['kind'] == 'pending' for e in events)
    assert not any(e['kind'] == 'true_up' for e in events)


def test_initial_public_wick_is_known_only_after_twelve_bars():
    bars = sample()
    bars = bars[:10] + (replace(bars[10], bar=replace(bars[10].bar, high=D('104'), low=D('96'))),) + bars[11:]
    assert project_breakout_events(bars[:11]) == ()
    events = [e for e in project_breakout_events(bars[:12]) if e['occur_bar_end'] == bars[10].bar.bar_end.isoformat()]
    assert {e['kind'] for e in events} == {'wick_upper', 'wick_lower'}
    for event in events:
        assert event['known_at'] == bars[11].bar.bar_end.isoformat()
        assert event['bar_end'] == bars[10].bar.bar_end.isoformat()
        assert event['confirmed_at'] is event['confirm_close'] is None
    assert project_breakout_events(bars, as_of=bars[10].bar.bar_end) == ()
    assert events == list(project_breakout_events(bars[:12], visible_bars=bars[10:12]))
    # Left clipping must not expose an event whose render anchor is absent.
    assert project_breakout_events(bars[:12], visible_bars=bars[11:12]) == ()
    # Right clipping must not expose a wick before its delayed knowledge Bar.
    assert project_breakout_events(bars[:12], visible_bars=bars[10:11]) == ()


@pytest.mark.parametrize('strategy', ['oscillation', 'trend', 'main_rise'])
def test_chart_wire_is_typed_and_breakouts_are_oscillation_only(strategy):
    from app.api.newow_presentation import _product_response
    from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
    from .test_product_service import _Reader
    bars = sample()
    as_of = bars[-1].bar.bar_end
    reader = _Reader(bars, bars[0].bar.bar_end, as_of)
    service = NewowProductService(lambda *_: reader, now=lambda: as_of)
    result = service.query(ProductServiceQuery('rb', strategy, '1d', as_of=as_of))
    wire = _product_response(result).model_dump(mode='json')['chart']['value']
    assert bool(wire['breakout_events']) == (strategy == 'oscillation')
    assert 'display_events' in wire
    if strategy == 'oscillation':
        assert wire['breakout_events'] == [BreakoutEventOut.model_validate(e).model_dump(mode='json') for e in result.chart.value.breakout_events]


def test_warmup_occurrence_cannot_confirm_as_display_event_after_rollover():
    bars = sample()
    full = project_breakout_events(bars)
    assert any(e['kind'] == 'true_up' for e in full)
    warmed = tuple(replace(b, bar=replace(b.bar, observation_eligible=False)) if i <= 11 else b for i, b in enumerate(bars))
    events = project_breakout_events(warmed, visible_bars=bars[12:])
    assert not any(e['occur_bar_end'] == bars[11].bar.bar_end.isoformat() for e in events)
    # A valid occurrence outside the viewport remains usable: window clipping
    # and physical eligibility are different contracts.
    assert any(e['kind'] == 'true_up' for e in project_breakout_events(bars, visible_bars=bars[12:]))
