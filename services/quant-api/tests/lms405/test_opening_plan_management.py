from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_opening_plan_management import SHORT_LEVELS, summarize
from lms405_protection_timeframes import VARIANTS
from lms405_right_side_study import ONE, US, at


def test_target_must_be_known_before_opposing_shape_starts():
    start = at("2026-10-26T21:00")
    bars = [
        Bar("SA2701", start + end * ONE, *map(Decimal, (950, 950, low, close)), start=start + (end - 1) * ONE)
        for end, low, close in ((1, 949, 949), (2, 943, 945), (3, 942, 942), (4, 947, 947), (5, 949, 950))
    ]
    events = {f"{shape}m_to_{confirm}m": [] for shape, confirm in VARIANTS}
    too_early = dict(shape_end=start + 3 * ONE, available_at=start + 4 * ONE + US)
    fresh = dict(shape_end=start + 4 * ONE, available_at=start + 5 * ONE + US)
    events["1m_to_1m"] = [too_early, fresh]

    before_fresh = summarize(bars, events, SHORT_LEVELS["SA2701"], as_of=fresh["available_at"])
    later = summarize(bars, events, SHORT_LEVELS["SA2701"], as_of=fresh["available_at"] + US)
    early_geometry = before_fresh["geometry"]["1m_to_1m"]
    later_geometry = later["geometry"]["1m_to_1m"]
    assert early_geometry["first_opposing"] == too_early
    assert early_geometry["first_fresh_after_target"]["TARGET_FAR_REACH"] is None
    assert later_geometry["first_fresh_after_target"]["TARGET_FAR_REACH"] == fresh
    assert later_geometry["first_fresh_after_target"]["TARGET_FAR_LITERAL_TOUCH"] == fresh
    assert later_geometry["first_fresh_after_target"]["TARGET_FAR_STRICT_CLOSE"] is None


def test_open_below_target_is_not_literal_touch():
    start = at("2026-10-26T21:00")
    first = Bar("SA2701", start + ONE, *map(Decimal, (941, 942, 940, 941)), start=start)
    opposite = dict(shape_end=start + 3 * ONE, available_at=start + 4 * ONE + US)
    events = {f"{shape}m_to_{confirm}m": [] for shape, confirm in VARIANTS} | {"1m_to_1m": [opposite]}
    report = summarize([first], events, SHORT_LEVELS["SA2701"], as_of=opposite["available_at"] + US)
    first_target = report["prices"]["target_1"]["far"]
    matched = report["geometry"]["1m_to_1m"]["first_fresh_after_target"]
    assert first_target["open_already_beyond"]
    assert first_target["first_range_reaches_direction"] == first.end
    assert matched["TARGET_FAR_REACH"] == opposite
    assert matched["TARGET_FAR_LITERAL_TOUCH"] is None
