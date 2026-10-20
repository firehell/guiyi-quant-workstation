from dataclasses import replace
from datetime import timedelta
from decimal import Inexact, ROUND_DOWN, Rounded, localcontext

from guiyi_quant.newow_futures import Decision, Profile, Variant
from guiyi_quant.newow_futures.reference import run_reference
from .test_engine import T, source


def test_reference_return_is_context_invariant_and_preserves_callers_context():
    bars, executions, ticks = source(count=199)
    minutes = tuple(x.bar for x in executions)
    profile = Profile(Variant.TREND, '5m')
    expected = run_reference(profile, bars, minutes, ticks=ticks)
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = context.traps[Rounded] = True
        actual = run_reference(profile, bars, minutes, ticks=ticks)
        assert actual == expected
        assert context.prec == 7 and context.traps[Inexact]


def test_eligible_overnight_position_can_reduce_at_day_end(monkeypatch):
    import guiyi_quant.newow_futures.reference as module
    bars, executions, ticks = source(count=115)
    end = T + timedelta(minutes=117)
    bars = {'5m': tuple(replace(b, session_close_at=end) for b in bars['5m'])}
    minutes = tuple(replace(x.bar, session_close_at=end) for x in executions)
    original = module.evaluate

    def scripted(profile, base, higher, position, **kwargs):
        if base.bar.bar_end == T + timedelta(minutes=110) and position:
            return Decision('ADD', 1, 'UPGRADE_ADD', replace(position, holding_frequency='60m',
                            upgrades=1, earned_r=True, overnight_eligible=True), True)
        if base.bar.bar_end == T + timedelta(minutes=115) and position:
            return Decision('REDUCE', 1, 'BASE_TREND_REDUCTION', position)
        return original(profile, base, higher, position, **kwargs)

    monkeypatch.setattr(module, 'evaluate', scripted)
    result = run_reference(Profile(Variant.TREND, '5m'), bars, minutes, ticks=ticks)
    assert [a['action'] for a in result['actions']] == ['OPEN_LONG', 'ADD', 'REDUCE']


def test_warmup_is_not_reported_as_valid_flat_zero_return():
    bars, executions, ticks = source(count=100)
    result = run_reference(Profile(Variant.MAIN_RISE, '5m'), bars, tuple(x.bar for x in executions), ticks=ticks)
    assert result['summary']['status'] == 'DATA_INSUFFICIENT'
    assert result['summary']['reference_return_pct'] is None
    assert result['snapshot']['side'] == 'UNAVAILABLE'


def test_real_engine_reference_open_quantity_is_independent_of_account_capital():
    from .test_engine import run

    bars, executions, ticks = source(multiplier="100000")
    result = run(bars, executions, ticks)
    assert result["fills"] == []
    trade = result["reference"]["trades"][-1]
    assert trade["status"] == "OPEN" and trade["qty"] == 1


def test_real_engine_reference_closed_trade_keeps_its_opened_unit_quantity():
    from decimal import Decimal as D
    from guiyi_quant.newow_futures import ExecutionBar
    from .test_engine import run

    bars, executions, ticks = source()
    old = executions[-1]
    at = old.bar.bar_end + timedelta(minutes=1)
    close_bar = replace(old.bar, bar_end=at, confirmed_at=at, open=D(100), high=D(101),
                        low=D(99), close=D(100), source_identity="protective-close")
    result = run(bars, (*executions, ExecutionBar(close_bar, old.facts)), ticks)
    trade = result["reference"]["trades"][-1]
    assert trade["status"] == "CLOSED" and trade["qty"] == 1


def test_real_engine_interrupted_reference_trade_preserves_old_contract_units():
    from decimal import Decimal as D
    from guiyi_quant.newow_futures import ExecutionBar
    from .test_engine import run

    bars, executions, ticks = source()
    old = executions[-1]
    at = old.bar.bar_end + timedelta(minutes=1)
    new_bar = replace(old.bar, physical_contract="RB2705", owner_segment_id="new",bar_end=at,
                      confirmed_at=at,open=D(5000),high=D(5001),low=D(4999),close=D(5000))
    result = run(bars,(*executions,ExecutionBar(new_bar,replace(old.facts,physical_contract="RB2705"))),ticks)
    trade = result["reference"]["trades"][-1]
    assert trade["status"] == "ROLLOVER_INTERRUPTED" and trade["qty"] == 1
    assert trade["physical_contract"] == "RB2701" and trade["exit_reference_price"] is None


def test_real_reference_qty_counts_opened_unit_layers_after_add_and_reduction():
    from decimal import Decimal as D

    _, executions, ticks = source(count=640)
    minutes = []
    for index, execution in enumerate(executions, start=1):
        b = execution.bar
        c = D(400) if index == 640 else b.close + D(12) if index == 105 else b.close
        minutes.append(replace(b,open=c,close=c,high=c+D(10),low=c-D(10),session_close_at=T+timedelta(hours=20)))
    bars = {}
    for interval in (5,30):
        grouped = []
        for end in range(interval,len(minutes)+1,interval):
            group = minutes[end-interval:end]
            grouped.append(replace(group[-1],frequency=f"{interval}m",open=group[0].open,
                                   high=max(b.high for b in group),low=min(b.low for b in group)))
        bars[f"{interval}m"] = tuple(grouped)
    result = run_reference(Profile(Variant.TREND,"5m"),bars,tuple(minutes),ticks=ticks)
    assert [a["action"] for a in result["actions"]] == ["OPEN_LONG","ADD","REDUCE"]
    trade = result["trades"][-1]
    assert trade["status"] == "OPEN" and trade["qty"] == 2
