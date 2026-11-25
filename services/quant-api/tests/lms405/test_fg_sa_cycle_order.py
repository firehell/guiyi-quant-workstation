from lms405_fg_sa_cycle_order import ordered_pairs
from lms405_right_side_study import US, at


def test_reprotection_requires_shape_that_starts_strictly_after_restore_is_known():
    restore = {"available_at": at("2026-06-12T21:35") + US}
    existing_shape = {"shape_start": at("2026-06-12T21:35")}
    exact_start = {"shape_start": at("2026-06-12T21:35") + US}
    new_shape = {"shape_start": at("2026-06-12T21:40")}
    assert ordered_pairs([restore], [existing_shape, exact_start, new_shape]) == [
        {"restore": restore, "re_protect": new_shape}
    ]
    assert ordered_pairs([], [new_shape]) == []
