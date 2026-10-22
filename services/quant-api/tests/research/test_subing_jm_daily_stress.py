"""Stress scenarios must change execution/risk, never ticks, stops or source facts."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from guiyi_quant.new_subing import ExecutionFacts, StrategyBar
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_jm_daily import DailyModel, Event
from scripts.research.subing_jm_daily_stress import make_model, cost_event, run_account, analyze

T = datetime(2025, 1, 2, 7, tzinfo=UTC)


def event(kind='1m', at=T, price='1000', ema=None, cross=0, fees=None):
    p = D(price)
    b = StrategyBar('jm', 'JM2505', kind, at, at.date(), p, p, p, p, D(10), None,
        f'{kind}:{at}:{price}', at, session_open_at=at-timedelta(hours=4), session_close_at=at+timedelta(hours=4))
    f = ExecutionFacts('JM2505', at.date(), D('.5'), D(60), D(1000), D('.2'), D('.3'),
        D(2000), D(100), fees or FeeSchedule(D(0), D(1), D(0), D(2), D(0), D(3), 'fees'), 'facts')
    return Event(kind, b, f if kind == '1m' else None, D(ema) if ema else None, cross)


def events():
    return (event(), event('1d', ema='990', cross=1),
        event(at=T+timedelta(minutes=2)),
        event('1d', T+timedelta(minutes=15), '980', '990', -1),
        event(at=T+timedelta(minutes=17), price='980'))


def test_baseline_keeps_all_phase_b_model_outputs():
    baseline = DailyModel()
    for e in events():
        baseline.apply(e)
    observed = run_account(events(), 'baseline')
    for key, value in baseline.result().items():
        assert observed[key] == value
    assert observed['risk_checks'][0]['estimated_risk'] is not None


def test_double_commission_preserves_tick_stop_and_source_objects():
    original = events()
    changed = cost_event(original[0], 'double_commission')
    assert changed.facts.tick_size == original[0].facts.tick_size
    assert changed.facts.fees.open_per_contract == D(2)
    assert original[0].facts.fees.open_per_contract == D(1)
    base, stress = run_account(original, 'baseline'), run_account(original, 'double_commission')
    assert [D(f['price']) for f in base['fills']] == [D(f['price']) for f in stress['fills']]
    assert D(stress['summary']['total_fees']) == D(base['summary']['total_fees'])*2
    assert D(stress['summary']['cash']) == D(base['summary']['cash'])-D(base['summary']['total_fees'])


def test_double_slippage_changes_buy_sell_prices_but_not_grid_or_protective_line():
    base, stress = run_account(events(), 'baseline'), run_account(events(), 'double_slippage')
    assert D(stress['fills'][0]['price']) == D(base['fills'][0]['price'])+D('.5')
    assert D(stress['fills'][1]['price']) == D(base['fills'][1]['price'])-D('.5')
    assert base['risk_checks'][0]['stop'] == stress['risk_checks'][0]['stop']
    assert all(f['tick_size'] == '0.5' for f in stress['fills'])


def test_double_slippage_reruns_admission_instead_of_subtracting_final_cost():
    stream = (event(), event('1d', ema='980', cross=1), event(at=T+timedelta(minutes=2)))
    assert len(run_account(stream, 'baseline')['fills']) == 1
    stressed = run_account(stream, 'double_slippage')
    assert not stressed['fills']
    assert stressed['risk_checks'][0]['reason'] == 'TRADE_RISK_EXCEEDED'


def test_double_fees_can_change_entry_eligibility():
    fees = FeeSchedule(D(0), D(8), D(0), D(10), D(0), D(10), 'boundary-fees')
    stream = (event(fees=fees), event('1d', ema='980', cross=1),
              event(at=T+timedelta(minutes=2), fees=fees))
    assert len(run_account(stream, 'baseline')['fills']) == 1
    assert not run_account(stream, 'double_commission')['fills']


@pytest.mark.parametrize('scenario', ['baseline', 'double_commission', 'double_slippage'])
def test_scenario_checkpoint_restores_the_same_cost_policy(scenario):
    model = make_model(scenario)
    stream = events()
    for e in stream[:2]:
        model.apply(cost_event(e, scenario))
    packet = model.checkpoint()
    restored = type(model).restore(packet)
    for e in stream[2:]:
        for m in (model, restored):
            m.apply(cost_event(e, scenario))
    assert model.result() == restored.result()
    if scenario != 'baseline':
        with pytest.raises(ValueError):
            DailyModel.restore(packet)
        other = 'double_slippage' if scenario == 'double_commission' else 'double_commission'
        with pytest.raises(ValueError):
            type(make_model(other)).restore(packet)


def test_risk_trace_accounts_for_available_equity_and_exact_costs():
    result = run_account(events(), 'baseline')
    check = result['risk_checks'][0]
    assert D(check['risk_budget']) == D('2000')
    assert D(check['estimated_risk']) == D('1350')+D('1')+D('3')+D('30')


def test_stressed_model_preserves_rollover_interruption_even_if_flat():
    e = event(at=T+timedelta(days=1))
    e = replace(e, bar=replace(e.bar, physical_contract='JM2509', source_identity='new-owner'),
                facts=replace(e.facts, physical_contract='JM2509'))
    for scenario in ('baseline', 'double_commission', 'double_slippage'):
        result = run_account((event(), e), scenario)
        assert result['summary']['status'] == 'ROLLOVER_INTERRUPTED'
        assert result['summary']['net_return_pct'] is None


def test_unknown_cost_profile_is_rejected():
    with pytest.raises(ValueError):
        make_model('optimistic')


def test_fee_transformation_is_independent_of_ambient_decimal_precision():
    from decimal import localcontext
    fees = FeeSchedule(D('0.000123456789'), D(0), D('0.0001'), D(0), D('0.0002'), D(0), 'precise-fees')
    source = event(fees=fees)
    with localcontext() as context:
        context.prec = 4
        changed = cost_event(source, 'double_commission')
    assert changed.facts.fees.open_rate == D('0.000246913578')


def test_signal_and_fill_rejections_have_separate_denominators():
    result = run_account(events(), 'baseline')
    result['risk_checks'].append({**result['risk_checks'][0], 'stage': 'FILL',
                                  'reason': 'TRADE_RISK_EXCEEDED'})
    value = analyze(result)
    assert value['signal_admission_checks'] == 1 and value['signal_rejections'] == 0
    assert value['fill_admission_checks'] == 2 and value['fill_rejections'] == 1
