"""C5-06A review foundation optional report payload pass-through."""

from __future__ import annotations

from app.api.backtests import _review_foundation_passthrough


def test_review_foundation_passthrough_defaults_to_null() -> None:
    out = _review_foundation_passthrough({"report_metadata": {"profile_id": "intraday_research_v1"}})
    assert out == {
        "oos_window_id": None,
        "walk_forward_fold_id": None,
        "candidate_status": None,
        "hard_reject_reason": None,
        "review_skip_status": None,
    }


def test_review_foundation_passthrough_reads_summary_and_metadata() -> None:
    out = _review_foundation_passthrough(
        {
            "oos_window_id": "oos_fixed",
            "report_metadata": {
                "walk_forward_fold_id": "walk_forward_a_test",
                "candidate_status": "validated_research_candidate",
                "hard_reject_reason": "max_drawdown_pct_gt_0.15",
                "review_skip_status": "SKIPPED_BY_FROZEN_HARD_REJECT",
            },
        }
    )
    assert out["oos_window_id"] == "oos_fixed"
    assert out["walk_forward_fold_id"] == "walk_forward_a_test"
    assert out["candidate_status"] == "validated_research_candidate"
    assert out["hard_reject_reason"] == "max_drawdown_pct_gt_0.15"
    assert out["review_skip_status"] == "SKIPPED_BY_FROZEN_HARD_REJECT"


def test_review_foundation_passthrough_does_not_invent_blank_strings() -> None:
    out = _review_foundation_passthrough(
        {
            "oos_window_id": "  ",
            "report_metadata": {"candidate_status": ""},
        }
    )
    assert out["oos_window_id"] is None
    assert out["candidate_status"] is None


def test_report14_style_summary_has_null_foundation_fields() -> None:
    """Legacy report14-like summary must not invent foundation fields."""
    out = _review_foundation_passthrough(
        {
            "report_metadata": {
                "strategy_code": "jm_v1b_daily_direction_fast_entry",
                "strategy_version": "v1b.0",
                "profile_id": "intraday_research_v1",
            }
        }
    )
    assert all(value is None for value in out.values())
