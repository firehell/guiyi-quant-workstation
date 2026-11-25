import pytest

from lms405_partial_protection_replay import STRICT, exposures, scenario_sets, summarize


def test_retained_lots_reduce_exposure_but_do_not_prove_old_removal_time():
    allocation = [(7, 0, 0, 13)]
    early = summarize("FG2701", 20, allocation, removal_clock_unknown=False)["checkpoints"]
    result = summarize("FG2701", 20, allocation, removal_clock_unknown=True)
    unknown = result["checkpoints"]
    assert early["after_middle_bucket"]["net_lots"] == [-13, -13]
    assert unknown["after_middle_bucket"]["net_lots"] == [-13, 0]
    assert early["at_terminal_quote_bound"] == unknown["at_terminal_quote_bound"] == {
        "protection_lots": [20, 20], "original_short_lots": 20, "net_lots": [0, 0], "gross_lots": [40, 40],
    }
    witness = result["witnesses_at_end_of_middle_bucket"]["least_open_short"]
    assert witness["origin_counts"] == allocation[0]
    assert list(witness["checkpoint_net_lots"].values()) == [0, 0, 0, 0]


def test_full_rebuild_counts_early_new_lots_and_keeps_infeasible_scenario_empty():
    source = {"summaries": {STRICT: {"joint_counts_across_quotes": [(0, 1, 3, 16), (7, 0, 0, 13)]}}}
    sets = scenario_sets(source)
    full = summarize("FG2701", 20, sets["full_rebuild"], removal_clock_unknown=False)["checkpoints"]
    assert full["before_new_lots"]["net_lots"] == [-20, -20]
    assert full["after_middle_bucket"]["net_lots"] == [-16, -16]
    assert summarize("FG2701", 20, sets["full_rebuild_only_after_second"], removal_clock_unknown=False) == {
        "compatible_allocation_count": 0, "checkpoints": None,
    }
    with pytest.raises(ValueError, match="LMS_PARTIAL_PROTECTION_INVALID_COUNTS"):
        exposures("FG2701", 20, (7, 0, 0, 13), old_in_transit=14)
