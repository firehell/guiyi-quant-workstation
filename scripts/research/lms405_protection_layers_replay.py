"""Replay price context, opposite confirmation and permission as separate protection conditions."""

import argparse
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from guiyi_quant.lms405.public_conditions import Condition, PublicCase, assess_case
from lms405_first_night_confirmation_clocks import POST, START
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_protection_lot_timing import verified_json
from lms405_protection_portfolio_study import totals
from lms405_right_side_study import ONE, US
from lms_near405_replay import encoded, sha

VERSION = "lms405-layered-protection-replay-v1"
PA_REPORT = Path("output/lms405-first-night-pa-20261125/final.json")
PA_HASH = "c1604a4edbd31a2e9abe20488a2e70bbe7662cb404c57b7784c8d6bf5fb37c56"
PA_LEVELS = {"I2701": "interruption_far", "SA2701": "interruption_far", "SH2701": "interruption_near"}
ROUTES = (
    ("OPENING_CONTEXT", "PROTECTION_REFERENCE", "PA_PRICE_OBSERVATION", "OPPOSITE_VPLUS", "LOCK_PERMISSION"),
    ("OPENING_CONTEXT", "PROTECTION_REFERENCE", "EXPLICIT_ADVANCE_ROUTE", "OPPOSITE_VPLUS", "LOCK_PERMISSION"),
)
ORDER = (
    ("OPENING_CONTEXT", "OPPOSITE_VPLUS"),
    ("PROTECTION_REFERENCE", "OPPOSITE_VPLUS"),
    ("PA_PRICE_OBSERVATION", "OPPOSITE_VPLUS"),
    ("EXPLICIT_ADVANCE_ROUTE", "OPPOSITE_VPLUS"),
    ("OPPOSITE_VPLUS", "LOCK_PERMISSION"),
)


def fact(case, name, at, source, *, value=True, known_at=None):
    return Condition(name, case.id, case.contract, value, at, at if known_at is None else known_at, source, "EVENT_TIME")


def assessment(case, position, facts, cut):
    return assess_case(case, position, Action("LOCK", position.short), tuple(facts), as_of=cut)


def trace(case, position, facts, cut):
    moments = {obs.known_at for obs in facts if obs.known_at < cut} | {cut}
    moments |= {instant + US for instant in moments if instant + US <= cut}
    rows = []
    for moment in sorted(moments):
        prefix = [obs for obs in facts if obs.known_at < moment]
        result = assessment(case, position, facts, moment)
        if result != assessment(case, position, prefix, moment):
            raise ValueError("PROTECTION_LAYERS_PREFIX_DIVERGED")
        rows.append(dict(cutoff=moment, status=result["status"], routes=result["routes"], after=result["after"]))
    return rows


def measure(position, result):
    if result["after"] is None:
        return position
    return Position(position.contract, Decimal(result["after"]["long"]), Decimal(result["after"]["short"]))


def replay(clock, pa):
    if pa["prior_sha256"] != REFERENCE_HASH or pa["photo"] != clock["photo"]:
        raise ValueError("PROTECTION_LAYERS_FROZEN_REPORT_SCOPE_CHANGED")
    if sha((ARCHIVE.parent / clock["photo"]["path"]).read_bytes()) != clock["photo"]["sha256"]:
        raise ValueError("PROTECTION_LAYERS_PHOTO_CHANGED")
    cases, initial, legacy, evidence, with_fixture = {}, {}, {}, {}, {}
    for contract in CONTRACTS:
        if contract not in clock["cases"]:
            cases[contract] = dict(status="NO_ROW_IN_THIS_405_SNAPSHOT", position=None, lock=None)
            continue
        row = clock["cases"][contract]
        before = Position(contract, short=Decimal(row["original_short"]["quantity"]))
        initial[contract] = before
        opening_end = START + ONE
        published = datetime.fromisoformat(row["plan"]["published_at"]) + ONE
        plan_url = row["plan"]["source_url"]
        case = PublicCase(f"{VERSION}:{contract}", contract, plan_url, published, True, ("LOCK",), ROUTES, ORDER)
        facts = [fact(case, "OPENING_CONTEXT", opening_end, "FROZEN_LOCAL_COMPLETED_OPENING_BAR", known_at=opening_end + US)]
        if row["protection_band"] is not None:
            facts.append(fact(case, "PROTECTION_REFERENCE", published, plan_url))
        pa_row = pa["cases"].get(contract)
        selected = None
        if pa_row is not None:
            if pa_row["market"] != row["market"]:
                raise ValueError("PROTECTION_LAYERS_MARKET_REPORT_MISMATCH")
            selected = pa_row["levels"][PA_LEVELS[contract]]["first_known_upward_excursion_inside_minute"]
        if selected is not None:
            end = datetime.fromisoformat(selected["bar_end"])
            known = datetime.fromisoformat(selected["facts_known_at"])
            facts.append(fact(case, "PA_PRICE_OBSERVATION", end, "FROZEN_OHLC_UPWARD_CROSSING_PROXY", known_at=known))
        actual = assessment(case, before, facts, POST)
        if actual["after"] is not None:
            raise ValueError("PROTECTION_LAYERS_ACTION_WITHOUT_SIGNAL_AND_PERMISSION")
        evidence[contract] = before
        shapes = [entry["first_candidate"] for entry in row["clocks"].values() if entry["first_candidate"]]
        legacy_event = min(shapes, key=lambda event: event["available_at"], default=None)
        legacy[contract] = apply_action(before, Action("LOCK", before.short)) if legacy_event else before

        fixture = None
        with_fixture[contract] = before
        if selected is not None:
            signal = known + US
            permission = signal + US
            positive = fact(case, "OPPOSITE_VPLUS", signal, "TEST_FIXTURE_VPLUS")
            accept = fact(case, "LOCK_PERMISSION", permission, "TEST_FIXTURE_PERMISSION")
            modes = dict(
                signal_only=(*facts, positive),
                permission_only=(*facts, accept),
                both=(*facts, positive, accept),
                denied=(*facts, positive, fact(case, "LOCK_PERMISSION", permission, "TEST_FIXTURE_DENIAL", value=False)),
                same_time_permission=(*facts, positive, fact(case, "LOCK_PERMISSION", signal, "TEST_FIXTURE_SAME_TIME")),
            )
            if contract == "SH2701":
                early = opening_end + 2 * US
                modes["explicit_advance_route"] = (
                    *facts,
                    fact(case, "EXPLICIT_ADVANCE_ROUTE", opening_end + US, "TEST_FIXTURE_ADVANCE_ROUTE"),
                    fact(case, "OPPOSITE_VPLUS", early, "TEST_FIXTURE_ADVANCE_VPLUS"),
                    fact(case, "LOCK_PERMISSION", early + US, "TEST_FIXTURE_ADVANCE_PERMISSION"),
                )
            verdicts = {name: trace(case, before, items, POST) for name, items in modes.items()}
            if any(verdicts[name][-1]["after"] is not None for name in (
                "signal_only", "permission_only", "denied", "same_time_permission",
            )):
                raise ValueError("PROTECTION_LAYERS_UNSUPPORTED_FIXTURE_ACTION")
            if (verdicts["both"][-1]["after"] is not None) != (contract in ("SA2701", "SH2701")):
                raise ValueError("PROTECTION_LAYERS_REFERENCE_FIXTURE_DIVERGED")
            if contract == "SH2701":
                early_rows = verdicts["explicit_advance_route"]
                first_after = next((item["cutoff"] for item in early_rows if item["after"] is not None), None)
                if first_after is None or first_after >= known:
                    raise ValueError("PROTECTION_LAYERS_ADVANCE_ROUTE_DIVERGED")
            with_fixture[contract] = measure(before, verdicts["both"][-1])
            fixture = dict(kind="TEST_FIXTURE", cases=verdicts)
        cases[contract] = dict(
            position=asdict(before), initial_basis="HYPOTHETICAL_OLD_SHORT_FROM_LATER_405_SNAPSHOT",
            plan=row["plan"], photo_market_fingerprint=row["market"], plan_band=row["protection_band"],
            opening_context=dict(first_completed_at=opening_end, observations=pa_row["first_bar"] if pa_row else None),
            pa_level_policy=PA_LEVELS.get(contract), price_proxy=selected,
            baseline=dict(method="FIRST_OPPOSING_GEOMETRY_ONLY_SENSITIVITY", candidate=legacy_event,
                          projected=asdict(legacy[contract])),
            layered_evidence=dict(timeline=trace(case, before, facts, POST), facts=[asdict(item) for item in facts]),
            fixture=fixture, author_vplus_at=None, author_permission=None, author_action_at=None,
        )
    if set(initial) != set(clock["cases"]):
        raise ValueError("PROTECTION_LAYERS_PORTFOLIO_SCOPE_CHANGED")
    return dict(
        version=VERSION, cases=cases, first_night_price_study_sha256=REFERENCE_HASH, pa_study_sha256=PA_HASH,
        portfolio=dict(initial=totals(initial), geometry_only=totals(legacy), layered_public_evidence=totals(evidence),
                       layered_authority_fixture=totals(with_fixture)),
        report_cutoff_exclusive=POST, strategy_version_scope="4.0.5_SNAPSHOT_CONTEXT_ONLY",
        historical_plan_revision_verified=False, author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    try:
        report = replay(verified_json(REFERENCE, REFERENCE_HASH), verified_json(PA_REPORT, PA_HASH))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("PROTECTION_LAYERS_") and code.isidentifier()
                        else "PROTECTION_LAYERS_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
