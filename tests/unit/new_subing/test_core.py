from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D, getcontext, localcontext

import pytest

from guiyi_quant.paper import FeeSchedule
from guiyi_quant.new_subing import (
    ExecutionBar, ExecutionFacts, Profile, StrategyBar, profile_payload, run_research,
)
from guiyi_quant.new_subing.account import ResearchAccount
from guiyi_quant.new_subing.signals import Snapshot, divergence_events


TZ = timezone(timedelta(hours=8))
T0 = datetime(2025, 1, 2, 9, 0, tzinfo=TZ)


def fees():
    return FeeSchedule(D('0'), D('2'), D('0'), D('3'), D('0'), D('5'), 'fee-v1')


def facts(day=date(2025, 1, 2), contract='RB2505'):
    return ExecutionFacts(contract, day, D('1'), D('10'), D('100'), D('.1'), D('.1'),
                          D('120'), D('80'), fees(), 'facts-v1')


def bar(at=T0 + timedelta(minutes=1), frequency='1m', close=D('100'), contract='RB2505', day=date(2025, 1, 2)):
    return StrategyBar('RB', contract, frequency, at, day, close, close, close, close,
                       D('100'), D('1000'), 'bar-' + at.isoformat(), at,
                       session_open_at=T0, session_close_at=T0 + timedelta(hours=6))


def test_profile_provenance_and_empty_replay_is_not_zero_return():
    payload = profile_payload(Profile())
    assert payload['strategy_code'] == 'new_subing_v1'
    assert payload['rules']['source']['ma21'] == 'owner_choice'
    assert payload['rules']['provenance']['add_oi_growth'] == 'guiyi_fixed_v1'
    assert payload['rules']['provenance']['ma_window'] == 'owner_choice'
    assert payload['rules']['provenance']['net_account'] == 'owner_choice'
    result = run_research({'1m': [], '5m': [], '15m': [], '1d': []}, [],
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert result['summary']['status'] == 'DATA_INSUFFICIENT'
    assert result['summary']['account_return_pct'] is None
    assert result['summary']['annual_eligible'] is False


def test_completed_and_temporal_facts_fail_closed():
    b = bar()
    with pytest.raises(ValueError):
        replace(b, confirmed_at=T0 - timedelta(seconds=1))
    with pytest.raises(ValueError):
        replace(b, close=D('NaN'))
    with pytest.raises(ValueError):
        ExecutionBar(b, replace(facts(), physical_contract='RB2509'))


def test_integer_lot_long_average_basis_and_close_today_fees():
    a = ResearchAccount(D('100000'))
    f = facts()
    a.open(1, 2, D('101'), f, T0, D('95'), D('2'), D('100'))
    a.open(1, 1, D('104'), f, T0 + timedelta(minutes=1), D('95'), D('2'), D('100'))
    assert a.qty == 3
    assert a.average_price == D('102')
    assert a.equity(D('103'), f) == D('100030') - D('6')
    a.close(1, D('105'), f, T0 + timedelta(minutes=2))
    assert a.qty == 2
    assert a.cash == D('100000') - D('6') + D('30') - D('5')


def test_short_close_yesterday_and_gap_loss_are_realized():
    a = ResearchAccount(D('100000'))
    f = facts()
    a.open(-1, 2, D('99'), f, T0, D('105'), D('2'), D('100'))
    a.begin_day(date(2025, 1, 3), D('101'), f)
    next_facts = replace(f, trading_day=date(2025, 1, 3))
    a.close(2, D('110'), next_facts, T0 + timedelta(days=1))
    assert a.qty == 0
    assert a.cash == D('100000') - D('4') - D('220') - D('6')
    assert a.closed_trades[0]['net_pnl'] == '-230'


def test_day_start_uses_prior_held_contract_mark_and_mixed_inventory_fees():
    a = ResearchAccount(D('100000'))
    f = facts()
    a.open(1, 2, D('100'), f, T0, D('95'), D('2'), D('100'))
    a.mark(D('110'), f)
    a.begin_day(date(2025, 1, 3), D('110'), f)
    assert a.day_start_equity == D('100196')
    next_facts = replace(f, trading_day=date(2025, 1, 3))
    a.open(1, 1, D('110'), next_facts, T0 + timedelta(days=1), D('95'), D('2'), D('100'))
    closed = a.close(3, D('110'), next_facts, T0 + timedelta(days=1, minutes=1))
    assert closed['close_yesterday_qty'] == 2
    assert closed['close_today_qty'] == 1
    assert closed['fee'] == '11'


def test_daily_loss_halt_persists_until_later_flat_day_and_blocks_reversal():
    a = ResearchAccount(D('100000'))
    f = facts()
    a.open(1, 10, D('100'), f, T0, D('95'), D('2'), D('100'))
    assert a.opening_direction == 1
    with pytest.raises(ValueError, match='cannot lock'):
        a.open(-1, 1, D('100'), f, T0 + timedelta(minutes=1), D('105'), D('2'), D('100'))
    a.mark(D('79'), f)
    assert a.daily_halt
    a.begin_day(date(2025, 1, 3), D('79'), f, can_reset=False)
    assert a.daily_halt
    next_facts = replace(f, trading_day=date(2025, 1, 3))
    a.close(10, D('79'), next_facts, T0 + timedelta(days=1))
    a.begin_day(date(2025, 1, 4), None)
    assert not a.daily_halt


def test_closed_loss_streak_resets_by_trading_day_even_with_carried_position():
    a = ResearchAccount(D('100000'))
    f = facts()
    a.open(1, 1, D('100'), f, T0, D('95'), D('2'), D('100'))
    a.close(1, D('99'), f, T0 + timedelta(minutes=1))
    assert a.closed_loss_streak == 1
    a.open(1, 1, D('100'), f, T0 + timedelta(minutes=2), D('95'), D('2'), D('100'))
    a.begin_day(date(2025, 1, 3), D('100'), f, can_reset=False)
    a.close(1, D('99'), replace(f, trading_day=date(2025, 1, 3)),
            T0 + timedelta(days=1))
    assert a.closed_loss_streak == 1


def test_no_fill_on_same_start_zero_volume_or_wrong_contract():
    decision = bar(T0 + timedelta(minutes=5), frequency='5m')
    same = bar(T0 + timedelta(minutes=5))
    later = bar(T0 + timedelta(minutes=6))
    no_volume = replace(later, volume=D('0'))
    result = run_research({'1m': [same, no_volume], '5m': [decision], '15m': [], '1d': []},
                          [ExecutionBar(same, facts()), ExecutionBar(no_volume, facts())],
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert result['fills'] == []


def test_execution_bar_must_match_authoritative_one_minute_history():
    histories, execution = scenario_bars()
    execution[0] = ExecutionBar(replace(execution[0].bar, source_identity='different'), facts())
    with pytest.raises(ValueError, match='execution bar differs'):
        run_research(histories, execution,
                     since=date(2025, 1, 2), through=date(2025, 1, 2))


def test_eligible_next_day_signal_without_execution_facts_fails_closed():
    histories, execution = scenario_bars()
    old = histories['5m'][-1]
    later_end = T0 + timedelta(days=1, minutes=5)
    histories['5m'].append(replace(old, bar_end=later_end, confirmed_at=later_end,
                                 trading_day=later_end.date(), source_identity='next-day-5m',
                                 session_open_at=T0 + timedelta(days=1),
                                 session_close_at=T0 + timedelta(days=1, hours=4)))
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 3))
    assert result['summary']['status'] == 'EXECUTION_FACTS_MISSING'
    assert result['summary']['account_return_pct'] is None


def scenario_bars(*, stopped=False, side=1):
    daily = []
    for i in range(25):
        end = T0 - timedelta(days=25-i) + timedelta(hours=6)
        price = (D('90') + D(i) / 5) if side > 0 else (D('110') - D(i) / 5)
        daily.append(StrategyBar('RB', 'RB2505', '1d', end, end.date(), price,
                                 price + D('.5'), price - D('.5'), price,
                                 D('100'), None, f'daily-{i}', end))
    fifteen = []
    for i in range(30):
        end = T0 + timedelta(minutes=(i-20)*15)
        price = (D('95') + D(i) / 10) if side > 0 else (D('105') - D(i) / 10)
        fifteen.append(StrategyBar('RB', 'RB2505', '15m', end, end.date(), price,
                                   price + D('.5'), price - D('.5'), price,
                                   D('100'), None, f'15m-{i}', end,
                                   session_open_at=T0 if end > T0 else None,
                                   session_close_at=T0 + timedelta(hours=4) if end > T0 else None))
    five = []
    for i in range(32):
        end = T0 + timedelta(minutes=(i+1)*5)
        price = (D('100.8') if side > 0 else D('99.2')) if i >= 24 else D('100')
        five.append(StrategyBar('RB', 'RB2505', '5m', end, end.date(), price,
                                price + D('.5'), price - D('.5'), price,
                                D('400') if i == 24 else D('100'), D('1000'),
                                f'5m-{i}', end, session_open_at=T0,
                                session_close_at=T0 + timedelta(hours=4)))
    one = []
    for i in range(171):
        end = T0 + timedelta(minutes=i+1)
        price = (D('101') if side > 0 else D('99')) if i >= 120 else D('100')
        if stopped and i >= 150:
            price = D('98')
        one.append(StrategyBar('RB', 'RB2505', '1m', end, end.date(), price,
                               price, price, price, D('100'), D('1000'), f'1m-{i}', end,
                               session_open_at=T0,
                               session_close_at=T0 + timedelta(hours=4)))
    return {'1m': one, '5m': five, '15m': fifteen, '1d': daily}, [ExecutionBar(b, facts()) for b in one]


def test_setup_confirms_after_three_five_minute_closes_and_fills_future_open():
    histories, execution = scenario_bars()
    result = run_research(histories, execution, since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert result['summary']['status'] == 'COMPLETED'
    setup = next(d for d in result['decisions'] if d['action'] == 'SETUP')
    opening = next(d for d in result['decisions'] if d['action'] == 'OPEN')
    fill = next(f for f in result['fills'] if f['action'] == 'OPEN')
    assert setup['at'] == (T0 + timedelta(minutes=125)).isoformat()
    assert opening['at'] == (T0 + timedelta(minutes=140)).isoformat()
    assert datetime.fromisoformat(fill['at']) > datetime.fromisoformat(opening['at'])
    assert fill['qty'] >= 1
    assert fill['price'] == '102'


def test_completed_one_minute_stop_closes_at_later_open_with_gap_loss():
    histories, execution = scenario_bars(stopped=True)
    result = run_research(histories, execution, since=date(2025, 1, 2), through=date(2025, 1, 2))
    close_decision = next(d for d in result['decisions'] if d['action'] == 'CLEAR' and d['reason'] == 'HARD_STOP')
    closing = next(f for f in result['fills'] if f['action'] == 'CLOSE')
    assert datetime.fromisoformat(closing['at']) > datetime.fromisoformat(close_decision['at'])
    assert D(closing['price']) < D('98')
    assert D(result['trades'][0]['net_pnl']) < 0


def test_two_percent_day_loss_clear_has_priority_over_hard_stop():
    histories, execution = scenario_bars(stopped=True)
    for i in range(150, len(histories['1m'])):
        b = histories['1m'][i]
        histories['1m'][i] = replace(b, open=D('70'), high=D('70'), low=D('70'), close=D('70'))
    execution = [ExecutionBar(b, replace(facts(), limit_down=D('50')))
                 for b in histories['1m']]
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    clear = next(d for d in result['decisions'] if d['action'] == 'CLEAR')
    assert clear['reason'] == 'DAILY_2_PERCENT_HALT'
    assert result['trades'][0]['status'] == 'CLOSED'


def test_short_setup_uses_bidirectional_account_and_sell_slippage():
    histories, execution = scenario_bars(side=-1)
    result = run_research(histories, execution, since=date(2025, 1, 2), through=date(2025, 1, 2))
    opening = next(f for f in result['fills'] if f['action'] == 'OPEN')
    assert opening['side'] == 'SHORT'
    assert opening['price'] == '98'
    assert result['summary']['ending_qty'] < 0


def test_future_high_timeframe_confirmations_cannot_create_past_setup():
    histories, execution = scenario_bars()
    for freq in ('1d', '15m'):
        histories[freq] = [replace(b, confirmed_at=T0 + timedelta(hours=5)) for b in histories[freq]]
    result = run_research(histories, execution, since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert not any(d['action'] == 'SETUP' for d in result['decisions'])
    assert result['fills'] == []


def test_stale_fifteen_minute_context_cannot_confirm_current_session():
    histories, execution = scenario_bars()
    histories['15m'] = [b for b in histories['15m'] if b.bar_end <= T0 + timedelta(minutes=45)]
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert not any(d['action'] == 'SETUP' for d in result['decisions'])
    assert result['fills'] == []


def test_opening_twenty_minutes_gates_setup_then_requires_three_more_confirmations():
    histories, execution = scenario_bars()
    session = T0 + timedelta(minutes=120)
    for i, b in enumerate(histories['5m']):
        if i < 24:
            continue
        price = D('100.8') if i >= 26 else D('100')
        histories['5m'][i] = replace(b, open=price, high=price + D('.5'),
                                     low=price - D('.5'), close=price,
                                     volume=D('400') if i == 26 else D('100'),
                                     session_open_at=session)
    histories['15m'] = [replace(b, session_open_at=session)
                        if b.bar_end >= session + timedelta(minutes=15) else b
                        for b in histories['15m']]
    previous_confirm = histories['15m'][-1]
    next_confirm_end = session + timedelta(minutes=30)
    histories['15m'].append(replace(previous_confirm,
                                   bar_end=next_confirm_end, confirmed_at=next_confirm_end,
                                   open=previous_confirm.close + D('.1'),
                                   high=previous_confirm.high + D('.1'),
                                   low=previous_confirm.low + D('.1'),
                                   close=previous_confirm.close + D('.1'),
                                   source_identity='15m-next'))
    for i, b in enumerate(histories['1m']):
        if b.bar_end <= session:
            continue
        price = D('101') if i >= 135 else D('100')
        new = replace(b, open=price, high=price, low=price, close=price,
                      session_open_at=session)
        histories['1m'][i] = new
        execution[i] = ExecutionBar(new, facts())
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert next(d for d in result['decisions'] if d['action'] == 'SETUP')['at'] == \
        (T0 + timedelta(minutes=140)).isoformat()
    assert next(d for d in result['decisions'] if d['action'] == 'OPEN')['at'] == \
        (T0 + timedelta(minutes=155)).isoformat()


def _lunch_gap(histories, execution):
    cutoff = T0 + timedelta(minutes=120)
    pause = timedelta(hours=2)
    for frequency in ('1m', '5m', '15m'):
        changed = []
        for b in histories[frequency]:
            if b.bar_end <= cutoff:
                changed.append(b)
                continue
            end = b.bar_end + pause
            changed.append(replace(b, bar_end=end, confirmed_at=end,
                                   session_close_at=T0 + timedelta(hours=8),
                                   source_identity=b.source_identity + '-lunch'))
        histories[frequency] = changed
    execution[:] = [ExecutionBar(b, facts()) for b in histories['1m']]


def test_lunch_gap_keeps_last_completed_fifteen_minute_bar_until_next_trading_close():
    histories, execution = scenario_bars()
    _lunch_gap(histories, execution)
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    setup = next(d for d in result['decisions'] if d['action'] == 'SETUP')
    assert setup['at'] == (T0 + timedelta(minutes=245)).isoformat()
    assert any(d['action'] == 'OPEN' for d in result['decisions'])


def test_missing_fifteen_minute_close_after_lunch_blocks_confirmation():
    histories, execution = scenario_bars()
    _lunch_gap(histories, execution)
    histories['15m'] = [b for b in histories['15m'] if b.bar_end <= T0 + timedelta(minutes=120)]
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert any(d['action'] == 'SETUP' for d in result['decisions'])
    assert not any(d['action'] == 'OPEN' for d in result['decisions'])


def test_flat_owner_switch_preserves_same_account_cash_and_completes_window():
    histories, execution = scenario_bars(stopped=True)
    first = run_research(histories, execution,
                         since=date(2025, 1, 2), through=date(2025, 1, 3))
    assert first['summary']['ending_qty'] == 0
    next_end = T0 + timedelta(days=1, minutes=1)
    new_contract = replace(execution[-1].bar, physical_contract='RB2509',
                           bar_end=next_end, confirmed_at=next_end,
                           trading_day=date(2025, 1, 3),
                           source_identity='next-owner-1m',
                           session_open_at=T0 + timedelta(days=1),
                           session_close_at=T0 + timedelta(days=1, hours=4))
    histories['1m'].append(new_contract)
    execution.append(ExecutionBar(new_contract, facts(date(2025, 1, 3), 'RB2509')))
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 3))
    assert result['summary']['status'] == 'COMPLETED'
    assert result['summary']['final_equity'] == first['summary']['final_equity']
    assert len(result['trades']) == len(first['trades'])


def test_prefix_and_replay_are_stable_despite_later_bars():
    histories, execution = scenario_bars(stopped=True)
    cutoff = T0 + timedelta(minutes=145)
    prefix_histories = {freq: [b for b in bars if b.bar_end <= cutoff]
                        for freq, bars in histories.items()}
    prefix_execution = [e for e in execution if e.bar.bar_end <= cutoff]
    first = run_research(prefix_histories, prefix_execution,
                         since=date(2025, 1, 2), through=date(2025, 1, 2))
    replayed = run_research(prefix_histories, prefix_execution,
                            since=date(2025, 1, 2), through=date(2025, 1, 2))
    full = run_research(histories, execution,
                        since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert first == replayed
    assert first['decisions'] == [d for d in full['decisions'] if datetime.fromisoformat(d['at']) <= cutoff]
    assert first['fills'] == [f for f in full['fills'] if datetime.fromisoformat(f['at']) <= cutoff]


def test_money_and_risk_are_stable_under_process_decimal_context_changes():
    histories, execution = scenario_bars(stopped=True)
    original_precision = getcontext().prec
    with localcontext() as context:
        context.prec = 7
        low = run_research(histories, execution,
                           since=date(2025, 1, 2), through=date(2025, 1, 2))
        assert context.prec == 7
    with localcontext() as context:
        context.prec = 50
        high = run_research(histories, execution,
                            since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert low == high
    assert getcontext().prec == original_precision


def test_divergence_waits_for_two_completed_right_bars():
    highs = [101, 102, 105, 102, 101, 103, 106, 103, 101]
    snapshots = []
    for i, high in enumerate(highs):
        b = replace(bar(T0 + timedelta(minutes=5 * (i+1)), frequency='5m'),
                    high=D(high), low=D('99'), source_identity=f'pivot-{i}')
        snapshots.append(Snapshot(b, None, None, None, None,
                                  D('5') if i == 2 else D('4') if i == 6 else D('1'),
                                  None, None, 0, 0, 0, 0, 0, None, False, False))
    events = divergence_events(snapshots, 1)
    assert events[7] is None
    assert events[8] == (2, 6)


def test_owner_roll_with_position_interrupts_without_synthetic_exit():
    histories, execution = scenario_bars()
    later = bar(T0 + timedelta(minutes=172), contract='RB2509')
    histories['1m'].append(later)
    execution.append(ExecutionBar(later, facts(contract='RB2509')))
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert result['summary']['status'] == 'ROLLOVER_INTERRUPTED'
    assert result['summary']['account_return_pct'] is None
    assert result['summary']['ending_qty'] > 0
    assert not any(f['action'] == 'CLOSE' for f in result['fills'])


def test_overlapping_other_contract_prefix_does_not_change_owner_signals():
    histories, execution = scenario_bars()
    baseline = run_research(histories, execution,
                            since=date(2025, 1, 2), through=date(2025, 1, 2))
    for freq in ('1m', '5m', '15m', '1d'):
        other = [replace(b, physical_contract='RB2509',
                         source_identity='other-' + b.source_identity,
                         observation_eligible=False,
                         open=b.open + D('100'), high=b.high + D('100'),
                         low=b.low + D('100'), close=b.close + D('100'))
                 for b in histories[freq]]
        histories[freq] = sorted([*histories[freq], *other],
                                 key=lambda b: (b.bar_end, b.physical_contract))
    with_overlap = run_research(histories, execution,
                                since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert with_overlap['decisions'] == baseline['decisions']
    assert with_overlap['fills'] == baseline['fills']


def test_zero_volume_after_confirmation_leaves_one_pending_open_without_fill():
    histories, execution = scenario_bars()
    for i in range(140, len(execution)):
        b = replace(histories['1m'][i], volume=D('0'))
        histories['1m'][i] = b
        execution[i] = ExecutionBar(b, facts())
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert len([d for d in result['decisions'] if d['action'] == 'OPEN']) == 1
    assert result['fills'] == []
    assert result['summary']['status'] == 'PENDING_UNFILLED'
    assert result['summary']['account_return_pct'] is None
    assert result['diagnostics']['pending_order'] is True
    assert result['diagnostics']['rejections']['NO_EXECUTABLE_VOLUME_OR_PRICE'] > 0


def test_cost_stress_scenarios_are_independent_and_worse_per_lot():
    histories, execution = scenario_bars(stopped=True)
    results = {scenario: run_research(histories, execution, scenario=scenario,
                                      since=date(2025, 1, 2), through=date(2025, 1, 2))
               for scenario in ('baseline', 'double_commission', 'double_slippage')}
    for result in results.values():
        assert result['summary']['initial_cash'] == '100000'
        assert len(result['trades']) == 1
    base = D(results['baseline']['trades'][0]['net_pnl']) / results['baseline']['fills'][0]['qty']
    for scenario in ('double_commission', 'double_slippage'):
        stressed = (D(results[scenario]['trades'][0]['net_pnl']) /
                    results[scenario]['fills'][0]['qty'])
        assert stressed < base


def test_fast_profit_reduction_uses_one_partial_close_and_blocks_adds():
    histories, execution = scenario_bars()
    histories['5m'] = [replace(b, open=D('108'), high=D('108.5'), low=D('107.5'), close=D('108'))
                        if i >= 28 else b for i, b in enumerate(histories['5m'])]
    for i in range(145, len(histories['1m'])):
        b = histories['1m'][i]
        histories['1m'][i] = replace(b, open=D('108'), high=D('108'), low=D('108'), close=D('108'))
        execution[i] = ExecutionBar(histories['1m'][i], facts())
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert any(d['action'] == 'REDUCE' and d['reason'] == 'FAST_PROFIT' for d in result['decisions'])
    closes = [f for f in result['fills'] if f['action'] == 'CLOSE']
    assert len(closes) == 1
    assert closes[0]['qty'] < result['fills'][0]['qty']
    assert not any(d['action'] == 'ADD' for d in result['decisions'])


def test_single_lot_records_unsplittable_reduction_without_closing():
    histories, execution = scenario_bars()
    histories['5m'] = [replace(b, open=D('108'), high=D('108.5'), low=D('107.5'), close=D('108'))
                        if i >= 28 else b for i, b in enumerate(histories['5m'])]
    for i in range(145, len(histories['1m'])):
        b = histories['1m'][i]
        histories['1m'][i] = replace(b, open=D('108'), high=D('108'), low=D('108'), close=D('108'))
    execution = [ExecutionBar(b, replace(facts(), multiplier=D('100')))
                 for b in histories['1m']]
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    assert result['fills'][0]['qty'] == 1
    assert any(d['action'] == 'REDUCE_SKIPPED' for d in result['decisions'])
    assert not any(d['action'] in ('REDUCE', 'CLEAR') for d in result['decisions'])
    assert not any(f['action'] == 'CLOSE' for f in result['fills'])


def test_add_waits_three_closes_after_rebreakout_and_uses_first_fill_cap():
    histories, execution = scenario_bars()
    five = histories['5m']
    pattern = {28: D('103'), 29: D('102'), 30: D('104'),
               31: D('104'), 32: D('104'), 33: D('104')}
    for i in (32, 33):
        end = T0 + timedelta(minutes=(i+1)*5)
        five.append(StrategyBar('RB', 'RB2505', '5m', end, end.date(), D('104'),
                                D('104.5'), D('103.5'), D('104'), D('100'), D('1010'),
                                f'5m-{i}', end, session_open_at=T0,
                                session_close_at=T0 + timedelta(hours=4)))
    for i, price in pattern.items():
        b = five[i]
        five[i] = replace(b, open=price, high=price + D('.5'), low=price - D('.5'),
                          close=price, volume=D('400') if i == 30 else D('100'),
                          open_interest=D('1010') if i >= 30 else D('1000'))
    one = histories['1m']
    for i in range(171, 176):
        end = T0 + timedelta(minutes=i+1)
        one.append(StrategyBar('RB', 'RB2505', '1m', end, end.date(), D('104'),
                               D('104'), D('104'), D('104'), D('100'), D('1010'),
                               f'1m-{i}', end, session_open_at=T0,
                               session_close_at=T0 + timedelta(hours=4)))
    for i in range(145, 176):
        b = one[i]
        price = D('103') if i < 150 else D('102') if i < 155 else D('104')
        one[i] = replace(b, open=price, high=price, low=price, close=price)
    execution = [ExecutionBar(b, facts()) for b in one]
    result = run_research(histories, execution,
                          since=date(2025, 1, 2), through=date(2025, 1, 2))
    adds = [d for d in result['decisions'] if d['action'] == 'ADD']
    assert len(adds) == 1
    assert adds[0]['at'] == (T0 + timedelta(minutes=170)).isoformat()
    opening = next(f for f in result['fills'] if f['action'] == 'OPEN')
    add_fill = next(f for f in result['fills'] if f['action'] == 'OPEN' and f is not opening)
    assert 1 <= add_fill['qty'] <= opening['qty'] * 2 // 3
