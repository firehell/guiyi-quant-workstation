from lms405_right_side_study import ONE, US, at
from lms405_v_exit_study import quote_pair_counts


def test_quote_candidates_distinguish_strict_placement_and_quote_minute_overlap():
    old_quote = at("2026-10-26T10:08")
    gap_quote = at("2026-10-26T11:24")
    before, after = [old_quote], [gap_quote]

    assert quote_pair_counts(old_quote - US, before, after) == {"possible": 1, "strictly_between": 0}
    assert quote_pair_counts(old_quote + US, before, after) == {"possible": 1, "strictly_between": 1}
    assert quote_pair_counts(gap_quote - ONE, before, after) == {"possible": 1, "strictly_between": 0}
    assert quote_pair_counts(gap_quote + US, before, after) == {"possible": 0, "strictly_between": 0}
