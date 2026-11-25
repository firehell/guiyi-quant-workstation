"""Test original-long protection candidates across session and price-band boundaries."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE
from lms405_pre_touch_protection import analyze
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed
from lms405_versioned_lock_audit import JM, REFERENCE, REFERENCE_SHA, market_fingerprints
from lms_near405_replay import encoded, sha

CONTRACT = "JM2609"
DAY, NIGHT_DAY = date(2026, 6, 8), date(2026, 6, 9)
LOWER, UPPER = Decimal(1446), Decimal(1464)
DAY_OPEN, NIGHT_OPEN = at("2026-06-08T09:00"), at("2026-06-08T21:00")
NIGHT_CUT = at("2026-06-09T09:00")


def feature(end, shape_start, segment_start, minutes):
    contacts = [b for b in minutes if b.end < end and b.low <= UPPER and LOWER <= b.high]
    same = [b for b in contacts if b.start >= segment_start]
    contact = same[-1] if same else None
    prior = next((b for b in reversed(contacts) if b.end <= segment_start), None)
    return dict(
        last_local_contact=contact.end if contact else None,
        local_contact_before_shape=any(b.end + US < shape_start for b in same),
        last_prior_segment_contact=prior.end if prior else None,
        gap_since_prior_segment_contact=end - prior.end if prior else None,
    )


def audits(series, start, cut, earlier_minutes):
    raw = analyze(series, start=start, cut=cut, band=(LOWER, UPPER), side="SHORT", leg=None)
    minutes = completed(series[1], start, cut)
    histories = [*earlier_minutes, *minutes]
    rows = {}
    for key, events in raw["variants"].items():
        shape_step = timedelta(minutes=int(key.split("m", 1)[0]))
        rows[key] = [e | feature(e["confirmed_at"], e["shape_end"] - shape_step,
                                  e["segment_start"], histories) for e in events]
    return raw, rows


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_SHA)
    source = reference["sources"][JM]
    path = ARCHIVE.parent / source["archive_path"]
    if sha(path.read_bytes()) != source["sha256"]:
        raise ValueError("LONG_PROTECTION_SOURCE_CHANGED")
    day, night = [read_window(session, market, CONTRACT, day) for day in (DAY, NIGHT_DAY)]
    market_inputs = {key: market_fingerprints(series)
                     for key, series in (("JM2609_0608", day), ("JM2609_0609", night))}
    if any(identity != reference["market"][key] for key, identity in market_inputs.items()):
        raise ValueError("LONG_PROTECTION_MARKET_CHANGED")
    day_cut = day[1][-1].end + 2 * US
    if not day_cut < NIGHT_OPEN < NIGHT_CUT < datetime.fromisoformat(source["published_at"]):
        raise ValueError("LONG_PROTECTION_CUTOFF_CHANGED")
    day_minutes = completed(day[1], DAY_OPEN, day_cut)
    night_minutes = completed(night[1], NIGHT_OPEN, NIGHT_CUT)
    day_low = min(b.low for b in day_minutes)
    first_new_low = next(b for b in night_minutes if b.low < day_low)
    first_new_low_close = next(b for b in night_minutes if b.close < day_low)
    day_raw, day_rows = audits(day, DAY_OPEN, day_cut, [])
    night_raw, night_rows = audits(night, NIGHT_OPEN, NIGHT_CUT, day_minutes)
    checks = 0
    for series, start, rows, history in ((day, DAY_OPEN, day_rows, []), (night, NIGHT_OPEN, night_rows, day_minutes)):
        boundaries = {e["available_at"] for entries in rows.values() for e in entries}
        for split in sorted(boundaries | {end + US for end in boundaries}):
            prefix = {p: completed(bars, start, split) for p, bars in series.items()}
            _, checked = audits(prefix, start, split, history)
            # Later-visibility annotations are excluded. The setup, relation and previous contacts are causal.
            keys = ("shape_end", "confirmed_at", "relation", "last_local_contact", "local_contact_before_shape",
                    "last_prior_segment_contact", "pre_touch_arm")
            def project(items):
                return [tuple(e[k] for k in keys) for e in items if e["available_at"] < split]

            if any(project(checked[clock]) != project(events) for clock, events in rows.items()):
                raise ValueError("LONG_PROTECTION_PREFIX_CHANGED")
            checks += 1

    clocks = {}
    for clock, events in night_rows.items():
        first = events[0] if events else None
        clocks[clock] = dict(first_geometry=first,
                             same_segment_contact_route=next((e for e in events if e["in_band"]
                                                              and e["local_contact_before_shape"]), None),
                             prior_contact_and_geometry=next((e for e in events if e["last_prior_segment_contact"]), None),
                             first_strictly_before_night_low_probe=first if first and
                             first["available_at"] < first_new_low.start else None)
    return dict(
        version="lms405-long-protection-session-audit-v1", contract=CONTRACT, source=source, market=market_inputs,
        retrospective_band=[LOWER, UPPER], verified_pretrade_plan=None, author_vplus_at=None,
        original_position_quantity=None, author_action_at=None, author_match_rate=None, fills=None, executable=False,
        day_candidates=day_rows, night_candidates=night_rows, night_clock_comparison=clocks,
        day_band_contact_ends=day_raw["contact_bar_ends"], night_band_contact_ends=night_raw["contact_bar_ends"],
        daytime_low=day_low, daytime_close=day_minutes[-1].close, night_open=night_minutes[0].open,
        night_first_close=night_minutes[0].close, night_high=max(b.high for b in night_minutes),
        night_first_lower_low=dict(end=first_new_low.end, low=first_new_low.low),
        night_first_close_below_day_low=dict(end=first_new_low_close.end, close=first_new_low_close.close),
        verified_comparison_input=REFERENCE_SHA, strict_prefix_checks=checks,
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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError, StopIteration):
        parser.exit(2, "LONG_PROTECTION_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
