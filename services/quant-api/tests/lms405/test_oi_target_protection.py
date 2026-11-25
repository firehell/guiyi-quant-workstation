from decimal import Decimal

from lms405_oi_target_protection import JULY_PROTECTION, signal_context
from lms405_right_side_study import US, at


def test_short_signal_already_below_band_does_not_retroactively_use_first_overlap():
    shape = at("2026-07-22T21:14")
    known = at("2026-07-22T21:15") + US
    event = dict(close=Decimal(9953), shape_start=shape, available_at=known)
    published = at("2026-07-17T17:18")
    current = signal_context(event, JULY_PROTECTION, None, published)
    assert current["direction_side_of_band"] == "BELOW"
    assert current["report_known_before_shape"] is True
    assert current["prior_overlap_known"] is False
    assert signal_context(event, JULY_PROTECTION, known, published) == current
    assert signal_context(event, JULY_PROTECTION, at("2026-07-22T22:11"), published) == current
    assert signal_context(event, JULY_PROTECTION, known - US, shape)["prior_overlap_known"] is True
    assert signal_context(event, JULY_PROTECTION, None, shape)["report_known_before_shape"] is False
