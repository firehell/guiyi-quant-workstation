from lms405_trial_to_trend import assess_role, milestones


def test_price_endpoints_do_not_prove_path_order_or_close_cross():
    minute = "2026-05-20T09:44+08:00"
    endpoint = dict(first_far_reach=minute, first_strict_close_beyond_far=minute)
    same_bar = dict(first_far_reach=minute, first_strict_close_beyond_far=None)
    result = milestones([endpoint, same_bar])
    assert result["far_reach"]["all_visible_endpoints_seen"] is True
    assert result["far_reach"]["first_observations_in_strict_order"] is None
    assert result["far_close_cross"]["all_visible_endpoints_seen"] is False
    assert milestones([])["far_reach"]["all_visible_endpoints_seen"] is None


def test_holding_review_requires_success_and_identity_for_the_same_trial():
    settings = dict(trend=True, trial_success=True, current_position_is_trial=True,
                    version_405=True, author_role=None)
    assert assess_role(**settings)["status"] == "CONDITIONS_MET"
    for name in ("trial_success", "current_position_is_trial", "version_405"):
        result = assess_role(**(settings | {name: None}))
        assert result["status"] == "INDETERMINATE"
        assert result["action"] is None
    assert assess_role(**(settings | {"trend": False}))["status"] == "CONDITION_REJECTED"
    assert assess_role(**(settings | {"author_role": "SHORT_TERM"}))["status"] == "AUTHOR_SHORT_TERM"
