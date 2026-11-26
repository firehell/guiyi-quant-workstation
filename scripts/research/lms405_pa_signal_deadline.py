"""Bound when a missing reverse VPLUS would have to be known using one shared quote."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_first_night_confirmation_clocks import DAY, POST, START
from lms405_first_night_pa import PA, REFERENCE, REFERENCE_HASH, documented_price_events
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_staged_protection import common_quote_ends
from lms405_protection_layers_replay import PA_HASH, PA_REPORT
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

VERSION = "lms405-pa-signal-deadline-v1"
CONTRACTS = ("SA2701", "SH2701")
RECAP = {"SA2701": "WRo1n9FjvJ", "SH2701": "WRo1A1rN9b"}
PROTECTION_LABELS = ("ALL_PRICES", "PROTECTION_BAND_ONLY")
INTRAMINUTE_GATES = (
    "fresh_inside_minute_near_excursion", "fresh_inside_minute_far_excursion", "first_m_touch",
)


def minute_ticks(bar, tick, band=None):
    """OHLC provides a possible range of ticks, with no implied prints or volume."""
    if tick <= 0:
        raise ValueError("PA_DEADLINE_OFF_TICK")
    lower, upper = bar.low, bar.high
    if band is not None:
        lower, upper = max(lower, band[0]), min(upper, band[1])
    values = lower / tick, upper / tick
    if any(value != int(value) for value in values):
        raise ValueError("PA_DEADLINE_OFF_TICK")
    return range(int(values[0]), int(values[1]) + 1)


def sums_by_size(ticks, lots):
    """Use a union of per-minute ranges, which can contain price gaps."""
    out = [{0}]
    for _ in range(lots):
        out.append({base + tick for base in out[-1] for tick in ticks})
    return out


def quantity_support(earlier, later, lots, totals):
    before, after = sums_by_size(earlier, lots), sums_by_size(later, lots)
    return [
        early for early in range(lots + 1)
        if any((total - first) in after[lots - early] for total in totals for first in before[early])
    ]


def comparison(rows, *, gate_known_at, lots, totals, tick, band):
    """Only complete minutes starting strictly after knowledge count as later."""
    if gate_known_at is None:
        return dict(late_price_tick_count=None, compatible_lots_outside_later_price_set=None,
                    minimum_outside_later_price_set=None, whole_leg_with_later_prices=None)
    earlier, later = set(), set()
    for bar in rows:
        if gate_known_at < bar.start:
            later.update(minute_ticks(bar, tick, band))
        else:
            # Allocate the whole overlapping minute to the earlier side. The
            # resulting bound describes a window, not a trade timestamp.
            earlier.update(minute_ticks(bar, tick))
    counts = quantity_support(earlier, later, lots, totals)
    return dict(late_price_tick_count=len(later), compatible_lots_outside_later_price_set=counts,
                minimum_outside_later_price_set=min(counts, default=None),
                whole_leg_with_later_prices=0 in counts)


def time_constraints(rows, *, event_clocks, quote_end, tick, band, lots, totals):
    labels = {}
    suffix_ticks = set()
    latest = None
    for bar in reversed(rows):
        new_ticks = set(minute_ticks(bar, tick, band)) - suffix_ticks
        if not new_ticks:
            continue
        suffix_ticks.update(new_ticks)
        if any(total in sums_by_size(suffix_ticks, lots)[lots] for total in totals):
            latest = bar.start
            break
    for name, evidence_at in event_clocks.items():
        known = evidence_at + US if evidence_at is not None else None
        labels[name] = dict(evidence_at=evidence_at, known_at=known, **comparison(
            rows, gate_known_at=known, lots=lots, totals=totals, tick=tick, band=band,
        ))
        if name in INTRAMINUTE_GATES and evidence_at is not None:
            labels[name]["include_entire_price_event_minute_as_sensitivity"] = comparison(
                rows, gate_known_at=evidence_at - ONE - US, lots=lots, totals=totals, tick=tick, band=band,
            )
    return dict(quote_end=quote_end, completed_minutes=len(rows), by_gate=labels,
                latest_strict_signal_knowledge_bound_exclusive=latest)


def clocks(series, prior):
    near, far, m = (prior["levels"][key] for key in ("interruption_near", "interruption_far", "m_near"))
    minutes = series[1]
    band = Decimal(near["level"]), Decimal(far["level"])
    prev_close = Decimal(prior["previous_day_close"])
    near_events, far_events = (documented_price_events(series, level, prev_close) for level in band)

    def raw(event):
        return event.end if event else None

    contact = next((bar for bar in minutes if bar.low <= band[1] and band[0] <= bar.high), None)
    returned = next((b for a, b in zip(minutes, minutes[1:]) if a.close > band[1] and band[0] <= b.close <= band[1]), None)
    return dict(
        opening_context_completed=minutes[0].end,
        protection_contact_completed=contact.end if contact else None,
        fresh_inside_minute_near_excursion=raw(near_events["first_known_upward_excursion_inside_minute"]),
        fresh_inside_minute_far_excursion=raw(far_events["first_known_upward_excursion_inside_minute"]),
        **{f"first_close_above_far_{period}": raw(event) for period, event in far_events["first_close_strictly_above"].items()},
        first_return_close_into_band=returned.end if returned else None,
        first_m_touch=next((bar.end for bar in minutes if bar.high >= Decimal(m["level"])), None),
    )


def study(session, market):
    first_night = verified_json(REFERENCE, REFERENCE_HASH)
    pa = verified_json(PA_REPORT, PA_HASH)
    index = input_sources()
    (raw_quote,) = common_quote_ends(first_night["cases"])
    quote_end = datetime.fromisoformat(raw_quote)
    image = first_night["photo"]
    conceptual_pa = load_source(index, PA)
    if (pa["prior_sha256"] != REFERENCE_HASH or pa["photo"] != image
            or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
            or conceptual_pa != pa["pa_reference"]):
        raise ValueError("PA_DEADLINE_REFERENCE_CHANGED")
    result = {}
    for contract in CONTRACTS:
        prior, first = pa["cases"][contract], first_night["cases"][contract]
        series = read_window(session, market, contract, DAY)
        fingerprints = {f"{period}m": digest(bars) for period, bars in series.items()}
        if fingerprints != prior["market"] or fingerprints != first["market"]:
            raise ValueError("PA_DEADLINE_MDS_DATA_CHANGED")
        night = {period: completed(bars, START, POST) for period, bars in series.items()}
        minutes = night[1]
        if not {quote_end, quote_end - ONE} <= {b.end for b in minutes}:
            raise ValueError("PA_DEADLINE_QUOTE_WINDOW_CHANGED")
        band = tuple(map(Decimal, first["protection_band"]))
        tick, lots = Decimal(first["tick"]), first["displayed_long"]["quantity"]
        totals = displayed_tick_totals(Decimal(first["average"]), lots, tick)
        if first["displayed_long"]["today_quantity"] != lots or first["original_short"]["today_quantity"] != 0:
            raise ValueError("PA_DEADLINE_LEG_ORIGIN_CHANGED")
        plan = first["plan"]
        if (sha((ARCHIVE.parent / plan["archive_path"]).read_bytes()) != plan["archive_sha256"]
                or datetime.fromisoformat(plan["published_at"]) + ONE >= START):
            raise ValueError("PA_DEADLINE_PLAN_CHANGED")
        recap = load_source(index, RECAP[contract])
        if not datetime.fromisoformat(conceptual_pa["published_at"]) < quote_end < datetime.fromisoformat(recap["published_at"]):
            raise ValueError("PA_DEADLINE_SOURCE_ORDER_CHANGED")
        event_clocks = clocks(night, prior)
        windows, geometry = {}, {}
        for name, last_bar in (("COMPLETE_MINUTES_BEFORE_QUOTE_MINUTE", quote_end - ONE),
                               ("INCLUDE_WHOLE_QUOTE_MINUTE_AS_SENSITIVITY", quote_end)):
            prefix = {period: [bar for bar in bars if bar.end <= last_bar] for period, bars in night.items()}
            visible_clocks = {gate: event if event is not None and event <= last_bar else None
                              for gate, event in event_clocks.items()}
            if visible_clocks != clocks(prefix, prior):
                raise ValueError("PA_DEADLINE_PREFIX_DIVERGED")
            geometry[name] = {f"{s}m_to_{c}m": geometry_events(
                series, s, c, start=START, as_of=last_bar + 2 * US, side="LONG",
            ) for s, c in VARIANTS}
            windows[name] = {label: time_constraints(
                prefix[1], event_clocks=visible_clocks, quote_end=quote_end,
                tick=tick, band=band if label == "PROTECTION_BAND_ONLY" else None,
                lots=lots, totals=totals,
            ) for label in PROTECTION_LABELS}
        quote_lots = comparison([bar for bar in minutes if bar.end <= quote_end],
                                gate_known_at=quote_end - ONE - US, lots=lots, totals=totals, tick=tick, band=None)
        result[contract] = dict(
            windows=windows, market=fingerprints, plan=plan, recap=recap, displayed=first["displayed_long"],
            band=band, opening_context=prior["first_bar"]["1m"], geometry_candidates=geometry,
            quote_minute_lots_required=lots - max(quote_lots["compatible_lots_outside_later_price_set"]),
            reverse_vplus=None, author_permission=None, author_action_at=None,
        )
    return dict(version=VERSION, cases=result, quote_end=quote_end, photo=image, historical_capture_time=None,
                pa_source=conceptual_pa, pa_usage="RETROSPECTIVE_CONCEPT_ONLY", opening_average_scope="NECESSARY_PRICE_SUPPORT_ONLY",
                historical_plan_revision_verified=False, executable=False, fills=None, pnl=None,
                references=dict(first_night=REFERENCE_HASH, pa=PA_HASH), author_action_samples=0, author_match_rate=None)


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
        parser.exit(2, f"{code if code.startswith('PA_DEADLINE_') and code.isidentifier() else 'PA_DEADLINE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
