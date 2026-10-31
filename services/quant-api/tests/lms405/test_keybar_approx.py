from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D, localcontext

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify, observe_next, replay, VERSION


def bar(i, o='10', h='14', low='8', c='12', contract='JM2509'):
    start = datetime(2025, 7, 22, 1, tzinfo=UTC) + timedelta(minutes=5 * i)
    return Bar(contract, start + timedelta(minutes=5), *map(D, (o, h, low, c)), start=start)


def test_ibar_strict_bounds_and_only_immediate_parent():
    mother = bar(0, h='20', low='5')
    inside = bar(1)
    assert classify(mother, inside).ibar is True
    assert classify(mother, replace(inside, high=D('20'))).ibar is False
    assert classify(mother, replace(inside, low=D('5'))).ibar is False
    assert classify(inside, bar(2, h='15')).ibar is False
    assert classify(None, mother).ibar is None


@pytest.mark.parametrize('o,h,low,c,expected', [
    ('10', '11', '7', '11', 'LONG'),  # exactly 3x, no upper wick
    ('11', '12', '7', '10', 'LONG'),  # opposite candle colour; other wick == body
    ('10', '14', '9', '11', 'SHORT'),
    ('11', '14', '10', '10', 'SHORT'),
    ('10', '12.01', '7', '11', None),  # other wick > body
    ('10', '11', '7.01', '11', None),  # long wick just below 3x
    ('10', '14', '6', '10', None),  # doji
    ('10', '10', '10', '10', None),  # flat
    ('10', '15', '5', '11', None),  # both long wicks, no qualified pin
])
def test_pinbar_boundaries_and_colour(o, h, low, c, expected):
    f = classify(None, bar(0, o, h, low, c))
    assert f.pinbar == expected
    assert f.confirmed_at == f.bar_end
    assert f.rule_version == VERSION == 'lms-keybar-approx-v1'


def test_metrics_are_decimal_and_independent_of_ambient_precision():
    x = bar(0, '1000000000000000000000000000000.1',
            '1000000000000000000000000000000.2',
            '999999999999999999999999999999.8',
            '1000000000000000000000000000000.2')
    with localcontext() as ctx:
        ctx.prec = 2
        f = classify(None, x)
    assert f.body == D('.1') and f.lower_wick == D('.3')
    assert f.pinbar == 'LONG'


@pytest.mark.parametrize('close,up,down', [
    ('14.5', True, False), ('7.5', False, True), ('14', False, False),
    ('8', False, False), ('11', False, False),
])
def test_next_close_observation_has_its_own_availability(close, up, down):
    signal = bar(0)
    f = classify(bar(-1, h='20', low='5'), signal)
    nxt = bar(1, '11', '16', '6', close)
    obs = observe_next(f, signal, nxt)
    assert obs.close_above_high is up and obs.close_below_low is down
    assert obs.observed_at == nxt.end and obs.signal_bar_end == signal.end
    assert obs.observed_at > f.confirmed_at
    # Both intrabar extremes crossed: this is not intrabar ordering or a fill.
    assert f == classify(bar(-1, h='20', low='5'), signal)


def test_prefix_and_incremental_parity_no_future_fields_in_frames():
    xs = [bar(0, h='20', low='5'), bar(1), bar(2, '10', '11', '7', '11'), bar(3)]
    frames, observations = replay(xs)
    for n in range(1, len(xs) + 1):
        fs, os = replay(xs[:n])
        assert fs == frames[:n]
        assert os == [o for o in observations if o.observed_at <= xs[n-1].end]
    streamed, checks = [], []
    for i, x in enumerate(xs):
        f = classify(xs[i-1] if i else None, x)
        if i and streamed[-1].has_pattern:
            checks.append(observe_next(streamed[-1], xs[i-1], x))
        streamed.append(f)
    assert (streamed, checks) == (frames, observations)
    assert replay([]) == ([], [])


@pytest.mark.parametrize('change', [
    {'contract': 'SH2701'}, {'start': None},
    {'start': datetime(2025, 7, 22, 1, 1, tzinfo=UTC)},
])
def test_pair_rejects_contract_and_bad_intervals(change):
    with pytest.raises(ValueError):
        classify(bar(0), replace(bar(1), **change))


def test_rejects_reversed_overlapping_and_uncompleted_bars():
    with pytest.raises(ValueError):
        classify(bar(1), bar(0))
    with pytest.raises(ValueError):
        classify(bar(0), bar(0))
    with pytest.raises(ValueError):
        classify(None, replace(bar(0), completed=False))


def test_frame_identity_must_match_signal_bar_and_reject_non_pattern():
    signal = bar(0, '10', '11', '7', '11')
    frame = classify(None, signal)
    with pytest.raises(ValueError):
        observe_next(frame, replace(signal, close=D('10')), bar(1))
    with pytest.raises(ValueError):
        observe_next(classify(None, bar(0)), bar(0), bar(1))
