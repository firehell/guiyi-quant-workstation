from copy import deepcopy

import pytest

from test_account import inputs
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import REGIME_PROFILE


def test_regime_at_future_minute_close_cannot_cancel_prior_open_fill():
    xs, obs = inputs([100, 101, 103, 104, 105, 106, 107, 108], frames={
        0: dict(near_zero_golden=True, regime='TREND_UP'),
        3: dict(qualified_pullback=True, pullback_high='104', regime='TREND_UP')})
    kwargs = dict(execution_model='theoretical_open', regime_research_profile=REGIME_PROFILE)
    baseline = replay(xs, obs, 'regime', **kwargs)
    assert [f['action'] for f in baseline['fills']] == ['OPEN', 'ADD']
    for index, expected in ((6, ['OPEN', 'ADD']), (5, ['OPEN'])):
        other = deepcopy(obs)
        other[xs[index].bar.bar_end]['m30'] = dict(obs[xs[3].bar.bar_end]['m30'],
            regime='RANGE', qualified_pullback=False, pullback_high=None)
        result = replay(xs, other, 'regime', **kwargs)
        assert [f['action'] for f in result['fills']] == expected
        if index == 6:
            assert result['fills'] == baseline['fills']
        else:
            assert result['execution_events'][0]['reason'] == 'CANCEL_REQUESTED'


def test_candidate_requires_declared_execution_model():
    xs, obs = inputs([100, 101, 103], frames={0: dict(near_zero_golden=True, regime='TREND_UP')})
    with pytest.raises(ValueError, match='REQUIRES_THEORETICAL_OPEN'):
        replay(xs, obs, 'regime', regime_research_profile=REGIME_PROFILE)
