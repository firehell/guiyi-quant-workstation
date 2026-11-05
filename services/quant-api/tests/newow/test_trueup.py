from dataclasses import asdict, replace
from decimal import Decimal

from guiyi_quant.newow.oscillation_trueup import (
    TrueupState, calculate_oscillation_series, restore_oscillation_state,
    step_oscillation, OSCILLATION_FORMULA_VERSION,
)
from .fixtures import _bars


def witness(failed=False):
    bars = list(_bars([Decimal('105')] * 13))
    bars = [replace(b, open=Decimal('105'), high=Decimal('110'), low=Decimal('100')) for b in bars]
    bars[10] = replace(bars[10], open=Decimal('115'), high=Decimal('120'), low=Decimal('110'), close=Decimal('118'))
    bars[11] = replace(bars[11], open=Decimal('118'), high=Decimal('119'), low=Decimal('115'), close=Decimal('118'))
    bars[12] = replace(bars[12], open=Decimal('119'), high=Decimal('121'), low=Decimal('115'), close=Decimal('119'))
    if failed:
        bars[11] = replace(bars[11], open=Decimal('109'), low=Decimal('108'), close=Decimal('109'))
    return tuple(bars)


def test_trueup_confirmed_hold_and_source_high_exit():
    result = calculate_oscillation_series(witness())
    assert [(i, s.action.value, s.price) for i, r in enumerate(result) for s in r.signals] == [(9, 'BUILD', Decimal('100')), (12, 'CLEAR', Decimal('121'))]
    assert result[10].state.pending_level == Decimal('110')
    assert result[11].state.holding and result[11].state.pos_true_up
    assert result[12].signals[0].true_up is True
    assert result[12].signals[0].formula_version == OSCILLATION_FORMULA_VERSION


def test_failure_uses_high_not_locked_level_and_never_rebuilds_same_bar():
    result = calculate_oscillation_series(witness(True))
    signal = result[11].signals[0]
    assert signal.action.value == 'CLEAR' and signal.price == Decimal('119')
    assert signal.reference_price == Decimal('110') and signal.true_up is False
    assert len(result[11].signals) == 1


def test_restart_prefix_and_contract_reset():
    bars = witness()
    batch = calculate_oscillation_series(bars)
    for cutoff in range(len(bars)):
        assert calculate_oscillation_series(bars[:cutoff + 1]) == batch[:cutoff + 1]
    state = restore_oscillation_state(asdict(batch[10].state))
    assert state == batch[10].state
    assert step_oscillation(state, bars[11]) == batch[11]
    rolled = replace(bars[11], physical_contract='RB2705', segment_id='next')
    reset = step_oscillation(state, rolled)
    assert reset.state.pending_level is None and not reset.state.holding
    assert restore_oscillation_state({'holding': True}) == TrueupState()
