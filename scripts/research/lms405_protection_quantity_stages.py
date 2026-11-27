"""Measure which part of a visible protection leg needs prices before confirmation."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_location_audit import location_flags
from lms405_protection_lot_timing import compatible_allocations, displayed_tick_totals, tick_bounds, verified_json
from lms405_protection_next_night_replay import TOUCH, TOUCH_SHA
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sh_reprotection_replay import shape_range_admits
from lms_near405_replay import encoded, sha

LOCATION = Path("output/lms405-protection-location-20261125/final.json")
LOCATION_SHA = "70b1f43e9980383a6ba8f1e67a14a4aa0dca358dc90bb64ceb37b0539e8a9677"
CLOCKS = {
    "FIXED_FAST": ((1, 1), (5, 1)),
    "ADD_15M": ((1, 1), (5, 1), (15, 15)),
}


def phase_bounds(minutes, touch, known, quote_end, tick, *, overlap):
    """Allow a boundary minute in both adjoining ranges in the permissive check."""
    prefix = [bar for bar in minutes if bar.end <= quote_end]
    if overlap:
        early = [bar for bar in prefix if bar.start < touch.end]
        middle = [bar for bar in prefix if touch.start < bar.end and bar.start < known]
        late = [bar for bar in prefix if known < bar.end]
    else:
        early = [bar for bar in prefix if bar.end <= touch.start]
        middle = [bar for bar in prefix if touch.end <= bar.start and bar.end <= known]
        late = [bar for bar in prefix if known < bar.start]
    return tuple(tick_bounds(rows, tick) for rows in (early, middle, late))


def quantity_result(minutes, touch, known, quote_end, tick, lots, totals, *, overlap):
    bounds = phase_bounds(minutes, touch, known, quote_end, tick, overlap=overlap)
    possible = compatible_allocations(lots, totals, bounds)
    return dict(
        quote_end=quote_end, tick_bounds_before_touch_middle_after_confirmation=bounds,
        feasible_allocation_count=len(possible),
        minimum_before_touch=min((row[0] for row in possible), default=None),
        minimum_between_touch_and_confirmation=min((row[1] for row in possible), default=None),
        minimum_before_confirmation=min((a + b for a, b, _ in possible), default=None),
        maximum_after_confirmation=max((row[2] for row in possible), default=None),
        whole_after_touch=any(row[0] == 0 for row in possible),
        whole_after_confirmation=any(row[2] == lots for row in possible),
    )


def protection_candidates(series, start, cutoff, band, *, clocks, shape_contact):
    candidates = []
    for period, confirmation in clocks:
        shapes = {bar.end: bar for bar in series[period]}
        for event in signals(series, period, confirmation, side="LONG", start=start, cut=cutoff):
            shape = shapes[event["shape_end"]]
            location = location_flags(shape, event["close"], band)
            if location["confirmation_close_inside"]:
                route = "IN_BAND"
            elif shape_contact and shape_range_admits(shape, event["close"], band):
                route = "SHAPE_RANGE_CONTACT"
            else:
                continue
            candidates.append(event | dict(route=route, variant=f"{period}m_to_{confirmation}m", placement=location))
    return sorted(candidates, key=lambda row: (row["available_at"], row["variant"]))


def case(series, datum, frozen, quote):
    start, cutoff = (datetime.fromisoformat(datum[key]) for key in ("start", "cut"))
    known = datetime.fromisoformat(datum["plan"]["published_at"])
    band = tuple(map(Decimal, datum["band"]))
    observed = datum["visible_leg"]
    tick, lots = Decimal(observed["tick_size"]), observed["quantity"]
    totals = displayed_tick_totals(Decimal(observed["display_average"]), lots, tick)
    minutes = completed(series[1], start, cutoff)
    first_touch = next(bar for bar in minutes if bar.low <= band[1] and band[0] <= bar.high)
    anchors = [bar.end for bar in minutes if bar.low <= Decimal(quote["mark"]) <= bar.high]
    if (known >= start or first_touch.end != datetime.fromisoformat(datum["contact_bar_ends"][0])
            or len(anchors) != frozen["candidate_quote_count"]
            or list((totals.start, totals.stop - 1)) != observed["displayed_tick_total_interval"]):
        raise ValueError("QUANTITY_STAGES_FROZEN_CONTEXT_CHANGED")
    eligible = {}
    for label, clocks in CLOCKS.items():
        for use_contact in (False, True):
            key = f"{label}:{'SHAPE_CONTACT' if use_contact else 'CONFIRMATION_INSIDE'}"
            events = protection_candidates(series, start, cutoff, band, clocks=clocks, shape_contact=use_contact)
            for cut in {*anchors, *(e["available_at"] for e in events), *(e["available_at"] + US for e in events)}:
                prefix = {p: [bar for bar in bars if bar.end + US < cut] for p, bars in series.items()}
                if protection_candidates(prefix, start, cut, band, clocks=clocks, shape_contact=use_contact) != [
                    row for row in events if row["available_at"] < cut
                ]:
                    raise ValueError("QUANTITY_STAGES_PREFIX_DIVERGED")
            event = next(iter(events), None)
            if event is None:
                eligible[key] = dict(earliest=None, usable_quote_ends=0, quantities=None)
                continue
            # This diagnostic applies only to confirmation following first contact.
            if not first_touch.end < event["confirmed_at"]:
                raise ValueError("QUANTITY_STAGES_CONTACT_ORDER_UNSUPPORTED")
            quote_rows = [end for end in anchors if event["available_at"] < end]
            quantities = {
                scope: [quantity_result(minutes, first_touch, event["available_at"], end, tick, lots, totals,
                                        overlap=overlap) for end in quote_rows]
                for scope, overlap in (("OVERLAP_ALLOWED", True), ("WHOLE_MINUTES_ONLY", False))
            }
            eligible[key] = dict(earliest=event, usable_quote_ends=len(quote_rows), quantities=quantities)
    return dict(
        band=band, source=datum["plan"], snapshot=observed, quote_minute_ends=anchors,
        first_touch_minute=dict(start=first_touch.start, end=first_touch.end, low=first_touch.low,
                                high=first_touch.high, close=first_touch.close),
        policies=eligible,
    )


def study(session, market):
    touch = verified_json(TOUCH, TOUCH_SHA)["cases"]
    location = verified_json(LOCATION, LOCATION_SHA)["cases"]
    quotes = scoped_input_quotes()
    cases = {}
    for name in ("fg_first_night", "jm_first_night"):
        datum, frozen = touch[name], location[name]
        contract = datum["contract"]
        day = date.fromisoformat(datum["trading_day"])
        for metadata, path_key in ((datum["plan"], "archive_path"), (datum["visible_leg"]["image"], "path")):
            expected = metadata.get("archive_sha256") or metadata["sha256"]
            if sha((ARCHIVE.parent / metadata[path_key]).read_bytes()) != expected:
                raise ValueError("QUANTITY_STAGES_SOURCE_CHANGED")
        series = read_window(session, market, contract, day)
        fingerprints = {f"{p}m": digest(bars) for p, bars in series.items()}
        if fingerprints != datum["market"] or fingerprints != frozen["market"]:
            raise ValueError("QUANTITY_STAGES_MARKET_CHANGED")
        cases[contract] = case(series, datum, frozen, quotes[datum["visible_leg"]["source"], contract]) | dict(
            trading_day=day, market=fingerprints,
        )
    same_quote = sorted(set(cases["FG2701"]["quote_minute_ends"]) & set(cases["JM2701"]["quote_minute_ends"]))
    return dict(
        version="lms405-protection-quantity-stages-v1", cases=cases,
        shared_quote_minute_ends=same_quote, shared_quote_proves_capture_time=False,
        references=dict(pre_touch=TOUCH_SHA, location=LOCATION_SHA),
        historical_plan_revision_verified=False,
        observed_leg_assumed_new_for_trading_day=True, action_permission=None, author_action_at=None,
        price_envelopes_are_necessary_only=True, admitted_author_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("QUANTITY_STAGES_ENV_MISSING_OR_OUTPUT_EXISTS")
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
        with args.output.open("x", encoding="utf-8") as f:
            f.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "QUANTITY_STAGES_LOCAL_MDS_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('QUANTITY_STAGES_') and code.isidentifier() else 'QUANTITY_STAGES_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
