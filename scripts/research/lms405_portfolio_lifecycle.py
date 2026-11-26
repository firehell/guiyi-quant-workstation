"""Replay one nine-contract evidence timeline and isolated conditional position episodes."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position, Zone
from guiyi_quant.lms405.handoff import HandoffConfirmation
from guiyi_quant.lms405.public_conditions import Condition
from guiyi_quant.lms405.public_plan_handoff import Publication
from lms405_lifecycle_tape import Attempt, Cursor, replay
from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_portfolio_staged_protection import SH_CYCLE_SHA
from lms405_portfolio_task_exits import HUMAN_SHA, ROOT
from lms405_protection_lot_timing import verified_json
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-lifecycle-v1"
REFS = {
    "portfolio": (ROOT / "human.json", HUMAN_SHA),
    "staged": (Path("output/lms405-portfolio-staged-protection-20261126/reviewed-a.json"),
               "a6732a86e139cb350d80a1615c1a5bf9f71c47d27289f2284144ca18aa3d0bd9"),
    "sh": (Path("output/lms405-sh-cycle-permissions-20261126/final-a.json"), SH_CYCLE_SHA),
    "pta": (Path("output/lms405-pta-public-plan-handoff-20261126/final-a.json"),
            "a2d127dacae7ebf7407233a1621012afe54df7d0bd1f9935d05e298fea87e6f6"),
    "ru": (Path("output/lms405-oi-ru-signal-deadlines-20261126/reviewed-a.json"),
           "6ebb8708b1058b68861f5ce38ecc851767f048381eaf8edabca6803f7be1a4fe"),
}
UNCOVERED = {
    "OI2701": "NEW_LONG_VISIBLE_ROLE_AND_CURRENT_PROTECTION_BAND_UNKNOWN",
    "SA2701": "VISIBLE_PROTECTION_WITHOUT_ADMITTED_TRIGGER",
    "V2701": "SEPARATE_PUBLIC_TARGET_AND_RECOVERY_PERMISSION; NO_LINKED_CURRENT_LIFECYCLE",
    "I2701": "NO_CURRENT_BOUND_PROTECTION_BAND_AND_UNLISTED_NIGHT_LONG",
}


def published(contract, revision, source, band=None):
    if sha((ARCHIVE.parent / source["archive_path"]).read_bytes()) != source["archive_sha256"]:
        raise ValueError("PORTFOLIO_LIFECYCLE_SOURCE_CHANGED")
    at = datetime.fromisoformat(source["published_at"])
    url = source["source_url"]
    zone = Zone(revision, contract, *map(Decimal, band), at + ONE, url) if band else None
    return Publication(revision, contract, at, at + ONE, url, zone)


def seed(episode, physical, at, *, long=0, short=0, protection=0):
    return Cursor(episode, "SEED", at, Position(physical, Decimal(long), Decimal(short)), Decimal(protection))


def candidate(step_id, before, operation, lots, clock, *, plan=None, offset=4, approve=True):
    attempt = Attempt(step_id, before, clock + offset * US, operation, Decimal(lots), clock + ONE, plan)
    request = attempt.request
    trigger = Condition("TRIGGER", request.scope, before.position.contract, True, clock, clock + US,
                        f"TEST_FIXTURE_TRIGGER:{step_id}", "EVENT_TIME")
    confirmation = HandoffConfirmation(request.confirmation_scope(trigger), f"TEST_FIXTURE:{step_id}",
                                       True, clock + 2 * US, clock + 3 * US, "TEST_FIXTURE") if approve else None
    return replace(attempt, trigger=trigger, approval=confirmation)


def next_cursor(attempt):
    after, protection = attempt.supported_projection()
    return Cursor(attempt.expected.episode, attempt.id, attempt.at, after, protection)


def construct(refs):
    seeds, attempts, publications = [], [], []
    for contract, amount, band in (("FG2701", 7, ("829", "836")), ("JM2701", 0, ("1382.5", "1397.5"))):
        row = refs["staged"]["cases"][contract]["first_night"]
        if amount not in row["compatible_early_lots"]:
            raise ValueError("PORTFOLIO_LIFECYCLE_STAGE_FIXTURE_CHANGED")
        touch, confirm = (datetime.fromisoformat(row[key]) for key in ("touch_at", "confirmation_at"))
        root = seed(f"{contract}:22N", contract, touch - 2 * ONE, short=row["whole_long"])
        plan = published(contract, row["plan"]["id"], row["plan"], band)
        seeds.append(root)
        publications.append(plan)
        before = root
        if amount:
            early = candidate(f"{contract}:EARLY", root, "PROTECT_ADD", amount, touch, plan=plan)
            attempts.append(early)
            before = next_cursor(early)
        top = candidate(f"{contract}:TOPUP", before, "PROTECT_ADD", row["whole_long"] - amount, confirm, plan=plan)
        if amount:
            attempts.extend((
                replace(top, observation=f"{contract}:NO_TOPUP_PERMISSION", at=confirm + 2 * US, approval=None),
                replace(top, observation=f"{contract}:REUSE_EARLY_APPROVAL", at=confirm + 3 * US,
                        approval=early.approval),
            ))
        attempts.extend((top, replace(top, observation=f"{contract}:REPEAT_TOPUP", at=confirm + 5 * US)))

    sh = refs["sh"]
    scenario = sh["scenarios"]["old_near_5m_to_1m:both_immediate"]
    noon = datetime.fromisoformat(sh["sources"]["WRoAkcEppg"]["published_at"]) + ONE
    paired = seed("SH2701:27D_TO_N", "SH2701", noon, long=20, short=20, protection=20)
    withdraw_clock = datetime.fromisoformat(scenario["recovery_candidate"]["confirmed_at"])
    fresh_clock = datetime.fromisoformat(scenario["protection_candidate"]["confirmed_at"])
    withdraw = candidate("SH:WITHDRAW_OLD", paired, "PROTECT_WITHDRAW", 20, withdraw_clock)
    night_plan = published("SH2701", "A5358686695981271", sh["sources"]["A5358686695981271"], ("1490", "1501"))
    replace_step = candidate("SH:PROTECT_NEW", next_cursor(withdraw), "PROTECT_ADD", 20, fresh_clock, plan=night_plan)
    seeds.append(paired)
    publications.append(night_plan)
    attempts.extend((withdraw, replace_step, replace(withdraw, observation="SH:REPEAT_WITHDRAW", at=replace_step.at + US)))

    ru = refs["ru"]["cases"]["RU2701"]
    if ru["old_short_retention"]["retained"] != [20]:
        raise ValueError("PORTFOLIO_LIFECYCLE_RU_SEED_CHANGED")
    shape = refs["ru"]["comparisons"][0]["cases"]["RU2701"]["clocks"]["candidates"][0]
    ru_clock = datetime.fromisoformat(shape["confirmed_at"])
    ru_root = seed("RU2701:27N", "RU2701", ru_clock - 16 * ONE, short=20)
    ru_band = published("RU2701", "A5358686695981271", ru["plan"], ru["band"])
    seeds.append(ru_root)
    publications.append(ru_band)
    attempts.append(candidate("RU:PROTECT", ru_root, "PROTECT_ADD", 20, ru_clock, plan=ru_band))

    pta = refs["pta"]
    paused = {key: published("TA2701", key, pta["sources"][key]) for key in pta["publication_timeline"]}
    publications.extend(paused.values())
    night = datetime.fromisoformat(pta["sources"][pta["carry"]["night_source"]]["published_at"]) + ONE
    morning = datetime.fromisoformat(pta["sources"][pta["carry"]["morning_source"]]["published_at"]) + ONE
    carried = seed("TA2701:23N_TO_26D", "TA2701", night, long=pta["carry"]["shown_long"])
    flat_control = seed("TA2701:PUBLIC_ENTRY_CONTROL", "TA2701", night)
    paused_plan = max((plan for plan in paused.values() if plan.known_at < night), key=lambda row: row.published_at)
    entry_paused = candidate("TA:PUBLIC_ENTRY_WITHHELD", flat_control, "ENTER_LONG", 1, night + ONE, plan=paused_plan)
    as_of = datetime.fromisoformat(pta["last_archived_publication_known_at"]) + ONE
    restarted = seed("TA2701:SYNTHETIC_RESTART", "TA2701", as_of - ONE)
    synthetic = "TEST_FIXTURE_PTA_NEW_REGION"
    reopened = Publication(synthetic, "TA2701", as_of, as_of, synthetic,
                           Zone(synthetic, "TA2701", Decimal(100), Decimal(110), as_of, synthetic))
    seeds.extend((carried, flat_control, restarted))
    publications.append(reopened)
    delayed_clear = candidate("TA:NO_OLD_POSITION_EXIT_PERMISSION", carried, "CLEAR", pta["carry"]["shown_long"],
                              morning, approve=False)
    expiry_control = candidate("TA:EXPIRED_OLD_EXIT", carried, "CLEAR", pta["carry"]["shown_long"], morning)
    restart = candidate("TA:REENTER", restarted, "REENTER_LONG", 1, as_of + ONE, plan=reopened)
    early_restart = candidate("TA:REENTER_STALE", restarted, "REENTER_LONG", 1, as_of - 10 * US, plan=reopened)
    attempts.extend((
        entry_paused, delayed_clear, replace(early_restart, at=as_of + US), restart,
        replace(restart, observation="TA:REENTER_AT_APPROVAL_CLOCK", at=restart.approval.known_at),
        replace(expiry_control, at=expiry_control.expires_at),
    ))
    return tuple(seeds), tuple(attempts), tuple(publications)


def run_mode(seeds, attempts, publications, cutoff, *, allow):
    events, state = replay(seeds, attempts, publications, cutoff=cutoff, allow_test_fixture=allow)
    times = {event["at"] for event in events} | {item.known_at for item in publications}
    resumed = 0
    for instant in sorted(t for t in times if t < cutoff):
        for split in (instant, instant + US):
            old, checkpoint = replay(seeds, attempts, publications, cutoff=split, allow_test_fixture=allow)
            tail, restored = replay(seeds, attempts, publications, cutoff=cutoff, start=split, cursors=checkpoint,
                                    allow_test_fixture=allow)
            if old != [event for event in events if event["at"] < split] or old + tail != events or restored != state:
                raise ValueError("PORTFOLIO_LIFECYCLE_RESTART_DIVERGED")
            resumed += 1
    return events, {key: asdict(row) for key, row in state.items()}, resumed


def study():
    refs = {key: verified_json(*file) for key, file in REFS.items()}
    baseline = refs["portfolio"]
    if set(baseline["contract_summaries"]) != set(CONTRACTS) or baseline["fixture"]:
        raise ValueError("PORTFOLIO_LIFECYCLE_SCOPE_CHANGED")
    cutoff = datetime.fromisoformat(baseline["as_of"])
    seeds, attempts, publications = construct(refs)
    factual_publications = tuple(row for row in publications if not row.source.startswith("TEST_FIXTURE"))
    public_episodes = tuple(row for row in seeds if row.episode != "TA2701:SYNTHETIC_RESTART")
    public_attempts = tuple(replace(row, approval=None, trigger=None) for row in attempts
                            if row.expected.episode != "TA2701:SYNTHETIC_RESTART")
    factual, public_end, public_prefixes = run_mode(public_episodes, public_attempts, factual_publications,
                                                   cutoff, allow=False)
    fixture, fixture_end, fixture_prefixes = run_mode(seeds, attempts, publications, cutoff, allow=True)
    if any(row.get("changed") for row in factual):
        raise ValueError("PORTFOLIO_LIFECYCLE_UNSUPPORTED_PUBLIC_ACTION")
    observations = [row for row in baseline["timeline"] if row["layer"] in ("AUTHOR_TEXT", "HOLDINGS_DISPLAY")]
    announced = [dict(at=row.known_at, kind="PLAN_PUBLICATION", publication=asdict(row),
                      mode="AUTHOR_PLAN_REFERENCE" if row in factual_publications else "TEST_FIXTURE")
                 for row in publications if row.known_at < cutoff]
    timeline = sorted([
        *(dict(at=datetime.fromisoformat(row["time"]), mode="AUTHOR_OBSERVATION", **row) for row in observations),
        *announced,
        *(row | {"mode": "PUBLIC_RESEARCH_PROJECTION"} for row in factual),
        *(row | {"mode": "TEST_FIXTURE"} for row in fixture),
    ], key=lambda row: (row["at"], row["mode"], row.get("episode", "")))
    return dict(
        version=VERSION, cutoff_exclusive=cutoff, contracts={contract: dict(
            episodes=[row.episode for row in seeds if row.position.contract == contract],
            remaining_input=UNCOVERED.get(contract),
        ) for contract in CONTRACTS}, timeline=timeline, public_projection=public_end, fixture_projection=fixture_end,
        restart_checks=dict(public=public_prefixes, fixture=fixture_prefixes),
        references={key: file[1] for key, file in REFS.items()}, seeds_are_distinct_research_hypotheses=True,
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("PORTFOLIO_LIFECYCLE_OUTPUT_EXISTS")
    try:
        result = study()
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith(('PORTFOLIO_LIFECYCLE_', 'LIFECYCLE_')) and code.isidentifier() else 'PORTFOLIO_LIFECYCLE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
