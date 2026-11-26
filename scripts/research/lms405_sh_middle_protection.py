"""Back-to-back protection changes between the early SH short and late relock."""

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_divider_short_candidates import divider_short_events
from lms405_m_permission_study import read_pair
from lms405_portfolio_leg_audit import SIZE, SIZE_SHA, SPECS, SPECS_SHA, leg_changes, load_specs, lot_profile, summarize
from lms405_portfolio_origin_window import ALL_DAYS, compare_rows
from lms405_portfolio_protection_gate import plan_rows
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import gated_replay, published_protection_events, replay_scoped_policy
from lms405_protection_handoff_candidates import HandoffPlan, handoff_events, scope_armed_replacement
from lms405_protection_lot_timing import verified_json
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_rubber_protection_handoff import displayed_minute_end
from lms405_sh_entry_and_handoff import CONTRACT, ENTRY, NEW_PROTECTION, OLD_LOCK, RECOVERY_REF, REREVIEW, case_options
from lms405_sh_lock_lifecycle import digest, signals
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

BASELINE = (Path("output/lms405-sh-entry-and-handoff-20261126/final-a.json"),
            "a842d3a14a2057418cc382661d2e9708b59d804239f4b8be390e0f9e5886e8e3")
INTERMEDIATE = (Path("output/lms405-sh-intermediate-chain-20261126/final-a.json"),
                "f223aadaa91b576429213971f58ee97861125e3a978bbc2c36577f8c7cffac41")
MID_LOCK = "A5357264793370945"
SINGLE_SIDE_TABLES = ("WRoqSWwLTg", "WRovrUdwHi")
MORNING_CUT = at("2026-10-27T10:13")
MORNING_SOURCE = "WRozNbg3en"
MODES = ("PENDING", "TOUCH_FAR", "CLOSE_BELOW_FAR")


def geometry_recoveries(series, start, cutoff, revision, *, close_below=None):
    """The scoped old lock must exist before a fresh 5m shape confirms down on 1m."""
    result = []
    for signal in signals(series, 5, 1, side="SHORT", start=start, cut=cutoff):
        ready = signal["available_at"] + 5 * US
        shape_start = signal["shape_end"] - 5 * ONE
        if ready < cutoff and (close_below is None or signal["close"] < close_below):
            result.append(dict(at=ready, known_at=signal["available_at"], shape_start=shape_start,
                               first_break_start=shape_start, contract=CONTRACT, revision=revision,
                               old_lock_revision=revision, signal=signal, period=5,
                               clock="FRESH_SHORT_SHAPE" if close_below is None else "FRESH_SHORT_BELOW_REFERENCE",
                               close_below_sensitivity=close_below))
    return result


def target_reclaim(minutes, known_at, cutoff, mode):
    """Post-review sensitivity: target completion, then separately recover both edges."""
    if mode not in MODES[1:]:
        raise ValueError("SH_MIDDLE_RECLAIM_MODE_INVALID")
    low, high = Decimal(1483), Decimal(1485)
    morning = at("2026-10-27T09:00")
    completed = near_known = previous = None
    for bar in minutes:
        if bar.end + US >= cutoff:
            break
        if bar.start <= known_at:
            continue
        if completed is None and (bar.low <= low <= bar.high if mode == "TOUCH_FAR" else bar.close < low):
            completed = bar.end + US
        if bar.start < morning or completed is None or not completed < bar.end:
            continue
        if previous is None or previous.end != bar.start or bar.close <= low:
            near_known = None
        if previous is not None and previous.end == bar.start and completed < bar.start:
            if near_known is not None and near_known < bar.start and previous.close <= high < bar.close:
                return dict(target_completed_at=completed, near_reclaimed_at=near_known,
                            far_reclaimed_at=bar.end + US, close=bar.close, bar_start=bar.start)
            if near_known is None and previous.close <= low < bar.close:
                near_known = bar.end + US
        previous = bar
    return None


def pending_review(bands, when):
    visible = visible_bands(bands, CONTRACT, when)
    eligible = [row for row in visible if row.role != "TARGET" and row.side == "SHORT" and row.effective_after < when]
    _, reason = active_band(visible, when, "SHORT")
    return reason == "PROTECTION_RANGE_REVIEW_PENDING" and max(eligible, key=lambda row: row.effective_after).revision == REREVIEW


def phase_events(series, bands, sources, cutoff, mode, night_edge):
    protections = published_protection_events(series, bands, cutoff, advance_at_touch=True)
    day_end = at("2026-10-23T15:01")
    recoveries = geometry_recoveries(series, at("2026-10-23T09:00"), min(day_end, cutoff), OLD_LOCK)
    mid_known = displayed_minute_end(sources[MID_LOCK])
    mid_day_end = at("2026-10-26T15:01")
    recoveries += geometry_recoveries(series, mid_known, min(mid_day_end, cutoff), MID_LOCK, close_below=night_edge)
    immediate = published_protection_events(series, bands, cutoff, advance_at_touch=False)
    protections += [e | dict(contract=CONTRACT, required_recovery=OLD_LOCK) for e in immediate
                    if e["band"].revision == MID_LOCK and e["operation"] == "PROTECT_EARLY"]
    if mode != "PENDING":
        revised = displayed_minute_end(sources[REREVIEW])
        observation = target_reclaim(series[1], revised, min(cutoff, MORNING_CUT), mode)
        if (observation is not None and observation["far_reclaimed_at"] + 5 * US < cutoff
                and all(pending_review(bands, clock) for clock in (
                    observation["bar_start"], observation["far_reclaimed_at"] + 5 * US,
                ))):
            band = ProtectionBandUpdate(CONTRACT, REREVIEW, "PROTECTION", revised, revised,
                                       sources[REREVIEW]["source_url"], "SHORT", Decimal(1483), Decimal(1485))
            protections.append(dict(at=observation["far_reclaimed_at"] + 5 * US,
                                    known_at=observation["far_reclaimed_at"], shape_start=observation["bar_start"],
                                    contract=CONTRACT, required_recovery=MID_LOCK, band=band, period=1,
                                    signal={"close": observation["close"]}, operation="PROTECT_REGULAR",
                                    target_role_sensitivity=observation | dict(mode=mode)))
        late = HandoffPlan(CONTRACT, REREVIEW, RECOVERY_REF, displayed_minute_end(sources[RECOVERY_REF]),
                           at("2026-10-27T11:35"), Decimal(1511), NEW_PROTECTION,
                           displayed_minute_end(sources[NEW_PROTECTION]), at("2026-10-27T21:00"),
                           "FAR_CLOSE_THEN_SHAPE", "ARM_THEN_TOUCH")
        late_recoveries, _ = handoff_events(series, bands, late, cutoff)
        recoveries += late_recoveries
        protections = scope_armed_replacement(protections, late)
    return (sorted(protections, key=lambda row: (row["at"], row["period"])),
            sorted(recoveries, key=lambda row: (row["at"], row["period"])))


def replay_middle(series, entry, bands, sources, cutoff, mode, night_edge):
    prefix = {p: [bar for bar in bars if bar.end + US < cutoff] for p, bars in series.items()}
    protect, recover = phase_events(prefix, bands, sources, cutoff, mode, night_edge)
    return gated_replay(prefix[5], cutoff, protect, minutes=prefix[1], recovery_events=recover,
                        divider_events=divider_short_events(prefix, entry, cutoff),
                        range_exit_requires_confirmation=True)


def table_conditions(actions, observations):
    changes = leg_changes(CONTRACT, actions)
    results = {}
    for name in SINGLE_SIDE_TABLES:
        checks = {}
        for value in observations[name]["quote_anchors"]:
            start = datetime.fromisoformat(value) - ONE
            state = next((s for when, s in reversed(changes) if when < start), {})
            checks[value] = dict(short_present="short" in state, long_absent="long" not in state)
        results[name] = checks
    return results


def reread_morning_field(rows, observation):
    """Apply the documented image reread for this experiment's comparison only."""
    image = observation["image"]
    reread = observation["field_reread"]
    if (sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
            or reread != dict(field="long.today_quantity", frozen=None, value=20, image_sha256=image["sha256"])):
        raise ValueError("SH_MIDDLE_MORNING_REREAD_CHANGED")
    output = []
    for row in rows:
        if (row["source"], row["side"]) == (MORNING_SOURCE, "long"):
            if (row["visible"] | dict(today_quantity=20)) != observation["legs"]["long"] or (
                row["visible"]["today_quantity"] is not None or observation["legs"]["short"]["today_quantity"] != 0
            ):
                raise ValueError("SH_MIDDLE_MORNING_VISIBLE_SCOPE_CHANGED")
            row = row | dict(visible=observation["legs"]["long"], paired_today_leg=True)
        output.append(row)
    return output


def study(session, market):
    reference = verified_json(*BASELINE)
    observation_scope = verified_json(*INTERMEDIATE)["observations"]
    index = input_sources()
    sources = {key: load_source(index, key) for key in (ENTRY, OLD_LOCK, MID_LOCK, RECOVERY_REF, REREVIEW, NEW_PROTECTION)}
    bands, _, _ = plan_rows(index, CONTRACT)
    days = tuple(day for day in ALL_DAYS if day >= date(2026, 10, 19))
    raw, market_bars = read_pair(session, market, CONTRACT, days)
    cutoff = at("2026-10-28T15:00") + 3 * US
    portfolio_spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
    unit_projection = lot_profile(verified_json(SIZE, SIZE_SHA))[CONTRACT]
    windows = {}
    for key, frozen in reference["windows"].items():
        start = date.fromisoformat(key)
        series = {p: [bar for native, bar in zip(raw[p], market_bars[p], strict=True) if native.trading_day >= start]
                  for p in (1, 5)}
        minutes = [bar for bar in raw[1] if bar.trading_day >= start]
        if (identity(minutes) != frozen["market"]["minutes"] or digest(series[5]) != frozen["market"]["five_digest"]):
            raise ValueError("SH_MIDDLE_FROZEN_MARKET_CHANGED")
        control = frozen["cases"]["FIRST_FAR_CLOSE_WITH_HANDOFF"]
        scoring_rows = reread_morning_field(control["comparisons"], observation_scope[MORNING_SOURCE])
        entry, previous_handoff = case_options(sources, "FIRST_FAR_CLOSE", True)
        control_actions, control_blocked, *_ = replay_scoped_policy(
            series[5], minutes, cutoff, index, published_bands=True, right_entries=True, left_mode="shape-overlap",
            advance_at_touch=True, range_exit_requires_confirmation=True, handoff_plan=previous_handoff,
            divider_short_plan=entry,
        )
        if json.loads(encoded((control_actions, control_blocked))) != [control["actions"], control["blocked"]]:
            raise ValueError("SH_MIDDLE_CONTROL_CHANGED")
        results = {}
        for mode in MODES:
            for night_edge in (None, Decimal(1543)):
                def replay_at(cut):
                    return replay_middle(series, entry, bands, sources, cut, mode, night_edge)

                actions, blocked = replay_at(cutoff)
                for cut in (at("2026-10-23T22:03"), at("2026-10-26T11:30"), at("2026-10-26T23:00"),
                            MORNING_CUT, at("2026-10-27T15:00"), at("2026-10-27T21:40")):
                    if replay_at(cut) != ([row for row in actions if datetime.fromisoformat(row["at"]) < cut],
                                          [row for row in blocked if row["at"] < cut]):
                        raise ValueError("SH_MIDDLE_ACTION_PREFIX_CHANGED")
                comparisons = compare_rows(CONTRACT, control["comparisons"], "replay", actions, minutes,
                                           unit_projection, None, portfolio_spec["tick"])
                with_reread = compare_rows(CONTRACT, scoring_rows, "replay", actions, minutes,
                                           unit_projection, None, portfolio_spec["tick"])
                strict = summarize({CONTRACT: with_reread})[CONTRACT]["strict_replay"]
                portfolio = control["portfolio"]
                if portfolio is not None:
                    portfolio = {name: value - control["strict"].get(name, 0) + strict.get(name, 0)
                                 for name, value in portfolio.items()}
                label = f"{mode}:{'BELOW_1543' if night_edge else 'SHAPE_ONLY'}"
                results[label] = dict(actions=actions, blocked=blocked, comparisons=with_reread,
                                      conditional_absent_long=table_conditions(actions, observation_scope),
                                      strict=strict, portfolio=portfolio,
                                      strict_frozen_fields=summarize({CONTRACT: comparisons})[CONTRACT]["strict_replay"])
        windows[key] = dict(control=control["strict"], cases=results)
    return dict(version="lms405-sh-middle-protection-v1", contract=CONTRACT, windows=windows, sources=sources,
                morning_field_reread=observation_scope[MORNING_SOURCE]["field_reread"],
                cited_baseline_sha256=BASELINE[1], cited_intermediate_sha256=INTERMEDIATE[1],
                target_reclaim_is_assumed_protection_mode=True, snapshot_positions_used_as_inputs=False,
                unlisted_side_is_unknown=True, approvals_are_fixtures=True, author_action_samples=0,
                author_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from sqlalchemy.exc import OperationalError
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('SH_MIDDLE_') and code.isidentifier() else 'SH_MIDDLE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
