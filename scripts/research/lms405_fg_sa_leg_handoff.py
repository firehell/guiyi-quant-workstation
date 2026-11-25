"""Constrain early FG/SA protection changes using frozen photos and market windows."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_case import DAYS, identity
from lms405_jm_m_leg_handoff import BOUNDARIES, formation
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_position_continuity import continuity
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import read_session_series
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA, SPECS_SHA, photo_row
from lms405_right_side_study import ONE, US
from lms405_rubber_m_replacements import compare_gate, first_gates
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms405_visible_lock_handoff import stamp
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

FIRST, MORNING, CLOSE, NIGHT = "WRnTlEfj1t", "WRnY5bznUE", "WRo00BFM1E", "WRo2KQ43iX"
OLD_PLAN, NEW_PLAN = "A5356884629782554", "A5357264059367516"
GLASS, SODA = "FG2701", "SA2701"
GLASS_BANDS = {"protection": (Decimal(829), Decimal(836)), "m": (Decimal(842), Decimal(844))}
SODA_BANDS = {"m_return": (Decimal(942), Decimal(945)), "protection_return": (Decimal(931), Decimal(936)),
              "strong_target": (Decimal(915), Decimal(927))}


def photo_times(photos, source, symbol, minutes, cut, *, field=None):
    index = {bar.end: bar for bar in minutes}
    row = photos[source]["per_symbol"][symbol]
    price = Decimal(row["mark"])
    candidates = photos[source][field] if field else row["contains"]
    anchors = [datetime.fromisoformat(value) for value in candidates]
    if not anchors:
        raise ValueError("FG_SA_HANDOFF_ANCHOR_MISSING")
    if any(t + US >= cut or not index[t].low <= price <= index[t].high
           or (field == "joint_equal_close" and index[t].close != price) for t in anchors):
        raise ValueError("FG_SA_HANDOFF_ANCHOR_CHANGED")
    return anchors


def quantify_glass(series, first, morning, close, initial, final, tick):
    lots = initial["quantity"]
    totals = [displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick) for leg in (initial, final)]
    cut = close + 2 * US
    gates = first_gates(series, max(morning) + US, cut, bands=GLASS_BANDS)
    for review in gates.values():
        if review["end"] is not None:
            review["partitions"] = {scope: compare_gate(
                series[1], [(old, close) for old in first], review["end"], boundary=scope, tick=tick,
                lots=lots, old_totals=totals[0], new_totals=totals[1],
            ) for scope in BOUNDARIES}
            review["independent_rebuild_if_morning_long_zero"] = {
                scope: {mark.isoformat(): formation(
                    [bar for bar in series[1] if bar.end >= mark], [close], review["end"], boundary=scope,
                    tick=tick, lots=lots, totals=totals[1],
                ) for mark in morning} for scope in BOUNDARIES
            }
    # Missing morning long means either some older lots can remain, or assume it was zero and rebuild.
    recreate = {scope: {mark.isoformat(): formation(
        [bar for bar in series[1] if bar.end >= mark], [close], mark, boundary=scope,
        tick=tick, lots=lots, totals=totals[1],
    ) for mark in morning} for scope in BOUNDARIES}
    return dict(protection_gates=gates, same_side_morning_lots=None,
                rebuild_if_assuming_morning_absence_means_zero=recreate)


def night_or_morning(minute_rows, old_marks, morning_marks, reopen, *, tick, lots, totals):
    result = {}
    for early in old_marks:
        previous_night = tick_bounds([bar for bar in minute_rows if early <= bar.end <= reopen], tick)
        result[early.isoformat()] = {}
        for late in morning_marks:
            morning = tick_bounds([bar for bar in minute_rows if reopen <= bar.start and bar.end <= late], tick)
            counts = earlier_lot_counts(previous_night, morning, lots, totals)
            if not counts:
                raise ValueError("FG_SA_HANDOFF_NIGHT_OR_MORNING_INCOMPATIBLE")
            result[early.isoformat()][late.isoformat()] = dict(
                minimum_night_lots=min(counts), maximum_night_lots=max(counts),
                whole_leg_can_form_in_night=lots in counts, whole_leg_can_form_in_morning=0 in counts,
            )
    return result


def quantify_soda(series, start, cut, earlier_times, morning_times, visible_short, tick):
    lots = visible_short["quantity"]
    totals = displayed_tick_totals(Decimal(visible_short["opening_average"]), lots, tick)
    gates = first_gates(series, start, cut, bands=SODA_BANDS, side="SHORT")
    morning = morning_times[0]
    reopen = next(bar.start for bar in series[1] if bar.start.astimezone(morning.tzinfo).date() == morning.date())
    for row in gates.values():
        if row["end"] is not None:
            row["after_early_snapshot"] = {scope: {prior.isoformat(): formation(
                completed(series[1], prior - ONE, cut), morning_times, row["end"], boundary=scope,
                tick=tick, lots=lots, totals=totals,
            ) for prior in earlier_times} for scope in BOUNDARIES}
    return dict(gates=gates, reopen=reopen, civil_sessions=night_or_morning(
        series[1], earlier_times, morning_times, reopen, tick=tick, lots=lots, totals=totals,
    ))


def study(session, market):
    reference = verified_json(PHOTO, PHOTO_SHA)
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    index = input_sources()
    source_ids = (FIRST, MORNING, CLOSE, NIGHT, OLD_PLAN, NEW_PLAN, "WRo0YIbejU", "WRo1n9FjvJ")
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in source_ids}
    tables = {row["source"]: row for row in exposure["tables"]}
    holdings = {c: {key: photo_row(tables, key, c) for key in keys} for c, keys in (
        (GLASS, (FIRST, MORNING, CLOSE)), (SODA, (FIRST, MORNING, NIGHT)),
    )}
    for contract, source, side, shown in (
        (GLASS, FIRST, "long", "828.0"), (GLASS, FIRST, "short", "850.0"),
        (GLASS, MORNING, "short", "856.0"), (GLASS, CLOSE, "short", "856.0"),
        (SODA, FIRST, "short", "945.0"), (SODA, MORNING, "short", "944.0"),
        (SODA, FIRST, "long", "935.0"), (SODA, NIGHT, "long", "963.0"),
    ):
        leg = holdings[contract][source]["legs"][side]
        if Decimal(leg["opening_average"]) != Decimal(shown) or leg["quantity"] != 20:
            raise ValueError("FG_SA_HANDOFF_FIELD_CHANGED")
        leg["opening_average"] = shown

    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    series, market_ids, times = {}, {}, {}
    for contract, last, field in ((GLASS, CLOSE, "joint_equal_close"), (SODA, NIGHT, None)):
        symbol = contract[:-4].lower()
        series[contract] = tuple(read_window(session, market, contract, day) for day in DAYS)
        raw = read_session_series(session, market, symbol, contract, "1m", ONE, DAYS)
        days = series[contract]
        if identity(raw) != reference["market_1m"][symbol] or digest(days[0][1] + days[1][1]) != bars_sha(raw):
            raise ValueError("FG_SA_HANDOFF_MARKET_CHANGED")
        market_ids[contract] = {day.isoformat(): {f"{p}m": digest(bars) for p, bars in rows.items()}
                                for day, rows in zip(DAYS, days, strict=True)}
        times[contract] = {key: photo_times(reference["photos"], key, symbol,
                                           days[1 if key == NIGHT else 0][1], stamp(sources[key]), field=mode)
                           for key, mode in ((FIRST, None), (MORNING, "joint_contains"), (last, field))}
    fg, sa = (holdings[c] for c in (GLASS, SODA))
    shared_early = sorted(set(times[GLASS][FIRST]) & set(times[SODA][FIRST]))
    if not shared_early:
        raise ValueError("FG_SA_HANDOFF_NO_SHARED_EARLY_QUOTE")
    c_short = {"glass_night_to_morning": continuity(fg[FIRST]["legs"]["short"], fg[MORNING]["legs"]["short"], same_day=True),
               "glass_morning_to_close": continuity(fg[MORNING]["legs"]["short"], fg[CLOSE]["legs"]["short"], same_day=True),
               "soda_night_to_morning": continuity(sa[FIRST]["legs"]["short"], sa[MORNING]["legs"]["short"], same_day=True),
               "soda_old_long_to_next_night": continuity(sa[FIRST]["legs"]["long"], sa[NIGHT]["legs"]["long"], same_day=False)}
    soda_start = max(stamp(sources[FIRST]), stamp(sources[OLD_PLAN])) + ONE
    return dict(
        version="lms405-fg-sa-leg-handoff-v1", sources=sources, positions=holdings, markets=market_ids,
        quote_anchors=times, common_two_product_early_price_minutes=shared_early,
        continuity_on_assumed_same_account=c_short,
        glass_long=quantify_glass(series[GLASS][0], times[GLASS][FIRST], times[GLASS][MORNING], times[GLASS][CLOSE][0],
                                  fg[FIRST]["legs"]["long"], fg[CLOSE]["legs"]["long"], specs[GLASS]["tick"]),
        soda_fresh_short=quantify_soda(series[SODA][0], soda_start, stamp(sources[MORNING]),
                                       times[SODA][FIRST], times[SODA][MORNING], sa[MORNING]["legs"]["short"], specs[SODA]["tick"]),
        evidence_scope="CONDITIONAL_SAME_ACCOUNT_STABLE_OPENING_AVERAGE_AND_QUOTE_SCOPE",
        actual_capture_time=None, actual_account_continuity=None, actual_actions=None,
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
        parser.exit(2, f"{code if code.startswith(('FG_SA_', 'RU_M_', 'JM_M_')) and code.isidentifier() else 'FG_SA_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
