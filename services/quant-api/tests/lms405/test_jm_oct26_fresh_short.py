from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_jm_oct26_fresh_short import CONTRACT, first_reversal_after, position_action, strict_prefix
from lms405_right_side_study import ONE, US, at


def test_reversal_requires_new_shape_and_precedes_cutoff_strictly():
    start = at("2026-10-27T09:00")
    bars = [
        Bar(CONTRACT, start + (i + 1) * ONE, *map(Decimal, prices), start=start + i * ONE)
        for i, prices in enumerate(((100, 105, 95, 100), (100, 105, 95, 100),
                                    (100, 103, 98, 101), (101, 105, 100, 104)))
    ]
    assert first_reversal_after({1: bars}, bars[0], bars[-1].end + US, position_known_at=start) is None
    cut = bars[-1].end + 2 * US
    event = first_reversal_after(strict_prefix({1: bars}, cut), bars[0], cut, position_known_at=start)
    assert event["shape_end"] == bars[2].end
    assert event["available_at"] == bars[-1].end + US
    assert first_reversal_after({1: bars}, bars[1], cut, position_known_at=start) is None
    assert first_reversal_after({1: bars}, bars[0], cut, position_known_at=bars[2].start) is None


def test_position_paths_end_with_identical_long_but_different_intermediate_exposure():
    start = at("2026-10-26T21:05")
    seed = [dict(at=start.isoformat(), action="ENTER_SHORT", before=["0", "0"], after=["0", "1"])]
    flat = position_action(seed, "CLEAR", start + ONE)
    independent = position_action(flat, "ENTER_LONG", start + 2 * ONE)
    protected = position_action(seed, "LOCK", start + 2 * ONE)
    released = position_action(protected, "EXIT_SHORT", start + 3 * ONE)
    assert independent[-1]["after"] == released[-1]["after"] == ["1", "0"]
    assert independent[-2]["after"] == ["0", "0"]
    assert released[-2]["after"] == ["1", "1"]
    with pytest.raises(ValueError, match="JM_OCT26_POSITION_ORDER_CONFLICT"):
        position_action(protected, "EXIT_SHORT", start + 2 * ONE)
