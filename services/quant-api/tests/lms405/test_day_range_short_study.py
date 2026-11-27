"""Causality and accounting checks for the sealed first-entry experiment."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant import lms_near405 as kernel
from lms405_day_range_short_study import direct_effects, filtered_replay, skip_first_entry
from test_near405 import bar, entry_bars, until


@pytest.mark.parametrize(("utc_hour", "action", "reason", "environment", "expected"), [
    (1, "ENTER_SHORT", "FRESH_PLAN_KEYBAR", "RANGE", True),
    (7, "ENTER_SHORT", "FRESH_PLAN_KEYBAR", "RANGE", True),
    (13, "ENTER_SHORT", "FRESH_PLAN_KEYBAR", "RANGE", False),
    (18, "ENTER_SHORT", "FRESH_PLAN_KEYBAR", "RANGE", False),
    (1, "REENTER_SHORT", "FRESH_SIGNAL_RETRY", "RANGE", False),
    (1, "ENTER_SHORT", "FRESH_PLAN_KEYBAR", "DOWN", False),
    (1, "ENTER_LONG", "FRESH_PLAN_KEYBAR", "RANGE", False),
    (1, "LOCK", "OPPOSING_KEYBAR", "RANGE", False),
    (1, "CLEAR", "RISK_INVALID", "RANGE", False),
])
def test_filter_scope(utc_hour, action, reason, environment, expected):
    evaluation = dict(bar_end=f"2026-11-27T{utc_hour:02}:00:00+00:00",
                      proposal=dict(action=action, reason=reason, plan=dict(environment=environment)))
    assert skip_first_entry(evaluation) is expected


def test_replay_skips_once_then_keeps_independent_flat_lifecycle_without_future_bars():
    originals = entry_bars()
    reflected = [
        bar(i, 210 - b.open, 210 - b.low, 210 - b.high, 210 - b.close)
        for i, b in enumerate(originals)
    ]
    series = reflected + [bar(8, 104, 108, 102, 106)]
    baseline = kernel.replay(series, as_of=until(series), timely_fixture=True)
    candidate = filtered_replay(series, until(series))
    at_first = filtered_replay(series, until(reflected))
    assert at_first == filtered_replay(reflected, until(reflected))
    skip = at_first["evaluations"][-1]["skipped_proposal"]
    assert skip["proposal_id"] == baseline["transitions"][0]["proposal_id"]
    assert skip["action"] == "ENTER_SHORT"
    assert not at_first["transitions"] and at_first["current_state"]["cycle_id"] is None
    assert at_first["evaluations"] == candidate["evaluations"][:len(reflected)]
    night = [replace(b, start=b.start + timedelta(hours=13), end=b.end + timedelta(hours=13)) for b in series]
    assert filtered_replay(night, until(night)) == kernel.replay(night, as_of=until(night), timely_fixture=True)


def test_direct_contribution_requires_original_proposal_and_allocates_residual():
    key = dict(window="sample", contract="JM2701")
    baseline = {"transitions": [{"proposal_id": "one", "action": "ENTER_SHORT", "after": {"cycle_id": "cycle"}}]}
    candidate = {"evaluations": [
        dict(bar_end="at", skipped_proposal=dict(proposal_id=i, generated_at="known", plan_id="plan",
                                                 state_fingerprint="flat"))
        for i in ("one", "after_divergence")
    ]}
    original = dict(cycle_id="cycle", entry_class="RANGE_SHORT", entry_session="DAY",
                    entry_at="open", gross=Decimal(-80), fee=Decimal(6), slippage=Decimal(20))
    segments = [dict(segment=1, net=Decimal(100))]
    operations = [dict(path="baseline", cycle_id="cycle", at="open", offset="OPEN",
                       side="short", shared=False, segment=1)]
    rows = direct_effects(key, baseline, candidate, [original], [], segments, operations)
    assert [r["status"] for r in rows] == ["DIRECT_CLOSED", "NO_COMMON_PREIMAGE"]
    assert rows[0]["effect"] == 106
    assert segments[0]["direct_net"] == 106 and segments[0]["remaining_path_net"] == -6
