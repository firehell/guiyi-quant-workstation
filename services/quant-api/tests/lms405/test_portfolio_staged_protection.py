from datetime import datetime, timedelta, timezone
from decimal import Decimal

from guiyi_quant.lms405 import Bar, Position
from lms405_portfolio_staged_protection import common_quote_ends, exposure_bounds, tape
from lms405_staged_protection_clocks import phase_prices
import pytest


START = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)
TOUCH = START + timedelta(minutes=1)
CONFIRM = START + timedelta(minutes=12)
CUT = START + timedelta(minutes=68)
FRAME = dict(plan=dict(source_url="TEST_FIXTURE:PLAN", available_at=START),
             touch=TOUCH, confirm=CONFIRM, cutoff=CUT)


def test_common_quote_boundaries_cannot_use_two_different_capture_minutes():
    assert common_quote_ends(dict(FG={"individual_quote_ends": ["a", "b"]},
                                  JM={"individual_quote_ends": ["a", "b"]},
                                  SH={"individual_quote_ends": ["a"]})) == ["a"]
    assert common_quote_ends(dict(FG={"individual_quote_ends": ["a"]},
                                  SH={"individual_quote_ends": ["b"]})) == []


@pytest.mark.parametrize("early,normal,sizes,result", [
    (False, False, [], 0),
    (True, False, [7], 7),
    (False, True, [20], 20),
    (True, True, [7, 13], 20),
])
def test_topup_permission_is_independent_and_uses_remaining_capacity(early, normal, sizes, result):
    replay = tape(Position("FG2701", short=Decimal(20)), 7, **FRAME, early=early, normal=normal)
    assert [event["amount"] for event in replay["events"]] == sizes
    assert replay["terminal"]["long"] == result
    assert replay["terminal"]["short"] == 20


def test_full_early_fixture_does_not_add_more_and_rejects_new_decision_at_cutoff():
    before = Position("FG2701", short=Decimal(20))
    result = tape(before, 20, **FRAME, early=True, normal=True)
    assert [row["stage"] for row in result["events"]] == ["EARLY_PROTECTION"]
    same_cut = FRAME | {"cutoff": CONFIRM + timedelta(microseconds=6)}
    with pytest.raises(ValueError, match="PORTFOLIO_STAGE_CLOCK_INVALID"):
        tape(before, 7, **same_cut, early=True, normal=True)


def test_two_paths_are_joined_at_the_same_evaluation_time():
    rows = {}
    for contract, first, confirmation in (("FG2701", (7, 20), 12), ("JM2701", (0, 16), 45)):
        seed = Position(contract, short=Decimal(20))
        frame = FRAME | {"confirm": START + timedelta(minutes=confirmation)}
        rows[contract] = dict(seed={"short": seed.short}, branches=dict(
            staged_independent_topup={lots: tape(seed, lots, **frame, early=True, normal=True) for lots in first},
            after_confirmation_only=tape(seed, 0, **frame, early=False, normal=True),
        ))
    report = exposure_bounds(rows, quote_ends=[CUT.isoformat()])
    assert report["number_of_compatible_joint_sizes"] == 4
    assert report["joint_sizes_with_two_nonzero_stages_in_every_contract"] == 1
    first, glass, coal, quote = report["rows"]
    assert first["protective_lots_range"] == [7, 36]
    assert glass["protective_lots_range"] == [20, 36]
    assert coal["abs_net_lots_range"] == quote["abs_net_lots_range"] == [0, 0]
    assert report["comparable_as_money_or_portfolio_risk"] is False


def test_permission_minute_price_relaxations_are_independent_and_exclude_quote_minute():
    minute = timedelta(minutes=1)
    microseconds = timedelta(microseconds=6)
    candles = [Bar("FG2701", START + i * minute, *map(Decimal, prices), start=START + (i - 1) * minute)
               for i, prices in enumerate(((828, 830, 827, 829), (829, 831, 826, 828), (828, 832, 828, 830),
                                          (830, 833, 829, 831), (831, 834, 827, 833), (833, 834, 829, 830),
                                          (830, 834, 825, 833)), 1)]
    args = (candles, START + minute + microseconds, START + 4 * minute + microseconds, candles[-1].end)
    assert phase_prices(*args, tick=Decimal(1)) == ((828, 833), (829, 834))
    assert phase_prices(*args, tick=Decimal(1), allow_early=True) == ((826, 833), (829, 834))
    assert phase_prices(*args, tick=Decimal(1), allow_late=True) == ((828, 833), (827, 834))
