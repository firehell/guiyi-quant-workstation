"""Reconcile FG2701 take-profit text and software rows with completed local bars."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position
from guiyi_quant.lms405.public_conditions import Condition, PublicCase, assess_case
from lms405_break_pressure_comparison import continuous_groups
from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_m_permission_study import read_pair
from lms405_opening_clock_comparison import boundary_clocks
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_handoff_study import price_window
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest as bar_digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256
from lms405_visible_lock_handoff import stamp
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

CONTRACT = "FG2701"
SOURCE_IDS = (
    "S5343083008886025", "S5344171942741583", "A5358325549629506", "WRoCswszPF",
    "WRov1j6e10", "WRovrUdwHi", "WRoAkcEppg", "U03",
)
MINUTE_HASHES = {
    "2026-09-14": "c91019bae89eec405aacfa8492048121abd12c96d20cd36c3bdbd848326b461c",
    "2026-09-15": "16f52b4f9dc7f3a906cf5701145459fe0bc35660681adf9e466d4ebed278887f",
    "2026-09-17": "b24da503f619cbcd3c28fe6c015019bd75484465054ab3f1ebf4b1df1e13a298",
    "2026-10-27": "c8b9b516d1051a775f47ae443ae0cf632af6bcb62096cfe06073db1a1ebe637c",
}
IMAGES = {
    "close_log": ("2026-10-27/U03-orders5-screen.png",
                  "2ae117882abaf8cf38ec50e99ea662d85a3fcfdfc1a7ab4733a892ace3e2db25"),
    "lunch_log": ("2026-10-27/WRoAkcEppg-orders4-screen.png",
                  "5f6f64336c5a267e1654ad15fd951424c71161be1b0dcad609c417ee12dd72ff"),
    "earlier_night_log": ("2026-10-26/WRovrUdwHi-image4-screen.png",
                          "f5afb7da82441bcea7e0b2e96b67b038fb421e9cc51de753fe149e8fc81f0165"),
}
FG_REPORT, LATER_HOLD = SOURCE_IDS[:2]
OCTOBER_PLAN = "A5358325549629506"
PVC_CLOCKS = Path("output/lms405-v-daytime-exit-20261125/final.json")
PVC_CLOCKS_SHA = "18e1c1ebbc8ef71a4d9ab9f74a9ed7a76d3730d9882cb2f4eca4ce556c22aab3"
EXTREME_BAND = Decimal(940), Decimal(946)
PRIOR_LOW = Decimal(925)
OCTOBER_EXIT_BASELINE = Path("output/lms405-fg-exit-20261125/final.json")
OCTOBER_EXIT_SHA = "42263c39dfe67167ede40436e5f0f50cd35e33225e2c4cd4ac899fffa21ef78f"
EXPOSURE = Path("output/lms405-exposure-20261125/exposure-audit.json")
CONTINUITY = Path("output/lms405-position-continuity-20261125/final.json")
CONTINUITY_SHA = "664dad4a242846f9602f86839788a319bf3d0091ece2e7a3cbdedaa731ccca60"
TABLE_TOTALS = Path("docs/research/lms405/evidence/portfolio-oct-table-totals.json")
TABLE_TOTALS_SHA = "474d797405d0e124d391aa34649d892948a4088f0c9963c0c3401bf8ee56ccd0"
ORDER_SCREEN_ROWS = {
    "WRovrUdwHi": ("1415109", "1415102", "102694086", "12979723"),
    "WRoAkcEppg": ("1415102", "1415109", "102694086", "12979723"),
    "U03": ("1415102", "1415109", "102694086", "12979723", "49974780"),
}
JULY_PROTECTION = "S5318448139471722"
JULY_BASELINE = Path("output/lms405-glass-lock-followup-20261125/reviewed.json")
JULY_BASELINE_SHA = "cbc1a8e41badb0cf18cc97c3ce63b82953f916b5f863643561d0cd996690f9f8"
ORDER_BASELINE = Path("output/lms405-fg-order-window-20261126/checked-c.json")
ORDER_BASELINE_SHA = "6fd0463441b614e10548155951ed09a1971a67b5e54574e8dc898daecb3dccde"
PRESSURE_SHA = "dcde821a829910773c4dda7951ff787fb09123d8017f4215716ad4cd844fb1d4"
SHORT_PLAN_ACTIONS = {"protection": "LOCK", "exit_original_short": "EXIT_SHORT"}
FOLLOWUP_PLAN = "A5358686423089344"
FOLLOWUP_RECAP = "S5359038701503531"


def october_followup(session, market):
    """Check the quoted extreme-M range against the full subsequent physical session."""
    index = input_sources()
    sources = {
        key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
        for key in (FOLLOWUP_PLAN, FOLLOWUP_RECAP)
    }
    series = read_window(session, market, CONTRACT, date(2026, 10, 28))
    minutes = series[1]
    start, end = minutes[0].start, minutes[-1].end
    if not stamp(sources[FOLLOWUP_PLAN]) + ONE < start < end < stamp(sources[FOLLOWUP_RECAP]):
        raise ValueError("FG_OCTOBER_FOLLOWUP_SOURCE_OR_SESSION_ORDER_INVALID")
    low, high = Decimal("854"), Decimal("857")
    cutoff = end + 2 * US
    return dict(
        study="FG2701_EXTREME_M_FOLLOWUP", contract=CONTRACT, trading_day=end.date(), sources=sources,
        start=start, end=end, high=max(row.high for row in minutes), close=minutes[-1].close,
        market={f"{period}m": dict(count=len(rows), sha256=bar_digest(rows)) for period, rows in series.items()},
        boundaries={str(edge): boundary_clocks(minutes, edge, "LONG") for edge in (low, high)},
        new_two_close_runs={str(edge): pressure_timeline(minutes, edge) for edge in (low, high)},
        geometry={f"{shape}m_to_{confirm}m": signals(series, shape, confirm, start=start, cut=cutoff, side="LONG")
                  for shape, confirm in VARIANTS},
        original_plan_revision_verified=False, author_version=None, author_action_samples=0,
        author_match_rate=None, actual_action=None, fills=None, pnl=None,
    )


def fg_window(series, start, cutoff, side, *, after_report):
    minutes = completed(series[1], start, cutoff)
    if not minutes:
        raise ValueError("FG_SEPTEMBER_EMPTY_COMPLETED_WINDOW")
    latest = minutes[-1].end + 2 * US
    lower, upper = EXTREME_BAND
    first_overlap = next((bar.end for bar in minutes if bar.low <= upper and lower <= bar.high), None)
    levels = {
        f"{edge}_{direction}": boundary_clocks(minutes, level, direction)
        for edge, level in (("940", lower), ("946", upper)) for direction in ("LONG", "SHORT")
    }
    prior_low = boundary_clocks(minutes, PRIOR_LOW, "SHORT") if after_report else None
    low_break = prior_low["first_close_strict_beyond"] if prior_low else None
    low_cross = prior_low["first_same_segment_new_close_cross"] if prior_low else None
    shapes_by_clock = {}
    for shape, confirm in VARIANTS:
        events = signals(series, shape, confirm, start=start, cut=latest, side=side)
        for anchor in (latest, *(event["available_at"] for event in events)):
            prefix = {p: [bar for bar in bars if bar.end + US < anchor] for p, bars in series.items()}
            if signals(prefix, shape, confirm, start=start, cut=anchor, side=side) != [
                event for event in events if event["available_at"] < anchor
            ]:
                raise ValueError("FG_SEPTEMBER_PREFIX_DRIFT")
        shapes_by_clock[f"{shape}m_to_{confirm}m"] = [
            event | dict(shape_start=event["shape_end"] - shape * ONE,
                         fresh_after_range_overlap=(first_overlap is not None
                                                    and first_overlap + US < event["shape_end"] - shape * ONE),
                         fresh_after_reference_low_close=(low_break is not None
                                                          and low_break + US < event["shape_end"] - shape * ONE),
                         fresh_after_reference_low_new_cross=(low_cross is not None
                                                              and low_cross + US < event["shape_end"] - shape * ONE))
            for event in events
        ]
    minimum = min(bar.low for bar in minutes)
    return dict(window_start=start, last_bar_end=minutes[-1].end, count=len(minutes), low=minimum,
                low_first_at=next(bar.end for bar in minutes if bar.low == minimum), close=minutes[-1].close,
                high=max(bar.high for bar in minutes), open=minutes[0].open, first_overlap=first_overlap,
                price_by_edge=levels, reference_low_925=prior_low, geometry_side=side, geometry=shapes_by_clock)


def compute_september_clocks(session, market):
    pvc = verified_json(PVC_CLOCKS, PVC_CLOCKS_SHA)
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in (FG_REPORT, LATER_HOLD)}
    report_cut, later_cut = (stamp(sources[key]) for key in (FG_REPORT, LATER_HOLD))
    market_digests, windows = {}, {}
    for day in (14, 15, 16, 17):
        trading_day = date(2026, 9, day)
        series = read_window(session, market, CONTRACT, trading_day)
        coverage = {f"{period}m": dict(count=len(rows), sha256=bar_digest(rows)) for period, rows in series.items()}
        frozen = MINUTE_HASHES.get(trading_day.isoformat())
        if frozen is not None and coverage["1m"]["sha256"] != frozen:
            raise ValueError("FG_SEPTEMBER_FROZEN_MARKET_DRIFT")
        market_digests[trading_day.isoformat()] = coverage
        day_open, night_open = at(f"{trading_day}T09:00"), series[1][0].start
        day_close = series[1][-1].end + 2 * US
        before_report = day == 14
        if not night_open < day_open < day_close or (
            before_report and day_close >= report_cut or not before_report and night_open <= report_cut + ONE
        ) or (day == 17 and day_close >= later_cut):
            raise ValueError("FG_SEPTEMBER_SOURCE_OR_SESSION_ORDER_DRIFT")
        side = "LONG" if before_report else "SHORT"
        windows[trading_day.isoformat()] = {
            "night": fg_window(series, night_open, day_open, side, after_report=not before_report),
            "day": fg_window(series, day_open, day_close, side, after_report=not before_report),
        }
    before = windows["2026-09-14"]
    return dict(version="lms405-fg-september-clock-contrast-v1", contract=CONTRACT, sources=sources,
                market=market_digests, windows=windows,
                public_evidence=dict(weak_side_extreme_m=EXTREME_BAND, orientation_in_unretrieved_prior_plan=None,
                                     same_direction_target=None, original_plan_available_at=None,
                                     estimate_low=PRIOR_LOW, estimate_low_available_after=report_cut + ONE,
                                     short_profit_taking_reported=True, actual_reentry=None, actual_short_size=None),
                comparison=dict(pvc_report_sha256=PVC_CLOCKS_SHA, pvc_strict_quote_pairs=pvc["quote_pair_count"],
                                glass_opposing_counts_before_report={
                                    period: sum(len(session["geometry"][period]) for session in before.values())
                                    for period in before["day"]["geometry"]
                                }, author_target_then_opposing_verdict=None),
                admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None)


def minute_context(minutes, disclosed_minute, opening_averages):
    """Assume a natural date for price comparison while leaving the row undated."""
    stamp = at(disclosed_minute)
    earlier = next((b for b in minutes if b.end == stamp), None)
    during = next((b for b in minutes if b.start == stamp), None)
    if earlier is None or during is None:
        raise ValueError("FG_ORDER_COMPARISON_MINUTE_MISSING")
    if earlier.start != stamp - ONE or during.end != stamp + ONE:
        raise ValueError("FG_ORDER_COMPARISON_MINUTE_INVALID")
    return dict(assumed_minute=stamp, last_bar_ending_at_minute=dict(end=earlier.end, close=earlier.close),
                containing_bar=dict(start=during.start, end=during.end, low=during.low,
                                    high=during.high, close=during.close),
                reference_opening_averages={str(avg): dict(inside_bar=during.low <= avg <= during.high,
                                                          strictly_above_all_prices=avg > during.high,
                                                          strictly_below_all_prices=avg < during.low)
                                            for avg in map(Decimal, opening_averages)})


def shapes(series, start, cutoff, direction):
    return {f"5m_to_{confirm}m": geometry_events(series, 5, confirm, start=at(start),
                                                as_of=at(cutoff), side=direction) for confirm in (1, 5)}


def analyze_september(series):
    mark = {"retrospective_extreme_m": "940 946"}
    day = price_window(series["2026-09-14"][1], "2026-09-14T09:00", "2026-09-14T15:01", "LONG", mark)
    night = price_window(series["2026-09-15"][1], "2026-09-14T21:00", "2026-09-14T23:01", "LONG", mark)
    sept17 = price_window(series["2026-09-17"][1], "2026-09-17T09:00", "2026-09-17T15:01", "SHORT",
                          {"reported_strong_side_test": "902 902"})
    return dict(
        source="S5343083008886025", reported_low=925, day=day, followup_night=night,
        night_short_candidates=shapes(series["2026-09-15"], "2026-09-14T21:00", "2026-09-14T23:01", "SHORT"),
        later_source="S5344171942741583", later_reported_low=902, later_day=sept17,
        trading_day_lows={day: min(b.low for b in series[day][1]) for day in ("2026-09-14", "2026-09-17")},
        historical_plan_verified=False, reported_exit_size=None, later_same_system=None,
        later_reentry_verified=False,
    )


def analyze_october(series, sources):
    minutes = series[1]
    day = "2026-10-27"
    open_mark, close_mark = ("2026-10-26T22:10", f"{day}T14:08")
    recognized = {
        "sell_open": {"row_time": "22:10:35", "side": "SHORT", "displayed_status": "FILLED",
                      "same_visible_report_row_sources": ["WRovrUdwHi", "WRoAkcEppg", "U03"]},
        "buy_close": {"row_time": "14:08", "side_closed": "SHORT", "displayed_status": "FILLED",
                      "known_source": "U03"},
    }
    previous_short_post = datetime.fromisoformat(sources["WRov1j6e10"]["published_at"])
    assumed_sell_time = at("2026-10-26T22:10:35")
    plan_publication = datetime.fromisoformat(sources["A5358325549629506"]["published_at"])
    if not plan_publication < at("2026-10-26T21:00") <= previous_short_post < assumed_sell_time:
        raise ValueError("FG_EXIT_SOURCE_TIMELINE_CHANGED")
    return dict(
        software_rows=recognized, row_dates=None, row_prices=None, row_quantities=None, account=None,
        short_display_before_assumed_sell_open=dict(source="WRov1j6e10", publication=previous_short_post,
                                                    lots=20, opening_average="832"),
        sell_open_context=minute_context(minutes, open_mark, ("831", "832")),
        buy_close_context=minute_context(minutes, close_mark, ("831", "832")),
        before_open_path=price_window(minutes, "2026-10-26T21:00", open_mark, "SHORT",
                                      {"restart": "828 832", "short_target": "825 825"}),
        before_close_downside=price_window(minutes, f"{day}T09:00", close_mark, "SHORT",
                                          {"short_first_target": "825 825", "short_extension": "814 821"}),
        before_close_upside=price_window(minutes, f"{day}T09:00", close_mark, "LONG",
                                        {"protection": "829 836", "counter_m": "842 844"}),
        eligible_geometry_before_close_minute={
            direction: shapes(series, f"{day}T11:35", close_mark, direction) for direction in ("LONG", "SHORT")
        },
        visible_short_at_lunch={"with_quantity": {"lots": 20, "opening_average": "832"},
                                "without_quantity": {"lots": None, "opening_average": "831"}},
        visible_short_at_close=None, author_exit_reason=None, actual_reentry=None, cross_log_same_account=None,
    )


def position_cutoffs():
    exposure = verified_json(EXPOSURE, EXPOSURE_SHA256)
    timeline = verified_json(CONTINUITY, CONTINUITY_SHA)["sources"]
    totals = {row["source"]: row for row in verified_json(TABLE_TOTALS, TABLE_TOTALS_SHA)}
    tables = {row["source"]: row for row in exposure["tables"]}
    comparisons = {}
    for source in ("WRoAkcEppg", "U03"):
        table, total = tables[source], totals[source]
        image = table["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"] or image != timeline[source]["image"]:
            raise ValueError("FG_ORDER_WINDOW_IMAGE_CHANGED")
        legs = {f"{contract}:{side}": leg for contract, position in table["contracts"].items()
                for side, leg in position["legs"].items()}
        legs.update({f"{contract}:{side}": {"quantity": lots} for contract, sides in total["other_legs"].items()
                     for side, lots in sides.items()})
        if len(legs) != total["row_count"] or sum(leg["quantity"] for leg in legs.values()) != total["total_lots"]:
            raise ValueError("FG_ORDER_WINDOW_TABLE_TOTAL_CHANGED")
        comparisons[source] = dict(image=image, legs=legs, total_lots=total["total_lots"],
                                   quote_anchor=timeline[source]["quote_anchor"], binding=table["binding"])
    return comparisons


def order_window(session, market):
    baseline = verified_json(OCTOBER_EXIT_BASELINE, OCTOBER_EXIT_SHA)
    index = input_sources()
    sources = {key: index[key] for key in ("WRovrUdwHi", "WRoAkcEppg", "U03", "A5358325549629506", "WRoCswszPF")}
    for source, row in sources.items():
        if any(row[key] != baseline["sources"][source][key] for key in ("published_at", "source_url")):
            raise ValueError("FG_ORDER_WINDOW_SOURCE_CHANGED")
    for label, (relative, digest) in IMAGES.items():
        if sha((ARCHIVE.parent / "02-持仓记录" / relative).read_bytes()) != digest:
            raise ValueError("FG_ORDER_WINDOW_REPORT_IMAGE_CHANGED")

    tables = position_cutoffs()
    before, after = (tables[source] for source in ("WRoAkcEppg", "U03"))
    previous, following = before["legs"], after["legs"]
    missing = {key: previous[key]["quantity"] for key in sorted(previous.keys() - following.keys())}
    common = sorted(previous.keys() & following.keys())
    unchanged_quantity = all(previous[key]["quantity"] == following[key]["quantity"] for key in common)
    no_long_shown = f"{CONTRACT}:long" not in (previous.keys() | following.keys())
    if (not unchanged_quantity or following.keys() - previous.keys()
            or sum(missing.values()) != before["total_lots"] - after["total_lots"]):
        raise ValueError("FG_ORDER_WINDOW_UNRECONCILED_DISPLAY")
    if f"{CONTRACT}:short" not in missing:
        raise ValueError("FG_ORDER_WINDOW_SHORT_ABSENCE_CHANGED")
    prior_short_quantity = missing[f"{CONTRACT}:short"]

    series = read_window(session, market, CONTRACT, date(2026, 10, 27))
    if bar_digest(series[1]) != MINUTE_HASHES["2026-10-27"]:
        raise ValueError("FG_ORDER_WINDOW_MARKET_CHANGED")
    start = datetime.fromisoformat(before["quote_anchor"])
    cutoff = at("2026-10-27T14:08")
    if not start < cutoff < datetime.fromisoformat(after["quote_anchor"]):
        raise ValueError("FG_ORDER_WINDOW_QUOTE_ORDER_CHANGED")
    prices = completed(series[1], start, cutoff)
    checks = {cutoff}
    geometry = {}
    for side in ("LONG", "SHORT"):
        events = fresh_geometry(series, start, cutoff, side)
        cuts = {cutoff} | {event["available_at"] for rows in events.values() for event in rows}
        cuts |= {instant + US for instant in cuts if instant + US < cutoff}
        for instant in cuts:
            prefix = {p: [bar for bar in bars if bar.end + US < instant] for p, bars in series.items()}
            expected = {clock: [event for event in rows if event["available_at"] < instant]
                        for clock, rows in events.items()}
            if fresh_geometry(prefix, start, instant, side) != expected:
                raise ValueError("FG_ORDER_WINDOW_PREFIX_DRIFT")
        checks.update(cuts)
        geometry[side] = events

    edges = {}
    for edge in map(Decimal, ("829", "836", "842", "844")):
        runs = strict_runs(prices, edge, "LONG")
        edges[str(edge)] = boundary_clocks(prices, edge, "LONG") | dict(
            first_new_cross_two_closes_at=next((end for end, run in runs.items()
                                               if run["fresh_crossing_known_at"] and run["close_count"] >= 2), None),
        )
    return dict(
        version="lms405-fg-october-order-window-v1", contract=CONTRACT, baseline_sha256=OCTOBER_EXIT_SHA,
        sources=sources, software_images=IMAGES, software_sequence_by_source=ORDER_SCREEN_ROWS,
        shared_order_ids=sorted(set.intersection(*(set(rows) for rows in ORDER_SCREEN_ROWS.values()))),
        newly_visible_at_close=sorted(set(ORDER_SCREEN_ROWS["U03"]) - set(ORDER_SCREEN_ROWS["WRoAkcEppg"])),
        software_buy_close=dict(report_order_id="49974780", displayed_time="14:08", displayed_filled=True,
                                executed_date=None, executed_price=None, executed_quantity=None, account=None,
                                strategy_version=None),
        position_tables=tables, same_quantity_common_rows=common, no_long_row_shown_in_either_table=no_long_shown,
        position_rows_unlisted_at_close=missing, assumed_close_minute_start=cutoff,
        conditional_position_conclusions=dict(
            required_assumptions=["SAME_ACCOUNT", "BOTH_POSITION_TABLES_COMPLETE_AND_SYNCHRONIZED_WITH_QUOTE_ANCHORS",
                                  "NORMAL_OPEN_CLOSE_POSITION_ACCOUNTING"],
            short_quantity_decrease=prior_short_quantity, minimum_buy_close_quantity_in_interval=prior_short_quantity,
            single_order_quantity=dict(quantity=prior_short_quantity, additional_assumption=
                                       "REPORT_49974780_IS_THIS_ACCOUNTS_ONLY_FG_POSITION_CHANGE_IN_INTERVAL"),
        ),
        chronological_single_stream_verified=False, actual_account_continuity=None,
        retrospective_price_conditions=edges, before_observed_minute_geometry=geometry,
        market={f"{p}m": dict(count=len(rows), sha256=bar_digest(rows)) for p, rows in series.items()},
        prefix_checks=len(checks), historical_plan_verified=False, author_exit_reason=None,
        admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None,
    )


def new_crosses(minutes, edge, side):
    return {run["fresh_crossing_known_at"]: end for end, run in strict_runs(minutes, edge, side).items()
            if run["fresh_crossing_known_at"] is not None and run["close_count"] == 2}


def first_same_segment_recapture(minutes, down, up):
    for segment in continuous_groups(minutes):
        first_down = next((end for end in down.values() if segment[0].start < end <= segment[-1].end), None)
        if first_down is None:
            continue
        first_up = next((end for instant, end in up.items()
                         if first_down + US < instant and end <= segment[-1].end), None)
        if first_up is not None:
            return dict(down_two_closes_at=first_down, recapture_two_closes_at=first_up)
    return None


def pressure_timeline(minutes, edge):
    """Two-close crossing evidence in each direction and a same-session recovery."""
    up = new_crosses(minutes, edge, "LONG")
    down = new_crosses(minutes, edge, "SHORT")
    return dict(first_up_two_closes_at=next(iter(up.values()), None),
                first_down_two_closes_at=next(iter(down.values()), None),
                up_after_down_in_same_segment=first_same_segment_recapture(minutes, down, up))


def range_recapture(minutes, lower, upper):
    return first_same_segment_recapture(minutes, new_crosses(minutes, lower, "SHORT"),
                                        new_crosses(minutes, upper, "LONG"))


def compare_exit_pressure(session, market):
    july = verified_json(JULY_BASELINE, JULY_BASELINE_SHA)
    order = verified_json(ORDER_BASELINE, ORDER_BASELINE_SHA)
    index = input_sources()
    cases = (
        ("july_4_0_5_protection", "FG2609", "2026-07-08", JULY_PROTECTION, "LOCK_INTENDED", (957, 960)),
        ("september_4_0_5_take_profit", CONTRACT, "2026-09-14", FG_REPORT, "TAKE_PROFIT_REPORTED", (940, 946)),
        ("october_software_buy_close", CONTRACT, "2026-10-27", "U03", "BUY_CLOSE_ROW_VERSION_UNKNOWN",
         (829, 836, 842, 844)),
    )
    observations = {}
    for label, contract, date_text, source_id, statement, levels in cases:
        source = index[source_id]
        published = datetime.fromisoformat(source["published_at"])
        series = read_window(session, market, contract, date.fromisoformat(date_text))
        market_id = {f"{p}m": dict(count=len(rows), sha256=bar_digest(rows)) for p, rows in series.items()}
        if source_id == JULY_PROTECTION:
            frozen = july["market_digests"][date_text]
            if any(row != {"count": frozen[p]["bars"], "sha256": frozen[p]["sha256"]}
                   for p, row in market_id.items()):
                raise ValueError("FG_PRESSURE_FROZEN_JULY_MARKET_CHANGED")
        elif market_id["1m"]["sha256"] != MINUTE_HASHES[date_text]:
            raise ValueError("FG_PRESSURE_FROZEN_MARKET_CHANGED")
        is_order = source_id == "U03"
        start = at(f"{date_text}T11:30") if is_order else series[1][0].start
        cutoff = at(f"{date_text}T14:08") if is_order else series[1][-1].end + 2 * US
        if not start < cutoff < published or (is_order and market_id != order["market"]):
            raise ValueError("FG_PRESSURE_SOURCE_SCOPE_CHANGED")
        active = completed(series[1], start, cutoff)
        bounds = {str(edge): pressure_timeline(active, Decimal(edge)) for edge in levels}
        bands = tuple(zip(levels[::2], levels[1::2]))
        recaptures = {(lower, upper): range_recapture(active, Decimal(lower), Decimal(upper)) for lower, upper in bands}
        clock_end = {
            time for row in bounds.values() for time in (row["first_up_two_closes_at"],
                                                        row["first_down_two_closes_at"],
                                                        (row["up_after_down_in_same_segment"] or {}).get(
                                                            "recapture_two_closes_at")) if time is not None
        }
        clock_end.update(pair["recapture_two_closes_at"] for pair in recaptures.values() if pair)
        for end in sorted(clock_end):
            prefix = completed(series[1], start, end + US)
            for edge, row in bounds.items():
                expected = {key: value if value and value < end else None for key, value in row.items()
                            if not isinstance(value, dict)}
                pair = row["up_after_down_in_same_segment"]
                expected["up_after_down_in_same_segment"] = pair if pair and pair["recapture_two_closes_at"] < end else None
                if pressure_timeline(prefix, Decimal(edge)) != expected:
                    raise ValueError("FG_PRESSURE_PREFIX_CHANGED")
            for (lower, upper), pair in recaptures.items():
                expected = pair if pair and pair["recapture_two_closes_at"] < end else None
                if range_recapture(prefix, Decimal(lower), Decimal(upper)) != expected:
                    raise ValueError("FG_PRESSURE_RANGE_PREFIX_CHANGED")
        geometry = fresh_geometry(series, start, cutoff, "LONG")
        observations[label] = dict(
            contract=contract, source_id=source_id, source=source, author_statement=statement,
            start=start, cutoff_exclusive=cutoff, completed_minutes=len(active), market=market_id,
            edges=bounds, long_geometry_counts={clock: len(events) for clock, events in geometry.items()},
            full_range_recaptures={f"{lower}–{upper}": pair for (lower, upper), pair in recaptures.items()},
            price_prefix_checks=len(clock_end), author_action_at=None, author_exit_trigger=None,
        )
    return dict(
        version="lms405-fg-exit-pressure-study-v1", cases=observations, retrospective=True,
        frozen_evidence_sha256={"july": JULY_BASELINE_SHA, "october": ORDER_BASELINE_SHA},
        author_match_rate=None, admitted_author_samples=0, executable=False, fills=None, pnl=None,
    )


def short_pressure_case(label, purpose, contract, source, available_at, version_405):
    return PublicCase(
        f"{label}:{contract}:{purpose}", contract, source, available_at, version_405,
        (SHORT_PLAN_ACTIONS[purpose],),
        (("PLAN_AUTHORIZES_PURPOSE", "COMPLETED_PRESSURE", "PURPOSE_CONFIRMATION"),),
        (("PLAN_AUTHORIZES_PURPOSE", "COMPLETED_PRESSURE"), ("COMPLETED_PRESSURE", "PURPOSE_CONFIRMATION")),
    )


def assess_short_pressure(case, close_at, as_of, *, purpose_allowed=None, approval=None,
                          plan_known_at=None, approval_at=None):
    """Project a unit old short under a purpose-specific, external plan."""
    price = Condition("COMPLETED_PRESSURE", case.id, case.contract, True, close_at, close_at + US,
                      "FROZEN_MARKET_PRICE_ONLY", "EVENT_TIME")
    facts = [price]
    if purpose_allowed is not None:
        # Late knowledge cannot bind an already completed market observation to a plan.
        value = purpose_allowed if plan_known_at < close_at else None
        facts.append(Condition("PLAN_AUTHORIZES_PURPOSE", case.id, case.contract, value,
                               case.available_at, plan_known_at, "TEST_FIXTURE", "EVENT_TIME"))
    if approval is not None:
        # Bind the approval to information available at decision time, as well as evaluation time.
        if approval_at <= max(fact.known_at for fact in facts):
            approval = None
        facts.append(Condition("PURPOSE_CONFIRMATION", case.id, case.contract, approval,
                               approval_at, approval_at + US, "TEST_FIXTURE", "EVENT_TIME"))
    unit = Decimal(1)
    position = Position(case.contract, short=unit)
    result = assess_case(case, position, Action(case.actions[0], unit), tuple(facts), as_of=as_of)
    return result | dict(
        before={"long": str(position.long), "short": str(position.short)},
        conditions={fact.name: dict(value=fact.value, source=fact.source, observed_at=fact.observed_at,
                                   known_at=fact.known_at) for fact in facts if fact.known_at < as_of},
    )


def plan_intent_sources(pressure):
    expected = {row["source_id"]: row["source"] for row in pressure["cases"].values()}
    expected[OCTOBER_PLAN] = input_sources()[OCTOBER_PLAN]
    result = {}
    with ARCHIVE.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = row["source_id"]
            if key not in expected:
                continue
            source = expected[key]
            if (key in result or row["path"] != source["archive_path"]
                    or row["published_at"] != source["published_at"] or row["url"] != source["source_url"]):
                raise ValueError("FG_PLAN_INTENT_ARCHIVE_BINDING_CHANGED")
            result[key] = dict(observed_at=datetime.fromisoformat(row["observed_at"]),
                               archive_sha256=sha((ARCHIVE.parent / row["path"]).read_bytes()),
                               source_url=row["url"], published_at=row["published_at"], archive_path=row["path"])
    if set(result) != set(expected):
        raise ValueError("FG_PLAN_INTENT_ARCHIVE_SOURCE_MISSING")
    return result


def compare_plan_intents(pressure, source_reads):
    """Compare what a separately authorized purpose changes on identical frozen price evidence."""
    public = {}
    definitions = (
        ("july_4_0_5_protection", "FG2609", "960", True, ("protection",)),
        ("september_4_0_5_take_profit", CONTRACT, "946", True, ("exit_original_short",)),
        ("october_software_buy_close", CONTRACT, "836", None, tuple(SHORT_PLAN_ACTIONS)),
    )
    fixture_close = None
    for label, contract, edge, version, purposes in definitions:
        row = pressure["cases"][label]
        cutoff = datetime.fromisoformat(row["cutoff_exclusive"])
        close_at = datetime.fromisoformat(row["edges"][edge]["first_up_two_closes_at"]).astimezone(cutoff.tzinfo)
        publication = datetime.fromisoformat(row["source"]["published_at"])
        source = source_reads[row["source_id"]]
        if row["contract"] != contract or not close_at + 6 * US < cutoff <= publication <= source["observed_at"]:
            raise ValueError("FG_PLAN_INTENT_PRICE_OR_SOURCE_WINDOW_INVALID")
        if label == "october_software_buy_close":
            fixture_close = close_at
        public[label] = {}
        for purpose in purposes:
            case = short_pressure_case(label, purpose, contract, row["source_id"], source["observed_at"], version)
            price_only = short_pressure_case("PRICE_ONLY", purpose, contract, "FROZEN_MARKET_PRICE_ONLY",
                                             source["observed_at"], None)
            public[label][purpose] = dict(
                before_disclosure=assess_short_pressure(price_only, close_at, cutoff),
                archived_readback=assess_short_pressure(case, close_at, case.available_at + US),
            )

    # Use the October close in both treatments. The historical 829–836 zone only
    # has a protection role in the archive. The alternative represents a separately
    # declared trailing profit exit, not a claim the original target was reached.
    close_at = fixture_close
    plan_at, approval_at = close_at - ONE, close_at + 2 * US
    approval_known_at = approval_at + US
    evaluated_at = approval_known_at + US
    fixture_inputs = dict(purpose_allowed=True, plan_known_at=plan_at, approval=True, approval_at=approval_at)
    fixtures = {}
    for purpose in SHORT_PLAN_ACTIONS:
        case = short_pressure_case("TEST_FIXTURE", purpose, CONTRACT, "TEST_FIXTURE", plan_at, True)
        fixtures[purpose] = dict(
            approved=assess_short_pressure(case, close_at, evaluated_at, **fixture_inputs),
            price_only=assess_short_pressure(case, close_at, evaluated_at),
            before_close_known=assess_short_pressure(case, close_at, close_at + US, **fixture_inputs),
            before_plan_known=assess_short_pressure(
                case, close_at, approval_known_at,
                **(fixture_inputs | {"plan_known_at": approval_known_at}),
            ),
            plan_learned_after_approval=assess_short_pressure(
                case, close_at, evaluated_at,
                **(fixture_inputs | {"plan_known_at": approval_known_at}),
            ),
            plan_learned_after_pressure=assess_short_pressure(
                case, close_at, evaluated_at,
                **(fixture_inputs | {"plan_known_at": close_at + US}),
            ),
            approval_without_plan=assess_short_pressure(
                case, close_at, evaluated_at, approval=True, approval_at=approval_at,
            ),
            at_approval_known=assess_short_pressure(case, close_at, approval_known_at, **fixture_inputs),
            simultaneous=assess_short_pressure(
                case, close_at, evaluated_at, **(fixture_inputs | {"approval_at": close_at}),
            ),
            wrong_purpose=assess_short_pressure(
                case, close_at, evaluated_at, **(fixture_inputs | {"purpose_allowed": False}),
            ),
            denied=assess_short_pressure(case, close_at, evaluated_at, **(fixture_inputs | {"approval": False})),
        )
    return dict(
        version="lms405-fg-plan-intent-contrast-v1", contract=CONTRACT, pressure_at=close_at, pressure_edge="836",
        pressure_report_sha256=PRESSURE_SHA, source_reads=source_reads, public=public, fixtures=fixtures,
        source_read_times_are_not_event_times=True,
        fixture_exit_intent="EXPLICIT_TRAILING_PROFIT_EXIT_ON_THE_SHARED_PRESSURE_EVENT",
        author_match_rate=None, admitted_author_samples=0, executable=False, fills=None, pnl=None,
    )


def compute(session, market):
    index = input_sources()
    sources = {key: index[key] | {"archive_sha256": sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes())}
               for key in SOURCE_IDS}
    images = {}
    for key, (relative, digest) in IMAGES.items():
        source = ARCHIVE.parent / "02-持仓记录" / relative
        if sha(source.read_bytes()) != digest:
            raise ValueError("FG_EXIT_IMAGE_CHANGED")
        images[key] = dict(path=str(source), sha256=digest)
    series, coverage = {}, {}
    for day, minute_hash in MINUTE_HASHES.items():
        raw, series[day] = read_pair(session, market, CONTRACT, (date.fromisoformat(day),))
        coverage[day] = {f"{period}m": dict(count=len(rows), sha256=bars_sha(rows)) for period, rows in raw.items()}
        if coverage[day]["1m"]["sha256"] != minute_hash:
            raise ValueError("FG_EXIT_FROZEN_MARKET_CHANGED")
    return dict(version="lms405-fg-exit-study-v1", contract=CONTRACT, sources=sources, images=images, market=coverage,
                september=analyze_september(series), october=analyze_october(series["2026-10-27"], sources),
                admitted_author_samples=0, author_matches=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--september-clocks", action="store_true")
    group.add_argument("--order-window", action="store_true")
    group.add_argument("--pressure-contrast", action="store_true")
    group.add_argument("--october-followup", action="store_true")
    group.add_argument("--plan-intents", type=Path, metavar="FROZEN_PRESSURE_REPORT")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("OUTPUT_EXISTS")
    if args.plan_intents is not None:
        try:
            pressure = verified_json(args.plan_intents, PRESSURE_SHA)
            result = compare_plan_intents(pressure, plan_intent_sources(pressure))
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded(result))
        except (OSError, ValueError, KeyError):
            parser.exit(2, "FG_PLAN_INTENT_FROZEN_INPUT_UNVERIFIED\n")
        return
    if args.env_file is None or not args.env_file.is_file():
        parser.error("ENV_FILE_MISSING")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            if args.september_clocks:
                run = compute_september_clocks
            elif args.pressure_contrast:
                run = compare_exit_pressure
            elif args.october_followup:
                run = october_followup
            else:
                run = order_window if args.order_window else compute
            result = run(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError):
        parser.exit(2, "FG_EXIT_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
