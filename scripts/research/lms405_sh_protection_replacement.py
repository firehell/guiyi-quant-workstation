"""Constrain SH2701 protection-leg replacement between two displayed averages."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import CLOSE, CONTRACT, LUNCH, NIGHT, completed, digest
from lms405_sizing_audit import SPECS, load_specs
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

LIFECYCLE = Path("output/lms405-sh-lock-lifecycle-20261125/report.json")
LIFECYCLE_SHA = "4bd0e828b6e654decbe6e2e8a5e3c547835c607f658b904b727aad3699368986"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
NIGHT_IMAGE_SHA = "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a"
NIGHT_TODAY_REREAD = 20
ORIGINAL = (Path("output/lms405-sh-original-short-20261126/verified-a.json"),
            "f87f4e253787c136307cac0da23b4f05ac3e564ee585982333f4bcc6b74d49de")
ORIGINAL_DAYS = tuple(date(2026, 10, day) for day in (16, 19, 20, 21, 22, 23, 26))
CYCLES = (Path("output/lms405-sh-cycle-permissions-20261126/final-a.json"),
          "f69045985afb4b72644c450627ba269eb35c3153361d6138964ffe8c022920a6")
COAL = (Path("output/lms405-jm-partial-carry-20261126/verified-a.json"),
        "eddece8ff04e266bd3722a5b1153bb55712266414b7837c1bbaaa92afc03945e")
CLOSE_GROSS = (182, (40, 40, 20, 10, 20, 16, 16, 20))


def compatible_counts(lots, old_total, new_total, old_ticks, afternoon_ticks, night_ticks):
    """Enumerate origin counts for the ending long using generous price-envelope intervals."""
    old_low, old_high = old_ticks
    day_low, day_high = afternoon_ticks or (0, 0)
    night_low, night_high = night_ticks or (0, 0)
    allowed = []
    for retained in range(lots + 1):
        replaced = lots - retained
        kept_low = max(retained * old_low, old_total.start - replaced * old_high)
        kept_high = min(retained * old_high, old_total.stop - 1 - replaced * old_low)
        if kept_low > kept_high:
            continue
        for day_lots in range(replaced + 1):
            night_lots = replaced - day_lots
            if (day_lots and afternoon_ticks is None) or (night_lots and night_ticks is None):
                continue
            ending_low = kept_low + day_lots * day_low + night_lots * night_low
            ending_high = kept_high + day_lots * day_high + night_lots * night_high
            if max(ending_low, new_total.start) <= min(ending_high, new_total.stop - 1):
                allowed.append([retained, day_lots, night_lots])
    return allowed


def extract_snapshots(reference):
    snapshots = reference["snapshots"]
    for source in (LUNCH, CLOSE, NIGHT):
        attachment = snapshots[source]["image"]
        if sha((ARCHIVE.parent / attachment["path"]).read_bytes()) != attachment["sha256"]:
            raise ValueError("SH_REPLACEMENT_SNAPSHOT_CHANGED")
    noon, closing, night = (snapshots[source]["legs"] for source in (LUNCH, CLOSE, NIGHT))
    if (not noon["short"] == closing["short"] == night["short"] or "long" in closing
            or noon["long"]["today_quantity"] != noon["long"]["quantity"]
            or night["long"]["today_quantity"] is not None
            or snapshots[NIGHT]["image"]["sha256"] != NIGHT_IMAGE_SHA
            or NIGHT_TODAY_REREAD != night["long"]["quantity"]
            or noon["long"]["quantity"] != night["long"]["quantity"]
            or Decimal(night["long"]["opening_average"]) != Decimal(reference["night_long_display_average"])):
        raise ValueError("SH_REPLACEMENT_LEG_FIELDS_CHANGED")
    return noon["long"], night["long"]


def retained_original_after_close(lots, total, original_ticks, close_minute_ticks):
    """Allow a same-day replacement in the ambiguous close minute, never an overnight today lot."""
    return sorted({retained for retained, _, _ in compatible_counts(
        lots, total, total, original_ticks, close_minute_ticks, None,
    )})


def check_permission_paths(reference, close, night_quotes, lots):
    cycles = verified_json(*CYCLES)
    if cycles["sources"] != reference["sources"] or (
        cycles["inputs"]["lifecycle"] != LIFECYCLE_SHA or cycles["contract"] != CONTRACT
        or any(Decimal(cycles["seed"][side]) != lots for side in ("long", "short"))
    ):
        raise ValueError("SH_REPLACEMENT_PERMISSION_SCOPE_CHANGED")
    paths = {}
    for name, path in cycles["scenarios"].items():
        trace = [(datetime.fromisoformat(row["as_of"]), row) for row in path["trace"]]
        if not all(int(row["original_short"]) == lots and int(row["short"]) == lots for _, row in trace):
            raise ValueError("SH_REPLACEMENT_PERMISSION_CHANGED_ORIGINAL_SHORT")
        observed_day = next((row for when, row in reversed(trace) if when <= close - ONE), cycles["seed"])
        held_at = []
        for label, facts in night_quotes.items():
            cut = datetime.fromisoformat(label) - ONE
            as_of = next(row for when, row in reversed(trace) if when <= cut)
            gate = "21:29" if name.endswith(":both_deferred") else "21:21"
            if (int(as_of["long"]) == int(as_of["new_protection_long"]) == lots
                    and facts["full_night_long_after_gate"][gate]):
                held_at.append(label)
        paths[name] = dict(
            initial_lots=cycles["seed"], projected_close_long=int(observed_day["long"]),
            projected_close_short=int(observed_day["short"]),
            recovery_confirmation=path["recovery_candidate"]["confirmed_at"],
            at_close_matches_if_table_complete=int(observed_day["long"]) == 0,
            night_strict_quote_labels=held_at,
            conditional_snapshot_compatibility=int(observed_day["long"]) == 0 and bool(held_at),
        )
    return paths


def compare_leg_lifetimes(session, market, reference, old_series, new_series, *, tick, lots, old_totals, new_totals):
    original, coal = verified_json(*ORIGINAL), verified_json(*COAL)["partial_carry_comparison"]
    raw, early = read_pair(session, market, CONTRACT, ORIGINAL_DAYS)
    if {f"{p}m": identity(rows) for p, rows in raw.items()} != original["market"]:
        raise ValueError("SH_REPLACEMENT_ORIGINAL_WINDOW_CHANGED")
    snapshots = reference["snapshots"]
    noon, close = (datetime.fromisoformat(snapshots[s]["quote_anchor"]) for s in (LUNCH, CLOSE))
    night_open, night_cut = (datetime.fromisoformat(reference[k]) for k in ("night_start", "night_cut"))
    long_old = [bar for bar in old_series[1] if bar.end <= noon - ONE]
    afternoon = [bar for bar in old_series[1] if noon <= bar.start and bar.end <= close - ONE]
    night = completed(new_series[1], night_open, night_cut)
    short = snapshots[CLOSE]["legs"]["short"]
    if any(snapshots[s]["legs"]["short"] != short for s in (LUNCH, NIGHT)) or (
        short["today_quantity"] != 0 or short["quantity"] != lots or Decimal(short["opening_average"]) != Decimal(1720)
    ):
        raise ValueError("SH_REPLACEMENT_OLD_SHORT_FIELDS_CHANGED")
    total = displayed_tick_totals(Decimal("1720.0"), lots, tick)
    original_ticks = tick_bounds(early[1], tick)
    close_minute_ticks = tick_bounds(old_series[1][-1:], tick)
    lunch_long_ticks = tick_bounds(long_old, tick)
    if (not earlier_lot_counts(None, original_ticks, lots, total)
            or not earlier_lot_counts(None, lunch_long_ticks, lots, old_totals)):
        raise ValueError("SH_REPLACEMENT_LUNCH_OPENING_AVERAGE_OUTSIDE_ENVELOPE")
    retained = retained_original_after_close(lots, total, original_ticks, close_minute_ticks)
    if not retained or sum(CLOSE_GROSS[1]) != CLOSE_GROSS[0] or "long" in snapshots[CLOSE]["legs"]:
        raise ValueError("SH_REPLACEMENT_CROSS_CASE_SCOPE_CHANGED")
    at_quote = {}
    combined = verified_json(
        Path("output/lms405-portfolio-coal-first-lock-20261126/verified-a.json"),
        "bcc41a64402e2c5735916ca3233e8d3509622bceab265e7af0b86b7c55e9327c",
    )
    reference_quote, = [row for row in combined["runs"]["TOUCH_FAR:IRON_RETAIN"]["comparisons"][CONTRACT]
                       if row["source"] == NIGHT and row["side"] == "long"]
    mark = Decimal(reference_quote["reported_quote"])
    for bar in night:
        if not bar.low <= mark <= bar.high:
            continue
        before_quote = [row for row in night if row.end <= bar.end - ONE]
        permissive = compatible_counts(lots, old_totals, new_totals, lunch_long_ticks,
                                       tick_bounds(afternoon, tick), tick_bounds(before_quote, tick))
        clock_choices = {}
        for clock in ("21:21", "21:29"):
            gate = at(f"2026-10-27T{clock}") + US
            allowed = [row for row in before_quote if gate < row.start]
            clock_choices[clock] = bool(earlier_lot_counts(None, tick_bounds(allowed, tick), lots, new_totals))
        at_quote[display(bar.end)] = dict(
            max_old_long_without_today=max((old for old, _, _ in permissive), default=None),
            full_night_long_possible=[0, 0, lots] in permissive,
            full_night_long_after_gate=clock_choices,
        )
    if set(map(datetime.fromisoformat, at_quote)) != set(map(
        datetime.fromisoformat, reference_quote["by_variant"]["strict_replay"],
    )):
        raise ValueError("SH_REPLACEMENT_NIGHT_QUOTE_SCOPE_CHANGED")
    return dict(
        lunch_seed=dict(trading_day=close.date(), direction_lots={"long": lots, "short": lots},
                        opening_average_price_compatible={"long": True, "short": True},
                        market_envelopes={"long": lunch_long_ticks, "short": original_ticks},
                        quote_minute_excluded=True, from_displayed_position=True),
        short_same_day_retained_if_same_account=lots,
        short_retained_after_close_allowing_ambiguous_close_minute=retained,
        prior_short_price_window=dict(days=ORIGINAL_DAYS, ticks=original_ticks, reference_sha256=ORIGINAL[1]),
        close_minute_ticks=close_minute_ticks, exact_short_origin_verified=False,
        close_table=dict(image=snapshots[CLOSE]["image"], total=CLOSE_GROSS[0], row_sizes=CLOSE_GROSS[1],
                         extra_longs_if_table_complete=0, account_completeness_verified=False),
        night_single_row_quote_checks=at_quote, night_old_protection_long_retained_if_same_account_and_trading_day=0,
        permission_replay_sha256=CYCLES[1], permission_paths=check_permission_paths(reference, close, at_quote, lots),
        coal_comparison=dict(reference_sha256=COAL[1], partial_price_compare_paths=sum(
            item["first_close_and_night_price_possible"] for item in coal["paths"].values()),
            shared_principle="TRACK_ORIGINAL_AND_PROTECTION_ORIGINS_SEPARATELY"),
        actual_fills=None, author_action_at=None, author_authorization_proven=False,
    )


def study(session, market, reference, spec, *, with_leg_lifetimes=False):
    old_leg, evening_leg = extract_snapshots(reference)
    old_series, new_series = (read_window(session, market, CONTRACT, date(2026, 10, day)) for day in (27, 28))
    for period in (1, 5):
        if reference["market"][f"{period}m"] != dict(afternoon=digest(old_series[period]), night=digest(new_series[period])):
            raise ValueError("SH_REPLACEMENT_FROZEN_MARKET_CHANGED")
    snapshots = reference["snapshots"]
    lunch, close = (datetime.fromisoformat(snapshots[source]["quote_anchor"]) for source in (LUNCH, CLOSE))
    night_open, night_cut = (datetime.fromisoformat(reference[key]) for key in ("night_start", "night_cut"))
    if old_series[1][-1].end != close or new_series[1][0].start != night_open or not lunch < close < night_open:
        raise ValueError("SH_REPLACEMENT_TRADING_DAY_BOUNDARY_CHANGED")
    tick, lots = spec["tick"], evening_leg["quantity"]
    old_totals = displayed_tick_totals(Decimal(old_leg["opening_average"]), lots, tick)
    new_totals = displayed_tick_totals(Decimal(reference["night_long_display_average"]), lots, tick)
    if reference["display_tick_totals"] != dict(noon_long=list(old_totals), night_long=list(new_totals)):
        raise ValueError("SH_REPLACEMENT_AVERAGE_CHANGED")
    old_bars = completed(old_series[1], old_series[1][0].start, lunch + 2 * US)
    night_bars = completed(new_series[1], night_open, night_cut)
    old_ticks, night_ticks = tick_bounds(old_bars, tick), tick_bounds(night_bars, tick)
    if old_ticks is None or night_ticks is None or not old_totals or not new_totals:
        raise ValueError("SH_REPLACEMENT_REQUIRED_WINDOW_MISSING")
    afternoon = {
        "after_lunch": completed(old_series[1], lunch, close + 2 * US),
        "after_1408_candidate": completed(old_series[1], at("2026-10-27T14:08") + US, close + 2 * US),
        "after_1434_candidate": completed(old_series[1], at("2026-10-27T14:34") + US, close + 2 * US),
        "only_night_additions": [],
    }
    for clock in ("14:08", "14:34"):
        afternoon[f"from_{clock.replace(':', '')}_overlap_allowed"] = completed(
            old_series[1], at(f"2026-10-27T{clock}"), close + 2 * US,
        )
    results = {}
    for label, bars in afternoon.items():
        day_ticks = tick_bounds(bars, tick)
        combinations = compatible_counts(lots, old_totals, new_totals, old_ticks, day_ticks, night_ticks)
        if not combinations:
            raise ValueError("SH_REPLACEMENT_NO_COMPATIBLE_ENVELOPE")
        old_retained, day_added, night_added = zip(*combinations, strict=True)
        results[label] = dict(
            afternoon_tick_envelope=day_ticks, afternoon_minutes=len(bars),
            origin_counts=combinations, old_retained=[min(old_retained), max(old_retained)],
            afternoon_new=[min(day_added), max(day_added)], night_new=[min(night_added), max(night_added)],
            minimum_removed=lots - max(old_retained),
        )
    night_only = results["only_night_additions"]["origin_counts"]
    with_today_field = [row for row in night_only if row[2] == NIGHT_TODAY_REREAD]
    if with_today_field != [[0, 0, lots]]:
        raise ValueError("SH_REPLACEMENT_TODAY_FIELD_PRICE_CONFLICT")
    first_whole_prefix = next(
        bar.end for index, bar in enumerate(night_bars, start=1)
        if earlier_lot_counts(None, tick_bounds(night_bars[:index], tick), lots, new_totals)
    )
    today_field = dict(
        source_id=NIGHT, image_sha256=NIGHT_IMAGE_SHA, reading="TWO_INDEPENDENT_NATIVE_PIXEL_READS",
        previous_transcription=None, today_quantity=NIGHT_TODAY_REREAD, today_available=NIGHT_TODAY_REREAD,
        conditions=["SAME_ACCOUNT", "POSITION_TODAY_FIELD_USES_TRADING_DAY", "NEW_SNAPSHOT_IN_NEXT_TRADING_DAY"],
        position_origin_counts=with_today_field, prior_displayed_long_lots_retained=0,
        latest_possible_whole_long_minute_start=reference["latest_possible_whole_long_minute_start"],
        first_completed_prefix_with_whole_long_price_compatibility=display(first_whole_prefix),
    )
    extra = {}
    if with_leg_lifetimes:
        extra["cross_case_leg_lifetimes"] = compare_leg_lifetimes(
            session, market, reference, old_series, new_series, tick=tick, lots=lots,
            old_totals=old_totals, new_totals=new_totals,
        )
    return dict(version="lms405-sh-protection-replacement-v1", contract=CONTRACT, specification=spec,
                lifecycle_sha256=LIFECYCLE_SHA, snapshots=snapshots, old_ticks=old_ticks, night_ticks=night_ticks,
                old_minute_count=len(old_bars), night_minute_count=len(night_bars),
                without_night_today_quantity=results, with_night_today_quantity=today_field,
                volume_and_price_evaluation="CONDITIONAL_TICK_ENVELOPES_ONLY", account_continuity=None,
                actual_legs_closed=None, close_snapshot_unshown_long=None, author_action_at=None,
                author_actions_scored=0, executable=False, fills=None, pnl=None, **extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare-leg-lifetimes", action="store_true")
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
        reference = verified_json(LIFECYCLE, LIFECYCLE_SHA)
        spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), reference, spec,
                           with_leg_lifetimes=args.compare_leg_lifetimes)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('SH_REPLACEMENT_') and code.isidentifier() else 'SH_REPLACEMENT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
