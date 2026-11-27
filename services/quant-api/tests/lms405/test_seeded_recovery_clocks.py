from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, US, at
from lms405_seeded_recovery_clocks import carried_crossings


def minute(clock, price, *, opened=None):
    end = at(f"2026-10-27T{clock}")
    closing = Decimal(price)
    opening = closing if opened is None else Decimal(opened)
    return Bar("I2701", end, opening, max(opening, closing), min(opening, closing), closing, start=end - ONE)


def test_carry_uses_two_new_closes_and_only_a_witness_from_the_same_revision():
    edge = Decimal(668)
    rows = [minute(clock, price) for clock, price in (('11:28', 669), ('11:29', 667), ('11:30', 666),
                                                       ('13:31', 667), ('13:32', 666))]
    carried = carried_crossings(rows, edge, "SHORT")
    assert rows[3].end not in carried
    assert carried[rows[4].end] == dict(witness_at=rows[1].end + US, segment_start=rows[3].start, from_prior_segment=True)
    assert carried_crossings(rows[3:], edge, "SHORT") == {}


def test_gap_open_equal_to_edge_discards_old_witness_even_if_it_closes_beyond():
    rows = [minute('11:28', 669), minute('11:29', 667), minute('11:30', 666),
            minute('13:31', 667, opened=668), minute('13:32', 666)]
    result = carried_crossings(rows, Decimal(668), "SHORT")
    assert rows[4].end not in result
