"""Compare opening gaps, intraminute PA, and close clocks for three protected contracts."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_first_night_confirmation_clocks import DAY, POST, START, price_envelope
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_shape_audit import outside_events
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

REFERENCE = Path("output/lms405-first-night-clocks-20261125/final.json")
REFERENCE_HASH = "3e24924927376a8fd9e0e06f099b5f12b78191b95df817ba8de4e69d91df1db5"
PRIOR_DAY = date(2026, 10, 22)
PA = "WRnThF3x5C"
LEVELS = {
    "I2701": ("PUBLISHED_INTERRUPTION_WITH_PROTECTION_TEXT_CONFLICT", "667", "671", "675"),
    "SA2701": ("PUBLISHED_INTERRUPTION_AND_PROTECTION", "931", "936", "942"),
    "SH2701": ("PUBLISHED_INTERRUPTION_AND_PROTECTION", "1610", "1632", "1660"),
}


def documented_price_events(series, level, prior_close):
    minutes = series[1]
    if not minutes or minutes[0].start != START:
        raise ValueError("FIRST_PA_OPEN_MISSING")
    first = minutes[0]
    return dict(
        open_already_strictly_above=first.open > level,
        opening_gap_from_at_or_below=prior_close <= level < first.open,
        first_high_strictly_above=next((bar for bar in minutes if bar.high > level), None),
        first_known_upward_excursion_inside_minute=next(
            (bar for bar in minutes if bar.open <= level < bar.high or bar.low <= level < bar.close), None,
        ),
        first_close_strictly_above={f"{p}m": next((bar for bar in rows if bar.close > level), None)
                                    for p, rows in series.items()},
    )


def compare_at_bar(minutes, bar, *, intraminute, tick, lots, totals, anchors):
    if bar is None:
        return None
    cutoff = bar.end + US
    result = dict(bar_end=bar.end, facts_known_at=cutoff, ohlc=ohlc(bar), by_quote_minute={})
    for quote_end in anchors:
        if intraminute:
            # Put the whole event minute in the later envelope. Its actual internal ordering is unknown.
            earlier = [b for b in minutes if b.end <= bar.start and b.end <= quote_end]
            later = [b for b in minutes if bar.start <= b.start and b.end <= quote_end]
            counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
            outcome = dict(event_minute_not_after_quote=bar.end <= quote_end,
                           minimum_lots_before_event_minute=min(counts, default=None) if later else None)
        else:
            outcome = price_envelope(minutes, {"available_at": cutoff}, tick, lots, totals, quote_end)
        result["by_quote_minute"][display(quote_end)] = outcome
    return result


def opening_shape_observations(series, *, tick, lots, totals, anchors):
    probes = {}
    for shape, confirmation in VARIANTS:
        args = dict(start=START, as_of=POST, side="LONG")
        opening = series[shape][0]
        keybars = [event for event in geometry_events(series, shape, confirmation, **args)
                   if event["shape_end"] == opening.end and event["pinbar"] == "LONG"]
        outside = outside_events(series, shape, confirmation, **args)
        if shape != confirmation:
            outside = [event for event in outside if event["kind"] == "OUTSIDE_NEXT_CLOSE"]
        key = f"{shape}m_to_{confirmation}m"
        probes[key] = {}
        for name, events in (("opening_pinbar", keybars), ("strict_outside", outside)):
            first = next(iter(events), None)
            probes[key][name] = dict(
                events=events, first_after_confirmation_price_bounds={
                    display(end): price_envelope(series[1], first, tick, lots, totals, end) for end in anchors
                } if first else {},
            )
    return probes


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_HASH)
    sources = input_sources()
    photo = reference["photo"]
    if sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]:
        raise ValueError("FIRST_PA_HOLDINGS_IMAGE_CHANGED")
    results = {}
    for contract, (role, near, far, m) in LEVELS.items():
        prior = reference["cases"][contract]
        series = read_window(session, market, contract, DAY)
        if {f"{p}m": digest(rows) for p, rows in series.items()} != prior["market"]:
            raise ValueError("FIRST_PA_FROZEN_MARKET_CHANGED")
        scoped = {p: completed(rows, START, POST) for p, rows in series.items()}
        previous = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (PRIOR_DAY,))
        if previous[-1].bar_end != at(f"{PRIOR_DAY}T15:00"):
            raise ValueError("FIRST_PA_PREVIOUS_CLOSE_UNVERIFIED")
        prior_close = previous[-1].close
        lots = prior["displayed_long"]["quantity"]
        average, tick = Decimal(prior["average"]), Decimal(prior["tick"])
        anchors = [datetime.fromisoformat(value) for value in prior["individual_quote_ends"]]
        completed_ends = {bar.end for bar in scoped[1]}
        if not anchors or not set(anchors) <= completed_ends:
            raise ValueError("FIRST_PA_QUOTE_WINDOW_CHANGED")
        kwargs = dict(tick=tick, lots=lots, totals=displayed_tick_totals(average, lots, tick), anchors=anchors)
        by_level = {}
        for label, raw in (("interruption_near", near), ("interruption_far", far), ("m_near", m)):
            level = Decimal(raw)
            clocks = documented_price_events(scoped, level, prior_close)
            for end in anchors:
                prefix = {p: [bar for bar in rows if bar.end + US < end + 2 * US] for p, rows in scoped.items()}
                visible = documented_price_events(prefix, level, prior_close)
                for name in ("first_high_strictly_above", "first_known_upward_excursion_inside_minute"):
                    event = clocks[name]
                    if visible[name] != (event if event is not None and event.end <= end else None):
                        raise ValueError("FIRST_PA_PREFIX_DIVERGED")
            results_at_bar = {name: compare_at_bar(scoped[1], clocks[name], intraminute=True, **kwargs)
                              for name in ("first_high_strictly_above", "first_known_upward_excursion_inside_minute")}
            results_at_bar["first_close_strictly_above"] = {
                period: compare_at_bar(scoped[1], bar, intraminute=False, **kwargs)
                for period, bar in clocks["first_close_strictly_above"].items()
            }
            by_level[label] = dict(level=level, **results_at_bar,
                                   open_already_strictly_above=clocks["open_already_strictly_above"],
                                   opening_gap_from_at_or_below=clocks["opening_gap_from_at_or_below"])
        results[contract] = dict(
            role=role, plan=prior["plan"], previous_day_close=prior_close,
            prior_day_market=dict(count=len(previous), sha256=bars_sha(previous)),
            night_open=scoped[1][0].open, opening_gap_ticks=(scoped[1][0].open - prior_close) / tick,
            first_bar={f"{p}m": dict(ohlc=ohlc(rows[0]), known_at=rows[0].end + US) for p, rows in scoped.items()},
            opening_shapes=opening_shape_observations(scoped, **kwargs), levels=by_level, quote_ends=anchors,
            visible_quantity=lots, visible_average=average, tick=tick, market=prior["market"],
            author_signal_at=None, author_action_at=None,
        )
    return dict(
        version="lms405-first-night-pa-v1", cases=results, prior_sha256=REFERENCE_HASH, photo=photo,
        pa_reference=load_source(sources, PA), pa_reference_scope="CONCEPTUAL_POST_AFTER_SESSION_START",
        retrospective_model_only=True, trading_day=DAY,
        intraminute_quote_prefix_checks=sum(len(case["quote_ends"]) * len(case["levels"]) for case in results.values()),
        start=START, cutoff_exclusive=POST, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("FIRST_PA_") and code.isidentifier()
                        else "FIRST_PA_SOURCE_OR_MARKET_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
