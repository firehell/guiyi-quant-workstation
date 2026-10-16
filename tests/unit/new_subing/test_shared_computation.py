"""Parity against actual pre-extraction output from 986a62f22712425221b7aeb24d2761bf04f09020.

The checked-in golden was recorded before either strategy implementation changed.
Synthetic fixtures are engineering evidence, not market or original-author cases.
"""
from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest

from guiyi_quant.new_subing import ExecutionBar
from tests.unit.new_subing.test_core import T0, bar, facts, scenario_bars

GOLDEN = Path(__file__).with_name('shared_computation_baseline.json')
DAY = date(2025, 1, 2)


def normalized(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def digest(value):
    return sha256(repr(value).encode()).hexdigest()


def boundary_bars():
    bars = []
    # Flat warm-up, oscillation/noise, rising/falling breakouts, volume and roll reset.
    for i in range(112):
        j = i % 56
        price = (Decimal('100.000000001') if j < 24 else
                 Decimal('100') + Decimal(j % 7 - 3) * Decimal('.123456789') if j < 40 else
                 Decimal('100') + Decimal(j - 40) * Decimal('.375000001'))
        b = bar(T0 + timedelta(minutes=1), '5m', price,
                contract='RB2505' if i < 56 else 'RB2510')
        bars.append(replace(b, bar_end=T0+timedelta(minutes=5*(i+1)),
                            confirmed_at=T0+timedelta(minutes=5*(i+1)),
                            source_identity=f'boundary-{i}',
                            high=price+Decimal('.2'), low=price-Decimal('.3'),
                            volume=Decimal('0') if j < 21 else Decimal('400') if j % 5 == 0 else Decimal('100'),
                            open_interest=None if j % 3 == 0 else Decimal('1234.56789'),
                            session_close_at=None, observation_eligible=j >= 10))
    return bars


def pivot_snapshots(signals, profile):
    snapshots = signals.build_snapshots(boundary_bars()[:18], profile)
    # Freeze scanner behavior with nonempty long/short pivot pairs and a roll boundary.
    for i, snapshot in enumerate(snapshots):
        high = Decimal(120 + (i // 4) * 2) if i % 4 == 2 else Decimal('105')
        low = Decimal(80 - (i // 4) * 2) if i % 4 == 0 else Decimal('95')
        snapshots[i] = replace(snapshot, dif=Decimal(10 - i) if i % 4 == 2 else Decimal(i),
                               bar=replace(snapshot.bar, high=high, low=low,
                                           physical_contract='RB2505' if i < 11 else 'RB2510'))
    return snapshots


def validation_cases():
    b = bar()
    b2 = bar(T0 + timedelta(minutes=2))
    e = ExecutionBar(b, facts())
    empty = {'1m': [], '5m': [], '15m': [], '1d': []}
    def history(**changes):
        return {**empty, **changes}
    delayed = replace(b, confirmed_at=b2.bar_end+timedelta(minutes=2))
    delayed2 = replace(b2, confirmed_at=b2.bar_end+timedelta(minutes=1))
    cases = [
        ('valid', history(**{'1m': [b]}), [e], 'baseline', DAY, DAY),
        ('scenario', empty, [], 'unknown', DAY, DAY),
        ('window_type', empty, [], 'baseline', T0, DAY),
        ('window_order', empty, [], 'baseline', DAY+timedelta(days=1), DAY),
        ('input_type', [], [], 'baseline', DAY, DAY),
        ('execution_type', empty, iter(()), 'baseline', DAY, DAY),
        ('missing', {}, [], 'baseline', DAY, DAY),
        ('frequency', history(**{'60m': []}), [], 'baseline', DAY, DAY),
        ('history_type', history(**{'1m': iter(())}), [], 'baseline', DAY, DAY),
        ('bar_type', history(**{'1m': [object()]}), [], 'baseline', DAY, DAY),
        ('frequency_mismatch', history(**{'5m': [b]}), [], 'baseline', DAY, DAY),
        ('monthly', history(**{'1m': [replace(b, physical_contract='RB.main')]}), [], 'baseline', DAY, DAY),
        ('duplicate', history(**{'1m': [b, b]}), [], 'baseline', DAY, DAY),
        ('unordered', history(**{'1m': [b2, b]}), [], 'baseline', DAY, DAY),
        ('confirmation', history(**{'1m': [delayed, delayed2]}), [], 'baseline', DAY, DAY),
        ('products', history(**{'1m': [b, replace(b2, product='AL')]}), [], 'baseline', DAY, DAY),
        ('execution_product', history(**{'1m': [b]}), [object()], 'baseline', DAY, DAY),
        ('execution_difference', history(**{'1m': [b2]}), [e], 'baseline', DAY, DAY),
        ('eligibility', history(**{'1m': [replace(b, observation_eligible=False)]}),
         [replace(e, bar=replace(b, observation_eligible=False))], 'baseline', DAY, DAY),
        ('outside_window', history(**{'1m': [b]}), [e], 'baseline', DAY+timedelta(days=1), DAY+timedelta(days=1)),
        ('execution_order', history(**{'1m': [b, b2]}), [ExecutionBar(b2, facts()), e], 'baseline', DAY, DAY),
        ('execution_confirmation', history(**{'1m': [delayed], '5m': []}),
         [ExecutionBar(delayed, facts()), ExecutionBar(b2, facts())], 'baseline', DAY, DAY),
    ]
    # Distinct contracts permit independent history confirmations, but execution must remain ordered.
    other = replace(b2, physical_contract='RB2510')
    cases[-1] = ('execution_confirmation', history(**{'1m': [delayed, other]}),
                 [ExecutionBar(delayed, facts()), ExecutionBar(other, replace(facts(), physical_contract='RB2510'))],
                 'baseline', DAY, DAY)
    return cases


def validation_outcomes(engine):
    outcomes = {}
    for name, *args in validation_cases():
        try:
            engine._validate_inputs(*args)
        except Exception as error:
            outcomes[name] = [type(error).__name__, str(error)]
        else:
            outcomes[name] = None
    return outcomes


def observed(version):
    strategy = importlib.import_module(f'guiyi_quant.{version}')
    signals = importlib.import_module(f'guiyi_quant.{version}.signals')
    engine = importlib.import_module(f'guiyi_quant.{version}.engine')
    profile = strategy.Profile()
    bars = boundary_bars()
    snapshots = signals.build_snapshots(bars, profile)
    pivots = pivot_snapshots(signals, profile)
    research = {}
    for side, stopped in ((1, False), (-1, False), (1, True)):
        histories, execution = scenario_bars(side=side, stopped=stopped)
        for scenario in ('baseline', 'double_commission', 'double_slippage'):
            key = f'{side}/{stopped}/{scenario}'
            result = strategy.run_research(histories, execution, scenario=scenario, since=DAY, through=DAY)
            research[key] = {'output_hash': digest(result), 'input_hash': digest(histories),
                             'execution_hash': digest(execution)}
    prepared = None
    if version == 'new_subing_v2':
        histories, _ = scenario_bars()
        p = strategy.prepare_research(histories)
        prepared = {'input_hash': p.input_hash, 'snapshot_hash': p.snapshot_hash}
    return normalized({'snapshots': [asdict(s) for s in snapshots],
                       'divergences': {str(side): signals.divergence_events(pivots, side, profile)
                                       for side in (-1, 1)},
                       'validation': validation_outcomes(engine), 'research': research,
                       'prepared': prepared})


@pytest.mark.parametrize('version', ['new_subing', 'new_subing_v2'])
def test_actual_baseline_outputs_and_hashes(version):
    assert observed(version) == json.loads(GOLDEN.read_text())[version]


@pytest.mark.parametrize('version', ['new_subing', 'new_subing_v2'])
def test_every_prefix_matches_frozen_values_and_roll_warmup(version):
    strategy = importlib.import_module(f'guiyi_quant.{version}')
    signals = importlib.import_module(f'guiyi_quant.{version}.signals')
    expected = json.loads(GOLDEN.read_text())[version]
    bars = boundary_bars()
    profile = strategy.Profile()
    for length in range(len(bars)+1):
        actual = signals.build_snapshots(bars[:length], profile)
        assert normalized([asdict(s) for s in actual]) == expected['snapshots'][:length]
        assert actual == signals.build_snapshots(bars[:length])
    assert expected['snapshots'][55]['ma'] is not None
    assert expected['snapshots'][56]['ma'] is None
    assert expected['snapshots'][75]['ma'] is None
    assert expected['snapshots'][76]['ma'] is not None
    pivots = pivot_snapshots(signals, profile)
    for side in (-1, 1):
        assert any(expected['divergences'][str(side)])
        assert signals.divergence_events(pivots, side) == signals.divergence_events(pivots, side, profile)
        for length in range(len(pivots)+1):
            assert normalized(signals.divergence_events(pivots[:length], side, profile)) == expected['divergences'][str(side)][:length]
    for snapshot in signals.build_snapshots(bars, profile):
        for name in ('ma', 'boll_upper', 'boll_lower', 'atr', 'dif', 'dea', 'histogram', 'breakout_level'):
            assert getattr(snapshot, name) is None or type(getattr(snapshot, name)) is Decimal


def test_version_profiles_and_prepared_hashes_remain_independent():
    import guiyi_quant.new_subing as v1
    import guiyi_quant.new_subing_v2 as v2
    from guiyi_quant.new_subing_common import COMPUTATION_VERSION, Snapshot
    from guiyi_quant.new_subing.signals import Snapshot as V1Snapshot
    from guiyi_quant.new_subing_v2.signals import Snapshot as V2Snapshot
    assert COMPUTATION_VERSION == 'new_subing_common_v1'
    assert V1Snapshot is V2Snapshot is Snapshot
    from guiyi_quant.new_subing.signals import build_snapshots as v1_build
    from guiyi_quant.new_subing_v2.signals import build_snapshots as v2_build
    assert v1.Profile is not v2.Profile
    assert v1.Profile().formula_version != v2.Profile().formula_version
    with localcontext() as context:
        context.prec = 17
        assert normalized([asdict(s) for s in v1_build(boundary_bars())]) == normalized(
            [asdict(s) for s in v2_build(boundary_bars())])
    histories, execution = scenario_bars()
    prepared = v2.prepare_research(histories)
    assert v2.run_research(histories, execution, since=DAY, through=DAY, prepared=prepared) == (
        v2.run_research(histories, execution, since=DAY, through=DAY))
    assert v2_build(boundary_bars(), v2.Profile(initial_cash=Decimal('1000000'))) == (
        v2_build(boundary_bars()))
    with pytest.raises(ValueError, match='prepared research input/formula mismatch'):
        v2.run_research(histories, execution, since=DAY, through=DAY,
                        prepared=replace(prepared, snapshot_hash='0'*64))
