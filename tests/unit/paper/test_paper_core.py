from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from guiyi_quant.paper import (
    BeginTradingDay, FeeSchedule, Initialize, ObserveDecision,
    ObserveExecutionBar, PaperProfile, ResolveOrder, apply_command, apply_events,
    command_from_dict, command_to_dict, event_from_dict, event_to_dict, replay,
)

T0 = datetime(2026, 10, 9, 9, 0, tzinfo=timezone(timedelta(hours=8)))
D = Decimal


def profile():
    return PaperProfile('jm-dual-v1', 'dual-causal-v1')


def fees():
    return FeeSchedule(D('0.0001'), D('0'), D('0.0001'), D('0'), D('0.0002'), D('0'), 'fee-jm-2026')


def step(state, command):
    return apply_events(state, apply_command(state, command))


def started():
    state = replay(apply_command(None, Initialize('init', T0, profile())))
    return step(state, BeginTradingDay('day', T0, '2026-10-09', 0, None, 'recon-1'))


def decision(action='BUILD', at=T0, contract='JM2701', command_id='dec', decision_id='signal'):
    return ObserveDecision(command_id, at, decision_id, 'source-hash', action, at, at,
                           '2026-10-09', contract, D('1200') if action == 'BUILD' else None, 'jm-dual-v1',
                           'dual-causal-v1', '5m')


def bar(start, close=D('1000'), contract='JM2701', command_id='bar', volume=10, completed=True):
    return ObserveExecutionBar(command_id, start + timedelta(minutes=1), '2026-10-09',
        contract, start, start + timedelta(minutes=1), completed, D('1000'), max(D('1010'), close),
        D('950'), close, volume, True, D('1300'), D('800'), D('1'), 0, D('60'),
        fees(), D('10000'), 'market-1', 'cost-1', 'limit-1', 'margin-1')


def test_command_and_event_round_trip_and_strict_values():
    c = decision()
    assert command_from_dict(command_to_dict(c)) == c
    with pytest.raises((ValueError, TypeError)):
        PaperProfile('p', 'v', initial_cash=D('NaN'))
    with pytest.raises((ValueError, TypeError)):
        BeginTradingDay('x', T0, '2026-10-09', True, None, 'fact')
    with pytest.raises((ValueError, TypeError)):
        Initialize('x', T0.replace(tzinfo=None), profile())
    first = apply_command(None, Initialize('roundtrip', T0, profile()))
    assert replay(tuple(event_from_dict(event_to_dict(e)) for e in first)) == replay(first)


def test_next_completed_1m_open_only_after_order_and_signal():
    state = started()
    state = step(state, decision())
    assert state.position_qty == 0
    state = step(state, bar(T0, command_id='same-start'))
    assert state.position_qty == 0
    state = step(state, bar(T0 + timedelta(minutes=1), completed=False, command_id='unfinished'))
    assert state.position_qty == 0
    state = step(state, bar(T0 + timedelta(minutes=2), command_id='next'))
    assert state.position_qty == 1
    assert state.fills[0].fill_at == T0 + timedelta(minutes=2)
    assert state.fills[0].recorded_at == T0 + timedelta(minutes=3)
    assert state.fills[0].price == D('1000')


def test_day_loss_marks_unrealized_halts_then_closes_only_future_bar():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), close=D('995'), command_id='entry'))
    assert state.position_qty == 1
    assert not state.daily_halt
    state = step(state, bar(T0 + timedelta(minutes=2), close=D('970'), command_id='loss'))
    assert state.daily_halt
    assert state.position_qty == 1
    assert len(state.fills) == 1
    assert any(o.side == 'CLOSE' and o.status == 'PENDING' for o in state.orders)
    state = step(state, decision(at=T0 + timedelta(minutes=3), command_id='late', decision_id='late'))
    assert not any(o.side == 'OPEN' and o.status == 'PENDING' for o in state.orders)
    state = step(state, bar(T0 + timedelta(minutes=4), close=D('970'), command_id='forced'))
    assert state.position_qty == 0
    assert len(state.fills) == 2


def test_daily_halt_cancels_restrictive_close_then_reissues_forced_close_after_restart():
    from dataclasses import replace
    events = []
    state = None
    def apply(command):
        nonlocal state
        generated = apply_command(state, command)
        events.extend(generated)
        state = apply_events(state, generated)
    apply(Initialize('init', T0, profile()))
    apply(BeginTradingDay('day', T0, '2026-10-09', 0, None, 'recon'))
    apply(decision())
    apply(bar(T0 + timedelta(minutes=1), command_id='entry'))
    apply(replace(decision('CLEAR', T0 + timedelta(minutes=2), command_id='clear', decision_id='clear'),
                  limit_price=D('1100')))
    apply(bar(T0 + timedelta(minutes=3), close=D('970'), command_id='loss'))
    assert state.daily_halt and state.position_qty == 1
    close_order = next(o for o in state.orders if o.side == 'CLOSE')
    assert close_order.status == 'CANCEL_REQUESTED'
    state = replay(tuple(event_from_dict(event_to_dict(e)) for e in events))
    apply(ResolveOrder('cancel-close', T0 + timedelta(minutes=4), close_order.order_id, 'CANCELLED', 'recon-cancel'))
    pending = [o for o in state.orders if o.status == 'PENDING']
    assert len(pending) == 1 and pending[0].limit_price is None
    apply(bar(T0 + timedelta(minutes=5), command_id='forced'))
    assert state.daily_halt and state.position_qty == 0 and len(state.fills) == 2


def test_zero_volume_limit_and_physical_roll_do_not_fill_or_reprice_old_position():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), volume=0, command_id='zero'))
    assert state.position_qty == 0
    state = step(state, bar(T0 + timedelta(minutes=2), command_id='entry'))
    equity = state.equity
    state = step(state, bar(T0 + timedelta(minutes=3), close=D('1200'), contract='JM2705', command_id='roll'))
    assert state.position_contract == 'JM2701'
    assert state.equity == equity
    assert state.rollover_halt


def test_duplicate_and_changed_command_id_and_unknown_order():
    state = step(started(), decision())
    assert apply_command(state, decision()) == ()
    with pytest.raises(ValueError):
        apply_command(state, decision(action='CLEAR'))
    order = state.orders[0]
    state = step(state, ResolveOrder('resolve', T0 + timedelta(seconds=1), order.order_id, 'UNKNOWN', 'recon-unknown'))
    assert state.orders[0].status == 'UNKNOWN'
    state = step(state, BeginTradingDay('next-day', T0 + timedelta(days=1), '2026-10-10', 0, None, 'recon-next'))
    assert state.orders[0].status == 'UNKNOWN'
    assert not state.daily_halt


def test_limit_and_insufficient_margin_leave_open_order_unfilled():
    from dataclasses import replace
    state = step(started(), decision())
    over_limit = replace(bar(T0 + timedelta(minutes=1), command_id='limit'),
                         open=D('1201'), high=D('1202'), close=D('1201'))
    state = step(state, over_limit)
    assert state.position_qty == 0
    too_expensive = replace(bar(T0 + timedelta(minutes=2), command_id='margin'),
                            margin_per_contract=D('50001'))
    state = step(state, too_expensive)
    assert state.position_qty == 0
    assert state.orders[0].status == 'PENDING'


def test_normal_overnight_position_uses_prior_last_mark_as_day_start_and_close_fee():
    from dataclasses import replace
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), close=D('995'), command_id='entry'))
    prior_mark = state.equity
    state = step(state, BeginTradingDay('day2', T0 + timedelta(days=1), '2026-10-10', 1, 'JM2701', 'recon-day2'))
    assert state.position_qty == 1 and not state.daily_halt
    assert state.day_start_equity == prior_mark
    clear = replace(decision('CLEAR', T0 + timedelta(days=1, minutes=1), command_id='clear', decision_id='clear'),
                    trading_day='2026-10-10')
    state = step(state, clear)
    state = step(state, replace(bar(T0 + timedelta(days=1, minutes=2), command_id='exit'), trading_day='2026-10-10'))
    assert state.position_qty == 0
    assert state.fills[-1].fee == D('6')


def test_event_cannot_inject_state_or_fill():
    from dataclasses import replace
    event = apply_command(None, Initialize('init', T0, profile()))[0]
    changed = dict(event.changes)
    changed['cash'] = {'$decimal': '60000'}
    with pytest.raises(ValueError):
        replay((replace(event, changes=changed),))


def test_duplicate_decision_identity_with_changed_payload_is_rejected():
    state = step(started(), decision())
    with pytest.raises(ValueError):
        step(state, decision('CLEAR', command_id='another-command'))


def test_rollover_cancels_pending_open_and_never_uses_new_contract_bar():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), contract='JM2705', command_id='new-contract'))
    assert state.position_qty == 0
    assert state.rollover_halt
    assert state.orders[0].status == 'CANCEL_REQUESTED'


def test_same_decision_id_same_payload_is_idempotent_across_command_ids():
    state = step(started(), decision())
    state = step(state, decision(command_id='redelivery'))
    assert len(state.orders) == 1


def test_rollover_queues_old_contract_close_without_new_contract_valuation():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), command_id='entry'))
    old_equity = state.equity
    state = step(state, bar(T0 + timedelta(minutes=2), contract='JM2705', command_id='roll'))
    assert state.equity == old_equity
    assert any(o.side == 'CLOSE' and o.contract == 'JM2701' and o.status == 'PENDING' for o in state.orders)
    state = step(state, bar(T0 + timedelta(minutes=4), contract='JM2701', command_id='old-exit'))
    assert state.position_qty == 0


def test_restart_replay_preserves_halt_and_delayed_close_order():
    commands = [Initialize('init', T0, profile()),
                BeginTradingDay('day', T0, '2026-10-09', 0, None, 'recon-1'),
                decision(),
                bar(T0 + timedelta(minutes=1), close=D('995'), command_id='entry'),
                bar(T0 + timedelta(minutes=2), close=D('970'), command_id='loss')]
    state = None
    events = []
    for command in commands:
        new = apply_command(state, command)
        events.extend(new)
        state = apply_events(state, new)
    restored = replay(tuple(event_from_dict(event_to_dict(e)) for e in events))
    assert restored == state
    assert restored.daily_halt
    assert restored.position_qty == 1
    assert any(o.side == 'CLOSE' and o.status == 'PENDING' for o in restored.orders)
    assert not any(o.side == 'OPEN' and o.status == 'PENDING' for o in restored.orders)


def test_close_today_uses_its_own_fee_schedule():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), command_id='entry'))
    assert state.fills[0].fee == D('6')
    state = step(state, decision('CLEAR', T0 + timedelta(minutes=2), command_id='clear', decision_id='clear'))
    state = step(state, bar(T0 + timedelta(minutes=3), command_id='exit'))
    assert state.fills[1].fee == D('12')
    assert state.cash == D('49982')


def test_old_decision_and_early_order_resolution_are_rejected():
    state = step(started(), decision())
    order = state.orders[0]
    with pytest.raises(ValueError):
        step(state, ResolveOrder('early', T0-timedelta(seconds=1), order.order_id, 'UNKNOWN', 'fact'))
    state = step(state, bar(T0 + timedelta(minutes=1), command_id='entry'))
    with pytest.raises(ValueError):
        step(state, decision('HOLD', T0, command_id='stale', decision_id='stale'))


def test_next_open_slippage_uses_open_and_tick_without_future_high_low_gate():
    from dataclasses import replace
    state = step(started(), decision())
    b = replace(bar(T0 + timedelta(minutes=1), command_id='slipped'),
                high=D('1000'), slippage_ticks=1)
    state = step(state, b)
    assert state.fills[0].price == D('1001')
    assert state.fills[0].fill_at == b.bar_start


def test_synthetic_or_other_product_cannot_become_execution_contract():
    with pytest.raises(ValueError):
        decision(contract='JM88')
    with pytest.raises(ValueError):
        decision(contract='RB2701')
    with pytest.raises(ValueError):
        bar(T0 + timedelta(minutes=1), contract='JM99')


def test_unfilled_open_order_carries_to_next_trading_day():
    from dataclasses import replace
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), volume=0, command_id='zero'))
    state = step(state, BeginTradingDay('day2', T0 + timedelta(days=1), '2026-10-10', 0, None, 'recon-day2'))
    assert state.orders[0].status == 'PENDING'
    state = step(state, replace(bar(T0 + timedelta(days=1, minutes=1), command_id='overnight-fill'),
                                trading_day='2026-10-10'))
    assert state.position_qty == 1
    assert state.entry_trading_day == '2026-10-10'


def test_halted_overnight_position_can_close_next_day_but_halt_persists():
    from dataclasses import replace
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), close=D('995'), command_id='entry'))
    state = step(state, bar(T0 + timedelta(minutes=2), close=D('970'), command_id='loss'))
    prior_mark = state.equity
    state = step(state, BeginTradingDay('day2', T0 + timedelta(days=1), '2026-10-10', 1, 'JM2701', 'recon-day2'))
    assert state.daily_halt and state.day_start_equity == prior_mark
    state = step(state, replace(bar(T0 + timedelta(days=1, minutes=1), command_id='forced-next-day'),
                                trading_day='2026-10-10'))
    assert state.position_qty == 0 and state.daily_halt
    assert state.fills[-1].fee == D('6')
    build = replace(decision(at=T0 + timedelta(days=1, minutes=2), command_id='blocked', decision_id='blocked'),
                    trading_day='2026-10-10')
    state = step(state, build)
    assert not any(o.side == 'OPEN' and o.status == 'PENDING' for o in state.orders)
    state = step(state, BeginTradingDay('day3', T0 + timedelta(days=2), '2026-10-11', 0, None, 'recon-day3'))
    assert not state.daily_halt


def test_unknown_halted_close_remains_blocked_until_fact_then_reissues():
    from dataclasses import replace
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), close=D('995'), command_id='entry'))
    state = step(state, bar(T0 + timedelta(minutes=2), close=D('970'), command_id='loss'))
    close_order = next(o for o in state.orders if o.side == 'CLOSE')
    state = step(state, ResolveOrder('unknown', T0 + timedelta(minutes=3), close_order.order_id,
                                     'UNKNOWN', 'account-unknown'))
    state = step(state, BeginTradingDay('day2', T0 + timedelta(days=1), '2026-10-10', 1, 'JM2701', 'recon-day2'))
    assert state.daily_halt
    state = step(state, replace(bar(T0 + timedelta(days=1, minutes=1), command_id='unknown-bar'),
                                trading_day='2026-10-10'))
    assert state.position_qty == 1 and state.daily_halt
    state = step(state, ResolveOrder('verified-cancel', T0 + timedelta(days=1, minutes=2),
                                     close_order.order_id, 'CANCELLED', 'account-cancel-fact'))
    assert any(o.side == 'CLOSE' and o.status == 'PENDING' for o in state.orders)
    state = step(state, replace(bar(T0 + timedelta(days=1, minutes=3), command_id='reissued-close'),
                                trading_day='2026-10-10'))
    assert state.position_qty == 0 and state.daily_halt


def test_open_admission_uses_open_fee_and_margin_before_close_mark():
    from dataclasses import replace
    state = step(started(), decision())
    high_close = replace(bar(T0 + timedelta(minutes=1), close=D('1200'), command_id='no-margin'),
                         margin_per_contract=D('50000'))
    state = step(state, high_close)
    assert state.position_qty == 0
    adverse_close = replace(bar(T0 + timedelta(minutes=2), close=D('950'), command_id='adverse'),
                            margin_per_contract=D('49990'))
    state = step(state, adverse_close)
    assert state.position_qty == 1
    assert state.daily_halt


def test_clear_cancels_unfilled_open_before_future_bar():
    state = step(started(), decision())
    state = step(state, bar(T0 + timedelta(minutes=1), volume=0, command_id='no-fill'))
    state = step(state, decision('CLEAR', T0 + timedelta(minutes=2), command_id='clear', decision_id='clear'))
    assert state.orders[0].status == 'CANCEL_REQUESTED'
    state = step(state, bar(T0 + timedelta(minutes=3), command_id='later-bar'))
    assert state.position_qty == 0 and not state.fills
    state = step(state, ResolveOrder('ack', T0 + timedelta(minutes=4), state.orders[0].order_id,
                                     'CANCELLED', 'local-simulator-cancel-ack'))
    assert state.orders[0].status == 'CANCELLED'
