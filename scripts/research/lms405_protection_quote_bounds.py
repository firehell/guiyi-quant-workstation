"""Use earlier per-row quotes to constrain glass and caustic-soda protection legs."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_leg_handoff import CLOSE, FIRST, GLASS, MORNING, photo_times
from lms405_jm_m_leg_handoff import BOUNDARIES, LATER, LATER_IMAGE, formation
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_reversal_stage_bounds import PHOTO, PHOTO_SHA, SPECS_SHA
from lms405_right_side_study import US
from lms405_rubber_m_replacements import compare_gate
from lms405_sh_lock_lifecycle import completed, digest
from lms405_sh_protection_replacement import CONTRACT as CAUSTIC
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA, NIGHT
from lms405_sizing_audit import SPECS, load_specs
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

GLASS_REFERENCE = Path("output/lms405-fg-sa-leg-handoff-20261125/final.json")
GLASS_SHA = "4e947ef9365180cb4330016fc18cff6737478c44f0473601f641425e8001d5da"
CAUSTIC_REFERENCE = Path("output/lms405-protection-next-night-20261125/verified.json")
CAUSTIC_SHA = "c4168e321b5a8987304b7a40198d2a2398ed4c6c59a09320615951813521c2ba"
CAUSTIC_MARK = Decimal(1491)  # Both sides imply this price from their displayed profit differences.


def check_image(image):
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("PROTECTION_QUOTE_IMAGE_CHANGED")


def glass_study(session, market, tick):
    source = input_sources()[LATER]
    image = dict(path=(Path(source["archive_path"]).parent / "RnZKEysLc-table2-screen.png").as_posix(),
                 sha256=LATER_IMAGE)
    check_image(image)
    frozen = verified_json(GLASS_REFERENCE, GLASS_SHA)
    for row in frozen["positions"][GLASS].values():
        check_image(row["image"])
    photos = verified_json(PHOTO, PHOTO_SHA)
    day = date(2026, 10, 23)
    series = read_window(session, market, GLASS, day)
    if {f"{p}m": digest(bars) for p, bars in series.items()} != frozen["markets"][GLASS][day.isoformat()]:
        raise ValueError("PROTECTION_QUOTE_GLASS_MARKET_CHANGED")
    minutes, cut = series[1], stamp(source)
    later = photo_times(photos["photos"], LATER, "fg", minutes, cut)
    first, morning = ([datetime.fromisoformat(t) for t in frozen["quote_anchors"][GLASS][photo]]
                      for photo in (FIRST, MORNING))
    old_leg = frozen["positions"][GLASS][FIRST]["legs"]["long"]
    close_leg = frozen["positions"][GLASS][CLOSE]["legs"]["long"]
    lots = old_leg["quantity"]
    if lots != close_leg["quantity"] or Decimal(close_leg["opening_average"]) != Decimal("828.8"):
        raise ValueError("PROTECTION_QUOTE_GLASS_FIELDS_CHANGED")
    old_total = displayed_tick_totals(Decimal(old_leg["opening_average"]), lots, tick)
    new_total = displayed_tick_totals(Decimal("828.8"), lots, tick)
    gates = {}
    for gate in ("protection_near_touch", "protection_near_strict_close", "protection_far_touch",
                 "protection_far_strict_close"):
        clock = datetime.fromisoformat(frozen["glass_long"]["protection_gates"][gate]["end"])
        checks = {}
        for scope in BOUNDARIES:
            carried = compare_gate(minutes, [(before, after) for before in first for after in later], clock,
                                   boundary=scope, tick=tick, lots=lots, old_totals=old_total, new_totals=new_total)
            rebuild = {m.isoformat(): formation([b for b in minutes if b.end >= m], later, clock, boundary=scope,
                                               tick=tick, lots=lots, totals=new_total) for m in morning}
            checks[scope] = dict(allow_old_lots=carried, assuming_zero_at_morning=rebuild)
        gates[gate] = dict(at=clock, checks=checks)
    return dict(contract=GLASS, source=source["source_url"], image=image, published_at=cut, possible_row_times=later,
                no_joint_quote_times=not photos["photos"][LATER]["joint_contains"],
                old_lots=lots, old_display=old_leg["opening_average"], new_lots=lots, new_display="828.8",
                morning_long_quantity=None, same_account=None, gates=gates,
                contradictory_old_short_rows=frozen["continuity_on_assumed_same_account"]["glass_night_to_morning"])


def gate_price_support(prefix, gate, *, tick, lots, totals):
    result = {}
    for scope, later in (
        ("including_minute_overlapping_permission", [b for b in prefix if b.end > gate]),
        ("only_complete_minutes_after_permission", [b for b in prefix if b.start > gate]),
    ):
        later_ends = {b.end for b in later}
        earlier = [b for b in prefix if b.end not in later_ends]
        counts = earlier_lot_counts(tick_bounds(earlier, tick), tick_bounds(later, tick), lots, totals)
        result[scope] = dict(whole_leg_possible=0 in counts, minimum_earlier_or_overlapping_lots=min(counts))
    return result


def caustic_study(session, market, tick):
    frozen = verified_json(CAUSTIC_REFERENCE, CAUSTIC_SHA)
    case = frozen["cases"][CAUSTIC]
    image = frozen["sources"][NIGHT]["image"]
    check_image(image)
    lifecycle = verified_json(LIFECYCLE, LIFECYCLE_SHA)
    start, cut = [datetime.fromisoformat(lifecycle[k]) for k in ("night_start", "night_cut")]
    series = read_window(session, market, CAUSTIC, date.fromisoformat(frozen["trading_day"]))
    if any(digest(series[p]) != lifecycle["market"][f"{p}m"]["night"] for p in (1, 5)):
        raise ValueError("PROTECTION_QUOTE_CAUSTIC_MARKET_CHANGED")
    minutes = completed(series[1], start, cut)
    anchor_rows = [b for b in minutes if b.low <= CAUSTIC_MARK <= b.high]
    shown = case["whole_leg_price_reference"]
    lots = shown["quantity"]
    totals = displayed_tick_totals(Decimal(shown["display_average"]), lots, tick)
    if (image != shown["image"] or case["displayed_night"]["long"]["today_quantity"] != lots
            or [totals.start, totals.stop - 1] != shown["displayed_tick_total_interval"]):
        raise ValueError("PROTECTION_QUOTE_CAUSTIC_FIELDS_CHANGED")
    immed, wait = (datetime.fromisoformat(row["first_projection_at"])
                   for row in (case["fixture"], case["fixture"]["deferred_until_touch"]))
    candidates = []
    for bar in anchor_rows:
        prefix = completed(minutes, start, bar.end + 2 * US)
        possible = bool(earlier_lot_counts(None, tick_bounds(prefix, tick), lots, totals))
        candidates.append(dict(quote_minute_end=bar.end, quote_equals_close=bar.close == CAUSTIC_MARK,
                               whole_leg_possible_inside_prefix=possible,
                               after_immediate=gate_price_support(prefix, immed, tick=tick, lots=lots, totals=totals)
                               if possible else None,
                               after_wait_for_touch=gate_price_support(prefix, wait, tick=tick, lots=lots, totals=totals)
                               if possible else None))
    return dict(contract=CAUSTIC, snapshot=shown, quote_mark=CAUSTIC_MARK, quote_candidates=candidates,
                immediate_fixture_at=immed, wait_for_touch_fixture_at=wait,
                quote_sync_and_capture_at=None, same_account=None)


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
        specs = load_specs(verified_json(SPECS, SPECS_SHA))
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            market = build_market_data_service(session)
            glass = glass_study(session, market, specs[GLASS]["tick"])
            caustic = caustic_study(session, market, specs[CAUSTIC]["tick"])
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(dict(version="lms405-protection-quote-bounds-v1", glass=glass, caustic=caustic,
                                      admitted_author_actions=0, author_match_rate=None, fills=None,
                                      executable=False)))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        if not code.isidentifier() or not code.startswith(("PROTECTION_QUOTE_", "FG_SA_", "JM_M_", "RU_M_")):
            code = "PROTECTION_QUOTE_INPUT_UNVERIFIED"
        parser.exit(2, f"{code}\n")


if __name__ == "__main__":
    main()
