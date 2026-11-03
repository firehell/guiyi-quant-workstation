from copy import deepcopy

from scripts.research.subing_regime_comparison import baseline_observations, context_at, context_index, measure
from guiyi_quant.subing_account import replay
from test_account import inputs


def test_environment_annotation_uses_strict_daily_and_completed_minute():
    rows = [dict(frequency=f, time=t, range_factor={'regime':r}) for f,t,r in (
        ('1d','2026-07-12T15:00:00+08:00','TREND_UP'),
        ('1d','2026-07-13T15:00:00+08:00','TREND_DOWN'),
        ('30m','2026-07-13T14:30:00+08:00','RANGE'),
        ('30m','2026-07-13T15:00:00+08:00','TREND_UP'))]
    index = context_index(rows)
    result = context_at(index, '2026-07-13T15:00:00+08:00')
    assert result['1d']['range_factor']['regime'] == 'TREND_UP'
    assert result['30m']['range_factor']['regime'] == 'TREND_UP'
    assert context_at(index, '2026-07-13T14:59:00+08:00')['30m']['range_factor']['regime'] == 'RANGE'


def test_annotation_removal_preserves_original_and_finance_reconciles():
    xs, obs = inputs([100,101,102,103,104,105], frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    annotated = deepcopy(obs)
    for row in annotated.values():
        if row['m30'] is not None:
            row['m30']['regime'] = 'UNKNOWN'
    assert baseline_observations(annotated) == obs
    assert next(iter(annotated.values()))['m30']['regime'] == 'UNKNOWN'
    r = replay(xs, obs, 'metrics', execution_model='theoretical_open')
    metrics, closed = measure(xs,r)
    assert metrics['rounds'] == 1 and len(closed) == 1
    assert metrics['net_pnl'] == r['net_pnl']
