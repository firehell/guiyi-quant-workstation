from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.new_subing import ExecutionBar, ExecutionFacts, StrategyBar
from guiyi_quant.new_subing_v2 import Profile, prepare_research, profile_payload, run_research
from guiyi_quant.new_subing_v2.account import LayerAccount
from guiyi_quant.new_subing_v2.signals import direction, setup_evidence
from guiyi_quant.new_subing_v2.engine import daily_anchor_trigger, daily_macd_reaction
from guiyi_quant.paper import FeeSchedule
from tests.unit.new_subing.test_core import scenario_bars


TZ = timezone(timedelta(hours=8))
T0 = datetime(2025, 1, 2, 9, tzinfo=TZ)
DAY = date(2025, 1, 2)


def fees():
    return FeeSchedule(D('0'), D('2'), D('0'), D('3'), D('0'), D('5'), 'fees')


def facts(day=DAY):
    return ExecutionFacts('RB2505', day, D('1'), D('10'), D('100'), D('.1'), D('.1'),
                          D('120'), D('80'), fees(), 'facts')


def bar(i, frequency='1m', price=D('100'), volume=D('100'), oi=D('1000')):
    end = T0 + timedelta(minutes=i)
    return StrategyBar('RB', 'RB2505', frequency, end, DAY, price, price, price, price,
                       volume, oi, f'{frequency}-{i}', end,
                       session_open_at=T0, session_close_at=T0 + timedelta(hours=5))


def test_profile_identity_and_cash_choices():
    assert profile_payload(Profile())['account_model_version'] == 'new_subing_layers_v2'
    assert Profile(initial_cash=D('1000000')).profile_id == 'new_subing_stage_v2_1m'
    with pytest.raises(ValueError):
        Profile(initial_cash=D('200000'))


def test_named_layer_close_preserves_base_and_charges_own_day_fee():
    account = LayerAccount(D('100000'))
    f = facts()
    account.open(1, 2, D('100'), f, T0, D('95'), D('2'), D('99'), 'TRIAL')
    account.open(1, 1, D('110'), f, T0 + timedelta(minutes=1), D('106'), D('2'), D('109'), 'ADD')
    assert account.average_price == D('310') / 3
    last_id = account.layers[-1].layer_id
    closed = account.close(1, D('105'), f, T0 + timedelta(minutes=2), layer_id=last_id)
    assert closed['layer_closes'][0]['layer_id'] == last_id
    assert closed['close_today_qty'] == 1
    assert account.average_price == D('100')
    assert account.qty == 2
    assert account.cash == D('100000') - D('6') - D('50') - D('5')
    account.begin_day(date(2025, 1, 3), D('105'), f)
    f2 = replace(f, trading_day=date(2025, 1, 3))
    closed = account.close(1, D('106'), f2, T0 + timedelta(days=1))
    assert closed['close_yesterday_qty'] == 1
    assert closed['fee'] == '3'
    assert account.average_price == D('100')


def test_fifo_reduce_and_short_layer_fee_identity():
    account = LayerAccount(D('100000'))
    f = facts()
    first = account.open(-1, 2, D('100'), f, T0, D('105'), D('2'), D('101'), 'TRIAL')
    second = account.open(-1, 1, D('95'), f, T0 + timedelta(minutes=1),
                          D('95'), D('2'), D('96'), 'ADD')
    ordinary = account.close(1, D('90'), f, T0 + timedelta(minutes=2))
    assert ordinary['layer_closes'][0]['layer_id'] == first['layer_id']
    assert account.average_price == (D('100') + D('95')) / 2
    assert second['stop'] == second['price']
    account.begin_day(date(2025, 1, 3), D('90'), f)
    next_facts = replace(f, trading_day=date(2025, 1, 3))
    named = account.close(1, D('96'), next_facts, T0 + timedelta(days=1),
                          layer_id=second['layer_id'])
    assert named['close_yesterday_qty'] == 1
    assert named['fee'] == '3'


def test_prepared_binding_and_repeatable_result():
    bars = {'1m': [], '5m': [], '15m': [], '1d': []}
    prepared = prepare_research(bars, Profile())
    result = run_research(bars, [], since=DAY, through=DAY, prepared=prepared)
    assert result['summary']['status'] == 'DATA_INSUFFICIENT'
    assert result == run_research(bars, [], since=DAY, through=DAY, prepared=prepared)
    with pytest.raises(ValueError, match='prepared'):
        run_research({**bars, '1m': [bar(1)]}, [], since=DAY, through=DAY, prepared=prepared)


def test_direction_is_price_side_without_slope_and_trial_setup_is_immediate():
    from guiyi_quant.new_subing_v2.signals import build_snapshots
    prices = [D('100')] * 22 + [D('101')]
    bars = [bar(5 * (i + 1), '5m', price, D('400') if i == 22 else D('100'))
            for i, price in enumerate(prices)]
    snapshots = build_snapshots(bars, Profile())
    assert direction(snapshots[-1]) == 1
    evidence = setup_evidence(snapshots, len(snapshots) - 1, 1, Profile())
    assert evidence is not None
    assert evidence['trigger'] in ('MA_CROSS', 'BREAKOUT')


def test_no_same_start_fill_and_unavailable_metrics_are_null():
    five = bar(25, '5m')
    one = bar(25)
    histories = {'1m': [one], '5m': [five], '15m': [], '1d': []}
    result = run_research(histories, [ExecutionBar(one, facts())], since=DAY, through=DAY)
    assert result['fills'] == []
    assert result['summary']['account_return_pct'] is None


def test_trial_fills_before_three_bar_confirmation_and_is_prefix_stable():
    histories, execution = scenario_bars()
    full = run_research(histories, execution, since=DAY, through=DAY)
    trial = next(d for d in full['decisions'] if d['action'] == 'OPEN')
    fill = next(f for f in full['fills'] if f['action'] == 'OPEN')
    assert trial['at'] == (T0 + timedelta(minutes=125)).isoformat()
    assert datetime.fromisoformat(fill['at']) > datetime.fromisoformat(trial['at'])
    assert fill['stage'] == 'TRIAL'
    assert full['fills'][0]['qty'] == 8
    confirmed = next(row for row in full['stages'] if row['stage'] == 'BREAKOUT_CONFIRMED')
    assert confirmed['at'] == (T0 + timedelta(minutes=140)).isoformat()
    cutoff = T0 + timedelta(minutes=145)
    prefix = {frequency: [b for b in bars if b.bar_end <= cutoff]
              for frequency, bars in histories.items()}
    prefix_execution = [e for e in execution if e.bar.bar_end <= cutoff]
    first = run_research(prefix, prefix_execution, since=DAY, through=DAY)
    assert first == run_research(prefix, prefix_execution, since=DAY, through=DAY)
    assert first['decisions'] == [d for d in full['decisions'] if datetime.fromisoformat(d['at']) <= cutoff]
    assert first['fills'] == [f for f in full['fills'] if datetime.fromisoformat(f['at']) <= cutoff]


def test_prepared_reuse_across_cash_and_cost_matches_unprepared():
    histories, execution = scenario_bars(stopped=True)
    p100 = Profile()
    prepared = prepare_research(histories, p100)
    for cash in (D('100000'), D('1000000')):
        for scenario in ('baseline', 'double_slippage', 'double_commission'):
            profile = Profile(initial_cash=cash)
            cached = run_research(histories, execution, profile=profile, scenario=scenario,
                                  since=DAY, through=DAY, prepared=prepared)
            fresh = run_research(histories, execution, profile=profile, scenario=scenario,
                                 since=DAY, through=DAY)
            assert cached == fresh
            assert cached['summary']['initial_cash'] == str(cash)


def test_future_daily_and_fifteen_minute_facts_cannot_make_past_setup():
    histories, execution = scenario_bars()
    for frequency in ('1d', '15m'):
        histories[frequency] = [replace(b, confirmed_at=T0 + timedelta(hours=5))
                                for b in histories[frequency]]
    result = run_research(histories, execution, since=DAY, through=DAY)
    assert result['fills'] == []


def test_held_roll_interrupts_but_flat_roll_keeps_cash():
    histories, execution = scenario_bars()
    for i in range(24, len(histories['5m'])):
        b = histories['5m'][i]
        histories['5m'][i] = replace(b, open=D('110'), high=D('110.5'),
                                     low=D('109.5'), close=D('110'))
    for i in range(120, len(histories['1m'])):
        b = histories['1m'][i]
        histories['1m'][i] = replace(b, open=D('105'), high=D('105'), low=D('105'), close=D('105'))
    execution = [ExecutionBar(b, facts()) for b in histories['1m']]
    new = replace(bar(172), physical_contract='RB2509', source_identity='next-owner')
    histories['1m'].append(new)
    execution.append(ExecutionBar(new, replace(facts(), physical_contract='RB2509')))
    held = run_research(histories, execution, since=DAY, through=DAY)
    assert held['summary']['status'] == 'ROLLOVER_INTERRUPTED'
    assert held['summary']['account_return_pct'] is None
    closed_histories, closed_execution = scenario_bars(stopped=True)
    flat = run_research(closed_histories, closed_execution, since=DAY, through=DAY)
    closed_histories['1m'].append(new)
    closed_execution.append(ExecutionBar(new, replace(facts(), physical_contract='RB2509')))
    rolled = run_research(closed_histories, closed_execution, since=DAY, through=DAY)
    assert rolled['summary']['status'] == 'COMPLETED'
    assert rolled['summary']['final_equity'] == flat['summary']['final_equity']


def test_pending_trial_cannot_cross_physical_owner():
    histories, execution = scenario_bars()
    cutoff = T0 + timedelta(minutes=125)
    histories['1m'] = [b for b in histories['1m'] if b.bar_end <= cutoff]
    execution = [e for e in execution if e.bar.bar_end <= cutoff]
    next_bar = replace(bar(126), physical_contract='RB2509', source_identity='new-owner')
    histories['1m'].append(next_bar)
    execution.append(ExecutionBar(next_bar, replace(facts(), physical_contract='RB2509')))
    result = run_research(histories, execution, since=DAY, through=DAY)
    assert any(d['action'] == 'OPEN' for d in result['decisions'])
    assert result['summary']['status'] == 'ROLLOVER_INTERRUPTED'
    assert result['fills'] == []
    assert result['summary']['account_return_pct'] is None


def test_first_margin_and_integer_lot_limits():
    histories, execution = scenario_bars()
    result = run_research(histories, execution, since=DAY, through=DAY)
    opening = next(f for f in result['fills'] if f['action'] == 'OPEN')
    assert type(opening['qty']) is int
    assert D(opening['qty']) * D(opening['price']) * D('10') * D('.1') <= D('10000')


def test_boll_vote_needs_prior_compression_and_current_volume():
    from guiyi_quant.new_subing_v2.signals import build_snapshots
    bars = [bar(5 * (i+1), '5m', D('100')) for i in range(22)]
    bars.append(bar(115, '5m', D('101'), D('200')))
    snapshots = list(build_snapshots(bars, Profile()))
    for i, width in ((19, D('10')), (20, D('9')), (21, D('8'))):
        snapshots[i] = replace(snapshots[i], boll_upper=D('100') + width/2,
                               boll_lower=D('100') - width/2,
                               ma=D('100') + D(i-19)/10)
    snapshots[22] = replace(snapshots[22], ma=D('100.2'), ma_cross=1, boll_cross=1,
                            breakout=0, breakout_level=None)
    for i in (20, 21):
        snapshots[i] = replace(snapshots[i], breakout=0, breakout_level=None)
    good = setup_evidence(snapshots, 22, 1, Profile())
    assert good is not None and good['votes']['boll'] is True
    wider = list(snapshots)
    wider[21] = replace(wider[21], boll_upper=D('106'), boll_lower=D('94'))
    assert setup_evidence(wider, 22, 1, Profile()) is None
    no_volume = list(snapshots)
    no_volume[22] = replace(no_volume[22], bar=replace(no_volume[22].bar, volume=D('100')))
    assert setup_evidence(no_volume, 22, 1, Profile()) is None


def test_chop_trial_requires_volume_breakout_and_layer_guard_is_named():
    from guiyi_quant.new_subing_v2.signals import build_snapshots
    bars = [bar(5 * (i+1), '5m', D('100')) for i in range(22)]
    bars.append(bar(115, '5m', D('101'), D('400')))
    snapshots = list(build_snapshots(bars, Profile()))
    snapshots[-1] = replace(snapshots[-1], chop=True, breakout=1, breakout_level=D('100.5'),
                            volume_spike=True)
    evidence = setup_evidence(snapshots, len(snapshots)-1, 1, Profile())
    assert evidence is not None and evidence['trigger'] == 'BREAKOUT'
    snapshots[-1] = replace(snapshots[-1], volume_spike=False)
    assert setup_evidence(snapshots, len(snapshots)-1, 1, Profile()) is None


def test_stage_and_layer_diagnostics_are_compact_and_account_backed():
    histories, execution = scenario_bars(stopped=True)
    result = run_research(histories, execution, since=DAY, through=DAY)
    diagnostics = result['diagnostics']
    assert diagnostics['stage_counts']['TRIAL'] == 1
    assert diagnostics['stage_summary']['transition_count'] == len(result['stages'])
    assert diagnostics['layer_summary']['opened_layers'] == len(
        [f for f in result['fills'] if f['action'] == 'OPEN'])
    assert diagnostics['layer_summary']['remaining_layers'] == len(result['projection']['open_layers'])


def test_known_opposite_week_blocks_trial_but_unknown_week_allows_it():
    histories, execution = scenario_bars()
    unknown = run_research(histories, execution, since=DAY, through=DAY)
    assert any(d['action'] == 'OPEN' for d in unknown['decisions'])
    weekly = []
    for i in range(23):
        end = T0 - timedelta(weeks=23-i)
        price = D('120') - D(i)
        weekly.append(replace(histories['1d'][0], frequency='1w',
                              bar_end=end, confirmed_at=end, trading_day=end.date(),
                              open=price, high=price, low=price, close=price,
                              source_identity=f'weekly-{i}'))
    histories['1w'] = weekly
    blocked = run_research(histories, execution, since=DAY, through=DAY)
    assert not any(d['action'] == 'OPEN' for d in blocked['decisions'])
    assert blocked['diagnostics']['rejections']['MULTI_TIMEFRAME_DIRECTION_UNREADY'] > 0


def test_add_layer_uses_fill_basis_and_guard_removes_only_that_layer():
    histories, _ = scenario_bars()
    warm = []
    for k in range(16):
        end = T0 - timedelta(minutes=(16-k)*5)
        warm.append(replace(histories['5m'][0], bar_end=end, confirmed_at=end,
                            source_identity=f'warm-{k}', session_open_at=None,
                            session_close_at=None, observation_eligible=False))
    prices = {24: '102', 25: '104', 26: '105', 27: '106', 28: '108',
              29: '107.8', 30: '109', 31: '110'}
    for i, value in prices.items():
        b = histories['5m'][i]
        price = D(value)
        histories['5m'][i] = replace(b, open=price, high=price+D('.5'),
                                     low=D('106') if i == 28 else price-D('.5'),
                                     close=price, volume=D('400') if i in (24, 30) else D('100'),
                                     open_interest=D('1001') if i >= 30 else D('1000'))
    histories['5m'] = warm + histories['5m']
    for i in range(120, len(histories['1m'])):
        b = histories['1m'][i]
        price = D(prices.get(i//5, '110'))
        histories['1m'][i] = replace(b, open=price, high=price, low=price, close=price)
    for n in (30, 31):
        b = histories['15m'][-1]
        end = T0 + timedelta(minutes=(n-20)*15)
        price = D('98') + D(n-30)/10
        histories['15m'].append(replace(b, bar_end=end, confirmed_at=end,
                                        open=price, high=price+D('.5'), low=price-D('.5'),
                                        close=price, source_identity=f'15m-{n}'))
    execution_facts = replace(facts(), tick_size=D('.1'),
                              long_margin_ratio=D('.3'), short_margin_ratio=D('.3'))
    execution = [ExecutionBar(b, execution_facts) for b in histories['1m']]
    result = run_research(histories, execution, since=DAY, through=DAY)
    adds = [d for d in result['decisions'] if d['action'] == 'ADD']
    opens = [f for f in result['fills'] if f['action'] == 'OPEN']
    assert len(adds) == 1
    assert len(opens) == 2
    assert datetime.fromisoformat(opens[1]['at']) > datetime.fromisoformat(adds[0]['at'])
    assert opens[1]['stop'] == opens[1]['price']
    named = [f for f in result['fills'] if f.get('named_layer_id')]
    assert len(named) == 1
    assert named[0]['named_layer_id'] == opens[1]['layer_id']
    assert result['projection']['open_layers'][0]['layer_id'] == opens[0]['layer_id']
    assert result['diagnostics']['layer_summary']['named_guard_closes'] == 1
    assert result['diagnostics']['stage_summary']['first_atr'] == opens[0]['atr']

    same_time = {frequency: list(bars) for frequency, bars in histories.items()}
    final_five = same_time['5m'][16+31]
    same_time['5m'][16+31] = replace(final_five, open=D('113.9'), high=D('114'),
                                     low=D('112'), close=D('112'))
    for i in range(156, 160):
        b = same_time['1m'][i]
        if i == 156:
            same_time['1m'][i] = replace(b, open=D('113.9'), high=D('114'),
                                          low=D('113.9'), close=D('114'))
        else:
            price = D('112') if i == 159 else D('114')
            same_time['1m'][i] = replace(b, open=price, high=price,
                                          low=price, close=price)
    moderate_margin = replace(execution_facts, long_margin_ratio=D('.2'),
                              short_margin_ratio=D('.2'))
    same_execution = [ExecutionBar(b, moderate_margin) for b in same_time['1m']]
    arbitrated = run_research(same_time, same_execution, since=DAY, through=DAY)
    simultaneous = [d for d in arbitrated['decisions']
                    if d['at'] == (T0+timedelta(minutes=160)).isoformat() and
                    d['action'] in ('LAYER_CLEAR', 'REDUCE', 'ADD')]
    assert [d['action'] for d in simultaneous] == ['LAYER_CLEAR']


def test_short_daily_anchor_and_macd_reaction_are_symmetric():
    from guiyi_quant.new_subing_v2.signals import build_snapshots
    previous_bar = bar(5, '1d', D('100'))
    previous = replace(previous_bar, high=D('101'), low=D('99'))
    assert daily_anchor_trigger(-2, D('102'), previous)
    assert not daily_anchor_trigger(-1, D('102'), previous)
    assert not daily_anchor_trigger(-2, D('100'), previous)
    history = [bar(5*(i+1), '5m', D('100')) for i in range(23)]
    snapshots = build_snapshots(history, Profile())
    before = replace(snapshots[-2], histogram=D('-3'))
    weak = replace(snapshots[-1], histogram=D('-2'))
    assert daily_macd_reaction(weak, before, -1, D('10')) == 'REDUCE'
    assert daily_macd_reaction(weak, before, -1, D('-1')) == 'CLEAR'
