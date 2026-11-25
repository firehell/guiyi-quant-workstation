"""Test source-linked OI2701 leg interpretations against completed price evidence."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_common_protection_window import OCT27_QUOTES, OCT27_SNAPSHOT
from lms405_i2701_case import FROZEN_COMPARISON_SHA256, readback
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_replay import display, ohlc
from lms405_right_side_study import US, at
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
        common = verified_json(COMMON, COMMON_SHA)
        continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
        quotes = verified_json(OCT27_QUOTES, FROZEN_COMPARISON_SHA256)
        specification = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), common, continuity, quotes, specification)
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
