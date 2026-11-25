from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_protection_location_audit import location_flags, recount
from lms405_right_side_study import ONE, at


def test_wick_contact_does_not_require_shape_or_confirmation_close_inside():
    end = at("2026-10-27T21:14")
    shape = Bar("RU2701", end, Decimal(19425), Decimal(19425), Decimal(19400), Decimal(19420), start=end - ONE)
    band = Decimal(19360), Decimal(19400)

    placement = location_flags(shape, Decimal(19435), band)
    assert placement == {
        "shape_range_contact": True,
        "shape_body_contact": False,
        "shape_close_inside": False,
        "confirmation_close_inside": False,
    }

    assert location_flags(shape, band[1], band)["confirmation_close_inside"]


def test_quote_support_distinguishes_uncertain_minute_from_missing_observation():
    row = dict(
        variant="5m_to_1m", shape_end=at("2026-10-27T21:15"),
        placement=dict(shape_range_contact=True, shape_body_contact=False, shape_close_inside=False,
                       confirmation_close_inside=False),
        same_row_quote_price_support_count=1, prior_to_quote_minute_price_support_count=0,
    )
    repeated_shape = row | {"variant": "5m_to_5m"}
    assert recount([row, repeated_shape], comparable_price=True)["shape_range_contact"] == dict(
        candidates=2, distinct_shapes=1, candidates_with_whole_leg_price_support=2,
        candidates_with_whole_leg_support_before_quote_minute=0,
    )
    assert recount([row], comparable_price=False)["shape_range_contact"][
        "candidates_with_whole_leg_price_support"
    ] is None
