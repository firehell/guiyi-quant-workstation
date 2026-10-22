"""Constructed execution cases, never historical trading evidence."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.new_subing import ExecutionFacts, StrategyBar
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_jm_daily import DailyModel, Event, daily_frames


T = datetime(2025, 1, 2, 7, tzinfo=UTC)


def facts(day=date(2025, 1, 2), contract='JM2505', **changes):
    base = ExecutionFacts(contract, day, D('.5'), D('60'), D('1000'), D('.2'), D('.3'),
        D('2000'), D('100'), FeeSchedule(D(0), D(1), D(0), D(2), D(0), D(3), 'fees'), 'facts')
    return replace(base, **changes)


def bar(at=T, price='1000', frequency='1m', contract='JM2505', day=None, volume='10'):
    p = D(price)
    return StrategyBar('jm', contract, frequency, at, day or at.date(), p, p, p, p, D(volume),
                       None, f'{contract}|{frequency}|{at}|{price}|{volume}', at,
                       session_open_at=at-timedelta(hours=4), session_close_at=at+timedelta(hours=4))


def minute(model, at=T, price='1000', contract='JM2505', day=None, **kwargs):
    b = bar(at, price, contract=contract, day=day, **kwargs)
    model.apply(Event('1m', b, facts(b.trading_day, contract)))


def signal(model, at=T, price='1000', ema='990', cross=1, contract='JM2505', day=None):
    model.apply(Event('1d', bar(at, price, '1d', contract, day), ema=D(ema), cross=cross))


def check(model, at, price='1000', **kwargs):
    model.apply(Event('15m', bar(at, price, '15m', **kwargs)))


def opened(side=1):
    model = DailyModel()
    minute(model)
    signal(model, price='1000', ema='990' if side == 1 else '1010', cross=side)
    minute(model, T+timedelta(minutes=1))  # Bar starts at decision: not strict-later.
    assert not model.fills
    minute(model, T+timedelta(minutes=2))
    assert model.position.side == side
    return model


@pytest.mark.parametrize('side', [1, -1])
def test_bidirectional_single_lot_costed_close_is_strict_later(side):
    model = opened(side)
    entry = D('1000.5') if side == 1 else D('999.5')
    assert D(model.fills[0]['price']) == entry
    assert model.fills[0]['qty'] == 1 and model.cash == D('99999')
    signal(model, T+timedelta(minutes=15), price='980' if side == 1 else '1020', ema='990' if side == 1 else '1010', cross=-side)
    minute(model, T+timedelta(minutes=16), '980' if side == 1 else '1020')
    assert len(model.fills) == 1
    minute(model, T+timedelta(minutes=17), '980' if side == 1 else '1020')
    assert model.position is None and model.pending is None
    assert D(model.fills[-1]['fee']) == 3
    assert model.cash == D('98736')
    assert len(model.trades) == 1 and D(model.trades[0]['net_pnl']) == -D('1264')
    minute(model, T+timedelta(minutes=18))
    assert len(model.fills) == 2  # Reverse event was consumed by exit.


def test_risk_gap_recheck_rejects_and_does_not_resize():
    model = DailyModel()
    minute(model)
    signal(model)
    minute(model, T+timedelta(minutes=2), '1100')
    assert model.position is None and model.pending is None
    assert model.decisions[-1]['reason'] == 'TRADE_RISK_EXCEEDED'


def test_protective_stop_waits_for_completed_15m_and_only_tightens():
    model = opened()
    assert model.position.stop == D('978')
    minute(model, T+timedelta(minutes=3), '977')
    assert model.pending is None
    check(model, T+timedelta(minutes=15), '978')
    assert model.pending.action == 'CLOSE'
    assert model.pending.reason == 'PROTECTIVE_STOP'


@pytest.mark.parametrize('side,emas,expected', [(1, ('995','991'), D('983')), (-1, ('1005','1009'), D('1017'))])
def test_daily_stop_never_loosens(side, emas, expected):
    model = opened(side)
    for i, ema in enumerate(emas, 1):
        at = T+timedelta(days=i)
        minute(model, at, day=at.date())
        signal(model, at, ema=ema, cross=0, day=at.date())
    assert model.position.stop == expected


def test_daily_five_percent_halt_persists_until_flat_and_next_day_reconciled():
    model = opened()
    at = T+timedelta(minutes=15)
    minute(model, at, '910')
    check(model, at, '910')
    assert model.daily_halt and model.pending.reason == 'DAILY_LOSS_HALT'
    minute(model, at+timedelta(minutes=2), '900')
    assert model.position is None and model.daily_halt
    signal(model, at+timedelta(minutes=3), price='1000', ema='990')
    assert model.pending is None
    nxt = T+timedelta(days=1)
    minute(model, nxt, day=nxt.date())
    assert not model.daily_halt
    assert model.day_start_equity == model.cash


def test_zero_volume_and_limit_block_keep_pending_real_position():
    model = opened()
    check(model, T+timedelta(minutes=15), '978')
    minute(model, T+timedelta(minutes=17), '970', volume='0')
    assert model.position and model.pending
    minute(model, T+timedelta(minutes=18), '100')  # sell blocked at lower limit
    assert model.position and model.pending


def test_rollover_preserves_old_position_mark_and_close_intent():
    model = opened()
    old = model.equity
    at = T+timedelta(days=1)
    minute(model, at, '1500', contract='JM2509', day=at.date())
    assert model.status == 'ROLLOVER_INTERRUPTED'
    assert model.position.contract == 'JM2505'
    assert model.pending.contract == 'JM2505' and model.pending.action == 'CLOSE'
    assert model.equity == old
    assert model.result()['summary']['net_return_pct'] is None
    assert len(model.fills) == 1


def test_duplicate_event_idempotence_identity_conflict_and_restart_parity():
    model = opened()
    event = Event('15m', bar(T+timedelta(minutes=15), '1000', '15m'))
    model.apply(event)
    before = model.checkpoint()
    model.apply(event)
    assert model.checkpoint() == before
    restored = DailyModel.restore(before)
    exit_event = Event('15m', bar(T+timedelta(minutes=30), '978', '15m'))
    for current in (model, restored):
        current.apply(exit_event)
        minute(current, T+timedelta(minutes=32), '970')
    assert model.result() == restored.result()
    with pytest.raises(ValueError):
        restored.apply(replace(event, bar=replace(event.bar, close=D('999'), low=D('999'))))


def test_signal_kernel_prefix_does_not_use_later_daily_bars():
    bars = [bar(T+timedelta(days=i), str(1000+i), '1d') for i in range(50)]
    frames = daily_frames(bars)
    assert daily_frames(bars[:40]) == frames[:40]
    assert frames[33].ema is None
    assert frames[34].ema is not None


def test_close_equal_ema_cannot_create_entry_even_if_caller_invents_cross():
    with pytest.raises(ValueError):
        Event('1d', bar(T, '1000', '1d'), ema=D('1000'), cross=1)


def test_next_daily_confirmation_cancels_unfilled_old_entry():
    model = DailyModel()
    minute(model)
    signal(model)
    at = T+timedelta(days=1)
    minute(model, at, '1000', day=at.date(), volume='0')
    signal(model, at, '1000', '1010', 0, day=at.date())
    assert model.pending is None
    assert model.decisions[-1]['reason'] == 'DAILY_ENTRY_EXPIRED'


def test_events_after_rollover_cannot_create_new_owner_trades():
    model = opened()
    at = T+timedelta(days=1)
    minute(model, at, contract='JM2509', day=at.date())
    check(model, at, contract='JM2509', day=at.date())
    assert len(model.fills) == 1
    assert model.status == 'ROLLOVER_INTERRUPTED'


def test_invalid_multiplier_does_not_partially_commit_event():
    model = opened()
    before = model.checkpoint()
    b = bar(T+timedelta(minutes=3))
    with pytest.raises(ValueError):
        model.apply(Event('1m', b, facts(multiplier=D('120'))))
    assert model.checkpoint() == before


def test_rollover_also_stops_flat_account_without_automatic_resume():
    model = DailyModel()
    minute(model)
    at = T+timedelta(days=1)
    minute(model, at, contract='JM2509', day=at.date())
    signal(model, at, contract='JM2509', day=at.date())
    assert model.status == 'ROLLOVER_INTERRUPTED'
    assert model.position is None and model.pending is None and not model.fills


def test_execution_price_outside_authoritative_limits_fails_before_state_mutation():
    model = DailyModel()
    b = bar(price='99')
    before = model.checkpoint()
    with pytest.raises(ValueError):
        model.apply(Event('1m', b, facts()))
    assert model.checkpoint() == before


def test_risk_budget_uses_reduced_equity_after_a_closed_loss():
    model = opened()
    signal(model, T+timedelta(minutes=15), '987.5', '990', -1)
    minute(model, T+timedelta(minutes=17), '987.5')
    assert model.cash == D('99186')
    at = T+timedelta(days=1)
    minute(model, at, day=at.date())
    signal(model, at, '1000', '980', 1, day=at.date())
    assert model.pending is None and model.decisions[-1]['reason'] == 'TRADE_RISK_EXCEEDED'


def test_margin_rejection_is_independent_of_trade_risk_budget():
    model = DailyModel()
    model.apply(Event('1m', bar(), facts(prev_settlement=D('1999'), long_margin_ratio=D('1'))))
    signal(model)
    assert model.pending is None and model.decisions[-1]['reason'] == 'INSUFFICIENT_MARGIN'


def test_next_trading_day_exit_uses_close_yesterday_fee():
    model = opened()
    at = T+timedelta(days=1)
    minute(model, at, day=at.date())
    signal(model, at, '980', '990', -1, day=at.date())
    minute(model, at+timedelta(minutes=2), '980', day=at.date())
    assert D(model.fills[-1]['fee']) == D('2')
    assert D(model.trades[-1]['fees']) == D('3')


def test_rollover_close_can_use_only_later_old_contract_execution():
    model = opened()
    at = T+timedelta(days=1)
    minute(model, at, contract='JM2509', day=at.date())
    minute(model, at+timedelta(minutes=2), '990', contract='JM2505', day=at.date())
    assert model.position is None
    assert model.status == 'ROLLOVER_INTERRUPTED'
    assert model.fills[-1]['contract'] == 'JM2505'


def test_ledger_replay_rejects_tampered_cash_even_with_recomputed_checksum():
    from guiyi_quant.subing_jm_daily import digest
    checkpoint = opened().checkpoint()
    checkpoint['state']['cash'] = '100000'
    checkpoint['hash'] = digest(checkpoint['state'])
    with pytest.raises(ValueError):
        DailyModel.restore(checkpoint)


@pytest.mark.parametrize('price,halt', [('500.6', True), ('500.7', False)])
def test_daily_loss_boundary_includes_fees_and_unrealized_loss(price, halt):
    model = DailyModel()
    f = facts(multiplier=D('10'))
    model.apply(Event('1m', bar(), f))
    signal(model)
    model.apply(Event('1m', bar(T+timedelta(minutes=2)), f))
    at = T+timedelta(minutes=15)
    model.apply(Event('1m', bar(at, price), f))
    check(model, at, price)
    assert model.daily_halt is halt
    assert model.pending.reason == ('DAILY_LOSS_HALT' if halt else 'PROTECTIVE_STOP')


def test_restart_rejects_unknown_pending_order_action():
    from guiyi_quant.subing_jm_daily import digest
    model = DailyModel()
    minute(model)
    signal(model)
    checkpoint = model.checkpoint()
    checkpoint['state']['pending']['action'] = 'UNKNOWN'
    checkpoint['hash'] = digest(checkpoint['state'])
    with pytest.raises(ValueError):
        DailyModel.restore(checkpoint)


def test_outputs_and_reconciliation_ignore_callers_decimal_context():
    from decimal import localcontext
    model = opened()
    signal(model, T+timedelta(minutes=15), '987.5', '990', -1)
    minute(model, T+timedelta(minutes=17), '987.5')
    expected = model.result()
    with localcontext() as context:
        context.prec = 4
        assert model.result() == expected


def test_clock_compares_instants_not_lexical_timezone_strings():
    model = DailyModel()
    minute(model)
    before = model.checkpoint()
    earlier = datetime(2025, 1, 2, 8, tzinfo=timezone(timedelta(hours=8)))
    with pytest.raises(ValueError):
        minute(model, earlier)
    assert model.checkpoint() == before
