"""Compare independent staged protection timing and preselected sizes on the same night image."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_staged_protection import tape
from lms405_protection_lot_timing import tick_bounds, verified_json
from lms405_protection_quantity_stages import compatible_allocations, protection_candidates
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_staged_protection_permissions import STAGES, STAGES_SHA
from lms_near405_replay import encoded, sha

# Comparison quantities fixed apart from the visible average, including the
# all-late and all-early endpoints. Neither midpoint implies an author rule.
FIRST_LOTS = (0, 5, 10, 15, 20)
PA_CONTEXT = "WRnThF3x5C"
COMBOS = ((1, 1), (5, 1), (5, 5), (15, 15))
PRICE_SCOPES = {
    "WHOLE_MINUTES_AFTER_EACH_PERMISSION": (False, False),
    "ALLOW_ONLY_EARLY_PERMISSION_MINUTE": (True, False),
    "ALLOW_ONLY_LATE_PERMISSION_MINUTE": (False, True),
    "ALLOW_BOTH_PERMISSION_MINUTES": (True, True),
}


def first_stage_clocks(minutes, band, before):
    lower, upper = band
    first_touch = first_close = consecutive = previous = None
    for bar in minutes:
        known = bar.end + US
        if known >= before:
            break
        if first_touch is None and bar.low <= upper and lower <= bar.high:
            first_touch = bar
        if first_touch is None:
            continue
        if bar.close > lower:
            first_close = first_close or bar
            if previous is not None and previous.end == bar.start and consecutive is None:
                consecutive = bar
            previous = bar
        else:
            previous = None
    return {key: bar.end if bar is not None else None for key, bar in (
        ("FIRST_RANGE_TOUCH", first_touch), ("FIRST_CLOSE_ABOVE_NEAR", first_close),
        ("TWO_CONTIGUOUS_CLOSES_ABOVE_NEAR", consecutive),
    )}


def phase_prices(minutes, early_effective, late_effective, quote_end, *, tick, allow_early=False, allow_late=False):
    """The first slice finishes before the second permission; no bar enters both slices."""
    prefix = [bar for bar in minutes if bar.end < quote_end]
    first = [bar for bar in prefix if early_effective < (bar.end if allow_early else bar.start)
             and bar.end + US < late_effective]
    later = [bar for bar in prefix if late_effective < (bar.end if allow_late else bar.start)]
    return tick_bounds(first, tick), tick_bounds(later, tick)


def case_study(series, contract, frozen, quote_ends):
    source, snap = frozen["source"], frozen["snapshot"]
    plan_at = datetime.fromisoformat(source["published_at"]) + ONE
    start = series[1][0].start
    if not plan_at < start or snap["quantity"] != 20 or snap["shown_as_today_quantity"] != 20:
        raise ValueError("STAGED_CLOCKS_PLAN_OR_SIZE_CHANGED")
    stop = datetime.fromisoformat(snap["published_at"])
    band = tuple(map(Decimal, frozen["band"]))
    minutes = completed(series[1], start, stop)
    if not minutes or any(left.end != right.start for left, right in zip(minutes, minutes[1:])):
        raise ValueError("STAGED_CLOCKS_TRADING_SEGMENT_CHANGED")
    later = frozen["policies"]["ADD_15M:SHAPE_CONTACT"]["earliest"]
    confirmation = datetime.fromisoformat(later["confirmed_at"])
    confirm_known = datetime.fromisoformat(later["available_at"])
    discovered = protection_candidates(series, start, stop, band, clocks=((1, 1), (5, 1), (15, 15)),
                                       shape_contact=True)
    if not discovered or encoded(discovered[0]) != encoded(later) or confirm_known != confirmation + US:
        raise ValueError("STAGED_CLOCKS_CONFIRMATION_CHANGED")
    clocks = first_stage_clocks(minutes, band, confirm_known)
    if clocks["FIRST_RANGE_TOUCH"] != datetime.fromisoformat(frozen["first_touch_minute"]["end"]):
        raise ValueError("STAGED_CLOCKS_TOUCH_CHANGED")
    for point in {confirm_known, *(v + US for v in clocks.values() if v), *(v + 2 * US for v in clocks.values() if v)}:
        check = first_stage_clocks([bar for bar in minutes if bar.end + US < point], band, point)
        if check != {key: value if value is not None and value + US < point else None
                     for key, value in clocks.items()}:
            raise ValueError("STAGED_CLOCKS_PREFIX_DIVERGED")
    early_shapes = {f"{shape}m_to_{confirm}m": signals(series, shape, confirm, side="LONG", start=start, cut=confirm_known)
                    for shape, confirm in COMBOS}
    tick = Decimal(snap["tick_size"])
    lo, hi = snap["displayed_tick_total_interval"]
    results = {}
    seed = Position(contract, short=Decimal(20))
    for label, early_clock in clocks.items():
        if early_clock is None or not early_clock + 6 * US < confirmation:
            results[label] = dict(clock=early_clock, status="NO_SEPARATE_EARLY_CLOCK")
            continue
        frame = dict(plan=source | {"available_at": plan_at}, touch=early_clock, confirm=confirmation,
                     cutoff=min(quote_ends))
        public = tape(seed, 10, **frame, early=False, normal=False)
        fixtures = {n: tape(seed, n, **frame, early=n > 0, normal=n < 20) for n in FIRST_LOTS}
        early_only = tape(seed, 10, **frame, early=True, normal=False)
        boundaries = {}
        for stage, effective in (("early", early_clock + 6 * US), ("later", confirmation + 6 * US)):
            (bar,) = [bar for bar in minutes if bar.start <= effective < bar.end]
            boundaries[stage] = dict(start=bar.start, end=bar.end, low=bar.low, high=bar.high)
        checks = {}
        for quote in quote_ends:
            outcomes = {}
            for scope, (early_overlap, late_overlap) in PRICE_SCOPES.items():
                first, second = phase_prices(minutes, early_clock + 6 * US, confirmation + 6 * US, quote, tick=tick,
                                             allow_early=early_overlap, allow_late=late_overlap)
                ways = compatible_allocations(20, range(lo, hi + 1), (None, first, second))
                allowed = sorted({early for _, early, _ in ways})
                outcomes[scope] = dict(price_ranges_in_ticks=[first, second], price_compatible_first_lots=allowed,
                                       coherent_preselected_sizes=[n for n in FIRST_LOTS if n in allowed])
            checks[quote.isoformat()] = outcomes
        results[label] = dict(clock=early_clock, status="HYPOTHETICAL_CLOCK", public=public, fixture_tapes=fixtures,
                              early_only_example=early_only, quote_checks=checks,
                              permission_overlapping_minutes=boundaries)
    return dict(source=source, snapshot=snap, band=band, later_confirmation=discovered[0],
                independent_pre_confirmation_geometries=early_shapes, first_stage_clock_comparison=results,
                historical_early_signal=None, historical_top_up_permission=None)


def study(session, market):
    refs = verified_json(STAGES, STAGES_SHA)
    index = input_sources()
    context = load_source(index, PA_CONTEXT)
    output = {}
    for contract, row in refs["cases"].items():
        plan, image = row["source"], row["snapshot"]["image"]
        if (sha((ARCHIVE.parent / plan["archive_path"]).read_bytes()) != plan["archive_sha256"]
                or sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]):
            raise ValueError("STAGED_CLOCKS_SOURCE_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(row["trading_day"]))
        if {f"{period}m": digest(bars) for period, bars in series.items()} != row["market"]:
            raise ValueError("STAGED_CLOCKS_MARKET_CHANGED")
        anchors = [datetime.fromisoformat(value) for value in row["quote_minute_ends"]]
        output[contract] = case_study(series, contract, row, anchors) | dict(market=row["market"])
    return dict(version="lms405-staged-protection-clocks-v1", cases=output, pa_context=context,
                pa_context_used_as_permission=False, source_ref_sha256=STAGES_SHA, first_lot_examples=FIRST_LOTS,
                same_screen_joint_quote_candidates=refs["shared_quote_minute_ends"],
                same_account_and_true_capture_verified=False, author_action_samples=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("STAGED_CLOCKS_ENV_MISSING_OR_OUTPUT_EXISTS")
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
    except (OSError, ValueError, KeyError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('STAGED_CLOCKS_') and code.isidentifier() else 'STAGED_CLOCKS_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
