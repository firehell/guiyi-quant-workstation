"""Check whether PVC's left-zone geometry transfers across price roles and contracts."""

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_breakout_trial_study import price_states
from lms405_m_permission_study import read_pair
from lms405_portfolio_left_entry import zone_signal_geometry
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

VERSION = "lms405-left-transfer-study-v1"
PVC_SA_PLAN = "A5358325549629506"
GLASS = "S5325691679933993"
COAL = "S5193109300577840"
SA_PHOTO = "WRov1j6e10"
SA_IMAGE = "Rov1j6e10-position-screen.png"


@dataclass(frozen=True)
class Case:
    contract: str
    trading_day: str
    start: str
    cut: str
    source_id: str
    source_role: str
    scope: str
    direction: str
    zone: tuple[str, str]


CASES = {
    "pvc": Case("V2701", "2026-10-27", "2026-10-26T21:00", "2026-10-27T15:01",
                PVC_SA_PLAN, "LEFT_ENTRY_REFERENCE", "NEXT_TRADING_DAY", "LONG", ("5045", "5074")),
    "glass_next": Case("FG2609", "2026-07-29", "2026-07-28T21:00", "2026-07-29T15:01",
                       GLASS, "LEFT_ENTRY_REFERENCE", "NEXT_TRADING_DAY", "SHORT", ("913", "915")),
    "glass_later": Case("FG2609", "2026-07-30", "2026-07-29T21:00", "2026-07-30T15:01",
                        GLASS, "LEFT_ENTRY_REFERENCE", "CONTINUITY_UNVERIFIED", "SHORT", ("913", "915")),
    "coal_high": Case("JM2509", "2025-07-28", "2025-07-25T21:00", "2025-07-25T23:01",
                      COAL, "RISK_AND_SHORT_TRIAL_REFERENCE_RECAP", "RETROSPECTIVE", "SHORT", ("1285", "1303.5")),
    "coal_switch": Case("JM2509", "2025-07-28", "2025-07-25T21:00", "2025-07-25T23:01",
                        COAL, "TREND_INTERRUPTION_REFERENCE_RECAP", "RETROSPECTIVE", "SHORT", ("1207", "1229.5")),
    "soda": Case("SA2701", "2026-10-27", "2026-10-26T21:00", "2026-10-26T22:04",
                 PVC_SA_PLAN, "RANGE_DIVIDER", "NEXT_TRADING_DAY", "SHORT", ("951", "957")),
}


def location_study(series, case, *, start, cutoff):
    low, high = map(Decimal, case.zone)
    minutes = [bar for bar in series[1] if start <= bar.start and bar.end + US < cutoff]
    first_contact = next((bar.end for bar in minutes if bar.low <= high and low <= bar.high), None)
    events = zone_signal_geometry(series, case.contract, start, cutoff, low, high, direction=case.direction)
    if minutes and any(bar.contract != case.contract for bar in minutes):
        raise ValueError("LEFT_TRANSFER_MARKET_SCOPE_MISMATCH")
    return dict(
        complete_minutes=len(minutes), first_range_contact=first_contact,
        price_range=[min(b.low for b in minutes), max(b.high for b in minutes)] if minutes else None,
        signal_count=dict(shape_overlap=sum(row["shape_overlap"] for row in events),
                          confirmation_inside=sum(row["confirmation_inside"] for row in events)),
        geometry=events,
    )


def glass_price_path(series, start, cutoff):
    minutes = [bar for bar in series[1] if start <= bar.start and bar.end + US < cutoff]
    states = price_states(minutes, "SHORT", Decimal(904), Decimal(907))
    return dict(
        zone=[904, 907], role="SEPARATE_BREAK_PRESSURE_REFERENCE",
        first_range_contact=next((bar.end for bar in minutes if bar.low <= 907 and bar.high >= 904), None),
        first_fresh_cross=next((end for end, state in states.items() if state["crossing"]), None),
        first_retest_proxy=next((end for end, state in states.items() if state["retest_confirmed_at"]), None),
    )


def coal_timing(series, start, cutoff):
    minutes = [b for b in series[1] if start <= b.start and b.end + US < cutoff]
    peak = max(b.high for b in minutes)
    top = next(b for b in minutes if b.high == peak)
    failure = next((b for b in minutes if top.end + US < b.end and b.close < Decimal("1207")), None)
    return dict(window_high=peak, first_maximum_bar_available_at=top.end + US,
                first_close_below_1207_after_high=failure.end + US if failure else None,
                role="RETROSPECTIVE_PEAK_AND_REGIME_SWITCH_PROXY")


def soda_envelope(raw, first_contact, start, cutoff, photo):
    if not first_contact or datetime.fromisoformat(photo["published_at"]) != cutoff:
        raise ValueError("LEFT_TRANSFER_SODA_CONTACT_OR_PHOTO_MISMATCH")
    tick = Decimal(1)
    total = displayed_tick_totals(Decimal("960.0"), 20, tick)
    full = [b for b in raw if start <= b.bar_end - ONE and b.bar_end < cutoff]
    early, after = [], []
    for bar in full:
        (after if first_contact + US < bar.bar_end - ONE else early).append(bar)
    envelope, after_touch = tick_bounds(full, tick), tick_bounds(after, tick)
    early_envelope = tick_bounds(early, tick)
    counts = earlier_lot_counts(early_envelope, after_touch, 20, total)
    return dict(
        photo=photo, observed_leg=dict(direction="SHORT", quantity=20, today=20, opening_average="960.0"),
        full_envelope=envelope, whole_leg_compatible_in_window=bool(earlier_lot_counts(None, envelope, 20, total)),
        excluded_early_minutes_envelope=early_envelope, after_contact_strict_envelope=after_touch,
        minimum_lots_outside_strict_post_contact=min(counts) if counts else None,
        whole_leg_compatible_after_contact=0 in counts,
        photo_used_to_assess_prior_permission=False, observation_at=None,
    )


def study(session, market):
    index = input_sources()
    results, windows = {}, {}
    photo = load_source(index, SA_PHOTO)
    path = (ARCHIVE.parent / photo["archive_path"]).parent / SA_IMAGE
    photo["image_sha256"] = sha(path.read_bytes())
    if photo["image_sha256"] not in (ARCHIVE.parent / photo["archive_path"]).read_text(encoding="utf-8"):
        raise ValueError("LEFT_TRANSFER_SODA_IMAGE_MISMATCH")
    for key, case in CASES.items():
        source = load_source(index, case.source_id)
        source_end = datetime.fromisoformat(source["published_at"]) + ONE
        location, cutoff = at(case.start), at(case.cut)
        retrospective = case.scope == "RETROSPECTIVE"
        if retrospective != (cutoff <= source_end):
            raise ValueError("LEFT_TRANSFER_SOURCE_TIME_MISMATCH")
        start = location if retrospective else max(location, source_end + US)
        window = (case.contract, case.trading_day)
        if window not in windows:
            windows[window] = read_pair(session, market, case.contract, (date.fromisoformat(case.trading_day),))
        raw, series = windows[window]
        result = location_study(series, case, start=start, cutoff=cutoff)
        split_times = {cutoff, start + (cutoff - start) / 2}
        if result["first_range_contact"] is not None:
            split_times.add(result["first_range_contact"] + US)
        for split in sorted(split_times):
            prefix = {period: [bar for bar in group if bar.end + US < split] for period, group in series.items()}
            if location_study(prefix, case, start=start, cutoff=split) != location_study(
                series, case, start=start, cutoff=split,
            ):
                raise ValueError("LEFT_TRANSFER_PREFIX_DIVERGED")
        result.update(source=source, source_role=case.source_role, evidence_scope=case.scope,
                      publication_minute_end_proxy=source_end, historical_revision_verified=False,
                      contract=case.contract, trading_day=case.trading_day, side=case.direction,
                      zone=case.zone, start=start, cutoff=cutoff, prefix_checks=len(split_times),
                      market={f"{period}m": identity(group) for period, group in raw.items()},
                      author_permission=None, author_action_at=None, admissible_as_author_entry=False)
        if key.startswith("glass"):
            result["separate_break_pressure"] = glass_price_path(series, start, cutoff)
        elif key.startswith("coal"):
            result["regime_timing"] = coal_timing(series, start, cutoff)
        elif key == "soda":
            result["opening_average_diagnostic"] = soda_envelope(
                raw[1], result["first_range_contact"], start, cutoff, photo,
            )
        results[key] = result
    return dict(version=VERSION, cases=results, author_action_samples=0, author_match_rate=None,
                applied_positions=0, executable=False, fills=None, pnl=None)


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
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('LEFT_TRANSFER_') and code.isidentifier() else 'LEFT_TRANSFER_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
