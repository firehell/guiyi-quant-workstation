from dataclasses import replace
from decimal import Decimal as D

from scripts.research.subing_three_nested import nested_m5
from scripts.research.subing_three_timing import TimingPortfolio, evaluate, setups
from tests.unit.subing_one_lot.test_portfolio import segment


def frame(close, *, cross=False):
    return dict(angle=3, ema=98, close=D(close), golden=cross, death=False, tier='TIER_2')


def test_nested_5m_requires_a_new_cross_after_the_confirmed_15m_setup():
    s = segment('jm', [100, 101, 102, 103, 104, 105])
    ends = [x.bar.bar_end for x in s.executions]
    m15 = {ends[2]: frame(102, cross=True)}
    old = {ends[1]: frame(101, cross=True), ends[3]: frame(103)}
    assert nested_m5(s, {'15m': m15, '5m': old}, 'trend') == {}
    new = {**old, ends[4]: frame(104, cross=True)}
    assert list(nested_m5(s, {'15m': m15, '5m': new}, 'trend')) == [ends[4]]


def test_timing_study_uses_next_minute_fills_and_real_30m_exit():
    s = segment('jm', [100, 101, 102, 101, 100])
    ends = [x.bar.bar_end for x in s.executions]
    obs = s.observations
    obs[ends[3]]['m30'] = dict(
        obs[ends[0]]['m30'], below_previous_low=True, near_zero_golden=False,
    )
    signals = {'JM2609': setups(s, {ends[0]: frame(100, cross=True)}, 'trend')}
    result = evaluate([s], signals, 'trend', '15m', 'test', 1, 1)
    trade, = result['trades']
    assert trade['entry']['fill_at'] == ends[1].isoformat()
    assert trade['exit']['reasons'] == ['ONE_LOT_ORDINARY_EXIT']
    assert trade['exit']['fill_at'] == ends[4].isoformat()
    incremental = TimingPortfolio(
        [s], 'subing_three_entry_clock_v1:test:trend-15m:f1s1', signals, 'trend', 1,
    )
    for x in s.executions:
        incremental.step_batch([(x, obs[x.bar.bar_end])])
    assert incremental.equity() - D('1000000') == D(result['net'])
    assert incremental.accounts['JM2609'].fills[-1]['fill_bar_end'] == ends[4]


def test_intraday_creates_a_close_obligation_at_penultimate_minute():
    s = segment('jm', [100, 101, 102, 103, 104])
    xs = s.executions
    ends = [x.bar.bar_end for x in xs]
    hour = dict(at=xs[0].bar.session_open_at.isoformat(), direction='UP')
    s = replace(s, structures={key: dict(row, hourly=hour) for key, row in s.structures.items()})
    signals = {'JM2609': setups(s, {ends[0]: frame(100, cross=True)}, 'intraday')}
    result = evaluate([s], signals, 'intraday', '30m', 'test', 1, 1)
    trade, = result['trades']
    assert trade['exit']['reasons'] == ['RESEARCH_SESSION_END']
    assert trade['exit']['decision_at'] == ends[-2].isoformat()
    assert trade['exit']['fill_at'] == ends[-1].isoformat()
    assert trade['crossed_session'] is False
