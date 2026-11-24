"""Link protection diagnostics to one permission contract and one exposure fixture."""

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from guiyi_quant.lms405.participation import Participation, assess_participation
from guiyi_quant.lms405.public_conditions import Condition
from lms405_carry_in_study import position_fields
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, input_sources
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

US = timedelta(microseconds=1)
ONE = timedelta(minutes=1)
INPUTS = {
    "oi": "0271cef0df2294add8d42c399190c95da3f640b6423d0c87206f88e2fb267a98",
    "iron": "1343cd7c6487e4cddfb0538a03ca18bc588e5fb3846dcd43d22a04d110658163",
    "sh": "ef76957c9b72111725adddcf4be832e7825002b9050b217b81f21d8bcf8098eb",
    "exposure": EXPOSURE_SHA256,
}
SCREEN = "WRnTlEfj1t"


def fact(request, name, value, at, *, policy=False):
    return Condition(
        name, request.scope, request.position.contract, value, at, at, request.source,
        "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME" if policy else "EVENT_TIME",
    )


def source_episode(contract, side, source_id, source, end, diagnostics, *, version_405=None, no_chase=False):
    """Prices and substitute shapes remain diagnostics. No claimed author action is injected."""
    available = datetime.fromisoformat(source["published_at"]) + ONE
    as_of = datetime.fromisoformat(end)
    if available >= as_of:
        raise ValueError("SOURCE_EPISODE_BEFORE_POLICY_AVAILABLE")
    position = Position(contract, Decimal(int(side == "LONG")), Decimal(int(side == "SHORT")))
    request = Participation(position, side, source_id, "unit-hypothesis", available,
                            available, source["source_url"], version_405)
    facts = (fact(request, "RIGHT_POLICY_PERMITS", False, available, policy=True),) if no_chase else ()
    result = assess_participation(request, facts, as_of=as_of)
    return dict(
        source_id=source_id, source_available_at=available.isoformat(),
        position_kind="UNIT_HYPOTHESIS", assessment=result,
        right_policy_scope="AUTHOR_DESCRIBED_HIGH_DIVERGENCE_ASSUMED" if no_chase else None,
        historical_revision_verified=False, diagnostics=diagnostics,
        diagnostics_role="OBSERVATION_ONLY_NO_PROTECTION_SIGNAL_OR_DUE_FACT",
    )


def case_episodes(oi, iron, sh, sources):
    day, night = (sh["windows"][name] for name in ("day", "night"))
    oi_source, iron_source = oi["source_id"], iron["plan_source"]
    iron_cut = datetime.fromisoformat(iron["midday_quote_at"])
    iron_contacts = {
        name: value["first_trigger_bar_end"] for name, value in iron["area_conditions"].items()
        if value["first_trigger_bar_end"] and datetime.fromisoformat(value["first_trigger_bar_end"]) < iron_cut
    }
    cases = {
        "oi_early_long_protection": source_episode(
            "OI2609", "LONG", oi_source, sources[oi_source], oi["as_of"],
            dict(band_levels=oi["band_levels"], band_path=oi["band_path"],
                 geometry=oi["short_keybar_geometry"], suggested_context=oi["source_suggested_context_period"]),
            version_405=True,
        ),
        "iron_existing_short": source_episode(
            "I2701", "SHORT", iron_source, sources[iron_source], iron["midday_quote_at"],
            dict(contacts_strictly_before_quote=iron_contacts,
                 geometry=[row for row in iron["keybar"] if datetime.fromisoformat(row["next_5m_at"]) < iron_cut]),
        ),
    }
    for label, row, source_id in (("sh_day", day, "WRnOnrllRX"), ("sh_night", night, "A5356884885635211")):
        geometry = row["geometry"]
        cases[label] = source_episode(
            "SH2701", "SHORT", source_id, sources[source_id], row["participation"]["as_of"],
            {key: geometry[key] for key in ("band", "first_contact", "extension",
                                           "first_extension_reached", "geometric_confirmations")},
            no_chase=label == "sh_day",
        )
    return cases


def fixture_lock(position, known_at, *, protection_confirmed, no_chase):
    """Require explicit fixture evidence. A right policy veto can coexist with protection."""
    request = Participation(
        position, "SHORT", "fixture-protection", "fixture-old-short", known_at, known_at,
        "SYNTHETIC_PROTECTION_CONFIRMATION", True,
    )
    next_tick = known_at + US
    facts = [fact(request, "POSITION_CONFIRMED", True, known_at)]
    if no_chase:
        facts.append(fact(request, "RIGHT_POLICY_PERMITS", False, known_at))
    if protection_confirmed:
        facts += [fact(request, name, True, next_tick) for name in ("PROTECTION_DUE", "PROTECTION_SIGNAL")]
    assessment = assess_participation(request, tuple(facts), as_of=next_tick + US)
    lock_allowed = assessment["decisions"]["LOCK_PROTECTION"]["status"] == "CONDITIONS_MET"
    after = apply_action(position, Action("LOCK", position.short)) if lock_allowed else position
    return after, dict(
        status={key: row["status"] for key, row in assessment["decisions"].items()},
        fixture_action="LOCK" if lock_allowed else None,
    )


def totals(positions):
    return dict(
        short_contracts=sum(p.short > p.long for p in positions.values()),
        equal_locked_contracts=sum(p.long == p.short > 0 for p in positions.values()),
        gross_lots_subtotal=str(sum(p.long + p.short for p in positions.values())),
        abs_net_lots_subtotal=str(sum(abs(p.long - p.short) for p in positions.values())),
    )


def common_snapshot(exposure):
    (screen,) = [table for table in exposure["tables"] if table["source"] == SCREEN]
    image = screen["image"]
    if (screen["binding"] != "SYSTEM_COVER" or screen["system"] != "4.0.5"
            or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]):
        raise ValueError("COMMON_SNAPSHOT_IDENTITY_MISMATCH")
    positions, visible = {}, {}
    for contract, row in screen["contracts"].items():
        legs = row["legs"]
        if set(legs) != {"long", "short"} or legs["short"]["today_quantity"] != 0:
            raise ValueError("EXPECTED_VISIBLE_OLD_SHORT_AND_PROTECTION_PAIR")
        short, long = (Decimal(legs[side]["quantity"]) for side in ("short", "long"))
        if short <= 0 or short != long or Decimal(legs["long"]["today_quantity"]) != long:
            raise ValueError("EXPECTED_EQUAL_PAIR_WITH_CURRENT_LONG")
        positions[contract] = Position(contract, short=short)
        visible[contract] = Position(contract, long, short)
    known_at = datetime.fromisoformat(screen["published_at"]) + ONE
    scenarios = {}
    for label, confirmed in (
        ("no_confirmation", set()), ("iron_only", {"I2701"}), ("caustic_only", {"SH2701"}),
        ("iron_and_caustic", {"I2701", "SH2701"}),
    ):
        after, checks = {}, {}
        for contract, start in positions.items():
            after[contract], checks[contract] = fixture_lock(
                start, known_at, protection_confirmed=contract in confirmed, no_chase=contract == "SH2701",
            )
        scenarios[label] = dict(
            positions={key: position_fields(pos) for key, pos in after.items()},
            checks=checks, **totals(after),
        )
    return dict(
        source=screen["source"], source_url=screen["source_url"], image=image,
        available_at=known_at.isoformat(), quote_anchor=None,
        in_scope_contracts=sorted(positions), not_shown=sorted(set(CONTRACTS) - positions.keys()),
        starting_basis="REMOVE_VISIBLE_CURRENT_LONGS_AS_HYPOTHESIS_KEEP_OLDER_SHORTS",
        scenario_policy="TEST_FIXTURE_ONLY_SH_NEW_SHORT_VETO_NOT_CARRIED_FROM_DAY_PLAN",
        scenarios=scenarios, visible_image=dict(
            positions={key: position_fields(pos) for key, pos in visible.items()}, **totals(visible),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in INPUTS:
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("OUTPUT_EXISTS")
        loaded = {}
        for name, expected in INPUTS.items():
            raw = getattr(args, name).read_bytes()
            if sha(raw) != expected:
                raise ValueError(f"FROZEN_{name.upper()}_CHANGED")
            loaded[name] = json.loads(raw)
        episodes = case_episodes(loaded["oi"], loaded["iron"], loaded["sh"], input_sources())
        result = dict(
            version="lms405-protection-permission-portfolio-study-v1", input_sha256=INPUTS,
            episodes=episodes, common_snapshot=common_snapshot(loaded["exposure"]),
            executable=False, admitted_author_samples=0, author_matches=None, fills=None, pnl=None,
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
