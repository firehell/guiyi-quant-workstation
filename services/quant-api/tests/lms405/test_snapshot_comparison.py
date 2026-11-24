from decimal import Decimal

from lms405_snapshot_comparison import compare_state, indexed_snapshots, old_leg_recurrence, study


def test_visible_leg_agreement_leaves_missing_author_side_unknown():
    action = dict(action="LOCK", after={"long": "20", "short": "20", "gross": "40", "net": "0"})
    result = compare_state({"short": {"quantity": 20}}, [action])
    assert result["classification"] == "VISIBLE_LEGS_AGREE_ONLY"
    assert result["legs"]["long"] == {"author_visible": None, "projected_lots": "20", "status": "AUTHOR_LEG_UNKNOWN"}


def test_old_leg_recurrence_uses_open_average_and_prior_today_field():
    first = {"contracts": {"FG2701": {"legs": {
        "short": {"quantity": 20, "opening_average": "850", "today_quantity": 0},
        "long": {"quantity": 20, "opening_average": "828", "today_quantity": 20},
    }}}}
    same_short = {"short": {"quantity": 20, "opening_average": "850.00"}}
    changed_short = {"short": {"quantity": 20, "opening_average": "856"}}
    assert old_leg_recurrence(first, "FG2701", same_short) == ["short"]
    assert old_leg_recurrence(first, "FG2701", changed_short) == []
    assert old_leg_recurrence(first, "FG2701", {"long": {"quantity": 20, "opening_average": "828"}}) == []


def test_quote_mismatch_rejects_comparison_and_close_response_is_separate():
    first = {"source": "early", "table": "图2", "published_at": "2026-10-22T22:10:00+08:00",
             "contracts": {}, "source_url": "early"}
    later = {"source": "later", "table": "图2", "published_at": "2026-10-27T11:34:00+08:00",
             "quote_anchor": "2026-10-27T11:30:00+08:00", "source_url": "later", "image": {},
             "binding": "MIXED_POST_TABLE_BINDING_UNKNOWN", "contracts": {"V2701": {
                 "legs": {"long": {"quantity": 40, "opening_average": "5100"}},
             }}}
    exposure = {"tables": [first, later]}
    inputs = {"first_night_older_leg_screen": "early", "snapshots": [
        {"source": "later", "table": "图2", "quotes": {"V2701": "5100"}},
    ]}
    sample = {"fixture_only": True, "executable": False, "windows": {"development": {"BASELINE": {
        "as_of": "2026-10-27T11:35:00+08:00", "timeline": [
            {"at": "2026-10-27T11:30:00.000002+08:00", "actions": [{
                "contract": "V2701", "action": "ENTER_LONG", "after": {
                    "long": "40", "short": "0", "gross": "40", "net": "40",
                },
            }]},
            {"at": "2026-10-27T11:30:00.000003+08:00", "actions": [{
                "contract": "V2701", "action": "CLEAR", "after": {
                    "long": "0", "short": "0", "gross": "0", "net": "0",
                },
            }]},
        ],
    }}}}
    _, anchor, _ = indexed_snapshots(exposure, inputs)[0]
    mismatched = study(exposure, sample, inputs, {("V2701", anchor): Decimal(5101)})
    assert mismatched["visible_baseline_classifications"] == {}
    matched = study(exposure, sample, inputs, {("V2701", anchor): Decimal(5100)})
    result = matched["snapshots"][0]["contracts"]["V2701"]["variants"]["BASELINE"]
    assert result["before_quote_close"]["classification"] == "NO_MODEL_ENTRY_BEFORE_ANCHOR"
    assert result["through_quote_close_response"]["classification"] == "VISIBLE_LEGS_AGREE_ONLY"
    assert len(result["quote_close_response_actions"]) == 1
    assert matched["admitted_author_action_samples"] == 0
