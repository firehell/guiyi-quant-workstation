"""Constrain SH2701 protection-leg replacement between two displayed averages."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_replay import display
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import CLOSE, CONTRACT, LUNCH, NIGHT, completed, digest
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

LIFECYCLE = Path("output/lms405-sh-lock-lifecycle-20261125/report.json")
LIFECYCLE_SHA = "4bd0e828b6e654decbe6e2e8a5e3c547835c607f658b904b727aad3699368986"
SPECS_SHA = "fc430ad455e81d41cdd479f470e26a7a543cac0f427729de150185dfb3e40652"
NIGHT_IMAGE_SHA = "67854d29d606b65cd88efe9af1fa939e86e20b713325732929b8a5a5aa6f9b0a"
NIGHT_TODAY_REREAD = 20


def compatible_counts(lots, old_total, new_total, old_ticks, afternoon_ticks, night_ticks):
    """Enumerate origin counts for the ending long using generous price-envelope intervals."""
    old_low, old_high = old_ticks
    day_low, day_high = afternoon_ticks or (0, 0)
    night_low, night_high = night_ticks or (0, 0)
    allowed = []
    for retained in range(lots + 1):
        replaced = lots - retained
        kept_low = max(retained * old_low, old_total.start - replaced * old_high)
        kept_high = min(retained * old_high, old_total.stop - 1 - replaced * old_low)
        if kept_low > kept_high:
            continue
        for day_lots in range(replaced + 1):
            night_lots = replaced - day_lots
            if (day_lots and afternoon_ticks is None) or (night_lots and night_ticks is None):
                continue
            ending_low = kept_low + day_lots * day_low + night_lots * night_low
            ending_high = kept_high + day_lots * day_high + night_lots * night_high
            if max(ending_low, new_total.start) <= min(ending_high, new_total.stop - 1):
                allowed.append([retained, day_lots, night_lots])
    return allowed


def extract_snapshots(reference):
    snapshots = reference["snapshots"]
    for source in (LUNCH, CLOSE, NIGHT):
        attachment = snapshots[source]["image"]
        if sha((ARCHIVE.parent / attachment["path"]).read_bytes()) != attachment["sha256"]:
            raise ValueError("SH_REPLACEMENT_SNAPSHOT_CHANGED")
    noon, closing, night = (snapshots[source]["legs"] for source in (LUNCH, CLOSE, NIGHT))
    if (not noon["short"] == closing["short"] == night["short"] or "long" in closing
            or noon["long"]["today_quantity"] != noon["long"]["quantity"]
            or night["long"]["today_quantity"] is not None
            or snapshots[NIGHT]["image"]["sha256"] != NIGHT_IMAGE_SHA
            or NIGHT_TODAY_REREAD != night["long"]["quantity"]
            or noon["long"]["quantity"] != night["long"]["quantity"]
            or Decimal(night["long"]["opening_average"]) != Decimal(reference["night_long_display_average"])):
        raise ValueError("SH_REPLACEMENT_LEG_FIELDS_CHANGED")
    return noon["long"], night["long"]


def study(session, market, reference, spec):
    old_leg, evening_leg = extract_snapshots(reference)
    old_series, new_series = (read_window(session, market, CONTRACT, date(2026, 10, day)) for day in (27, 28))
    for period in (1, 5):
        if reference["market"][f"{period}m"] != dict(afternoon=digest(old_series[period]), night=digest(new_series[period])):
            raise ValueError("SH_REPLACEMENT_FROZEN_MARKET_CHANGED")
    snapshots = reference["snapshots"]
    lunch, close = (datetime.fromisoformat(snapshots[source]["quote_anchor"]) for source in (LUNCH, CLOSE))
    night_open, night_cut = (datetime.fromisoformat(reference[key]) for key in ("night_start", "night_cut"))
    if old_series[1][-1].end != close or new_series[1][0].start != night_open or not lunch < close < night_open:
        raise ValueError("SH_REPLACEMENT_TRADING_DAY_BOUNDARY_CHANGED")
    tick, lots = spec["tick"], evening_leg["quantity"]
    old_totals = displayed_tick_totals(Decimal(old_leg["opening_average"]), lots, tick)
    new_totals = displayed_tick_totals(Decimal(reference["night_long_display_average"]), lots, tick)
    if reference["display_tick_totals"] != dict(noon_long=list(old_totals), night_long=list(new_totals)):
        raise ValueError("SH_REPLACEMENT_AVERAGE_CHANGED")
    old_bars = completed(old_series[1], old_series[1][0].start, lunch + 2 * US)
    night_bars = completed(new_series[1], night_open, night_cut)
    old_ticks, night_ticks = tick_bounds(old_bars, tick), tick_bounds(night_bars, tick)
    if old_ticks is None or night_ticks is None or not old_totals or not new_totals:
        raise ValueError("SH_REPLACEMENT_REQUIRED_WINDOW_MISSING")
    afternoon = {
        "after_lunch": completed(old_series[1], lunch, close + 2 * US),
        "after_1408_candidate": completed(old_series[1], at("2026-10-27T14:08") + US, close + 2 * US),
        "after_1434_candidate": completed(old_series[1], at("2026-10-27T14:34") + US, close + 2 * US),
        "only_night_additions": [],
    }
    for clock in ("14:08", "14:34"):
        afternoon[f"from_{clock.replace(':', '')}_overlap_allowed"] = completed(
            old_series[1], at(f"2026-10-27T{clock}"), close + 2 * US,
        )
    results = {}
    for label, bars in afternoon.items():
        day_ticks = tick_bounds(bars, tick)
        combinations = compatible_counts(lots, old_totals, new_totals, old_ticks, day_ticks, night_ticks)
        if not combinations:
            raise ValueError("SH_REPLACEMENT_NO_COMPATIBLE_ENVELOPE")
        old_retained, day_added, night_added = zip(*combinations, strict=True)
        results[label] = dict(
            afternoon_tick_envelope=day_ticks, afternoon_minutes=len(bars),
            origin_counts=combinations, old_retained=[min(old_retained), max(old_retained)],
            afternoon_new=[min(day_added), max(day_added)], night_new=[min(night_added), max(night_added)],
            minimum_removed=lots - max(old_retained),
        )
    night_only = results["only_night_additions"]["origin_counts"]
    with_today_field = [row for row in night_only if row[2] == NIGHT_TODAY_REREAD]
    if with_today_field != [[0, 0, lots]]:
        raise ValueError("SH_REPLACEMENT_TODAY_FIELD_PRICE_CONFLICT")
    first_whole_prefix = next(
        bar.end for index, bar in enumerate(night_bars, start=1)
        if earlier_lot_counts(None, tick_bounds(night_bars[:index], tick), lots, new_totals)
    )
    today_field = dict(
        source_id=NIGHT, image_sha256=NIGHT_IMAGE_SHA, reading="TWO_INDEPENDENT_NATIVE_PIXEL_READS",
        previous_transcription=None, today_quantity=NIGHT_TODAY_REREAD, today_available=NIGHT_TODAY_REREAD,
        conditions=["SAME_ACCOUNT", "POSITION_TODAY_FIELD_USES_TRADING_DAY", "NEW_SNAPSHOT_IN_NEXT_TRADING_DAY"],
        position_origin_counts=with_today_field, prior_displayed_long_lots_retained=0,
        latest_possible_whole_long_minute_start=reference["latest_possible_whole_long_minute_start"],
        first_completed_prefix_with_whole_long_price_compatibility=display(first_whole_prefix),
    )
    return dict(version="lms405-sh-protection-replacement-v1", contract=CONTRACT, specification=spec,
                lifecycle_sha256=LIFECYCLE_SHA, snapshots=snapshots, old_ticks=old_ticks, night_ticks=night_ticks,
                old_minute_count=len(old_bars), night_minute_count=len(night_bars),
                without_night_today_quantity=results, with_night_today_quantity=today_field,
                volume_and_price_evaluation="CONDITIONAL_TICK_ENVELOPES_ONLY", account_continuity=None,
                actual_legs_closed=None, close_snapshot_unshown_long=None, author_action_at=None,
                author_actions_scored=0, executable=False, fills=None, pnl=None)


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
        reference = verified_json(LIFECYCLE, LIFECYCLE_SHA)
        spec = load_specs(verified_json(SPECS, SPECS_SHA))[CONTRACT]
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), reference, spec)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('SH_REPLACEMENT_') and code.isidentifier() else 'SH_REPLACEMENT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
