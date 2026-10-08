import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from guiyi_quant.newow.oscillation_attack import calculate_oscillation_attack


def test_public_v3379_golden_and_prefix_invariance():
    fixture = json.loads(Path(__file__).with_name('oscillation_attack_golden.json').read_text())
    bars = tuple(SimpleNamespace(**{k: Decimal(v) for k,v in b.items()}) for b in fixture['bars'])
    result = calculate_oscillation_attack(bars)
    expected = fixture['expected']
    assert [int(r['buy']) for r in result] == expected['series']['buyF']
    assert [int(r['sell']) for r in result] == expected['series']['sellF']
    assert [int(r['j_warning']) for r in result] == expected['series']['jWarn']
    assert abs(result[-1]['zlgj'] - Decimal(str(expected['zlgj']))) < Decimal('1e-9')
    assert abs(result[-1]['j'] - Decimal(str(expected['j']))) < Decimal('1e-9')
    assert any(r['buy'] for r in result) and any(r['sell'] for r in result) and any(r['j_warning'] for r in result)
    for n in range(10, len(bars)):
        assert calculate_oscillation_attack(bars[:n]) == result[:n]
    assert calculate_oscillation_attack(bars[:9]) == ()


def test_flat_prices_do_not_divide_by_zero_or_generate_hints():
    bars = tuple(SimpleNamespace(open=Decimal(100), high=Decimal(100),low=Decimal(100),close=Decimal(100)) for _ in range(20))
    result = calculate_oscillation_attack(bars)
    assert all(r['zlgj']==0 and r['j']==50 and not r['buy'] and not r['sell'] and not r['j_warning'] for r in result)


def test_overlapping_owner_warmup_never_receives_other_owner_hints():
    from dataclasses import dataclass
    from datetime import UTC, datetime, timedelta
    from guiyi_quant.newow.product_adapters import build_product_identity
    from app.market_data.newow.oscillation_attack_display import with_attack_hints
    @dataclass
    class Frame:
        bar: object
        hints: tuple = ()
    @dataclass
    class Replay:
        identity: object
        frames: tuple
        hints: tuple = ()
    fixture = json.loads(Path(__file__).with_name('oscillation_attack_golden.json').read_text())
    frames = []
    for contract, eligible in [('JM2601', True), ('JM2605', False)]:
        for i, row in enumerate(fixture['bars']):
            at = datetime(2026,1,1,tzinfo=UTC)+timedelta(hours=i)
            bar = SimpleNamespace(**{k:Decimal(v) for k,v in row.items()},physical_contract=contract,
                segment_id=contract, observation_eligible=eligible,bar_end=at,trading_day=at.date())
            frames.append(Frame(SimpleNamespace(bar=bar,calculation_segment_id=contract)))
    replay = Replay(build_product_identity('jm','oscillation','60m'),tuple(frames))
    result = with_attack_hints(replay)
    assert result.hints and all(h.physical_contract=='JM2601' for h in result.hints)
    assert all(not f.hints for f in result.frames[180:])
    assert all(h.physical_contract==f.bar.bar.physical_contract for f in result.frames for h in f.hints)
    assert not replay.hints and all(not f.hints for f in replay.frames)
