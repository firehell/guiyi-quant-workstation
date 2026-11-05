"""Bounded outputs executed from SHA-bound public JS, independent of Python."""
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from guiyi_quant.newow.oscillation_trueup import calculate_oscillation_series, SOURCE_SHA256
from guiyi_quant.newow.breakout_shapes import compute_breakout_shapes, SOURCE_SHA256 as SHAPE_SHA
from .fixtures import _bars

ORACLE = json.loads((Path(__file__).parent / 'fixtures/trueup-kernel111-detail3449.json').read_text())


def bars_for(case):
    base = _bars([Decimal(str(r['close'])) for r in case['bars']])
    return tuple(replace(b, **{k: Decimal(str(r[k])) for k in ('open', 'high', 'low')}, volume=r['volume']) for b, r in zip(base, case['bars'], strict=True))


@pytest.mark.parametrize('case', ORACLE['cases'], ids=lambda c: c['name'])
def test_kernel_and_display_against_original_js(case):
    assert SOURCE_SHA256 == ORACLE['kernel_sha256']
    assert SHAPE_SHA == ORACLE['detail_sha256']
    bars = bars_for(case)
    steps = calculate_oscillation_series(bars)
    actual = [dict(index=i, type=s.action.value.lower(), price=float(s.price), ref=float(s.reference_price), true_up=s.true_up, score=s.score) for i, step in enumerate(steps) for s in step.signals]
    assert actual == case['events']
    shapes = compute_breakout_shapes(bars)
    assert len(shapes) == len(case['shapes'])
    for a, e in zip(shapes, case['shapes'], strict=True):
        assert (a.kind, a.index, a.occur, a.side, a.regime, a.volume_ok, a.doubt) == (e['kind'], e['i'], e['occur'], e['side'], e['regime'], e['volOk'], e['doubt'])
        assert a.level == pytest.approx(e['level'], abs=1e-12)
        assert a.buffer == pytest.approx(e['B'], abs=1e-12)
        assert a.volume_ratio == pytest.approx(e['volRatio'], abs=1e-12) if e['volRatio'] is not None else a.volume_ratio is None
    for cutoff in range(1, len(bars)+1):
        assert calculate_oscillation_series(bars[:cutoff]) == steps[:cutoff]
