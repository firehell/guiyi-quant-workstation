"""Narrow nine-product visible-leg retention bounds with joint opening-price sums."""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_oi_leg_intent import CONTINUITY, CONTINUITY_SHA, SPECS_SHA
from lms405_portfolio_leg_audit import SH_REREAD, SH_REREAD_SHA, scoped_input_quotes
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS
from lms405_position_continuity import INPUTS, SNAPSHOTS, continuity
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_pta_pause_carry import MORNING as PTA_MORNING
from lms405_pta_pause_carry import MORNING_IMAGE, MORNING_IMAGE_SHA
from lms405_pta_pause_carry import REFERENCE as PTA_ENTRY
from lms405_pta_pause_carry import REFERENCE_SHA as PTA_ENTRY_SHA
from lms405_replay import read_session_series
from lms405_right_side_study import ONE
from lms405_sizing_audit import SPECS, load_specs
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-retention-prices-v1"
SIDES = ("long", "short")
PTA_CARRY = Path("output/lms405-pta-pause-carry-20261126/reviewed-a.json")
PTA_SHA = "f3d0e65fefc9f64265809b1bff2f861078b39e2b61beda70ebff06dfdafa71ff"


def feasible_retention(before, after, bounds, old_totals, new_totals, old, interim, today, *, same_day):
    """Necessary integer tick bounds with one shared sum for the retained lots."""
    if not old_totals or not new_totals:
        return []
    old_low, old_high = old
    counts = []
    for retained in range(bounds[0], bounds[1] + 1):
        removed, added = before - retained, after["quantity"] - retained
        keep_low = max(retained * old_low, old_totals.start - removed * old_high)
        keep_high = min(retained * old_high, old_totals.stop - 1 - removed * old_low)
        new_today = after["today_quantity"]
        if same_day or new_today is None:
            groups = [(added, today)]
        else:
            groups = [(added - new_today, interim), (new_today, today)]
        if (keep_low > keep_high
                or any(qty < 0 or (qty and interval is None) for qty, interval in groups)):
            continue
        add_low = sum(qty * interval[0] for qty, interval in groups if qty)
        add_high = sum(qty * interval[1] for qty, interval in groups if qty)
        if max(keep_low + add_low, new_totals.start) <= min(keep_high + add_high, new_totals.stop - 1):
            counts.append(retained)
    return counts


def capture_window(source, quote, bars, bar_index):
    day = date.fromisoformat(source["trading_day"])
    published = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0)
    day_bars = [bar for bar in bars if bar.trading_day == day]
    if source["quote_anchor"]:
        bounds = [datetime.fromisoformat(source["quote_anchor"])]
        identity = "JOINT_QUOTE_ANCHOR"
    elif quote and quote["contains"]:
        bounds = sorted(datetime.fromisoformat(end) for end in quote["contains"])
        identity = "SINGLE_ROW_QUOTE_MINUTE_ENVELOPE"
    else:
        # Using every possible minute of the named session is deliberately permissive.
        eligible = [bar.bar_end for bar in day_bars if bar.bar_end - ONE < published + ONE]
        if not eligible:
            raise ValueError("LMS_RETENTION_PUBLICATION_WINDOW_EMPTY")
        return dict(day=day, earliest=eligible[0], latest=eligible[-1], scope="CONDITIONAL_NAMED_SESSION_NO_QUOTE")
    for end in bounds:
        bar = bar_index[end]
        if (bar.trading_day != day or end >= published
                or (identity == "SINGLE_ROW_QUOTE_MINUTE_ENVELOPE"
                    and not bar.low <= Decimal(quote["mark"]) <= bar.high)):
            raise ValueError("LMS_RETENTION_QUOTE_CHANGED")
    return dict(day=day, earliest=bounds[0], latest=bounds[-1], scope=identity)


def compare(before_leg, after_leg, coarse, early, late, bars, tick, *, prior_close=False):
    bounds = coarse["bounds"]
    if bounds is None:
        return dict(status="ENDPOINT_CONFLICT" if coarse.get("inconsistent_same_scope") else "SIDE_UNLISTED",
                    retained=None)
    before, after = before_leg["quantity"], after_leg["quantity"]
    same_day = early["day"] == late["day"]
    first, second = before_leg["opening_average"], after_leg["opening_average"]
    if first is None or second is None or late["latest"] < early["earliest"]:
        return dict(status="AVERAGE_OR_CAPTURE_UNVERIFIED", retained=None)
    old_totals = displayed_tick_totals(Decimal(first), before, tick)
    new_totals = displayed_tick_totals(Decimal(second), after, tick)
    if not old_totals or not new_totals:
        return dict(status="DISPLAY_AVERAGE_OUTSIDE_TICK_GRID", retained=None)
    old_prefix_bound = before == before_leg["today_quantity"]
    old = (tick_bounds([b for b in bars if b.trading_day == early["day"] and b.bar_end <= early["latest"]], tick)
           if old_prefix_bound else (1, old_totals.stop - 1))
    # The earlier quote minute can straddle the capture. At a verified close,
    # new lots must instead use a minute from a later trading day.
    new_rows = [bar for bar in bars if early["earliest"] <= bar.bar_end <= late["latest"]
                and (not prior_close or bar.trading_day > early["day"])]
    now, previous = ([b for b in new_rows if b.trading_day == late["day"]],
                     [b for b in new_rows if b.trading_day < late["day"]])
    if after_leg["today_quantity"] is None:
        now = new_rows
    today, interim = tick_bounds(now, tick), tick_bounds(previous, tick)
    counts = feasible_retention(before, after_leg, bounds, old_totals, new_totals, old, interim, today,
                                same_day=same_day)
    old_counts = set(range(bounds[0], bounds[1] + 1))
    return dict(
        status="PRICE_SCOPE_CONFLICT" if not counts else "PRICE_TIGHTENED" if old_counts != set(counts) else "UNCHANGED_BOUND",
        retained=counts, coarse_retained=list(bounds), old_ticks=old, old_open_within_first_trading_day=old_prefix_bound,
        new_today_ticks=today, new_older_ticks=interim, old_tick_sum=[old_totals.start, old_totals.stop - 1],
        new_tick_sum=[new_totals.start, new_totals.stop - 1], retained_all_prior=before in counts,
        partly_replaced=any(0 < n < min(before, after) for n in counts), full_replacement=0 in counts,
    )


def corrected_endpoint(source, contract, legs, correction):
    if (source, contract) != (correction["source_id"], "SH2701"):
        return legs
    observed = legs["long"]
    if observed["quantity"] != correction["today_quantity"] or observed["today_quantity"] is not None:
        raise ValueError("LMS_RETENTION_SH_REREAD_CHANGED")
    return legs | {"long": observed | {"today_quantity": correction["today_quantity"]}}


def observations(transitions, contract, references, correction):
    """Keep adjacent comparisons and recover pairs across intermediate unlisted directions."""
    visible, pairs = {}, {}
    for row in transitions:
        before, after = row["earlier"], row["later"]
        visible[before] = corrected_endpoint(before, contract, row["earlier_legs"], correction)
        visible[after] = corrected_endpoint(after, contract, row["later_legs"], correction)
        for side in SIDES:
            # Preserve independently verified restraints from the existing report.
            pairs[(before, after, side)] = (row["sides"][side], row["verified_session_boundary"])
    for side in SIDES:
        history = sorted((key for key, legs in visible.items() if side in legs),
                         key=lambda key: references[key]["published_at"])
        for before, after in zip(history, history[1:]):
            if (before, after, side) not in pairs:
                pairs[(before, after, side)] = (continuity(
                    visible[before][side], visible[after][side],
                    same_day=references[before]["trading_day"] == references[after]["trading_day"],
                ), None)
    return visible, pairs


def add_pta_pair(refs, quotes):
    entry = verified_json(PTA_ENTRY, PTA_ENTRY_SHA)
    carry = verified_json(PTA_CARRY, PTA_SHA)
    night = entry["snapshot"]["source"]
    old = entry["snapshot"]["legs"]["long"]
    new = {key: carry["morning_long"][key] for key in old}
    day = carry["trading_day"]
    if (carry["frozen_input_sha256"] != PTA_ENTRY_SHA or refs[night]["trading_day"] != day
            or any(old[key] != new[key] for key in ("quantity", "today_quantity"))
            or Decimal(old["opening_average"]) != Decimal(new["opening_average"])
            or refs[night]["image"] != entry["snapshot"]["image"]):
        raise ValueError("LMS_RETENTION_PTA_DISPLAY_CHANGED")
    refs[PTA_MORNING] = carry["sources"][PTA_MORNING] | dict(
        trading_day=day, quote_anchor=None, image=dict(path=MORNING_IMAGE, sha256=MORNING_IMAGE_SHA),
        timing_scope="CONDITIONAL_POST_SESSION", binding="SYSTEM_POST_MIXED_ROWS",
    )
    quotes[(night, "TA2701")] = dict(mark=entry["row_mark"]["price"], contains=entry["row_mark"]["quote_captures"])
    quotes[(PTA_MORNING, "TA2701")] = carry["morning_quote"]["per_symbol"]["ta"]
    return (
        {night: {"long": old}, PTA_MORNING: {"long": new}},
        {(night, PTA_MORNING, "long"): (continuity(old, new, same_day=True), None)},
        {day: carry["ta_market"]["1m"]},
    )


def study(session, market):
    frozen = verified_json(CONTINUITY, CONTINUITY_SHA)
    anchors = verified_json(SNAPSHOTS, INPUTS[SNAPSHOTS])["market_1m"]
    sh = verified_json(SH_REREAD, SH_REREAD_SHA)["with_night_today_quantity"]
    specs, quotes = load_specs(verified_json(SPECS, SPECS_SHA)), scoped_input_quotes()
    refs = frozen["sources"]
    pta_visible, pta_pairs, pta_market = add_pta_pair(refs, quotes)
    for source in refs.values():
        image = source["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("LMS_RETENTION_IMAGE_CHANGED")
    if refs[sh["source_id"]]["image"]["sha256"] != sh["image_sha256"]:
        raise ValueError("LMS_RETENTION_SH_IMAGE_CHANGED")
    results = {}
    for contract in CONTRACTS:
        tick = specs[contract]["tick"]
        bars = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, DAYS)
        bar_index = {bar.bar_end: bar for bar in bars}
        bars_by_day = defaultdict(list)
        for bar in bars:
            bars_by_day[bar.trading_day].append(bar)
        market_days = {str(day): dict(count=len(bars_by_day[day]), sha256=bars_sha(bars_by_day[day])) for day in DAYS}
        if any(market_days.get(key.split(":")[1]) != observation for key, observation in anchors.items()
               if key.startswith(f"{contract}:")):
            raise ValueError("LMS_RETENTION_PREVIOUS_MARKET_CHANGED")
        history = frozen["contracts"][contract]
        visible, pairs = observations(history["transitions"], contract, refs, sh)
        if contract == "TA2701":
            if visible or pairs or any(market_days[day] != row for day, row in pta_market.items()):
                raise ValueError("LMS_RETENTION_PTA_MARKET_OR_PAIR_CHANGED")
            visible, pairs = pta_visible, pta_pairs
        scopes = {key: capture_window(refs[key], quotes.get((key, contract)), bars, bar_index) for key in visible}
        checks = []
        for (before, after, side), (coarse, session_bound) in pairs.items():
            early, late = scopes[before], scopes[after]
            if session_bound and (market_days[str(early["day"])] != session_bound["earlier_day"]
                                  or market_days[str(late["day"])] != session_bound["later_day"]
                                  or early["latest"] != datetime.fromisoformat(session_bound["last_end"])):
                raise ValueError("LMS_RETENTION_SESSION_BOUNDARY_CHANGED")
            earlier, later = visible[before].get(side), visible[after].get(side)
            row = compare(earlier, later, coarse, early, late, bars, tick, prior_close=session_bound is not None)
            checks.append(dict(before=before, after=after, side=side, earlier_leg=earlier, later_leg=later,
                               prior_session_close=session_bound is not None, **row))
        results[contract] = dict(visible_tables=len(visible), market=market_days, capture_scopes=scopes,
                                 checks=checks, summary=dict(Counter(row["status"] for row in checks)))
    return dict(
        version=VERSION, contracts=results, snapshot_sources=refs,
        inputs=dict(continuity=CONTINUITY_SHA, sh_reread=SH_REREAD_SHA, contract_ticks=SPECS_SHA,
                    pta_entry=PTA_ENTRY_SHA, pta_carry=PTA_SHA),
        assumptions=["SAME_ACCOUNT_AND_VISIBLE_POSITION_SCOPE", "CONSISTENT_TRADING_DAY_AND_AVERAGE_FIELDS",
                     "QUOTE_MINUTE_AND_POSITION_ROW_SYNCHRONIZED_WHEN_QUOTE_ANCHORED",
                     "INTEGER_PRICE_ENVELOPES_NECESSARY_ONLY"],
        author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=75):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("LMS_RETENTION_") and code.isidentifier()
                        else "LMS_RETENTION_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
