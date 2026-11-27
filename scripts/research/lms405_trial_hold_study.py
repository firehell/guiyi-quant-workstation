"""Compare trial holding, flat reentry, and original-leg unlock in research."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.trial_hold import TrialHold, assess_trial_hold
from lms405_trial_to_trend import frozen
from lms_near405_replay import encoded

JM_CARRY_HASH = "271406451fa98ec2bdafa365ee255ad0a9634d4405ddee4a9b8ec874f2607295"
P2_HASHES = {
    "sh-both": "c8c535394d36728e6b92aae497c21e7f63237b8fbef3d305426abd93471893d3",
    "jm-13-all": "cc55208551e573271aeea8595f346250726231bdfc622f786c7f75fd5a499181",
    "jm-0-all": "1416254706c16620ddf4a67ede3f511a08c8ad27e92715f3611b6d1160ac3483",
}


def transition(step):
    before, after = step["before"], step["after"]
    if step["status"] != "CONDITIONAL_ACTION" or before["episode"] != after["episode"]:
        raise ValueError("FROZEN_POSITION_TRANSITION_CHANGED")
    return dict(operation=step["operation"], plan_id=step["current_plan_id"],
                before={key: before[key] for key in ("original", "protection", "counter_m", "attempt")},
                after={key: after[key] for key in ("original", "protection", "counter_m", "attempt")})


def report(jm_carry, p2_dir):
    carry = json.loads(frozen(jm_carry, JM_CARRY_HASH))
    p2 = {key: json.loads(frozen(p2_dir / f"{key}.json", expected)) for key, expected in P2_HASHES.items()}
    if any(not value["test_fixture_allowed"] or value["author_action_samples"] for value in p2.values()):
        raise ValueError("FROZEN_PATH_PERMISSIONS_CHANGED")

    plan_id, night_id = "A5358686423089344", "WRoEvasxQR"
    plan_seen = datetime.fromisoformat(carry["sources"][plan_id]["published_at"]) + timedelta(minutes=1)
    night_seen = datetime.fromisoformat(carry["sources"][night_id]["published_at"]) + timedelta(minutes=1)
    # No archived price or screenshot in this case confirms an attributable trial.
    archived = dict(status="INDETERMINATE", after=None, attributable_trial_id=None,
                    trial_started_at=None, trial_version_405=None, account_bound_snapshot_at=None)
    success, live = night_seen + timedelta(minutes=1), night_seen + timedelta(minutes=2)
    hypotheses = TrialHold(Position(carry["contract"], Decimal(20)), plan_id,
                           "JM2701:OCT27:TRIAL_HYPOTHESIS", plan_seen - timedelta(hours=1), plan_seen, live, True)
    facts = tuple(Condition(name, hypotheses.scope, carry["contract"], True, when, when, "TEST_FIXTURE", "EVENT_TIME")
                  for name, when in (("TRIAL_SUCCEEDED", success), ("TREND_CONFIRMED", success),
                                     ("SAME_TRIAL_STILL_OPEN", live)))
    fixture = assess_trial_hold(hypotheses, facts, as_of=live + timedelta(microseconds=1), allow_test_fixture=True)
    if fixture["after"] is None:
        raise ValueError("TRIAL_HOLD_PERMISSION_DIVERGED")

    unlock = transition(p2["sh-both"]["steps"][0])
    from_empty = {key: [transition(step) for step in p2[key]["steps"][-2:]]
                  for key in ("jm-13-all", "jm-0-all")}
    for exit_m, reentry in from_empty.values():
        if (exit_m["operation"] != "EXIT_COUNTER_M" or reentry["operation"] != "REENTER_TREND"
                or exit_m["after"] != reentry["before"] or reentry["before"]["attempt"] + 1 != reentry["after"]["attempt"]
                or any(Decimal(reentry["before"][key]) for key in ("original", "protection", "counter_m"))):
            raise ValueError("FROZEN_FLAT_REENTRY_IDENTITY_CHANGED")
    if (unlock["operation"] != "RECOVER_ORIGINAL" or unlock["before"]["attempt"] != unlock["after"]["attempt"]
            or unlock["before"]["original"] != unlock["after"]["original"]
            or not Decimal(unlock["before"]["protection"]) or Decimal(unlock["after"]["protection"])):
        raise ValueError("FROZEN_UNLOCK_IDENTITY_CHANGED")
    return dict(
        version="lms405-trial-position-paths-v1", references=dict(jm_carry=JM_CARRY_HASH, p2=P2_HASHES),
        paths={
            "trial_hold_jm2701_oct27": dict(
                sources=carry["sources"], archived_assessment=archived,
                fixture_assessment=fixture, fixture_kind="TEST_FIXTURE",
                conditional_same_long_lot_counts=carry["conditional_lunch_to_night_retention"],
                account_scope_verified=carry["account_and_position_scope_verified"],
                market_and_declared_bands=carry["night_window"],
            ),
            "flat_reentry_jm2701_oct23": dict(
                test_paths=from_empty, fixture_kind="TEST_FIXTURE",
                sources=["WRo0OCbeQG", "WRo00BFM1E", "WRo2KQ43iX"],
            ),
            "unlock_sh2701_oct27": dict(
                test_path=unlock, fixture_kind="TEST_FIXTURE",
                sources=["WRoAkcEppg", "U03", "WRoEvasxQR"],
            ),
        },
        author_action_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("jm-carry", "p2-dir", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    result = report(args.jm_carry, args.p2_dir)
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")


if __name__ == "__main__":
    main()
