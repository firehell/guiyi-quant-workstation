"""Compare fresh protection shapes, session gaps, and visible-leg price constraints."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_leg_handoff import CLOSE, GLASS, GLASS_BANDS, MORNING, OLD_PLAN, SODA, SPECS_SHA
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import CLOSE as CAUSTIC_CLOSE
from lms405_sh_lock_lifecycle import CONTRACT as CAUSTIC
from lms405_sh_lock_lifecycle import LUNCH as CAUSTIC_LUNCH
from lms405_sh_lock_lifecycle import NIGHT, PLAN as CAUSTIC_PLAN, completed, digest
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA, extract_snapshots
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

PAIR = Path("output/lms405-fg-sa-leg-handoff-20261125/final.json")
PAIR_SHA = "4e947ef9365180cb4330016fc18cff6737478c44f0473601f641425e8001d5da"


def annotated_geometry(series, start, cut, *, side="LONG"):
    rows = {}
    for shape, confirm in VARIANTS:
        parents = {cur.end: prev for prev, cur in zip(series[shape], series[shape][1:])}
        frames = {bar.end: bar for bar in series[shape]}
        events = geometry_events(series, shape, confirm, side=side, start=start, as_of=cut)
        for event in events:
            frame_end = event["shape_end"]
            mother = parents.get(frame_end)
            frame = frames[frame_end]
            event.update(
                shape_start=frame.start, shape_low=frame.low, mother_end=mother.end if mother else None,
                mother_contiguous=mother is not None and mother.end == frame.start,
            )
            # A pinbar can stand alone. The mother-bar dependency is specific to the ibar path.
            event["survives_resetting_ibar_at_session_gap"] = (
                event["pinbar"] == side or (event["ibar"] and event["mother_contiguous"])
            )
        rows[f"{shape}m_to_{confirm}m"] = events
    return rows


def leg_envelope(bars, gate_end, quote_cut, leg, tick, *, include_upper_tie=False):
    lots = leg["quantity"]
    totals = displayed_tick_totals(Decimal(leg["opening_average"]), lots, tick, include_upper_tie=include_upper_tie)
    rows = [bar for bar in bars if bar.end + US < quote_cut]
    result = {}
    # Completed evidence is known just after the gate. One minute can overlap that timestamp.
    for name, later in (
        ("overlap_allowed", [bar for bar in rows if bar.end > gate_end + US]),
        ("strictly_whole_after_known", [bar for bar in rows if bar.start > gate_end + US]),
    ):
        later_bounds = tick_bounds(later, tick)
        whole = bool(earlier_lot_counts(None, later_bounds, lots, totals))
        earlier = tick_bounds([bar for bar in rows if bar not in later], tick)
        earlier_counts = earlier_lot_counts(earlier, later_bounds, lots, totals)
        result[name] = dict(later_tick_bounds=later_bounds, whole_leg_price_compatible=whole,
                            minimum_outside_later_window=min(earlier_counts, default=None))
    return result


def inspect(series, *, start, cut, quote_cut, band, leg, tick):
    whole = annotated_geometry(series, start, cut)
    active = completed(series[1], start, cut)
    low, high = band
    first_touch = next((bar for bar in active if bar.low <= high and bar.high >= low), None)
    checks = {cut}
    if first_touch:
        checks.add(first_touch.end + US)
    checks.update(row["available_at"] for events in whole.values() for row in events)
    checks |= {instant + US for instant in checks if instant < cut}
    for checkpoint in sorted(checks):
        prefix = {p: [bar for bar in bars if bar.end + US < checkpoint] for p, bars in series.items()}
        expected = {variant: [row for row in events if row["available_at"] < checkpoint]
                    for variant, events in whole.items()}
        if annotated_geometry(prefix, start, checkpoint) != expected:
            raise ValueError("FRESH_REPROTECTION_PREFIX_DIVERGED")
    prices = completed(series[1], start, quote_cut)
    for events in whole.values():
        for row in events:
            inside = low <= row["close"] <= high
            row["signal_close_in_band"] = inside
            row["wholly_before_first_touch_bar"] = bool(first_touch and row["available_at"] < first_touch.start)
            if row["wholly_before_first_touch_bar"]:
                observed = [bar for bar in active if bar.start > row["available_at"] and bar.end < first_touch.end]
                row["whole_minutes_after_confirmation_before_touch"] = len(observed)
                hold_level = row["shape_low"]
                row["shape_low_retest_before_touch"] = dict(
                    first_low_below=next((bar.end for bar in observed if bar.low < hold_level), None),
                    first_close_below=next((bar.end for bar in observed if bar.close < hold_level), None),
                )
            if leg is not None:
                row["prices_after_confirmation"] = leg_envelope(prices, row["confirmed_at"], quote_cut, leg, tick)
                if row["wholly_before_first_touch_bar"]:
                    row["prices_after_confirmation_before_touch"] = leg_envelope(
                        prices, row["confirmed_at"], first_touch.end, leg, tick,
                    )
    touch_prices = leg_envelope(prices, first_touch.end, quote_cut, leg, tick) if first_touch and leg else None
    return dict(start=start, candidate_cut_exclusive=cut, price_cut_exclusive=quote_cut, band=band,
                initially_above_band=active[0].open > high, comparison_minutes=len(active),
                first_touch_bar_end=first_touch.end if first_touch else None,
                first_touch_bar_start=first_touch.start if first_touch else None,
                prices_after_first_touch=touch_prices, shape_candidates=whole, prefix_checks=len(checks))


def study(session, market):
    pair = verified_json(PAIR, PAIR_SHA)
    sh = verified_json(LIFECYCLE, LIFECYCLE_SHA)
    _, sh_leg = extract_snapshots(sh)
    sh_leg = sh_leg | dict(opening_average=sh["night_long_display_average"])
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    plans = {OLD_PLAN: pair["sources"][OLD_PLAN], CAUSTIC_PLAN: sh["sources"][CAUSTIC_PLAN]}
    for source in plans.values():
        if sha((ARCHIVE.parent / source["archive_path"]).read_bytes()) != source["archive_sha256"]:
            raise ValueError("FRESH_REPROTECTION_PLAN_CHANGED")
    for rows in pair["positions"].values():
        for record in rows.values():
            image = record["image"]
            if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
                raise ValueError("FRESH_REPROTECTION_PHOTO_CHANGED")
    day = date(2026, 10, 23)
    close = datetime.fromisoformat(pair["quote_anchors"][GLASS][CLOSE][0])
    morning_post = datetime.fromisoformat(pair["positions"][GLASS][MORNING]["published_at"])
    if pair["quote_anchors"][GLASS][MORNING] != pair["quote_anchors"][SODA][MORNING]:
        raise ValueError("FRESH_REPROTECTION_MORNING_QUOTE_ANCHORS_CHANGED")
    glass_leg = pair["positions"][GLASS][CLOSE]["legs"]["long"]
    cases, market_hashes = {}, {}
    for contract, band, leg in ((GLASS, GLASS_BANDS["protection"], glass_leg), (SODA, (Decimal(931), Decimal(936)), None)):
        series = read_window(session, market, contract, day)
        hashes = {f"{p}m": digest(bars) for p, bars in series.items()}
        if hashes != pair["markets"][contract][str(day)]:
            raise ValueError("FRESH_REPROTECTION_PAIR_MARKET_CHANGED")
        market_hashes[contract] = hashes
        windows = {anchor: datetime.fromisoformat(anchor) + US for anchor in pair["quote_anchors"][contract][MORNING]}
        windows["after_full_morning_post_minute"] = morning_post + ONE
        cases[contract] = dict(
            plan_source=OLD_PLAN, before_source=MORNING, quote_source=CLOSE if leg else None,
            visible_long=leg, authorship="MORNING_ABSENT_LONG_QUANTITY_UNKNOWN",
            assumed_full_rebuild_scope=bool(leg),
            windows={name: inspect(series, start=start, cut=close, quote_cut=close + 2 * US,
                                   band=band, leg=leg, tick=specs[contract]["tick"])
                     for name, start in windows.items()},
        )
    series = read_window(session, market, CAUSTIC, date(2026, 10, 28))
    hashes = {f"{p}m": digest(bars) for p, bars in series.items()}
    if any(hashes[period] != sh["market"][period]["night"] for period in ("1m", "5m")):
        raise ValueError("FRESH_REPROTECTION_SH_MARKET_CHANGED")
    start, cut = (datetime.fromisoformat(sh[key]) for key in ("night_start", "night_cut"))
    market_hashes[CAUSTIC] = hashes
    cases[CAUSTIC] = dict(
        plan_source=CAUSTIC_PLAN, before_source=CAUSTIC_CLOSE, earlier_locked_source=CAUSTIC_LUNCH,
        quote_source=NIGHT, visible_long=sh_leg,
        authorship="AFTERNOON_UNSHOWN_LONG_QUANTITY_UNKNOWN", assumed_full_rebuild_scope=True,
        windows=dict(night=inspect(series, start=start, cut=cut, quote_cut=cut, band=tuple(map(Decimal, sh["night_band"])),
                                   leg=sh_leg, tick=specs[CAUSTIC]["tick"])),
    )
    for contract, case in cases.items():
        leg = case["visible_long"]
        case["visible_long_tick_sum_candidates"] = list(displayed_tick_totals(
            Decimal(leg["opening_average"]), leg["quantity"], specs[contract]["tick"],
        )) if leg else None
    return dict(version="lms405-fresh-reprotection-study-v1", scope="RETROSPECTIVE_NO_REAL_ACTION_INFERENCE",
                cases=cases, market=market_hashes, inputs=dict(pair=PAIR_SHA, caustic=LIFECYCLE_SHA, specs=SPECS_SHA),
                plan_archive_hashes={key: source["archive_sha256"] for key, source in plans.items()},
                prefix_scope="GEOMETRY_AND_MOTHER_IDENTITY_ONLY",
                subsequent_touch_and_price_envelopes_are_retrospective=True,
                actual_reprotection_at=None, author_action_samples=0, author_match_rate=None,
                historical_source_revision_verified=False, executable=False, fills=None, pnl=None)


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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError):
        parser.exit(2, "FRESH_REPROTECTION_EVIDENCE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
