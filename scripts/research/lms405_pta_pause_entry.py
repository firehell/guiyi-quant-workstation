"""Bound the visible TA2701 new long while the author published no new zone."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_jm_m_leg_handoff import BOUNDARIES, formation
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, latest_whole_leg_start, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import display, ohlc, photo_comparison, read_session_series
from lms405_reversal_stage_bounds import SPECS_SHA, photo_row
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sh_protection_replacement import compatible_counts
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms405_v_ta_case import DAYS, identity
from lms405_visible_lock_handoff import stamp
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "TA2701"
DAY, PRIOR_DAY = DAYS[5], DAYS[4]
PLAN, MODEL_PAUSE = "A5357264793370945", "A5355789916438626"
HOLDINGS, OTHER_SYSTEM, SUMMARY = "WRo2KQ43iX", "WRo2LIbP3s", "WRo39kul2n"
PHOTO = Path("output/lms-v-ta-oct-20261125/comparison.json")
PHOTO_SHA = "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"
SIZED = Path("output/lms405-sized-portfolio-20261125/pta-case-sized.json")
SIZED_SHA = "df9a3e0e9d88143b4b67ac468dc35fd292f52dac8df8b3cbc8c58676f5d48084"
AVG, SPREAD, FLOAT = Decimal("6548.0"), Decimal("186.0"), Decimal(31620)
SUMMARY_MARKS = {"ta": "6762", "v": "5249", "sa": "967", "rb": "3042", "sh": "1585", "i": "670.5"}
SUMMARY_IMAGES = {"Ro39kul2n-table2-screen.png": "e32278d3c79115d170e64ff87e3dd600dac5c43bbeba35816d15376b125d8112",
                  "Ro39kul2n-table3-screen.png": "224e8c1ce8724eee911cdf8f1f02b5f257f477025ba108fe16c3e0790970a482"}


def gap_gates(minutes, prior_close):
    opening = minutes[0].open
    touch = next((bar.end for bar in minutes if bar.low <= prior_close <= bar.high), None)
    # For an upward opening gap, reclaiming the opening price is a separate hypothesis.
    reclaim = next((bar.end for bar in minutes if touch is not None and bar.end > touch and bar.close > opening), None)
    return dict(opening=opening, prior_close=prior_close, difference=opening - prior_close,
                touch_prior_close=touch, later_strict_close_above_open=reclaim)


def geometry_gates(series, start, cut):
    scoped = {period: completed(rows, start, cut) for period, rows in series.items()}
    result = {}
    for shape, confirm in VARIANTS:
        full = signals(scoped, shape, confirm, side="LONG", start=start, cut=cut)
        for event in full:
            split = event["available_at"]
            prefix = {p: [bar for bar in rows if bar.end + US < split] for p, rows in scoped.items()}
            earlier = signals(prefix, shape, confirm, side="LONG", start=start, cut=split)
            if earlier != [row for row in full if row["available_at"] < split]:
                raise ValueError("PTA_PAUSE_GEOMETRY_PREFIX_DIVERGED")
        result[f"{shape}m_to_{confirm}m"] = dict(count=len(full), first=full[0] if full else None)
    return result


def retention_bounds(minutes, starts, ends, *, tick, lots, totals):
    """Keep equal-average positions distinct unless scope and order are explicitly assumed."""
    result = {}
    for first in starts:
        was = tick_bounds([bar for bar in minutes if bar.end <= first], tick)
        for later in ends:
            if first >= later:
                continue
            replacement = tick_bounds([bar for bar in minutes if first <= bar.end <= later], tick)
            allowed = compatible_counts(lots, totals, totals, was, None, replacement)
            if not allowed:
                raise ValueError("PTA_PAUSE_REPEATED_AVERAGE_INCOMPATIBLE")
            result[f"{display(first)} / {display(later)}"] = dict(
                min_retained=min(k[0] for k in allowed), max_replaced=max(k[2] for k in allowed),
                unchanged_possible=any(k[2] == 0 for k in allowed),
            )
    return result


def summary_evidence(session, market, source, raw_day, start):
    root = Path(source["archive_path"]).parent
    images = {str(root / name): expected for name, expected in SUMMARY_IMAGES.items()}
    if any(sha((ARCHIVE.parent / path).read_bytes()) != expected for path, expected in images.items()):
        raise ValueError("PTA_PAUSE_SUMMARY_IMAGE_CHANGED")
    quote_minutes = {
        symbol: read_session_series(session, market, symbol, f"{symbol.upper()}2701", "1m", ONE, (DAY,))
        for symbol in SUMMARY_MARKS if symbol != "ta"
    } | {"ta": raw_day}
    cutoff = stamp(source)
    return dict(images=images, quote_candidates=photo_comparison(quote_minutes, start, cutoff, SUMMARY_MARKS),
                market_1m={symbol: identity(bars) for symbol, bars in quote_minutes.items()},
                displayed_ta_long=dict(quantity=34, today_quantity=34, opening_average=AVG,
                                       profit_spread=Decimal("214.0"), position_float=Decimal(36380)),
                source_table_system_binding=None, exact_capture_at=None)


def study(session, market):
    ref = verified_json(PHOTO, PHOTO_SHA)
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    selected = verified_json(SIZED, SIZED_SHA)["pta_case"]
    index = input_sources()
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in (PLAN, MODEL_PAUSE, HOLDINGS, OTHER_SYSTEM, SUMMARY)}
    snapshot = photo_row({row["source"]: row for row in exposure["tables"]}, HOLDINGS, CONTRACT)
    row = snapshot["legs"]["long"]
    lots = row["quantity"]
    if (Decimal(row["opening_average"]) != AVG or lots != 34 or row["today_quantity"] != lots or
            snapshot["version_on_post"] != "4.0.5" or Decimal(selected["lots"]) != lots or selected["source"] != HOLDINGS):
        raise ValueError("PTA_PAUSE_VISIBLE_FIELDS_CHANGED")
    spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
    tick, multiplier = spec["tick"], spec["multiplier"]
    mark = AVG + SPREAD
    if lots * multiplier * SPREAD != FLOAT or mark % tick != 0:
        raise ValueError("PTA_PAUSE_ROW_MARK_NOT_CONSISTENT")
    totals = displayed_tick_totals(AVG, lots, tick)
    series = read_window(session, market, CONTRACT, DAY)
    raw = read_session_series(session, market, "ta", CONTRACT, "1m", ONE, DAYS)
    raw_day = [bar for bar in raw if bar.trading_day == DAY]
    if identity(raw) != ref["market_1m"]["ta"] or digest(series[1]) != bars_sha(raw_day):
        raise ValueError("PTA_PAUSE_FROZEN_MARKET_CHANGED")
    prior = [row for row in raw if row.trading_day == PRIOR_DAY][-1]
    start, cut = series[1][0].start, stamp(sources[HOLDINGS])
    if not prior.bar_end < stamp(sources[PLAN]) + ONE < start < cut:
        raise ValueError("PTA_PAUSE_TIMELINE_CHANGED")
    minutes = completed(series[1], start, cut)
    captures = [bar.end for bar in minutes if bar.low <= mark <= bar.high]
    original = ref["photos"][HOLDINGS]
    if [display(at) for at in captures] != original["per_symbol"]["ta"]["contains"] or original["joint_contains"]:
        raise ValueError("PTA_PAUSE_SNAPSHOT_CLOCK_CHANGED")
    summary = summary_evidence(session, market, sources[SUMMARY], raw_day, start)
    seen_later = summary["displayed_ta_long"]
    if (seen_later["quantity"] != lots or seen_later["today_quantity"] != lots or
            seen_later["opening_average"] != AVG or AVG + seen_later["profit_spread"] != Decimal(SUMMARY_MARKS["ta"]) or
            lots * multiplier * seen_later["profit_spread"] != seen_later["position_float"]):
        raise ValueError("PTA_PAUSE_SUMMARY_ROW_MARK_NOT_CONSISTENT")
    summary_quote = summary["quote_candidates"]
    summary_times = [datetime.fromisoformat(t) for t in summary_quote["per_symbol"]["ta"]["contains"]]
    later_window = completed(series[1], start, stamp(sources[SUMMARY]))
    quote_details = retention_bounds(later_window, captures, summary_times, tick=tick, lots=lots, totals=totals)
    summary.update(assumed_same_account_lot_bounds=quote_details, earlier_and_summary_account_continuity=None)
    gap = gap_gates(minutes, prior.close)
    geometry = geometry_gates(series, start, cut)
    fixture_time = datetime.fromisoformat(selected["entry_at"])
    gates = {"gap_touch_completed": gap["touch_prior_close"],
             "later_strict_close_above_open": gap["later_strict_close_above_open"],
             "frozen_research_cycle_time": fixture_time.replace(microsecond=0),
             **{key: value["first"]["confirmed_at"] if value["first"] else None for key, value in geometry.items()}}
    bounds = {key: dict(end=when, capture_cases={scope: formation(
        minutes, captures, when, boundary=scope, tick=tick, lots=lots, totals=totals,
    ) for scope in BOUNDARIES}) for key, when in gates.items()}
    first = minutes[0]
    return dict(
        version="lms405-pta-pause-entry-study-v1", contract=CONTRACT, trading_day=DAY.isoformat(), sources=sources,
        snapshot=snapshot, exact_tick_totals=list(totals), opening_average_as_displayed=AVG,
        row_mark=dict(price=mark, spread=SPREAD, floating=FLOAT, quote_captures=captures, exact_photo_capture=None),
        different_version_reference=ref["photos"][OTHER_SYSTEM], size_fixture=selected,
        first_completed_minute=dict(end=first.end, ohlc=ohlc(first)), gap=gap, geometry=geometry, gates=bounds,
        latest_whole_leg_minute_start_by_quote={display(at): latest_whole_leg_start(
            [row for row in raw_day if row.bar_end <= at], tick, lots, totals,
        ) for at in captures},
        compatible_mean_minutes=[bar.end for bar in minutes if bar.low <= AVG <= bar.high],
        repeated_holdings_summary=summary,
        market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
        retrospective_text_history_unverified=True, actual_configuration=None, author_action_at=None,
        admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None,
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
        parser.exit(2, f"{code if code.startswith(('PTA_', 'JM_M_')) and code.isidentifier() else 'PTA_PAUSE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
