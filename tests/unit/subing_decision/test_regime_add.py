"""Approved regime filter changes adds only, with causal fresh qualification."""
from copy import deepcopy

import pytest

from guiyi_quant.subing_decision import DecisionModel, REGIME_PROFILE
from tests.unit.subing_decision.test_core import ack, frame, observation


def rf(n, regime='TREND_UP', **changes):
    return frame(n, regime=regime, **changes)


def opened(regime='TREND_UP'):
    m = DecisionModel('JM2609', 'regime', regime_research_profile=REGIME_PROFILE)
    m.apply({**rf(0, regime, near_zero_golden=True, ema21='100', low='99'), 'close': '110'})
    assert m.pending['kind'] == 'OPEN'
    m.apply(ack(m, 1, price='110'))
    return m


@pytest.mark.parametrize('regime', ['RANGE', 'UNKNOWN', 'TREND_DOWN', 'TREND_UP'])
def test_first_entry_unchanged_and_nonmatching_cannot_arm(regime):
    m = opened(regime)
    m.apply(rf(30, regime, qualified_pullback=True, pullback_high='132'))
    assert (m.pullback is not None) == (regime == 'TREND_UP')
    result = m.apply(observation(31, close='133'))
    assert bool(result['actions']) == (regime == 'TREND_UP')


def test_resume_requires_strictly_later_new_pullback_not_old_or_same_bar():
    m = opened()
    m.apply(rf(30, qualified_pullback=True, pullback_high='132'))
    assert m.pullback
    m.apply(rf(60, 'RANGE', qualified_pullback=True, pullback_high='132'))
    assert m.pullback is None
    m.apply(rf(90, qualified_pullback=True, pullback_high='132'))
    assert m.pullback is None
    assert m.apply(observation(91, close='133'))['actions'] == []
    m.apply(rf(120, qualified_pullback=True, pullback_high='132'))
    assert m.pullback
    assert m.apply(observation(121, close='133'))['actions'][0]['kind'] == 'ADD'


@pytest.mark.parametrize('regime', ['RANGE', 'UNKNOWN', 'TREND_DOWN'])
def test_pending_add_cancel_but_base_kept_and_no_replay(regime):
    m = opened()
    m.apply(rf(30, qualified_pullback=True, pullback_high='132'))
    m.apply(observation(31, close='133'))
    result = m.apply(rf(60, regime))
    assert result['actions'][0]['kind'] == 'CANCEL'
    assert len(m.layers) == 1
    assert m.clear_reasons == []
    m.apply(ack(m, 61, status='CANCELLED', price=None))
    m.apply(rf(90))
    assert m.apply(observation(91, close='133'))['actions'] == []


def test_unknown_regime_does_not_block_exit_and_restore_preserves_wait():
    m = opened('RANGE')
    m.apply(rf(30))
    restored = DecisionModel.restore(m.checkpoint())
    assert restored.state() == m.state()
    e = rf(60, 'UNKNOWN', below_ema=True)
    assert m.apply(e) == restored.apply(e)
    assert m.pending['kind'] == 'CLOSE'
    assert m.pending['reasons'] == ['EMA_CLEAR']


def test_short_mirror_and_no_cross_contract_or_profile_mix():
    m = DecisionModel('JM2609', 's', regime_research_profile=REGIME_PROFILE)
    e = rf(0, 'TREND_DOWN', minute_angle='-2', near_zero_death=True, above_ema=False,
           below_ema=True, ema21='120', high='121')
    e.update(close='110', daily_direction='DOWN')
    m.apply(e); m.apply(ack(m, 1, price='110'))
    e = rf(30, 'TREND_DOWN', minute_angle='-2', above_ema=False, below_ema=True,
           qualified_rebound=True, rebound_low='105', rebound_invalidated=False)
    e.update(close='106', daily_direction='DOWN')
    m.apply(e)
    assert m.pullback['level'] == 105
    assert m.apply(observation(31, close='104', daily_direction='DOWN'))['actions'][0]['kind'] == 'ADD'
    for kwargs in ({'research_profile':'window4'}, {'risk_research_profile':'round1500'}):
        with pytest.raises(ValueError, match='COMBINATION'):
            DecisionModel('JM2609', 'x', regime_research_profile=REGIME_PROFILE, **kwargs)
    with pytest.raises(ValueError, match='REGIME_RESEARCH'):
        DecisionModel('MA2609', 'x', regime_research_profile=REGIME_PROFILE)


def test_invalid_input_atomic_and_future_cannot_change_prefix():
    m = opened()
    checkpoint = m.checkpoint()
    for e in (frame(30), rf(30, 'INVALID')):
        with pytest.raises(ValueError):
            m.apply(e)
        assert m.checkpoint() == checkpoint
    prefix = deepcopy(m.results)
    m.apply(rf(30, 'RANGE'))
    assert all(m.results[k] == v for k, v in prefix.items())
    assert DecisionModel.restore(m.checkpoint()).state() == m.state()
