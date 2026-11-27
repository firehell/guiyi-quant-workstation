"""Test RU2701 protective candidates against conditional quote windows and fill price bounds."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from guiyi_quant.lms405 import Bar
from lms405_i2701_case import FROZEN_COMPARISON_SHA256
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_replay import display, ohlc, read_session_series
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded, sha

VERSION = "lms405-rubber-quote-windows-v2"
RELEASE_VERSION = "lms405-rubber-first-night-release-v1"
CONTRACT = "RU2701"
TIMING = Path("output/lms405-pre-touch-protection-20261125/final.json")
TIMING_SHA = "d5053217c8be047d853955709fdca77b8b268656f5cb2af0b078574399e94a60"
NIGHT_QUOTE = Path("output/lms-i2701-oct-20261125/comparison.json")


def partition_tick_bounds(bars, tick, edge, *, below):
    """Envelopes for prices on either side of the observed band's relevant edge."""
    edge_ticks = edge / tick
    if edge_ticks != int(edge_ticks):
        raise ValueError("RU_PROTECTION_EDGE_OFF_TICK")
    edge_ticks = int(edge_ticks)
    outside, other = [], []
    for bar in bars:
        lo, hi = tick_bounds((bar,), tick)
        if below:
            outside.append((lo, min(hi, edge_ticks - 1)))
            other.append((max(lo, edge_ticks), hi))
        else:
            outside.append((max(lo, edge_ticks + 1), hi))
            other.append((lo, min(hi, edge_ticks)))

    def envelope(pieces):
        valid = [(lo, hi) for lo, hi in pieces if lo <= hi]
        return (min(lo for lo, _ in valid), max(hi for _, hi in valid)) if valid else None

    return envelope(outside), envelope(other)


def price_constraints(bars, *, tick, lots, average, band):
    """Lower bound on same-side outside lots if the entire leg formed in this interval."""
    below = average < band[0]
    if not (below or average > band[1]):
        raise ValueError("RU_DISPLAY_AVERAGE_SHOULD_BE_OUTSIDE_BAND")
    edge = band[0] if below else band[1]
    outside, other = partition_tick_bounds(bars, tick, edge, below=below)
    counts = earlier_lot_counts(outside, other, lots, displayed_tick_totals(average, lots, tick))
    return dict(
        completed_minutes=len(bars), price_extrema_ticks=tick_bounds(bars, tick),
        whole_leg_price_possible=bool(counts), relative_side="BELOW" if below else "ABOVE",
        minimum_lots_outside_on_that_side=min(counts, default=None),
    )


def compare_candidate(bars, event, known_at, anchors, leg):
    eligible = [b for b in bars if b.start > known_at]
    by_anchor = {display(anchor): price_constraints([b for b in eligible if b.end <= anchor], **leg)
                 for anchor in anchors}
    earliest = next((label for label, bounds in by_anchor.items() if bounds["whole_leg_price_possible"]), None)
    return dict(known_at=known_at, event=event, by_quote_minute=by_anchor, first_compatible_quote_minute=earliest,
                before_post=price_constraints(eligible, **leg))


def compare_release_lots(bars, *, touch, confirmed, anchors, tick, lots, average):
    """Necessary lot counts and the earliest complete prefix supporting the whole leg."""
    if not touch < confirmed:
        raise ValueError("RU_RELEASE_GATE_ORDER_CHANGED")
    totals = displayed_tick_totals(average, lots, tick)
    paths = {}
    for name, gate in (("first_contact", touch), ("completed_confirmation", confirmed)):
        eligible = [bar for bar in bars if bar.start > gate]
        # An immediately completed opening minute and a later admissible aggregate are distinct events.
        first = next(iter(eligible), None)
        next_window = tick_bounds(eligible[:1], tick)
        earliest = next((bar.end + US for i, bar in enumerate(eligible, 1)
                         if earlier_lot_counts(None, tick_bounds(eligible[:i], tick), lots, totals)), None)
        paths[name] = dict(gate_known_at=gate, first_unambiguous_minute_end=first.end if first else None,
                           first_unambiguous_minute_ticks=next_window,
                           whole_leg_possible_in_first_minute=bool(earlier_lot_counts(None, next_window, lots, totals)),
                           earliest_whole_leg_compatible_completed_prefix_known_at=earliest)

    comparisons = []
    for anchor in anchors:
        scopes = {}
        for name, prefix in (
            ("before_quote_minute_start", [b for b in bars if b.end + US < anchor - ONE]),
            ("through_quote_minute_end", [b for b in bars if b.end <= anchor]),
        ):
            early = [b for b in prefix if b.start > touch and b.end + US < confirmed]
            late = [b for b in prefix if b.start > confirmed]
            early_overlap = [b for b in prefix if b.end > touch and b.start < confirmed]
            late_overlap = [b for b in prefix if b.end > confirmed]
            variants = {}
            for type_, earlier, later in (("complete_minutes_only", early, late),
                                           ("boundary_minutes_allowed", early_overlap, late_overlap)):
                early_bounds, late_bounds = tick_bounds(earlier, tick), tick_bounds(later, tick)
                counts = earlier_lot_counts(early_bounds, late_bounds, lots, totals)
                variants[type_] = dict(early_minutes=len(earlier), later_minutes=len(later),
                                       early_tick_bounds=early_bounds, later_tick_bounds=late_bounds,
                                       possible_lots_after_touch_before_confirmation=counts,
                                       whole_leg_possible_only_after_confirmation=0 in counts)
            scopes[name] = variants
        comparisons.append(dict(quote_minute_end=anchor, scopes=scopes))
    return dict(paths=paths, by_quote_minute=comparisons, displayed_tick_total_range=(totals.start, totals.stop - 1))


def visible_leg_args(case):
    visible = case["visible_leg"]
    if sha((ARCHIVE.parent / visible["image"]["path"]).read_bytes()) != visible["image"]["sha256"]:
        raise ValueError("RU_HOLDINGS_IMAGE_CHANGED")
    return dict(tick=Decimal(visible["tick_size"]), lots=visible["quantity"],
                average=Decimal(visible["display_average"]), band=tuple(map(Decimal, case["band"])))


def candidate_events(case):
    for variant, events in case["variants"].items():
        for event in events:
            available = datetime.fromisoformat(event["available_at"])
            if event["survives_both_diagnostics"]:
                gate = datetime.fromisoformat(event["touch_known_at"])
                yield variant, "PRE_TOUCH_SIGNAL_RETAINED_TO_CONTACT", event, gate, event["observed_leg_price_after_touch"]
            if event["first_touch_known_before_shape"]:
                yield variant, "SHAPE_AFTER_CONTACT", event, available, event["observed_leg_price_after_signal"]
    for variant, events in case["opening_pinbar_in_band_sensitivity"].items():
        for event in events:
            available = datetime.fromisoformat(event["available_at"])
            yield variant, "OPENING_PINBAR_IN_BAND_CONFIRMATION", event, available, event["observed_leg_price_after_signal"]


def case_metadata(case, quote_row):
    return dict(contract=CONTRACT, trading_day=case["trading_day"], plan=case["plan"], visible_leg=case["visible_leg"],
                first_contact_minute=case["contact_bar_ends"][0],
                photo_quote=dict(value=Decimal(quote_row["mark"]), compatible_minute_ends=quote_row["contains"],
                                 close_equal=quote_row["equal_close"], whole_photo_exact_time=None),
                actual_signal_at=None, actual_action_at=None, fills=None)


def joint_quote_timing(photo):
    """Find the shortest hypothetical observation span for all displayed marks."""
    comparison = {}
    for field in ("contains", "equal_close"):
        times = {key: {datetime.fromisoformat(value) for value in row[field]}
                 for key, row in photo["per_symbol"].items()}
        timeline = sorted(set().union(*times.values()))
        best_count, best_minutes, shortest, witnesses = 0, [], None, []
        latest = {}
        for end in timeline:
            matched = sorted(key for key, ends in times.items() if end in ends)
            if len(matched) > best_count:
                best_count, best_minutes = len(matched), []
            if len(matched) == best_count:
                best_minutes.append(dict(minute_end=display(end), unmatched=sorted(times.keys() - set(matched))))
            latest.update((key, end) for key in matched)
            if latest.keys() != times.keys():
                continue
            width = int((end - min(latest.values())) / ONE)
            if shortest is None or width < shortest:
                shortest, witnesses = width, []
            if width == shortest:
                witness = {key: display(value) for key, value in latest.items()}
                witnesses.append(dict(last_minute_end=display(end), matched_per_symbol=witness))
        comparison[field] = dict(symbols=len(times), best_same_minute_count=best_count, best_minutes=best_minutes,
                                 minimum_bar_end_separation_minutes=shortest, witnesses=witnesses)
    return comparison


def compare_frozen_case(case, quote_row):
    """Use only frozen price extrema; individual quote prefixes remain unverified."""
    leg = visible_leg_args(case)
    anchors = [datetime.fromisoformat(value) for value in quote_row["contains"]]
    reports = []
    for variant, mode, event, known, snapshot in candidate_events(case):
        low, high = map(Decimal, snapshot["extrema"])
        # Treat the union as one price envelope. This only gives a necessary bound.
        bounds = price_constraints([SimpleNamespace(low=low, high=high)], **leg)
        reports.append(dict(variant=variant, mode=mode, event=event, known_at=known,
                            before_post=bounds | {"completed_minutes": snapshot["minute_count"]},
                            quote_minutes_too_early=[display(anchor) for anchor in anchors if anchor <= known + ONE],
                            by_quote_minute=None, first_compatible_quote_minute=None))
    return case_metadata(case, quote_row) | dict(candidates=reports, whole_observation=None)


def compare_case(minutes, case, quote_row, *, compare_release=False):
    start, cut = (datetime.fromisoformat(case[key]) for key in ("start", "cut"))
    if digest(minutes) != case["market"]["1m"]:
        raise ValueError("RU_FROZEN_MINUTE_INPUT_CHANGED")
    bars = [bar for bar in minutes if start <= bar.start and bar.end + US < cut]
    mark = Decimal(quote_row["mark"])
    anchors = [bar.end for bar in bars if bar.low <= mark <= bar.high]
    if not anchors or [display(anchor) for anchor in anchors] != quote_row["contains"]:
        raise ValueError("RU_FROZEN_QUOTE_WINDOWS_CHANGED")
    leg = visible_leg_args(case)
    reports = [dict(variant=variant, mode=mode, **compare_candidate(bars, event, known, anchors, leg))
               for variant, mode, event, known, _ in candidate_events(case)]
    result = case_metadata(case, quote_row) | dict(whole_observation=price_constraints(bars, **leg), candidates=reports)
    if compare_release:
        touch, = {row["known_at"] for row in reports if row["mode"] == "PRE_TOUCH_SIGNAL_RETAINED_TO_CONTACT"}
        confirm, = {row["known_at"] for row in reports if row["mode"] == "OPENING_PINBAR_IN_BAND_CONFIRMATION"}
        result["release_lot_comparison"] = compare_release_lots(
            bars, touch=touch, confirmed=confirm, anchors=anchors,
            tick=leg["tick"], lots=leg["lots"], average=leg["average"],
        )
    return result


def run_cases(args, cases):
    if args.frozen_only:
        return {key: compare_frozen_case(case, quote) for key, (case, quote) in cases.items()}
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    result = {}
    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            market = build_market_data_service(session)
            for key, (case, quote) in cases.items():
                bars = read_session_series(session, market, "ru", CONTRACT, "1m", ONE,
                                           (date.fromisoformat(case["trading_day"]),))
                minutes = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in bars]
                result[key] = compare_case(minutes, case, quote,
                                           compare_release=args.first_night_release and key == "ru_first_night")
    except (OperationalError, MarketDataError) as exc:
        raise ValueError("LOCAL_MARKET_READ_FAILED") from exc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env-file", type=Path)
    source.add_argument("--frozen-only", action="store_true")
    parser.add_argument("--first-night-release", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.env_file and not args.env_file.is_file()) or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    if args.frozen_only and args.first_night_release:
        parser.error("RELEASE_COMPARISON_REQUIRES_COMPLETE_LOCAL_MINUTES")

    timing = verified_json(TIMING, TIMING_SHA)
    snapshots = (verified_json(PHOTO, PHOTO_SHA), verified_json(NIGHT_QUOTE, FROZEN_COMPARISON_SHA256))
    cases, photos = {}, {}
    for key, snap in zip(("ru_first_night", "ru_before_m"), snapshots, strict=True):
        case = timing["cases"][key]
        photo = snap["photos"][case["visible_leg"]["source"]]
        cases[key], photos[key] = (case, photo["per_symbol"]["ru"]), photo
    try:
        results = run_cases(args, cases)
        for key, result in results.items():
            result["joint_quote_timing"] = joint_quote_timing(photos[key])
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(dict(version=RELEASE_VERSION if args.first_night_release else VERSION,
                                      cases=results, source_signal_samples=0, author_matches=None,
                                      historical_orders=None, executable=False,
                                      individual_quote_price_prefixes_checked=not args.frozen_only,
                                      input_hashes=[TIMING_SHA, PHOTO_SHA, FROZEN_COMPARISON_SHA256])))
    except FileExistsError:
        parser.error("OUTPUT_EXISTS")
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
