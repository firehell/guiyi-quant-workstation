"""Test source-linked OI2701 leg interpretations against completed price evidence."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from lms405_common_protection_window import OCT27_QUOTES, OCT27_SNAPSHOT
from lms405_i2701_case import FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import display, ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

CONTRACT = "OI2701"
DAY = date(2026, 10, 28)
START, CUT = at("2026-10-27T21:00"), at("2026-10-27T22:12")
SOURCES = ("A5357264059367516", "A5358325549629506", "WRoCuRq1nf", "A5358686423089344",
           "U03", OCT27_SNAPSHOT, "S5341725283323022", "S5343801842598111")
DIVIDER = (10240, 10283)
DOWNWARD_NODES = ((10125, 10142), (10094, 10115))
UPWARD_NODE = (10321, 10356)
DISPLAYED_OPENING_AVERAGE = Decimal("10224.0")  # One decimal digit preserved in the saved screenshot.
COMMON = Path("output/lms405-common-protection-oct27-20261125/final.json")
COMMON_SHA = "1f8faeba34873d4be26cb01145dbb994305c01aa45a0af3d905ea35442f09264"
CONTINUITY = Path("output/lms405-position-continuity-20261125/final.json")
CONTINUITY_SHA = "664dad4a242846f9602f86839788a319bf3d0091ece2e7a3cbdedaa731ccca60"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
RANGE_REFERENCE = (Path("output/lms405-oi-range-roles-20261125/final.json"),
                   "2270fc86233facf687b31566dd9d24d557e258cfbabaed2380fbe8fe3e04451e")
RECOVERY_REFERENCE = (Path("output/lms405-recovery-path-20261125/final.json"),
                      "46eaa17983c645fd9035dd4317851e2d47ffc26b7105f45aed37e1efaa768fa7")


def first_contact(bars, band):
    low, high = band
    return next((bar for bar in bars if bar.low <= high and bar.high >= low), None)


def lot_bound(bars, cutoff, *, lots, tick, totals):
    earlier = [bar for bar in bars if bar.start < cutoff]
    later = [bar for bar in bars if bar.start >= cutoff]
    before, after = tick_bounds(earlier, tick), tick_bounds(later, tick)
    possibilities = earlier_lot_counts(before, after, lots, totals)
    if not possibilities:
        raise ValueError("OI_LEG_TICK_SUM_INCOMPATIBLE")
    return dict(window_cutoff=cutoff, first_later_completed_minute_end=display(later[0].end) if later else None,
                prior_tick_range=before, later_tick_range=after,
                minimum_prior_lots=min(possibilities), maximum_prior_lots=max(possibilities),
                whole_leg_after_possible=0 in possibilities)


def evidence(common, continuity):
    index = input_sources()
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in SOURCES}
    prior_plan = datetime.fromisoformat(sources["A5358686423089344"]["published_at"])
    if not prior_plan < START < CUT == datetime.fromisoformat(sources[OCT27_SNAPSHOT]["published_at"]):
        raise ValueError("OI_LEG_SOURCE_ORDER_CHANGED")
    snapshots = continuity["sources"]
    (transition,) = [row for row in continuity["contracts"][CONTRACT]["transitions"]
                     if (row["earlier"], row["later"]) == ("U03", OCT27_SNAPSHOT)]
    image = common["image"]
    if (common["source_id"] != OCT27_SNAPSHOT or image != snapshots[OCT27_SNAPSHOT]["image"]
            or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]):
        raise ValueError("OI_LEG_TABLE_CHANGED")
    return sources, transition


def study(session, market, common, continuity, quotes, specification):
    sources, transition = evidence(common, continuity)
    raw, series = read_pair(session, market, CONTRACT, (DAY,))
    identity = readback(raw[1])[DAY.isoformat()]
    frozen_market = common["input_1m"][CONTRACT]
    if identity != {key: frozen_market[key] for key in identity}:
        raise ValueError("OI_LEG_COMMON_MARKET_CHANGED")
    if identity != quotes["market_1m"]["oi"][DAY.isoformat()]:
        raise ValueError("OI_LEG_FROZEN_MARKET_CHANGED")
    minutes = completed(series[1], START, CUT)
    joint = common["by_contract"][CONTRACT]
    if len(minutes) != common["input_1m"][CONTRACT]["window_minutes"]:
        raise ValueError("OI_LEG_COMMON_WINDOW_CHANGED")
    lots, average, tick = joint["quantity"], DISPLAYED_OPENING_AVERAGE, specification["tick"]
    new_long = transition["later_legs"]["long"]
    if (new_long["quantity"] != lots or new_long["today_quantity"] != lots
            or Decimal(new_long["opening_average"]) != average or Decimal(joint["shown_average"]) != average
            or transition["sides"]["short"]["bounds"] != [40, 40]):
        raise ValueError("OI_LEG_POSITION_CONTEXT_CHANGED")
    totals = displayed_tick_totals(average, lots, tick)
    bound_args = dict(lots=lots, tick=tick, totals=totals)
    compatible = [bar for bar in minutes if bar.low <= average <= bar.high]
    if (len(compatible) != joint["number_of_minimum_windows"]
            or [display(compatible[0].end), display(compatible[-1].end)] != [
                joint["first_single_minute_end"], joint["last_single_minute_end"],
            ]):
        raise ValueError("OI_LEG_COMMON_AVERAGE_CHANGED")

    divider = first_contact(minutes, DIVIDER)
    if divider is None:
        raise ValueError("OI_LEG_FIRST_DIVIDER_CONTACT_NOT_FOUND")
    first_close_inside = next((bar for bar in minutes if DIVIDER[0] <= bar.close <= DIVIDER[1]), None)
    roles = {
        "divider_first_contact_including_entire_contact_minute": lot_bound(minutes, divider.start, **bound_args),
        "divider_first_contact_after_contact_minute": lot_bound(minutes, divider.end, **bound_args),
        "divider_first_close_inside_following_minute_overlap_allowed": (
            lot_bound(minutes, first_close_inside.end, **bound_args) if first_close_inside else None
        ),
        "divider_first_close_inside_only_wholly_later_minutes": (
            lot_bound(minutes, first_close_inside.end + US, **bound_args) if first_close_inside else None
        ),
    }
    geometry = {}
    for shape, confirmation in ((1, 1), (5, 1), (5, 5)):
        events = signals(series, shape, confirmation, side="LONG", start=START + US, cut=CUT)
        geometry[f"{shape}m_to_{confirmation}m"] = [
            event | dict(
                earlier_than_first_divider_contact_bar=event["available_at"] < divider.start,
                inside_divider_at_confirmation=DIVIDER[0] <= event["close"] <= DIVIDER[1],
                after_available_wholly_later=lot_bound(minutes, event["available_at"], **bound_args),
            ) for event in events
        ]
    return dict(
        version="lms405-oi-leg-intent-study-v1", contract=CONTRACT, trading_day=DAY.isoformat(),
        sources=sources, snapshot_transition=transition, start=display(START), cutoff_exclusive=display(CUT),
        market={"1m": identity, "5m": dict(count=len(series[5]), sha256=digest(series[5]))},
        observed_lots=lots, opening_average=average, total_ticks=list(totals), spec=specification,
        range=[min(bar.low for bar in minutes), max(bar.high for bar in minutes)],
        average_compatible_minute_ends=[display(bar.end) for bar in compatible],
        divider=DIVIDER, first_divider_contact_minute=dict(start=display(divider.start), end=display(divider.end),
                                                            ohlc=ohlc(divider)),
        first_divider_close_inside=display(first_close_inside.end) if first_close_inside else None,
        divider_upper_strict_close=next((display(bar.end) for bar in minutes if bar.close > DIVIDER[1]), None),
        downward_nodes=[dict(band=band, first_contact=display(bar.end) if (bar := first_contact(minutes, band))
                             else None) for band in DOWNWARD_NODES],
        upward_node=dict(band=UPWARD_NODE, touched=first_contact(minutes, UPWARD_NODE) is not None),
        lot_condition_comparison=roles, geometry=geometry, author_signal_at=None, author_leg_intent=None,
        author_action_at=None, executable=False, fills=None, pnl=None,
    )


def quote_relation(event_known_at, quote_end):
    if event_known_at is None:
        return "EVENT_UNAVAILABLE"
    if event_known_at < quote_end - ONE:
        return "BEFORE_QUOTE_MINUTE"
    if event_known_at < quote_end:
        return "WITHIN_QUOTE_MINUTE"
    return "AT_OR_AFTER_QUOTE_END"


def standing_long(series, observations, upper, start, cut):
    """A fresh shape must start during a continuous run after two complete closes."""
    runs = strict_runs(observations, Decimal(upper), "LONG")
    two = next((end for end, run in runs.items() if run["close_count"] >= 2), None)
    candidates = {}
    for shape, confirm in VARIANTS:
        kept = []
        for event in signals(series, shape, confirm, side="LONG", start=start, cut=cut):
            run = runs.get(event["confirmed_at"])
            if not run or run["close_count"] < 2:
                continue
            stand = event["confirmed_at"] - (run["close_count"] - 2) * ONE
            if stand + US < event["shape_end"] - shape * ONE:
                kept.append(dict(event=event, two_closes_known_at=stand + US))
        candidates[f"{shape}m_to_{confirm}m"] = kept
    return dict(first_strict_close=next(iter(runs), None), first_two_strict_closes=two,
                fresh_long_in_same_run=candidates)


def role_study(session, market, common, continuity, quotes, specification):
    base = study(session, market, common, continuity, quotes, specification)
    september = verified_json(*RANGE_REFERENCE)["cases"]["september_protection_plan"]
    recovery = verified_json(*RECOVERY_REFERENCE)["cases"]["OI-long"]
    sources = base["sources"]
    known_recovery = datetime.fromisoformat(sources["S5341725283323022"]["published_at"]) + ONE
    known_protection = datetime.fromisoformat(sources["S5343801842598111"]["published_at"]) + ONE
    october = read_window(session, market, CONTRACT, DAY)
    protected = read_window(session, market, CONTRACT, date(2026, 9, 17))
    reverse = read_window(session, market, CONTRACT, date(2026, 9, 11))
    fingerprints = {name: {f"{p}m": dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()}
                    for name, series in (("october", october), ("protection", protected), ("reversal", reverse))}
    oct_compact = [[b.end.isoformat(), *map(str, ohlc(b))] for b in october[1]]
    if (sha(json.dumps(oct_compact, separators=(",", ":")).encode()) != base["market"]["1m"]["ohlc_sha256"]
            or any(fingerprints["protection"][key] != val for key, val in september["market"].items())
            or digest(reverse[1]) != recovery["local_market_sha256"]):
        raise ValueError("OI_LEG_ROLE_MARKET_CHANGED")
    last_protection = protected[1][-1].end + 2 * US
    protected_obs = completed(protected[1], known_protection, last_protection)
    band = (10059, 10109)
    protection_low = min(b.low for b in protected_obs)
    if protection_low <= band[1] or first_contact(protected_obs, band) is not None:
        raise ValueError("OI_LEG_ROLE_REFERENCE_RANGE_CHANGED")
    protection = dict(band=band, low=protection_low, high=max(b.high for b in protected_obs), overlap=False,
                      signal_counts_confirmed_above_upper={f"{p}m_to_{c}m": sum(row["close"] > band[1]
                          for row in signals(protected, p, c, side="LONG", start=known_protection,
                                             cut=last_protection)) for p, c in VARIANTS})
    reverse_cut = reverse[1][-1].end + 2 * US
    reverse_obs = completed(reverse[1], known_recovery, reverse_cut)
    reversal = standing_long(reverse, reverse_obs, 10270, known_recovery, reverse_cut)
    expected_reversal_price = recovery["routes"]["price_recovery_candidate"]["first_active"]
    if len(reverse_obs) != recovery["plan_observable_minutes"] or (
        display(reversal["first_two_strict_closes"]) != expected_reversal_price
    ):
        raise ValueError("OI_LEG_ROLE_REVERSAL_PRICE_CHANGED")

    whole_day_cut = october[1][-1].end + 2 * US
    oct_full = standing_long(october, october[1], DIVIDER[1], START, whole_day_cut)
    minutes = completed(october[1], START, CUT)
    contact = first_contact(minutes, DIVIDER)
    inside = next((b for b in minutes if DIVIDER[0] <= b.close <= DIVIDER[1]), None)
    if contact is None or inside is None:
        raise ValueError("OI_LEG_ROLE_DIVIDER_CONTACT_CHANGED")
    marks = quotes["photos"][OCT27_SNAPSHOT]["per_symbol"]["oi"]
    totals = displayed_tick_totals(DISPLAYED_OPENING_AVERAGE, base["observed_lots"], specification["tick"])
    results = {}
    for label in marks["contains"]:
        quote = datetime.fromisoformat(label)
        cut = quote - ONE
        current = completed(october[1], START, cut)
        prefix = {p: [b for b in bars if b.end + US < cut] for p, bars in october.items()}
        context = standing_long(october, current, DIVIDER[1], START, cut)
        if context != standing_long(prefix, current, DIVIDER[1], START, cut):
            raise ValueError("OI_LEG_ROLE_PREFIX_CHANGED")
        price = {row["confirmed_at"].isoformat(): lot_bound(current, row["available_at"],
                         lots=base["observed_lots"], tick=specification["tick"], totals=totals)
                 for events in base["geometry"].values() for row in events if row["available_at"] < cut}
        relation = quote_relation(inside.end + US, quote)
        results[label] = dict(
            quote_anchor_verified=False, price_of_long_after_early_candidate=price,
            raw_touch_minute_overlaps_quote=contact.start < quote and quote - ONE < contact.end,
            completed_first_range_touch_relation=quote_relation(contact.end + US, quote),
            completed_first_close_inside_relation=relation,
            hypothetical_first_close_exit=dict(
                prerequisites=["ASSUMED_QUOTE_MATCH_AND_SYNCHRONOUS_POSITION", "SAME_ACCOUNT_AND_LONG_ROLE",
                               "FULL_LONG_EXIT_WHEN_FIRST_CLOSE_INSIDE_BECOMES_KNOWN", "NO_REENTRY_BEFORE_QUOTE"],
                conflicts_with_visible_long=relation == "BEFORE_QUOTE_MINUTE",
            ),
            strong_side_context=context,
        )
    return dict(version="lms405-oi-protection-or-short-term-v1", contract=CONTRACT, sources=sources,
                market=fingerprints, september_protection=protection, september_reversal=reversal,
                october_full_trading_day=dict(maximum_high=max(b.high for b in october[1]), strength_proxy=oct_full),
                october_divider_clocks=dict(range_touch_minute_end=contact.end, first_close_inside=inside.end),
                october_quote_cases=results, october_actual_protection_band=None,
                author_vplus=None, proven_author_leg_role=None, author_action_samples=0, author_match_rate=None,
                assumptions=dict(october_comparison_upper_used_only_for_test=True,
                                 september_window_starts=dict(protection=known_protection, reversal=known_recovery)),
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role-contrast", action="store_true")
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        common = verified_json(COMMON, COMMON_SHA)
        continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
        quotes = verified_json(OCT27_QUOTES, FROZEN_COMPARISON_SHA256)
        specification = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            run = role_study if args.role_contrast else study
            report = run(session, build_market_data_service(session), common, continuity, quotes, specification)
        report["input_sha256"] = dict(common=COMMON_SHA, continuity=CONTINUITY_SHA, quotes=FROZEN_COMPARISON_SHA256)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OI_LEG_') and code.isidentifier() else 'OI_LEG_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
