from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.research.subing_portfolio_inputs import observations, select_facts

UTC = timezone.utc
DAY = date(2026, 7, 13)
END = datetime(2026, 7, 13, 7, tzinfo=UTC)


def bar(at):
    return SimpleNamespace(physical_contract='JM2609', trading_day=DAY, bar_end=at, close=Decimal('100.50'))


def daily(at, direction):
    return dict(frequency='1d', time=at.isoformat(), direction=direction)


def sessions():
    return {DAY: (SimpleNamespace(start=END-timedelta(hours=6), end=END),)}


def test_daily_same_timestamp_is_excluded_and_night_uses_trading_day():
    night = datetime(2026, 7, 12, 13, 1, tzinfo=UTC)
    before = END-timedelta(days=3)
    rows = [daily(before, 'UP'), daily(END, 'DOWN')]
    result = observations([bar(night), bar(END)], rows, sessions())
    assert all(r['daily_direction'] == 'UP' for r in result.values())
    assert all(r['daily_at'] == before.isoformat() for r in result.values())
    assert result[night]['trading_day'] == str(DAY)
    assert not result[night]['day_end_window']
    assert result[END]['day_end_window']
    assert result[END]['close'] == '100.50'


def test_end_window_boundary_and_no_forward_daily_fill():
    times = [END-timedelta(minutes=11), END-timedelta(minutes=10)]
    result = observations([bar(t) for t in times], [daily(END,'UP')], sessions())
    assert [r['day_end_window'] for r in result.values()] == [False, True]
    assert all(r['daily_direction'] == 'UNKNOWN' and r['daily_at'] is None for r in result.values())


def test_missing_minute_at_completed30_endpoint_fails_closed():
    with pytest.raises(ValueError, match='M30_ENDPOINT'):
        observations([bar(END)], [dict(frequency='30m', owned=True, time=(END-timedelta(minutes=30)).isoformat())], sessions())


def test_fact_projection_is_exact_dated_and_does_not_mutate_source():
    raw = dict(source='rqdata', contracts={'JM2609':dict(instrument={'tick_size':'0.5'},
        parameters=[{'date':str(DAY)},{'date':'2026-07-14'}], daily=[{'date':str(DAY)},{'date':'2026-07-14'}]),
        'JM2701':{}})
    original = deepcopy(raw)
    result = select_facts(raw, [bar(END)])
    assert raw == original
    assert set(result['contracts']) == {'JM2609'}
    assert result['contracts']['JM2609']['parameters'] == [{'date':str(DAY)}]
    raw['contracts']['JM2609']['daily'] = []
    with pytest.raises(ValueError, match='EXECUTION_FACTS_MISSING'):
        select_facts(raw, [bar(END)])


def test_duplicate_dated_facts_are_not_silently_filtered():
    raw = dict(contracts={'JM2609':dict(parameters=[{'date':str(DAY)}]*2,daily=[{'date':str(DAY)}])})
    with pytest.raises(ValueError, match='EXECUTION_FACTS_MISSING'):
        select_facts(raw, [bar(END)])


def test_m30_qualification_keeps_decimal_high_and_ignores_display_breakout():
    row = dict(frequency='30m', owned=True, time=END.isoformat(), angle=3.2, direction='NEUTRAL', low=Decimal('99.5'), high=Decimal('101'),
        macd={'near_zero_golden':False,'near_zero_death':False,'low_golden':False}, volume_factor={'effective':True,'tier':'TIER_2'},
        price_factor={'ema21':Decimal('100'),'above_ema':True,'below_ema':False,
            'rebound':{'qualified_hold':False,'armed_high':None},
            'pullback':{'qualified_hold':True,'armed_high':Decimal('1234.5'),'breakout':True,'invalidated':False}},
        joint={'exits':{'below_previous_low':False,'high_death':False,'above_previous_high':False}})
    result = observations([bar(END)], [row], sessions())[END]['m30']
    assert result['pullback_high'] == '1234.5'
    assert result['qualified_pullback'] is True
    assert result['pullback_invalidated'] is False
    row['direction'] = 'DOWN'
    assert observations([bar(END)], [row], sessions())[END]['m30']['pullback_invalidated']


def test_portfolio_replay_rejects_old_scope_before_loading_settings(tmp_path):
    import json

    from guiyi_quant.subing_one_lot import PORTFOLIO_PRODUCTS
    from scripts.research.subing_portfolio_replay import load_segments

    plan = {"dates": ["2026-11-16", "2026-11-17"], "products": list(PORTFOLIO_PRODUCTS)}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="PORTFOLIO_PLAN_SCOPE_INVALID"):
        load_segments(tmp_path)
