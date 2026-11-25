from decimal import Decimal

from lms405_m_difficulty_study import fresh_candidates
from lms405_right_side_study import at


def test_retrospective_price_contact_requires_a_wholly_subsequent_shape():
    contact = at("2026-09-09T09:11")
    events = [dict(shape_end=at(f"2026-09-09T{time}"), close=Decimal(close)) for time, close in (
        ("09:15", "1658"), ("09:16", "1658"), ("09:17", "1658"), ("09:18", "1656"),
    )]
    inside, beyond = fresh_candidates(events, 5, contact, (Decimal(1657), Decimal("1663.5")), "SHORT")
    assert inside == events[2] | dict(inside_m=True, beyond_m=False)
    assert beyond == events[3] | dict(inside_m=False, beyond_m=True)
