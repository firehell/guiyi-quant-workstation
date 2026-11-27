from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_lot_timing import displayed_tick_totals
from lms405_right_side_study import ONE, US, at
from lms405_sh_first_protection_rearm import first_close_reset, reclaim_tape, stage_allocations


def candle(time, price):
    close = Decimal(price)
    return Bar("SH2701", time + ONE, close, close, close, close, start=time)


def test_reclaim_requires_consecutive_strict_closes_and_cannot_backfill():
    start = at("2026-10-22T21:48")
    rows = [candle(start + offset * ONE, close) for offset, close in enumerate((100, 101, 102, 100, 101, 102, 103))]
    observations, eligible = reclaim_tape(rows, edge=Decimal(100), required=2)
    assert observations == [(rows[2].end, Decimal(102)), (rows[5].end, Decimal(102))]
    assert eligible == [(rows[3], rows[2].end + US), (rows[6], rows[5].end + US)]
    assert reclaim_tape([rows[0], rows[1], rows[5], rows[6]], edge=Decimal(100), required=2)[1] == []


def test_late_only_and_two_stage_require_a_quote_minute_when_the_prior_range_is_too_low():
    start = at("2026-10-22T22:00")
    early, near, quote = (candle(start + offset * ONE, close) for offset, close in enumerate((100, 102, 110)))
    totals = displayed_tick_totals(Decimal("105.0"), 2, Decimal(1))
    result = stage_allocations([early], [near, quote], quote.end, lots=2, totals=totals)
    assert result["allocations"] == [(1, 0, 1)]
    assert result["both"] and not result["late_only"] and not result["without_quote_minute"]
    assert stage_allocations([early], [near], quote.end, lots=2, totals=totals)["allocations"] == []


def test_failed_first_breach_does_not_authorize_later_minutes_without_rearming():
    start = at("2026-10-22T21:20")
    prices = ((100, 101, 99, 100), (100, 101, 100, 100), (100, 102, 100, 102),
              (102, 105, 102, 103), (103, 110, 103, 105))
    rows = [Bar("SH2701", start + (i + 1) * ONE, *map(Decimal, fields), start=start + i * ONE)
            for i, fields in enumerate(prices)]
    breach = {"breach_end": rows[0].end, "boundary": Decimal(100)}
    result = first_close_reset(rows, breach, rows[-1].end, lots=1, totals=range(110, 111))
    assert result["witnessed_recross_minute_ends"] == [rows[1].end, rows[2].end]
    outcomes = result["allocations"]
    for path in ("no_rearm", "fresh_intraminute_recross_minutes_only", "2_close_rearm_complete_minutes_only"):
        assert not outcomes[path]["allocations"]
    for path in ("1_close_rearm_complete_minutes_only", "2_close_rearm_overlap"):
        assert outcomes[path]["allocations"] == [(0, 0, 1)]
