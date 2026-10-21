"""Offline recomputation/Position-boundary recovery and independent fill replay.

These checks do not implement a persistent Paper runtime or claim runtime recovery.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from guiyi_quant.newow_futures import Bar, ExecutionBar, Position, Profile, Variant
from guiyi_quant.newow_futures.engine import run_research
from guiyi_quant.newow_futures.features import prepare_features
from guiyi_quant.newow_futures.strategy import evaluate
from guiyi_quant.paper import FeeSchedule
from .test_engine import DAY, T, source


def _strategy_bars():
    base = []
    for index in range(160):
        close = D(100) + D(min(index, 80)) / 4
        op, high, low = close, close + D('.05'), close - D('.05')
        if index == 129:
            high, low = D(130), D(110)
        elif index == 130:
            op, close, high, low = D(118), D(119), D(129), D(109)
        elif index > 130:
            close = op = D(119) + D(index - 130) / 2
            high, low = close + D('.05'), close - D('.05')
        at = T + timedelta(minutes=5 * (index + 1))
        base.append(Bar('rb','RB2701','5m',at,DAY,op,high,low,close,D(100),str(index),at,
                        owner_segment_id='owner',calculation_segment_id='calc'))
    higher = []
    for index in range(26):
        at = T + timedelta(minutes=30 * (index + 1))
        close = D(100 + index * 2)
        higher.append(replace(base[0],frequency='30m',bar_end=at,confirmed_at=at,
                              open=close,high=close+D('.2'),low=close-D('.2'),close=close,
                              source_identity=f'higher-{index}'))
    return {'5m':tuple(base),'30m':tuple(higher)}


def _json_default(value):
    if isinstance(value,D):
        return {'decimal':str(value)}
    if isinstance(value,datetime):
        return {'datetime':value.isoformat()}
    raise TypeError(type(value).__name__)


def _json_hook(value):
    if set(value) == {'decimal'}:
        return D(value['decimal'])
    if set(value) == {'datetime'}:
        return datetime.fromisoformat(value['datetime'])
    return value


def _restore(position):
    return Position(**json.loads(json.dumps(asdict(position),default=_json_default),object_hook=_json_hook))


def _decision_path(profile, bars, *, incremental, restore):
    # This adapter applies only unit fills; all indicator and strategy rules are
    # delegated to production, with no thresholds or signal rules duplicated.
    prepared = None if incremental else prepare_features(bars)
    position, decisions = None, []
    restored_open = False
    for index, base_bar in enumerate(bars['5m']):
        current = prepare_features({frequency:tuple(b for b in rows if b.confirmed_at <= base_bar.confirmed_at)
                                    for frequency,rows in bars.items()}) if incremental else prepared
        base = current.at('5m','RB2701',base_bar.confirmed_at,strict=False,owner=base_bar.owner)
        higher = {'30m':current.at('30m','RB2701',base_bar.confirmed_at,owner=base_bar.owner)}
        decision = evaluate(profile,base,higher,position,tick=D('.1'))
        decisions.append(decision)
        position = decision.position
        if decision.action == 'CLOSE':
            position = None
        elif decision.action == 'ADD':
            position = replace(position,adds=position.adds+1)
        elif decision.action == 'REDUCE':
            position = replace(position,reduced=True)
        if restore and position is not None and (index % 13 == 0 or decision.action == 'ENTER'):
            recovered = _restore(position)
            assert recovered == position and recovered is not position
            position = recovered
            restored_open = True
    return decisions, restored_open


@pytest.mark.parametrize('variant',list(Variant))
def test_all_applicable_variants_batch_incremental_and_position_boundary_restart_match(variant):
    bars = _strategy_bars()
    profile = Profile(variant,'5m')
    batch,_ = _decision_path(profile,bars,incremental=False,restore=False)
    incremental,_ = _decision_path(profile,bars,incremental=True,restore=False)
    resumed,restored_open = _decision_path(profile,bars,incremental=True,restore=True)
    assert any(d.action == 'ENTER' for d in batch), 'parity must exercise a real open position'
    assert restored_open
    assert incremental == batch
    assert resumed == batch


def _account_input(*, close_at_end, direction=1):
    _,executions,ticks = source(count=660,multiplier='1')
    fees = FeeSchedule(open_rate=D('.0001'),open_per_contract=D(2),
                       close_rate=D('.0002'),close_per_contract=D(3),
                       close_today_rate=D('.0003'),close_today_per_contract=D(4),source_id='nonzero-fees')
    result = []
    for index,execution in enumerate(executions,start=1):
        b = execution.bar
        close = D(400) if index == 640 else b.close+D(12) if index == 105 else b.close
        b = replace(b,open=close,close=close,high=close+D(10),low=close-D(10),
                    session_close_at=T+timedelta(hours=20))
        result.append(ExecutionBar(b,replace(execution.facts,fees=fees)))
    bars = {}
    for interval in (5,30):
        grouped = []
        for end in range(interval,len(result)+1,interval):
            group = [e.bar for e in result[end-interval:end]]
            grouped.append(replace(group[-1],frequency=f'{interval}m',open=group[0].open,
                                   high=max(b.high for b in group),low=min(b.low for b in group)))
        bars[f'{interval}m'] = tuple(grouped)
    if close_at_end:
        old = result[-1]
        at = old.bar.bar_end+timedelta(minutes=1)
        result.append(ExecutionBar(replace(old.bar,bar_end=at,confirmed_at=at,open=D(100),
                                          high=D(101),low=D(99),close=D(100)),old.facts))
        # A second minute makes the close intent eligible for strict next-open fill.
        result.append(ExecutionBar(replace(result[-1].bar,bar_end=at+timedelta(minutes=1),
                                          confirmed_at=at+timedelta(minutes=1)),old.facts))
        result.append(ExecutionBar(replace(result[-1].bar,bar_end=at+timedelta(minutes=2),
                                          confirmed_at=at+timedelta(minutes=2)),old.facts))
    if direction == -1:
        def mirror(bar):
            return replace(bar,open=D(600)-bar.open,close=D(600)-bar.close,
                           high=D(600)-bar.low,low=D(600)-bar.high)
        bars = {frequency:tuple(mirror(b) for b in rows) for frequency,rows in bars.items()}
        result = [ExecutionBar(mirror(e.bar),e.facts) for e in result]
    return bars,tuple(result),ticks


def _replay_fills(fills, executions):
    # Independent arithmetic over serialized facts. No Account methods, reported
    # gross/net PnL, or equity values are used to calculate the replay balances.
    cash,fees = D(100000),D(0)
    layers = {}
    by_id = {e.facts.source_id:e.facts for e in executions}
    for fill in fills:
        facts = by_id[fill['facts_id']]
        price,qty = D(fill['price']),fill['qty']
        side = 1 if fill['side'] == 'LONG' else -1
        if fill['action'] in ('OPEN','ADD'):
            fee = qty*(price*facts.multiplier*facts.fees.open_rate+facts.fees.open_per_contract)
            assert fill['layer_id'] not in layers
            layers[fill['layer_id']] = {'qty':qty,'price':price,'side':side,
                                        'day':facts.trading_day,'multiplier':facts.multiplier}
            cash -= fee
        else:
            gross,fee = D(0),D(0)
            assert sum(item['qty'] for item in fill['layers']) == qty
            for item in fill['layers']:
                layer = layers[item['layer_id']]
                taken = item['qty']
                assert 0 < taken <= layer['qty']
                gross += (price-layer['price'])*layer['side']*layer['multiplier']*taken
                today = layer['day'] == facts.trading_day
                rate = facts.fees.close_today_rate if today else facts.fees.close_rate
                fixed = facts.fees.close_today_per_contract if today else facts.fees.close_per_contract
                fee += taken*(price*facts.multiplier*rate+fixed)
                layer['qty'] -= taken
            cash += gross-fee
            assert D(fill['gross_pnl']) == gross
        assert D(fill['fee']) == fee
        fees += fee
    mark = executions[-1].bar.close
    signed_qty = sum(layer['qty']*layer['side'] for layer in layers.values())
    equity = cash+sum(((mark-layer['price'])*layer['side']*layer['multiplier']*layer['qty']
                       for layer in layers.values()),D(0))
    return cash,fees,signed_qty,equity


@pytest.mark.parametrize('direction',[-1,1])
@pytest.mark.parametrize('close_at_end',[False,True])
def test_real_engine_fills_independently_replay_cash_fees_layers_and_marked_equity(close_at_end,direction):
    bars,executions,ticks = _account_input(close_at_end=close_at_end,direction=direction)
    result = run_research(bars,executions,profile=Profile(Variant.TREND,'5m'),since=DAY,through=DAY,ticks=ticks)
    actions = [f['action'] for f in result['fills']]
    assert {'OPEN','ADD','REDUCE'} <= set(actions)
    assert {f['side'] for f in result['fills']} == {'LONG' if direction == 1 else 'SHORT'}
    assert ('CLOSE' in actions) == close_at_end
    cash,fees,qty,equity = _replay_fills(result['fills'],executions)
    summary = result['summary']
    assert cash == D(summary['ending_cash'])
    assert fees > 0 and fees == D(summary['total_fees'])
    assert qty == summary['ending_qty']
    assert equity == D(summary['final_equity'])
    assert (equity-D(100000))/D(100000)*100 == D(summary['account_return_pct'])
    assert (qty == 0) == close_at_end
