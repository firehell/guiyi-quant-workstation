"""Bound first-night protection-leg timing against declared PA events and opening prices."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_snapshot_window import price_window
from lms405_protection_timeframes import read_window
from lms405_replay import ohlc, read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import digest
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

REFERENCES = {
    "previous_study": (Path("output/lms405-pre-touch-protection-20261125/final.json"),
                       "d5053217c8be047d853955709fdca77b8b268656f5cb2af0b078574399e94a60"),
    "exposure": (EXPOSURE, EXPOSURE_SHA256),
}
START, CUT = at("2026-10-22T21:00"), at("2026-10-22T22:10")
DAY = date(2026, 10, 23)
DAY_CLOSE = at("2026-10-22T15:00")
CASES = {
    "SA2701": ("sa_first_night", ("926", "931"), ("942", "945"), ("953", "957")),
    "SH2701": ("sh", ("1596", "1610"), ("1660", "1668"), ("1707", "1711")),
}
POSTS = ("WRnThF3x5C", "WRnTl1Ej2P", "WRnTlEfj1t", "WRnTmqo3x5", "WRo1A1rN9b")
LEGACY_POST = "Q8XhoDvO8"


def split_lots(earlier, later, tick, lots, totals):
    counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
    return dict(earlier_whole_leg_possible=lots in counts, later_whole_leg_possible=0 in counts,
                earlier_count_interval=[min(counts), max(counts)] if counts else None,
                minimum_later_lots=lots - max(counts) if counts else None)


def compare_gate(minutes, gate, tick, lots, totals):
    if gate is None:
        return None
    known = gate.bar_end + US
    earlier = [b for b in minutes if b.bar_end <= gate.bar_end]
    later = [b for b in minutes if b.bar_end > known]
    strict = [b for b in later if known < b.bar_end - ONE]
    straddling = [b for b in later if b.bar_end - ONE <= known]
    # The straddling minute can contain prints on both sides of availability.
    # Giving it entirely to later bounds the minimum earlier lots; giving it
    # entirely to earlier bounds their maximum.
    give_later = split_lots(earlier, later, tick, lots, totals)
    give_earlier = split_lots(earlier + straddling, strict, tick, lots, totals)
    lower, upper = give_later["earlier_count_interval"], give_earlier["earlier_count_interval"]
    if lower is None or upper is None:
        raise ValueError("FIRST_NIGHT_GATE_PRICE_PARTITION_INCOMPATIBLE")
    earlier_interval = [lower[0], upper[1]]
    return dict(bar_end=gate.bar_end, known_at=known, ohlc=list(ohlc(gate)),
                straddling_minute_allocated_later=give_later, straddling_minute_allocated_earlier=give_earlier,
                earlier_lots_conservative_interval=earlier_interval,
                wholly_after_gate=price_window(strict, tick, lots, totals) if strict else None)


def first_events(minutes, resistance, protection, m, extreme):
    lower, upper = protection
    return_from_above = next((b for a, b in zip(minutes, minutes[1:])
                              if a.close > upper and lower <= b.close <= upper), None)
    return dict(
        resistance_high_strictly_above=next((b for b in minutes if b.high > resistance[1]), None),
        protection_first_overlap=next((b for b in minutes if b.low <= upper and b.high >= lower), None),
        protection_high_strictly_above_far=next((b for b in minutes if b.high > upper), None),
        protection_close_strictly_above_far=next((b for b in minutes if b.close > upper), None),
        protection_return_from_above=return_from_above,
        m_near_reached=next((b for b in minutes if b.high >= m[0]), None),
        extreme_m_near_reached=next((b for b in minutes if b.high >= extreme[0]), None),
    )


def check_legacy_soda(session, market):
    from app.market_data.market_data_service import MarketDataError

    day = date(2025, 10, 13)
    try:
        raw = read_session_series(session, market, "sa", "SA2601", "1m", ONE, (day,))
    except MarketDataError as exc:
        if exc.code != "DATASET_OR_PARTITION_MISSING":
            raise
        return dict(contract="SA2601", trading_day=day, status=exc.code)
    day_open = at("2025-10-13T09:00")
    lower, upper = Decimal(1219), Decimal(1223)

    def scope(rows):
        minimum = min(b.low for b in rows)
        return dict(minimum=minimum, maximum=max(b.high for b in rows), minute_count=len(rows),
                    first_minimum_bar_end=next(b.bar_end for b in rows if b.low == minimum),
                    target_range_touched=any(b.low <= upper and b.high >= lower for b in rows),
                    matches_reported_minimum=minimum == Decimal(1224))

    return dict(contract="SA2601", trading_day=day, reported_minimum=Decimal(1224), target_band=[lower, upper],
                full_trading_day=scope(raw), day_session=scope([b for b in raw if b.bar_end > day_open]),
                source_id=LEGACY_POST, usage="POST_SESSION_AUTHOR_REPORT_ONLY", author_action_at=None,
                minute_sha256=sha(encoded([[b.bar_end.isoformat(), *map(str, ohlc(b))] for b in raw]).encode()))


def study(session, market, refs):
    index = input_sources()
    (table,) = [row for row in refs["exposure"]["tables"] if row["source"] == "WRnTlEfj1t"]
    image = table["image"]
    if (sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
            or table["system"] != "4.0.5" or datetime.fromisoformat(table["published_at"]) != CUT):
        raise ValueError("FIRST_NIGHT_PHOTO_CHANGED")
    results, ids = {}, {*POSTS, LEGACY_POST}
    for contract, (previous_case, resistance, m, extreme) in CASES.items():
        frozen = refs["previous_study"]["cases"][previous_case]
        plan = frozen["plan"]
        ids.add(plan["id"])
        if datetime.fromisoformat(plan["published_at"]) + ONE > START:
            raise ValueError("FIRST_NIGHT_PLAN_TOO_LATE")
        series = read_window(session, market, contract, DAY)
        fingerprints = {f"{p}m": digest(rows) for p, rows in series.items()}
        if fingerprints != frozen["market"] or any(frozen["variants"].values()):
            raise ValueError("FIRST_NIGHT_SHAPE_OR_MARKET_CHANGED")
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (DAY_CLOSE.date(), DAY))
        close = next(b for b in raw if b.bar_end == DAY_CLOSE)
        minutes = [b for b in raw if START <= b.bar_end - ONE and b.bar_end + US < CUT]
        by_end = {b.end: ohlc(b) for b in series[1]}
        if any(ohlc(bar) != by_end[bar.bar_end] for bar in minutes):
            raise ValueError("FIRST_NIGHT_MINUTE_SOURCE_DIVERGED")
        old_leg = table["contracts"][contract]["legs"]["short"]
        visible = frozen["visible_leg"]
        tick, lots, average = Decimal(visible["tick_size"]), visible["quantity"], Decimal(visible["display_average"])
        if lots != visible["shown_as_today_quantity"] or old_leg["today_quantity"] != 0:
            raise ValueError("FIRST_NIGHT_POSITION_FIELDS_CHANGED")
        totals = displayed_tick_totals(average, lots, tick)
        prices = [tuple(map(Decimal, pair)) for pair in (resistance, frozen["band"], m, extreme)]
        gates = first_events(minutes, *prices)
        first_possible = price_window(minutes, tick, lots, totals)
        if not first_possible["whole_leg_price_possible"]:
            raise ValueError("FIRST_NIGHT_PRICE_RANGE_INCOMPATIBLE")
        first_end = datetime.fromisoformat(first_possible["first_compatible_prefix_end"])
        first_compatible = next(b for b in minutes if b.bar_end == first_end)
        earlier = [b for b in minutes if b.bar_end < first_compatible.bar_end]
        later = [b for b in minutes if b.bar_end >= first_compatible.bar_end]
        first_block = [b for b in minutes if b.bar_end <= START + ONE]
        results[contract] = dict(
            plan=plan, market=fingerprints, old_short=old_leg, displayed_long=visible,
            minute_count=len(minutes), price_ranges=dict(resistance=prices[0], protection=prices[1], m=prices[2], extreme=prices[3]),
            open_price=minutes[0].open, previous_day_close=close.close,
            opening_gap_ticks=(minutes[0].open - close.close) / tick,
            first_minute_ohlc=list(ohlc(minutes[0])),
            first_completed_minute_only=split_lots(first_block, minutes[1:], tick, lots, totals),
            all_formation_window=first_possible,
            split_at_first_feasible_bar_close=compare_gate(minutes, first_compatible, tick, lots, totals),
            split_at_first_feasible_bar_start=dict(
                minute_start=first_compatible.bar_end - ONE,
                **split_lots(earlier, later, tick, lots, totals),
            ),
            by_pa_gate={name: compare_gate(minutes, gate, tick, lots, totals) for name, gate in gates.items()},
            original_author_vplus_at=None, author_execution_mode=None,
        )
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in sorted(ids)}
    return dict(version="lms405-first-night-protection-v1", cases=results, source_evidence=sources, photo=image,
                legacy_soda_recap=check_legacy_soda(session, market),
                start=START, cutoff_exclusive=CUT, account_continuity=None,
                assumed_window_scope="ALL_VISIBLE_TODAY_LONG_LOTS_IN_RETAINED_NIGHT_MINUTES",
                references={name: value for name, (_, value) in REFERENCES.items()},
                author_actions_scored=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
        refs = {name: verified_json(*reference) for name, reference in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), refs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('FIRST_NIGHT_') and code.isidentifier() else 'FIRST_NIGHT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
