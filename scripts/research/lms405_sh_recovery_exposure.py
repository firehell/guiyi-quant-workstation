"""Compare directional price exposure after frozen SH2701 recovery candidates."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_explicit_near_recovery import market_for
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import CLOSE, CONTRACT, LUNCH, completed, digest
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA, extract_snapshots
from lms405_sh_recovery_progress import SNAPSHOTS, SNAPSHOTS_SHA
from lms_near405_replay import encoded

RECOVERY = Path("output/lms405-sh-recovery-progress-20261126/verified.json")
RECOVERY_SHA = "09ed30afda94f92089d15f5e10f9e2aa125908bfca30fdb1aa962ae041966d66"


def price_path(bars, reference, levels):
    if not bars:
        return None
    high = max(bars, key=lambda bar: bar.high)
    low = min(bars, key=lambda bar: bar.low)
    prior_low = bars[0]
    rebound = dict(points=Decimal(0), low_bar_end=None, high_bar_end=None)
    for bar in bars[1:]:
        points = bar.high - prior_low.low
        if points > rebound["points"]:
            rebound = dict(points=points, low_bar_end=prior_low.end, high_bar_end=bar.end)
        if bar.low < prior_low.low:
            prior_low = bar
    return dict(
        minutes=len(bars), first_start=bars[0].start, last_end=bars[-1].end,
        first_open=bars[0].open, last_close=bars[-1].close,
        high=high.high, high_bar_end=high.end, low=low.low, low_bar_end=low.end,
        max_short_adverse_points=max(Decimal(0), high.high - reference),
        max_short_favorable_points=max(Decimal(0), reference - low.low),
        max_rebound_from_earlier_minute_low=rebound,
        upper_level_observations={name: dict(
            first_high_at_or_above_end=next((bar.end for bar in bars if bar.high >= level), None),
            first_range_contains_end=next((bar.end for bar in bars if bar.low <= level <= bar.high), None),
            first_close_at_or_above_end=next((bar.end for bar in bars if bar.close >= level), None),
            first_strict_close_end=next((bar.end for bar in bars if bar.close > level), None),
        ) for name, level in levels.items()},
    )


def study(session, market):
    frozen = verified_json(RECOVERY, RECOVERY_SHA)
    replacement = verified_json(SNAPSHOTS, SNAPSHOTS_SHA)
    life = verified_json(LIFECYCLE, LIFECYCLE_SHA)
    noon_leg, night_leg = extract_snapshots(life)
    photos = replacement["snapshots"]
    if any(frozen["photos"][key] != photos[key] for key in (LUNCH, CLOSE)):
        raise ValueError("SH_EXPOSURE_PHOTO_CHANGED")
    day = date.fromisoformat(frozen["trading_day"])
    afternoon = market_for(session, market, CONTRACT, day, frozen["market"])[1]
    night = read_window(session, market, CONTRACT, date(2026, 10, 28))[1]
    if life["market"]["1m"] != dict(afternoon=digest(afternoon), night=digest(night)):
        raise ValueError("SH_EXPOSURE_FROZEN_MINUTES_CHANGED")
    close_at = datetime.fromisoformat(photos[CLOSE]["quote_anchor"])
    night_start, night_cut = (datetime.fromisoformat(life[key]) for key in ("night_start", "night_cut"))
    if afternoon[-1].end != close_at or night[0].start != night_start:
        raise ValueError("SH_EXPOSURE_SESSION_CHANGED")
    levels = {name: Decimal(value) for name, value in frozen["target_prices"].items()}
    far, near = map(Decimal, frozen["recovery_proxy"])
    levels.update(old_resistance_far=far, old_resistance_near=near)
    front, back = map(Decimal, life["night_band"])
    night_edges = dict(protection_near=front, protection_far=back)
    first_overlap = life["night_price_only"]["first_completed_overlap"]
    (fast_confirmation,) = life["variants"]["1m_to_1m"]["night_signals"]
    night_milestones = {label: datetime.fromisoformat(clock) for label, clock in dict(
        fast_shape_confirmation=fast_confirmation["confirmed_at"],
        first_protection_zone_touch=first_overlap["bar_end"],
        first_whole_lot_envelope_if_after_zone_touch=first_overlap["wholly_after_known_at"]["first_compatible_prefix_end"],
    ).items()}
    full_night = completed(night, night_start, night_cut)
    old_short = photos[LUNCH]["legs"]["short"]["quantity"]
    if not old_short == noon_leg["quantity"] == night_leg["quantity"]:
        raise ValueError("SH_EXPOSURE_LOCK_SIZE_CHANGED")
    cases = []
    for row in frozen["afternoon"]["candidates"]:
        bar_end = datetime.fromisoformat(row["confirmed_at"])
        known = datetime.fromisoformat(row["available_at"])
        anchor = Decimal(row["close"])
        if (known != bar_end + US or bar_end >= close_at
                or not any(bar.end == bar_end and bar.close == anchor for bar in afternoon)):
            raise ValueError("SH_EXPOSURE_CONFIRMATION_CHANGED")
        post_signal = completed(afternoon, known, close_at + 2 * US)
        cases.append(dict(
            candidate_bar_end=bar_end, candidate_known_at=known, comparison_reference_close=anchor,
            afternoon=price_path(post_signal, anchor, levels),
            night_open_gap_from_day_close=night[0].open - afternoon[-1].close,
            night_until={label: price_path(completed(night, night_start, end + 2 * US), anchor, night_edges)
                         for label, end in night_milestones.items()},
            night_to_post_cut_if_still_unprotected=price_path(full_night, anchor, night_edges),
        ))
    return dict(
        version="lms405-sh-recovery-exposure-v1", contract=CONTRACT, trading_day=day,
        scope="RETROSPECTIVE_PRICE_PATH_UNDER_HYPOTHETICAL_FULL_RELEASE",
        references=dict(recovery=RECOVERY_SHA, replacement=SNAPSHOTS_SHA, lifecycle=LIFECYCLE_SHA),
        night_milestones_bar_end=night_milestones, close_quote_anchor=close_at, night_cut=night_cut,
        afternoon_reference_levels=levels, night_reference_levels=night_edges,
        locked=dict(gross_lots=2 * old_short, net_lots=0),
        hypothetical_full_release=dict(gross_lots=old_short, net_lots=-old_short),
        cases=cases, account_continuity=None, author_actual_action_at=None, author_action_samples=0,
        author_match_rate=None, executable=False, fills=None, pnl=None,
    )


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError):
        parser.exit(2, "SH_EXPOSURE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
