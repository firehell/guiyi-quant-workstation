from dataclasses import replace
from decimal import Decimal as D
import pytest
from guiyi_quant.newow.breakout_shapes import compute_breakout_shapes
from .fixtures import _bars


@pytest.mark.parametrize('side', ['up', 'down'])
@pytest.mark.parametrize('confirmed', [True, False])
def test_two_bar_confirm_and_pending_never_look_ahead(side, confirmed):
    bars = [replace(b, open=D('100'), high=D('101'), low=D('99')) for b in _bars([D('100')]*13)]
    down = side == 'down'
    bars[11] = replace(bars[11], high=D('100') if down else D('104'), low=D('96') if down else D('100'), close=D('97') if down else D('103'))
    bars[12] = replace(bars[12], high=D('105'), low=D('95'), close=(D('96') if down else D('104')) if confirmed else D('100'))
    pending = [e for e in compute_breakout_shapes(tuple(bars[:12])) if e.kind == 'pending']
    assert len(pending) == 1 and pending[0].side == side
    events = [e for e in compute_breakout_shapes(tuple(bars)) if e.occur == 11 and not e.kind.endswith('_ib')]
    assert events[0].kind == ('true_' if confirmed else 'false_')+side
    assert events[0].index == 12 and events[0].occur == 11


def test_dual_wicks_and_warmup():
    bars = [replace(b, high=D('101'), low=D('99')) for b in _bars([D('100')]*12)]
    bars[10] = replace(bars[10], high=D('104'), low=D('96'))
    assert compute_breakout_shapes(tuple(bars[:11])) == ()
    events = compute_breakout_shapes(tuple(bars))
    assert {e.kind for e in events if e.occur == 10} == {'fake_up_ib', 'fake_dn_ib'}
    assert all(e.regime == 'unknown' for e in events)
