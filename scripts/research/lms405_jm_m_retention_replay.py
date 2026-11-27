"""Replay JM2601 long-lot histories and compare the frozen JM2701 counter-M paths."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_lot_roles import DECEMBER, DECEMBER_SHA, exit_projection
from lms405_jm2601_m_window import TICK, read_sources
from lms405_jm2601_structure import DAYS, LOCAL, ONE
from lms405_portfolio_retention_prices import feasible_retention
from lms405_protection_lot_timing import displayed_tick_totals, tick_bounds, verified_json
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

SETTLEMENT = Path("output/jm-paper-first-three-20261011/execution-facts-v2.json")
SETTLEMENT_SHA = "b15ec9ad682f0ce6f7d40749bc395f8bf2269935235c0900b50aa87316785d5e"
OCTOBER = Path("output/lms405-jm-first-lock-handoff-20261126/final-a.json")
OCTOBER_SHA = "477cd10a951d399f3e8bc44641d37a899634ae82c532055f4e3412b0f0594310"
P2 = Path("output/lms405-p2-two-leg-20261127")
P2_SHA = {
    "jm-0-all": "1416254706c16620ddf4a67ede3f511a08c8ad27e92715f3611b6d1160ac3483",
    "jm-13-all": "cc55208551e573271aeea8595f346250726231bdfc622f786c7f75fd5a499181",
    "jm-13-public": "138ef87adb15e62bdfef0b86c5fc23d23ed0bc3d59f5f3c26b3c0b69f88d6045",
}


def december_paths(retained, capture_boundary, day_close, cutoff, historical_shorts):
    replaced = 20 - retained
    stages = [dict(event="OBSERVED_START_IF_SAME_SCOPE", old_protection_lots=20,
                   replacement_lots=0, december_today_lots=0, long=20, short=historical_shorts)]
    if replaced:
        # The two operations imply quantities, not an intraday execution order.
        stages.append(dict(event="PRE_CLOSE_REPLACEMENT_IF_FEASIBLE", close_old_long=replaced,
                           open_replacement_long=replaced, window_after=capture_boundary,
                           window_through=day_close, old_protection_lots=retained,
                           replacement_lots=replaced, december_today_lots=0, long=20, short=None))
    stages.extend([
        dict(event="START_OF_NEXT_TRADING_DAY", old_protection_lots=retained,
             replacement_lots=replaced, carried_long=20, today_long=0, long=20, short=None),
        dict(event="TWO_SURVIVING_NEW_TRADING_DAY_LONGS", old_protection_lots=retained,
             replacement_lots=replaced, carried_long=20, today_long=2, long=22, short=None,
             cutoff_exclusive=cutoff),
    ])
    role_quantities = {"ONLY_TODAY_LOTS_ARE_M": 2, "ALL_VISIBLE_LONGS_ARE_M": 22}
    if replaced:
        role_quantities["REPLACEMENT_AND_TODAY_LOTS_ARE_M"] = replaced + 2
    exits = {role: {case: exit_projection("JM2601", 22, short, qty) for case, short in (
        ("ORIGINAL_SHORT_STILL_HELD", historical_shorts), ("ORIGINAL_SHORT_CLOSED_NO_OTHER_SHORT", 0),
    )} for role, qty in role_quantities.items()}
    return dict(path="PRE_CLOSE_PARTIAL_REPLACEMENT" if replaced else "ALL_OLD_LONGS_RETAINED",
                retained=retained, replaced=replaced, stages=stages, exits=exits,
                minimum_long_turnover_through_m_snapshot=2 * replaced + 2)


def december(minutes, frozen, daily):
    rows = [(b.bar_end.isoformat(), *map(str, ohlc(b))) for b in minutes]
    expected = frozen["input_ohlc"]["1m"]
    if len(rows) != expected["count"] or sha(encoded(rows).encode()) != expected["hash"]:
        raise ValueError("JM_RETENTION_MARKET_CHANGED")
    first_day, last_day = DAYS[1:]
    first_day_bars = [b for b in minutes if b.trading_day == first_day]
    day_close = first_day_bars[-1].bar_end.astimezone(LOCAL)
    cutoff = datetime.fromisoformat(frozen["snapshot_post_display_minute"])
    settlement = {row["date"]: row for row in daily["contracts"]["JM2601"]["daily"]}
    settle = Decimal(settlement[last_day.isoformat()]["prev_settlement"])
    lots = frozen["added_lot_hypothesis"]
    if settle != Decimal(settlement[first_day.isoformat()]["settlement"]) or (
        lots["old_lots"], lots["visible_lots"], lots["visible_today_lots"]
    ) != (20, 22, 2):
        raise ValueError("JM_RETENTION_POSITION_OR_SETTLEMENT_CHANGED")
    (start_total,) = displayed_tick_totals(Decimal(lots["old_display_open_average"]), 20, TICK)
    (end_total,) = displayed_tick_totals(Decimal(lots["visible_display_open_average"]), 22, TICK)
    (marked_total,) = displayed_tick_totals(Decimal("1065.89"), 22, TICK)
    today_total = marked_total - int(20 * settle / TICK)
    yesterday_total = end_total - today_total
    today_windows = frozen["conditional_price_envelopes"]
    if today_total != lots["conditional_total_ticks"][0] or not today_windows[
        "trading_day_through_snapshot_cutoff"
    ]["envelope_allows_average"]:
        raise ValueError("JM_RETENTION_TODAY_PRICE_CONFLICT")

    checkpoints = {}
    for hour, minute in ((9, 56), (14, 40), (15, 0)):
        capture = day_close.replace(hour=hour, minute=minute)
        old = tick_bounds([b for b in first_day_bars if b.bar_end <= capture], TICK)
        replacement = tick_bounds([b for b in first_day_bars if b.bar_end > capture], TICK)
        retained = feasible_retention(20, {"quantity": 20, "today_quantity": 20}, (0, 20),
                                      range(start_total, start_total + 1), range(yesterday_total, yesterday_total + 1),
                                      old, None, replacement, same_day=True)
        checkpoints[capture.isoformat()] = dict(old_ticks=old, replacement_ticks=replacement, possible_retention=retained,
                                                paths=[december_paths(k, capture, day_close, cutoff, 20)
                                                       for k in retained if k > 0])
    return dict(checkpoints=checkpoints, source_ids=["N01", "N02", "O02", "N05"],
                frozen_ohlc=expected, end_opening_average=lots["visible_display_open_average"],
                old_total_ticks=start_total, yesterday_total_ticks=yesterday_total, today_total_ticks=today_total,
                today_price_windows=today_windows, structure_clock=frozen["prior_structure_candidate_bar_end"],
                original_short_band_first_touch=frozen["first_band_contact"],
                original_short_band_strict_close=frozen["first_strict_close_below_upper"],
                author_retained=None, author_later_short=None, author_m_quantity=None)


def october(frozen, sequences):
    close_bounds = frozen["replacement"]["WRo00BFM1E"]["m_near_5m_to_5m_same_run"]
    projections = {name: [dict(operation=step["operation"], status=step["status"],
                               after=step["after"]) for step in record["steps"]]
                   for name, record in sequences.items()}
    return dict(retention_by_quote=close_bounds, next_night_original_short_retention=frozen[
                    "prior_short_quantity_that_can_be_today"],
                late_short_new_entry_paths=frozen["fresh_short"], projections=projections,
                early_panel_scope=None, author_retained=None, author_actions=None)


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
        dec = verified_json(DECEMBER, DECEMBER_SHA)
        daily = verified_json(SETTLEMENT, SETTLEMENT_SHA)
        oct_ = verified_json(OCTOBER, OCTOBER_SHA)
        sequences = {name: verified_json(P2 / f"{name}.json", digest) for name, digest in P2_SHA.items()}
        read_sources()
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            minutes = read_session_series(session, market, "jm", "JM2601", "1m", ONE, DAYS)
        report = dict(version="lms405-jm-m-retention-replay-v1", conditional=True, executable=False,
                      jm2601=december(minutes, dec, daily), jm2701=october(oct_, sequences),
                      references=dict(december=DECEMBER_SHA, settlement=SETTLEMENT_SHA,
                                      october=OCTOBER_SHA, october_sequences=P2_SHA),
                      author_action_samples=0, author_match_rate=None, fills=None, pnl=None)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "JM_RETENTION_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
