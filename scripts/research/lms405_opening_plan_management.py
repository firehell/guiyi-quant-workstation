"""Compare published target progress with opposing geometry after a reference opening."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_opening_clock_comparison import REFERENCES, boundary_clocks
from lms405_opening_exit_sensitivity import BASE_SHA, BASELINE, OPENING, OPENING_SHA, SCENARIOS
from lms405_portfolio_replay import ARCHIVE, DAYS, FIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

VERSION = "lms405-opening-plan-management-v1"
PRICE_CASES = {
    "jm_new_short": ("JM2701", "2026-10-26", "2026-10-23T21:00", "WRo2KQ43iX", "A5357264059367516"),
    "soda_new_short": ("SA2701", "2026-10-27", "2026-10-26T21:00", "WRov1j6e10", "A5358325549629506"),
    "jm_target_control": ("JM2701", "2026-10-27", "2026-10-26T21:00", "WRov1j6e10", "A5358325549629506"),
}
SHORT_LEVELS = {
    "JM2701": (("1392", "1415.5"), ("1375", "1391"), ("1354.5", "1372.5")),
    "SA2701": (("951", "957"), ("943", "946"), ("932", "939")),
}
TARGET_CLOCKS = {
    "TARGET_NEAR_REACH": ("near", "first_range_reaches_direction"),
    "TARGET_FAR_REACH": ("far", "first_range_reaches_direction"),
    "TARGET_FAR_LITERAL_TOUCH": ("far", "first_range_contains_level"),
    "TARGET_FAR_STRICT_CLOSE": ("far", "first_close_strict_beyond"),
}
CONTROL_REVIEW = "WRoCqMClgV"
EXIT_COMPARISON = Path("output/lms405-opening-exit-sensitivity-20261125/final.json")
EXIT_COMPARISON_SHA = "dca775ec35043a9c5b240ad853014b61e3a0ce408fc3cd0561c087351a6d7290"


def summarize(minute_bars, events_by_clock, levels, *, as_of):
    minutes = [bar for bar in minute_bars if bar.end + US < as_of]
    if not minutes:
        raise ValueError("OPENING_PLAN_EMPTY_COMPLETED_PREFIX")
    prices = {role: {edge: boundary_clocks(minutes, level, "SHORT")
                     for edge, level in zip(("far", "near"), map(Decimal, band), strict=True)}
              for role, band in zip(("divider", "target_1", "target_2"), levels, strict=True)}
    target_marks = {rule: prices["target_1"][edge][measure] for rule, (edge, measure) in TARGET_CLOCKS.items()}
    geometry = {}
    for shape, confirm in VARIANTS:
        key = f"{shape}m_to_{confirm}m"
        visible = [event for event in events_by_clock[key] if event["available_at"] < as_of]
        after_targets = {rule: next((event for event in visible
                                   if when is not None and when + US < event["shape_end"] - shape * ONE), None)
                         for rule, when in target_marks.items()}
        geometry[key] = dict(count=len(visible), first_opposing=visible[0] if visible else None,
                             first_fresh_after_target=after_targets)
    second_near = prices["target_2"]["near"]["first_range_reaches_direction"]
    divider_far, divider_near = map(Decimal, levels[0])
    return dict(prices=prices, min_low=min(bar.low for bar in minutes), last_close=minutes[-1].close,
                geometry=geometry,
                close_back_in_divider_after_second_near=next((bar.end for bar in minutes
                    if second_near is not None and second_near + US < bar.start
                    and divider_far <= bar.close <= divider_near), None))


def assess(series, *, clock, entry, start, cutoff, quotes, exits, levels):
    end = series[1][-1].end + 2 * US
    held_start = entry + US
    post_entry = completed(series[1], held_start, end)
    event_args = dict(side="LONG", start=held_start)
    events = {f"{shape}m_to_{confirm}m": signals(series, shape, confirm, cut=end, **event_args)
              for shape, confirm in VARIANTS}
    checkpoints = {}
    exit_clocks = {datetime.fromisoformat(row["known_at"]) for row in exits}
    if not all(entry < stamp < cutoff for stamp in exit_clocks):
        raise ValueError("OPENING_PLAN_PROXY_EXIT_WINDOW_DRIFT")
    for anchor in sorted(set((*quotes, *exit_clocks, cutoff, end))):
        if anchor <= entry:
            checkpoints[str(anchor)] = None
            continue
        prefix = {p: [bar for bar in rows if bar.end + US < anchor] for p, rows in series.items()}
        prefix_events = {f"{shape}m_to_{confirm}m": signals(prefix, shape, confirm, cut=anchor, **event_args)
                         for shape, confirm in VARIANTS}
        scoped_events = {key: [row for row in rows if row["available_at"] < anchor] for key, rows in events.items()}
        result = summarize(post_entry, scoped_events, levels, as_of=anchor) if any(
            bar.end + US < anchor for bar in post_entry) else None
        if (prefix_events != scoped_events or result is not None and result != summarize(
            completed(prefix[1], held_start, anchor), prefix_events, levels, as_of=anchor,
        )):
            raise ValueError("OPENING_PLAN_PREFIX_DRIFT")
        checkpoints[str(anchor)] = result
    whole_night = summarize(completed(series[1], start, end), {key: [] for key in events}, levels, as_of=cutoff)
    return dict(reference_clock=clock, reference_entry_known_at=entry, before_post_target_clocks=whole_night["prices"],
                held_clock_checkpoints=checkpoints, first_visible_quote_candidates=list(quotes),
                observation_cutoff=cutoff, trading_day_end_cutoff=end,
                prior_proxy_clear_candidates=exits,
                candidates_require_shape_to_start_after_entry_and_target_if_required=True,
                actual_hold_permission=None, actual_protection_permission=None, actual_exit_permission=None)


def study(session, market):
    openings = verified_json(OPENING, OPENING_SHA)
    baseline = verified_json(BASELINE, BASE_SHA)
    exit_comparison = verified_json(EXIT_COMPARISON, EXIT_COMPARISON_SHA)
    if exit_comparison["frozen_opening_clock_sha256"] != OPENING_SHA or exit_comparison["baseline_sha256"] != BASE_SHA:
        raise ValueError("OPENING_PLAN_EXIT_REFERENCE_DRIFT")
    photo_path, photo_sha = REFERENCES["photos"]
    photos = verified_json(Path("output") / photo_path, photo_sha)["photos"]
    index = input_sources()
    sources = {}
    for key in sorted({CONTROL_REVIEW, *(source for cfg in PRICE_CASES.values() for source in cfg[3:])}):
        row = index[key]
        sources[key] = row | dict(archive_sha256=sha((ARCHIVE.parent / row["archive_path"]).read_bytes()))
    cases = {}
    for name, (contract, day, start_value, photo, plan) in PRICE_CASES.items():
        start, cutoff = at(start_value), stamp(sources[photo])
        if stamp(sources[plan]) + ONE >= start:
            raise ValueError("OPENING_PLAN_PUBLICATION_NOT_BEFORE_SESSION")
        series = read_window(session, market, contract, date.fromisoformat(day))
        market_digests = {f"{period}m": digest(rows) for period, rows in series.items()}
        exits = []
        if name in openings["cases"]:
            previous = openings["cases"][name]
            clock = next(clock for scenario, clock in SCENARIOS if scenario == name)
            if market_digests != previous["market"]:
                raise ValueError("OPENING_PLAN_FROZEN_MARKET_DRIFT")
            entry = datetime.fromisoformat(previous["gates"][f"keybar:{clock}"]) + 2 * US
            quotes = tuple(map(datetime.fromisoformat, previous["capture_boundaries"]))
            comparison = exit_comparison["scenarios"][f"{name}/{clock}"]
            if entry != datetime.fromisoformat(comparison["fixture_authorized_at"]):
                raise ValueError("OPENING_PLAN_EXIT_REFERENCE_DRIFT")
            for variant, outcome in comparison["outcomes"].items():
                first_clear = outcome["first_original_clear"]
                if first_clear is not None:
                    exits.append(first_clear | dict(variant=variant))
        else:
            reference_bars = read_session_series(session, market, "jm", contract, "5m", FIVE, DAYS)
            as_of = datetime.fromisoformat(baseline["as_of"])
            rows = [row for row in reference_bars if row.bar_end + US <= as_of]
            fingerprint = sha(encoded([[row.bar_end.isoformat(), *map(str, ohlc(row))] for row in rows]).encode())
            if fingerprint != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
                raise ValueError("OPENING_PLAN_CONTROL_BASELINE_DRIFT")
            clock = "1m_to_1m"
            first = signals(series, 1, 1, side="SHORT", start=start, cut=cutoff)[0]
            if first["confirmed_at"] != at("2026-10-26T21:05"):
                raise ValueError("OPENING_PLAN_CONTROL_REFERENCE_DRIFT")
            entry = first["available_at"] + US
            quotes = tuple(map(datetime.fromisoformat, photos[photo]["per_symbol"]["jm"]["contains"]))
        if (not start < entry < cutoff or not all(start < t < cutoff for t in quotes)
                or name in openings["cases"] and cutoff != datetime.fromisoformat(previous["cutoff_exclusive"])):
            raise ValueError("OPENING_PLAN_REFERENCE_WINDOW_DRIFT")
        mark = Decimal(photos[photo]["per_symbol"][contract[:-4].lower()]["mark"])
        by_end = {bar.end: bar for bar in series[1]}
        if any(not by_end[t].low <= mark <= by_end[t].high for t in quotes):
            raise ValueError("OPENING_PLAN_QUOTE_RANGE_DRIFT")
        cases[name] = assess(series, clock=clock, entry=entry, start=start, cutoff=cutoff, quotes=quotes,
                             exits=exits, levels=SHORT_LEVELS[contract]) | dict(
            contract=contract, trading_day=day, plan_source=plan, snapshot_source=photo,
            snapshot_mark=mark, market=market_digests, public_edition_at_event_verified=False,
            review_source=CONTROL_REVIEW if name == "jm_target_control" else None,
        )
    return dict(version=VERSION, cases=cases, sources=sources, frozen_opening_sha256=OPENING_SHA,
                frozen_portfolio_sha256=BASE_SHA, frozen_photos_sha256=photo_sha,
                frozen_exit_comparison_sha256=EXIT_COMPARISON_SHA,
                author_match_rate=None, admitted_author_actions=0, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OPENING_PLAN_') and code.isidentifier() else 'OPENING_PLAN_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
