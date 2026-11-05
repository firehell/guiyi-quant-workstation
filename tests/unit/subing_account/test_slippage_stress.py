from dataclasses import replace
from decimal import Decimal as D
import pytest
from test_account import inputs
from guiyi_quant.subing_account import replay


@pytest.mark.parametrize('ticks', [True, 0, -1, 4, 1.5, '2', None])
def test_invalid_stress_rejected(ticks):
    xs, obs = inputs([100])
    with pytest.raises(ValueError, match='ACCOUNT_SLIPPAGE_SCENARIO_INVALID'):
        replay(xs, obs, 'r', slippage_ticks=ticks)


@pytest.mark.parametrize('ticks', [1, 2, 3])
def test_slippage_prices_and_cash(ticks):
    xs, obs = inputs([100, 101, 105, 106], frames={0:dict(near_zero_golden=True), 2:dict(below_ema=True)})
    xs = [replace(x, bar=replace(x.bar, high=x.bar.close+D(2), low=x.bar.close-D(2))) for x in xs]
    r = replay(xs, obs, 'r', slippage_ticks=ticks)
    assert [D(f['price']) for f in r['fills']] == [D(101)+D('.5')*ticks, D(106)-D('.5')*ticks]
    assert D(r['net_pnl']) == (D(5)-ticks)*60-6
    if ticks == 1:
        assert r == replay(xs, obs, 'r')
    else:
        assert r['version'].endswith(f'_research_slip{ticks}')


def test_larger_slippage_cancels_entry_without_clamping():
    xs, obs = inputs([100, 101, 105], frames={0:dict(near_zero_golden=True)})
    assert len(replay(xs, obs, 'r')['fills']) == 1
    r = replay(xs, obs, 'r', slippage_ticks=3)
    assert not r['fills'] and r['execution_events'][0]['reason'] == 'SLIPPAGE_OUTSIDE_BAR'


def test_larger_slippage_delays_exit_keeps_obligation():
    xs, obs = inputs([100, 101, 105, 106, 107], frames={0:dict(near_zero_golden=True), 2:dict(below_ema=True)})
    for i in (1,4):
        xs[i]=replace(xs[i],bar=replace(xs[i].bar,high=xs[i].bar.close+D(2),low=xs[i].bar.close-D(2)))
    r = replay(xs, obs, 'r', slippage_ticks=3)
    assert r['execution_events'][0]['kind'] == 'UNFILLED'
    assert r['fills'][-1]['fill_at'] == xs[4].bar.bar_end.isoformat()
    assert r['status'] == 'COMPLETED'


@pytest.mark.parametrize('ticks', [2,3])
def test_stress_short_mirrors_long_cash(ticks):
    from test_account_bidirectional import mirror_inputs
    xs, obs = inputs([100,101,105,106], frames={0:dict(near_zero_golden=True),2:dict(below_ema=True)})
    xs = [replace(x,bar=replace(x.bar,high=x.bar.close+D(2),low=x.bar.close-D(2))) for x in xs]
    sx, so = mirror_inputs(xs,obs)
    long = replay(xs,obs,'long',slippage_ticks=ticks)
    short = replay(sx,so,'short',slippage_ticks=ticks)
    assert long['net_pnl'] == short['net_pnl']
    assert len(long['fills']) == len(short['fills']) == 2
    assert [f['order_side'] for f in short['fills']] == ['SELL','BUY']


def test_stress_slippage_used_by_financial_admission():
    xs, obs = inputs([100,101,102],frames={0:dict(near_zero_golden=True)})
    xs=[replace(x,facts=replace(x.facts,long_margin_ratio=D('11.55')),
        bar=replace(x.bar,high=x.bar.close+D(2),low=x.bar.close-D(2))) for x in xs]
    # 1tick passes at the decision, while 3tick violates the 70% bound.
    one=replay(xs[:1],{xs[0].bar.bar_end:obs[xs[0].bar.bar_end]},'one')
    three=replay(xs[:1],{xs[0].bar.bar_end:obs[xs[0].bar.bar_end]},'three',slippage_ticks=3)
    assert one['pending'] is not None and three['pending'] is None
