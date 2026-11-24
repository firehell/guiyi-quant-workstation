"""Production-shaped replay boundaries; all action examples are synthetic."""

from dataclasses import replace
from decimal import Decimal
import pytest

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms_author_regions import AuthorRegion, RegionInput
from guiyi_quant.lms_near405 import replay
from lms_near405_author_study import compare_events
from test_near405 import (
    T,
    US,
    bar,
    decision,
    entry_bars,
    lock_restore_bars,
    retry_bars,
    until,
)


def area(
    *, known=T, effective=T, purpose="PLAN_RANGE", basis="VERIFIED_PRE_EVENT", **kw
):
    zone = Zone(
        kw.pop("id", "area-a"),
        kw.pop("contract", "JM2509"),
        Decimal(100),
        Decimal(110),
        known,
        "synthetic-evidence",
        kw.pop("expires_at", None),
    )
    return AuthorRegion(zone, effective, purpose, basis, **kw)


def study(bars, *regions, recovery="KEYBAR", **kwargs):
    return replay(
        bars,
        as_of=kwargs.pop("as_of", until(bars)),
        region_input=RegionInput("AUTHOR", recovery, regions),
        **kwargs,
    )


def test_author_plan_range_must_be_verified_and_known_before_pattern():
    bars = entry_bars()
    accepted = study(bars, area())
    assert accepted["proposals"][0]["plan"]["author_region_id"] == "area-a"
    assert not accepted["transitions"]
    cases = [
        (area(known=bars[6].start), "AUTHOR_PLAN_RANGE_NOT_KNOWN_BEFORE_PATTERN"),
        (area(effective=bars[6].start), "AUTHOR_PLAN_RANGE_NOT_KNOWN_BEFORE_PATTERN"),
        (area(basis="RETROSPECTIVE"), "AUTHOR_PLAN_RANGE_UNAVAILABLE"),
        (area(basis="TEST_FIXTURE"), "AUTHOR_PLAN_RANGE_UNAVAILABLE"),
        (area(purpose="DIVIDE"), "AUTHOR_PLAN_RANGE_UNAVAILABLE"),
        (area(purpose="TARGET"), "AUTHOR_PLAN_RANGE_UNAVAILABLE"),
        (area(expires_at=bars[7].end + US), "AUTHOR_PLAN_RANGE_EXPIRED"),
    ]
    for item, reason in cases:
        result = study(bars, item)
        assert not result["proposals"]
        assert result["evaluations"][-1]["region"] is None
        assert result["evaluations"][-1]["region_issue"] == reason
    assert study(bars, area(basis="TEST_FIXTURE"), timely_fixture=True)["transitions"]


def test_conflict_expiry_and_contract_fail_closed():
    bars = entry_bars()
    assert (
        study(bars, area(), area(id="other"))["evaluations"][-1]["region_issue"]
        == "AUTHOR_PLAN_RANGE_CONFLICT"
    )
    assert (
        study(bars, area(), area(id="expired", known=T + US, expires_at=bars[6].start))[
            "evaluations"
        ][-1]["region_issue"]
        == "AUTHOR_PLAN_RANGE_EXPIRED"
    )
    with pytest.raises(ValueError, match="CONTRACT_BOUNDARY"):
        study(bars, area(contract="JM2510"))


def test_checkpoint_binds_known_region_prefix_and_candidate_identity():
    bars = lock_restore_bars()
    new = area(id="future", known=bars[10].end + US)
    kw = dict(timely_fixture=True)
    first = study(bars[:8], area(), **kw)
    assert first == study(bars, area(), new, as_of=until(bars[:8]), **kw)
    full = study(bars, area(), new, **kw)
    assert full == study(bars, new, area(), checkpoint=first["checkpoint"], **kw)
    second = study(bars, area(), new, as_of=until(bars[:11]), **kw)
    assert full == study(bars, area(), new, checkpoint=second["checkpoint"], **kw)
    for modified in (area(known=T - US), area(basis="RETROSPECTIVE")):
        with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
            study(bars, modified, new, checkpoint=first["checkpoint"], **kw)
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        study(
            bars,
            area(),
            new,
            recovery="TWO_CLOSES_BEYOND",
            checkpoint=first["checkpoint"],
            **kw,
        )


def test_recovery_hypothesis_changes_only_unlock_and_uses_strict_closes():
    bars = lock_restore_bars()
    for mirrored in (False, True):
        direction = "SHORT" if mirrored else "LONG"
        if mirrored:
            bars = [
                replace(
                    b,
                    open=210 - b.open,
                    high=210 - b.low,
                    low=210 - b.high,
                    close=210 - b.close,
                )
                for b in bars
            ]
        plain = study(bars, area(), timely_fixture=True)
        assert [t["action"] for t in plain["transitions"]] == [
            "ENTER_" + direction,
            "LOCK",
            "UNLOCK_" + direction,
            "CLEAR",
        ]
        for price, expected in (
            (None, "RECOVERY_BOUNDARY_UNKNOWN"),
            (103 if mirrored else 104, "RECOVERY_TWO_CLOSES_NOT_MET"),
            (400 if mirrored else 90, None),
        ):
            region = area(
                **{
                    "recovery_" + direction.lower(): Decimal(price)
                    if price is not None
                    else None
                }
            )
            adjusted = study(
                bars, region, recovery="TWO_CLOSES_BEYOND", timely_fixture=True
            )
            actions = [t["action"] for t in adjusted["transitions"]]
            assert actions[:2] == ["ENTER_" + direction, "LOCK"]
            assert actions[-1] == "CLEAR"
            if expected:
                assert actions == ["ENTER_" + direction, "LOCK", "CLEAR"]
                assert expected in {e["status"] for e in adjusted["evaluations"]}
                assert adjusted["transitions"][-1]["before"]["long"] == "1"
                assert adjusted["transitions"][-1]["before"]["short"] == "1"
            else:
                assert actions == [
                    "ENTER_" + direction,
                    "LOCK",
                    "UNLOCK_" + direction,
                    "CLEAR",
                ]
    independent = replay(
        lock_restore_bars(),
        as_of=until(lock_restore_bars()),
        timely_fixture=True,
        region_input=RegionInput(recovery_rule="TWO_CLOSES_BEYOND"),
    )
    assert [t["action"] for t in independent["transitions"]] == [
        "ENTER_LONG",
        "LOCK",
        "UNLOCK_LONG",
        "CLEAR",
    ]


def test_expired_or_replaced_region_does_not_refill_old_plan():
    bars = retry_bars()
    one = study(bars, area(), timely_fixture=True)
    assert [t["action"] for t in one["transitions"]] == [
        "ENTER_LONG",
        "CLEAR",
        "REENTER_LONG",
        "CLEAR",
    ]
    expiry = study(bars, area(expires_at=bars[9].end), timely_fixture=True)
    assert [t["action"] for t in expiry["transitions"]] == ["ENTER_LONG", "CLEAR"]
    replacement = area(id="revision", known=bars[9].end)
    two = study(bars, area(), replacement, timely_fixture=True)
    assert [t["action"] for t in two["transitions"]][:3] == [
        "ENTER_LONG",
        "CLEAR",
        "ENTER_LONG",
    ]
    assert two["transitions"][2]["after"]["plan"]["author_region_id"] == "revision"


def test_study_requires_confirmation_and_matches_separate_labels():
    bars = entry_bars()
    result = study(bars, area())
    proposal = result["proposals"][0]
    as_human = decision(proposal, record_kind="HUMAN_RESEARCH_DECISION")
    confirmed = study(bars, area(), decisions=[as_human, as_human])
    assert len(confirmed["transitions"]) == 1
    rejected = study(bars, area(), decisions=[as_human | {"decision": "REJECT"}])
    assert not rejected["transitions"]
    late = bars + [bar(8, 106, 109, 102, 107)]
    expired = study(
        late,
        area(),
        decisions=[as_human | {"known_at": (late[-1].end + US).isoformat()}],
    )
    assert not expired["transitions"]
    t = proposal["generated_at"]
    event = dict(
        id="event",
        contract="JM2509",
        source="fixture-source",
        action="ENTER_LONG",
        earliest_at=t,
        latest_at=t,
        version_405=True,
        five_minute_alignment=True,
        initial_state_aligned=True,
        time_basis="AUTHOR_EVENT_TIME_OR_OBSERVED_INTERVAL",
    )

    def compare(result, *events, coverage=True):
        return compare_events(
            result, events, contract="JM2509", session_coverage=coverage
        )

    assert compare(result, event)["match_fraction"] == {
        "denominator": 1,
        "numerator": 1,
    }
    assert (
        compare(result, event | {"action": "CLEAR", "original_side": "LONG"})["rows"][
            0
        ]["status"]
        == "ACTION_MISMATCH"
    )
    assert compare(result, event | {"latest_at": None})["match_fraction"] is None
    assert compare(result, event, event | {"id": "collision"})["match_fraction"] is None
    assert compare(result, event, coverage=False)["match_fraction"] is None
    assert compare(study(bars, area(), timely_fixture=True), event)["eligible"] == 0
    blocked = study(bars, area(purpose="TARGET"))
    assert compare(blocked, event)["eligible"] == 0


def test_external_fixture_cannot_create_a_human_study_path():
    bars = lock_restore_bars()
    proposal = study(bars[:8], area())["proposals"][0]
    path = study(bars, area(), decisions=[decision(proposal)])
    assert path["decisions"][0]["reason"] == "HUMAN_DECISION_REQUIRED"
    assert not path["transitions"]


@pytest.mark.parametrize("supersede", [False, True])
def test_author_area_must_still_apply_at_human_confirmation(supersede):
    bars = entry_bars()
    decision_at = bars[-1].end + 2 * US
    regions = (
        (area(), area(id="replacement", known=decision_at))
        if supersede
        else (area(expires_at=decision_at),)
    )
    before = study(bars, *regions, as_of=decision_at - US)
    proposal = before["proposals"][0]
    answer = decision(proposal, record_kind="HUMAN_RESEARCH_DECISION")
    result = study(bars, *regions, decisions=[answer], checkpoint=before["checkpoint"])
    assert not result["transitions"]
    assert result["decisions"][0]["reason"] == (
        "AUTHOR_PLAN_RANGE_NOT_KNOWN_BEFORE_PATTERN"
        if supersede
        else "AUTHOR_PLAN_RANGE_EXPIRED"
    )
    assert not study(bars, *regions)["checkpoint"]["pending_proposals"]


def test_missing_area_remains_unknown_even_with_stale_signal():
    bars = entry_bars() + [bar(8, 100, 109, 99, 99.5), bar(9, 99.5, 101, 97, 98)]
    result = study(bars, area(expires_at=bars[-1].end), timely_fixture=True)
    assert result["evaluations"][-1]["status"] == "INDETERMINATE"
    assert result["evaluations"][-1]["region_issue"] == "AUTHOR_PLAN_RANGE_EXPIRED"


def test_lock_scoring_requires_and_compares_original_direction():
    bars = lock_restore_bars()
    first = study(bars[:8], area())["proposals"][0]
    path = study(
        bars, area(), decisions=[decision(first, record_kind="HUMAN_RESEARCH_DECISION")]
    )
    lock = next(p for p in path["proposals"] if p["action"] == "LOCK")
    event = dict(
        id="lock",
        contract="JM2509",
        source="fixture-source",
        action="LOCK",
        earliest_at=lock["generated_at"],
        latest_at=lock["generated_at"],
        version_405=True,
        five_minute_alignment=True,
        initial_state_aligned=True,
        time_basis="AUTHOR_EVENT_TIME_OR_OBSERVED_INTERVAL",
    )
    for side, expected in [
        (None, "INDETERMINATE"),
        ("SHORT", "SIDE_MISMATCH"),
        ("LONG", "ACTION_AND_TIME_MATCH"),
    ]:
        result = compare_events(
            path,
            [event | {"original_side": side}],
            contract="JM2509",
            session_coverage=True,
        )
        assert result["rows"][0]["status"] == expected
