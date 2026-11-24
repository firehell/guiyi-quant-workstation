from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_jm2601_structure import DAY_START, FIVE, US, peer_observation, point, structure_trace


def bar(index, high, low, close, *, contract="JM2601"):
    start = DAY_START + index * FIVE
    return Bar(contract, start + FIVE, Decimal(close), Decimal(high), Decimal(low), Decimal(close), start=start)


def path():
    return [bar(i, *ohlc) for i, ohlc in enumerate([
        (107, 100, 103), (105, 98, 102), (107, 100, 104), (111, 102, 109),
        (107, 100, 105), (106, 99, 102), (110, 101, 106), (113, 105, 112),
    ])]


def test_first_breakout_after_pivots_are_known_and_strict_cutoff():
    bars = path()
    last = bars[-1].end
    full = structure_trace(bars, as_of=last + 2 * US)
    assert len(full["breakouts"]) == 1
    event = full["breakouts"][0]
    assert event["timing"] == "PREVIOUSLY_CONFIRMED_PIVOTS"
    assert [p["price"] for p in event["pivots"]] == [Decimal(98), Decimal(111), Decimal(99)]
    assert event["higher_second_low"] and event["available_at"] == last + US
    assert event["pivots"][-1]["known_at"] == bars[-2].end + US
    cutoff = bars[-1].end + US
    assert structure_trace(bars, as_of=cutoff) == structure_trace(bars[:-1], as_of=cutoff)
    assert structure_trace(bars, as_of=cutoff)["breakouts"] == []


def test_joint_completed_bar_is_separate_from_sequential_confirmation():
    bars = path()
    bars[6] = bar(6, 114, 101, 112)
    cut = bars[6].end + US
    assert structure_trace(bars, as_of=cut)["breakouts"] == []
    events = structure_trace(bars, as_of=bars[-1].end + 2 * US)["breakouts"]
    assert len(events) == 1
    joint = events[0]
    assert joint["timing"] == "JOINT_COMPLETED_BAR"
    assert joint["available_at"] == joint["pivots"][-1]["known_at"] == cut


def test_same_bar_floor_break_or_session_gap_does_not_fire():
    bars = path()
    broken = bars[:-1] + [replace(bars[-1], low=Decimal(98))]
    assert structure_trace(broken, as_of=broken[-1].end + 2 * US)["breakouts"] == []
    gap = timedelta(minutes=15)
    delayed = bars[:-1] + [replace(bars[-1], start=bars[-1].start + gap, end=bars[-1].end + gap)]
    assert structure_trace(delayed, as_of=delayed[-1].end + 2 * US)["breakouts"] == []


def test_outside_or_equal_neighbors_are_not_unique_pivots():
    left, right = bar(0, 105, 99, 101), bar(2, 106, 98, 103)
    outside = bar(1, 107, 97, 100)
    tied = bar(1, 106, 98, 100)
    assert point(left, outside, right) is None
    assert point(left, tied, right) is None


def test_peer_requires_exact_endpoint_and_day_open_from_prefix():
    bars = path()
    end = bars[6].end
    assert peer_observation(bars, end + timedelta(minutes=1)) is None
    assert peer_observation(bars, end) == peer_observation(bars[:7], end)
    assert peer_observation(bars, end)["day_open"] == bars[0].open


def test_prior_session_context_is_not_morning_context():
    morning = path()[:2]
    overnight = [bar(i, 120 - i, 95 + i, 106) for i in range(7)]
    overnight = [replace(b, start=b.start - timedelta(hours=12), end=b.end - timedelta(hours=12))
                 for b in overnight]
    result = peer_observation(overnight + morning, morning[-1].end)
    assert result["context"] is not None and result["morning_context"] is None
