from decimal import Decimal

from guiyi_quant.lms405 import Bar, Position
from lms405_protection_route_comparison import candidate_clocks, replay_case, wick_beyond
from lms405_right_side_study import ONE, US, at


def test_contact_confirmation_and_permission_remain_distinct_clocks():
    start = at("2026-10-22T21:00")
    prices = ((825, 828, 823, 826), (828, 833, 825, 828), (828, 832, 827, 831),
              (831, 834, 830, 833), (833, 834, 829, 831), (831, 835, 829, 834))
    bars = [Bar("FG2701", start + i * ONE, *map(Decimal, ohlc), start=start + (i - 1) * ONE)
            for i, ohlc in enumerate(prices, 1)]
    series = {1: bars, 5: [], 15: []}
    cutoff = start + 7 * ONE
    band = (Decimal(829), Decimal(836))
    clocks, contact = candidate_clocks(series, band, start=start, cutoff=cutoff)
    assert contact == bars[1]
    assert clocks == {
        "opening": bars[0].end + 2 * US,
        "contact": bars[1].end + 2 * US,
        "ordinary": bars[3].end + US,
    }
    seed = Position("FG2701", short=Decimal(20))
    row = dict(start=start, cutoff=cutoff, band=band, tick="1", average="831.0",
               plan=dict(source_url="fixture", published_at="2026-10-22T18:18:00+08:00"))
    result = replay_case(seed, row, series, [bars[1].end, bars[-1].end])
    assert result["public_assessment"]["after"] is None
    assert result["modes"]["ordinary_only"]["modeled_event"]["source"] == "TEST_FIXTURE:ordinary"
    assert result["modes"]["either_from_contact"]["modeled_event"]["source"] == "TEST_FIXTURE:contact"
    assert result["modes"]["either_from_contact"]["position"]["long"] == Decimal(20)
    assert result["modes"]["either_from_contact"]["quotes"][bars[1].end.isoformat()]["position"]["long"] == 0


def test_touch_only_learned_in_next_minute_cannot_cancel_earlier_advance_candidate():
    start = at("2026-10-22T21:00")
    prices = ((825, 828, 821, 827), (825, 827, 823, 826), (827, 828, 826, 828), (828, 832, 826, 830))
    bars = [Bar("FG2701", start + i * ONE, *map(Decimal, ohlc), start=start + (i - 1) * ONE)
            for i, ohlc in enumerate(prices, 1)]
    band = (Decimal(829), Decimal(836))
    prefix, unseen = candidate_clocks({1: bars[:3], 5: [], 15: []}, band, start=start, cutoff=bars[2].end + 2 * US)
    full, touch = candidate_clocks({1: bars, 5: [], 15: []}, band, start=start, cutoff=bars[-1].end + 3 * US)
    assert unseen is None and touch == bars[-1]
    assert prefix["precontact"] == full["precontact"] == bars[2].end + US


def test_report_cutoff_is_exclusive_at_permission_and_projected_action():
    start = at("2026-10-22T21:00")
    end = start + ONE
    bar = Bar("FG2701", end, *map(Decimal, (828, 830, 827, 828)), start=start)
    series = {1: [bar], 5: [], 15: []}
    seed = Position("FG2701", short=Decimal(20))
    row = dict(start=start, band=(Decimal(829), Decimal(836)), tick="1", average="828.0",
               plan=dict(source_url="fixture", published_at="2026-10-22T18:18:00+08:00"))
    for offset, expected in ((3, 0), (4, 0), (5, 20)):
        result = replay_case(seed, row | {"cutoff": end + offset * US}, series, [])
        assert result["modes"]["advance_from_open"]["position"]["long"] == Decimal(expected)


def test_wick_only_requires_body_and_confirmation_beyond_the_same_edge():
    band = tuple(map(Decimal, (829, 836)))
    assert wick_beyond(tuple(map(Decimal, (837, 838, 836, 837))), Decimal(839), band, side="LONG")
    assert not wick_beyond(tuple(map(Decimal, (836, 838, 836, 837))), Decimal(839), band, side="LONG")
    assert not wick_beyond(tuple(map(Decimal, (837, 838, 837, 837))), Decimal(839), band, side="LONG")
    assert not wick_beyond(tuple(map(Decimal, (837, 838, 836, 837))), Decimal(836), band, side="LONG")
    assert wick_beyond(tuple(map(Decimal, (828, 829, 826, 827))), Decimal(825), band, side="SHORT")


def test_wick_comparison_keeps_original_routes_and_locks_once_when_both_qualify():
    start = at("2026-10-22T21:00")
    prices = ((834, 841, 828, 835), (837, 838, 836, 837), (837, 840, 837, 839),
              (833, 837, 830, 834), (831, 832, 831, 832), (832, 836, 831, 834), (834, 835, 834, 835))
    bars = [Bar("FG2701", start + i * ONE, *map(Decimal, ohlc), start=start + (i - 1) * ONE)
            for i, ohlc in enumerate(prices, 1)]
    series = {1: bars, 5: [], 15: []}
    seed = Position("FG2701", short=Decimal(20))
    row = dict(start=start, cutoff=bars[-1].end + ONE, band=(Decimal(829), Decimal(836)), tick="1", average="835.0",
               plan=dict(source_url="fixture", published_at="2026-10-22T18:18:00+08:00"))
    before = replay_case(seed, row, series, [bars[2].end, bars[-1].end])
    compared = replay_case(seed, row, series, [bars[2].end, bars[-1].end], compare_wick=True)
    assert all(mode == compared["modes"][name] for name, mode in before["modes"].items())
    selected = compared["modes"]["geometry_with_wick"]
    assert selected["modeled_event"]["source"] == "TEST_FIXTURE:wick_1m_to_1m"
    assert selected["quotes"][bars[2].end.isoformat()]["position"]["long"] == 0
    assert selected["position"] == dict(contract="FG2701", long=Decimal(20), short=Decimal(20))
    assert compared["public_assessment"]["after"] is None
