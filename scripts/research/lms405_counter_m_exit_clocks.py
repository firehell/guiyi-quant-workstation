"""Observe counter-M risk separately from the next trend or original-side recovery."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_break_pressure_comparison import continuous_groups, first_shape_after
from lms405_counter_m_study import beyond
from lms405_jm_oct_recovery_clock import window_signals
from lms405_portfolio_replay import input_sources
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded

CASES = (
    ("JM2509", "2025-07-28", "S5193109300577840", "LONG", (
        ("short_m_risk_near", "1145.5"), ("short_m_risk_far", "1155.5"),
        ("long_stability_near", "1173"), ("long_stability_far", "1185"),
        ("potential_long_m_reference", "1199.5"), ("potential_long_m_far", "1204"),
        ("long_extension_near", "1224.5"), ("long_extension_far", "1233.5"),
    )),
    ("SH2609", "2026-07-27", "S5325329692361179", "SHORT", (
        ("retreat_from_extreme_m_far", "1911"), ("retreat_from_extreme_m_near", "1896"),
        ("original_short_recovery_near", "1870"), ("original_short_recovery_far", "1859"),
    )),
)
PROGRESS_CASES = (
    ("FG2701", "2026-09-14", "S5343083008886025", "SHORT", "940", "RETROSPECTIVE_M_RATING",
     "c91019bae89eec405aacfa8492048121abd12c96d20cd36c3bdbd848326b461c"),
    ("OI2609", "2026-06-08", "WR2IUYCQHj", "SHORT", "9924", "FORWARD_REFERENCE_HYPOTHETICAL_POSITION",
     "2f722530356aef05c2c7b8f767cd416749ef5db7dc6019c325def34fd550a583"),
    ("JM2701", "2026-10-23", "A5356884629782554", "LONG", "1427.5", "PREVIOUS_PLAN_M_RATING",
     "133c90a735f864f09b13ad3573abedfa179e3b47fa7ec971e250abc8a8549757"),
)


def inspect_level(groups, side, level, signals):
    first_touch, first_close, first_cross = None, None, None
    for group in groups:
        for index, bar in enumerate(group):
            if first_touch is None and bar.low <= level <= bar.high:
                first_touch = bar.end
            if not beyond(bar.close, level, side):
                continue
            if first_close is None:
                first_close = bar.end
            if first_cross is None and index and not beyond(group[index - 1].close, level, side):
                reset = next((item for item in group[index + 1:] if not beyond(item.close, level, side)), None)
                cap = reset.end + US if reset else group[-1].end + 2 * US
                first_cross = dict(
                    at=bar.end, close=bar.close, reset_at=reset.end if reset else None,
                    observed_until=cap, geometry_starting_after_cross=first_shape_after(signals, bar.end, cap),
                )
    return dict(level=level, first_touch=first_touch, first_strict_close=first_close, first_fresh_cross=first_cross)


def observe(series, start, cutoff, side, levels):
    bars = completed(series[1], start, cutoff)
    if not bars:
        raise ValueError("LMS_M_EXIT_EMPTY_WINDOW")
    groups = continuous_groups(bars)
    signals, checks = window_signals(series, start, cutoff, side)
    return dict(
        start=start, cutoff_exclusive=cutoff, minutes=len(bars), open=bars[0].open,
        high=max(bar.high for bar in bars), low=min(bar.low for bar in bars), close=bars[-1].close,
        price_observations={role: inspect_level(groups, side, Decimal(level), signals) for role, level in levels},
        geometry_prefix_checks=checks,
    )


def study(session, market):
    index = input_sources()
    result = {}
    for contract, day, source_id, side, levels in CASES:
        series = read_window(session, market, contract, date.fromisoformat(day))
        source = load_source(index, source_id)
        published = datetime.fromisoformat(source["published_at"])
        night_open, day_open, end = series[1][0].start, at(f"{day}T09:00"), series[1][-1].end
        night_end = max(bar.end for bar in series[1] if bar.end < day_open)
        if contract == "JM2509":
            if not night_end < published < day_open:
                raise ValueError("LMS_M_EXIT_JM_SOURCE_WINDOW_CHANGED")
            day_role = "POST_PUBLICATION_CURRENT_TEXT"
        else:
            if not end < published:
                raise ValueError("LMS_M_EXIT_SH_RECAP_WINDOW_CHANGED")
            day_role = "RETROSPECTIVE"
        result[contract] = dict(
            source=source, trading_day=day, side=side,
            night=observe(series, night_open, day_open, side, levels) | dict(source_role="RETROSPECTIVE"),
            day=observe(series, day_open, end + 2 * US, side, levels) | dict(source_role=day_role),
            market={str(p): dict(count=len(bars), sha256=digest(bars)) for p, bars in series.items()},
            historical_revision_verified=False, author_version=None,
            actual_exit_at=None, actual_original_recovery_at=None,
            author_exit_formula=None, author_recovery_formula=None,
        )
    return dict(version="lms405-counter-m-exit-clocks-v1", cases=result, admitted_author_actions=0,
                author_action_match_rate=None, fills=None, pnl=None, executable=False)


def progress_clocks(bars, side, far):
    """Compare two completed-minute reactions inside the segment of the first target touch."""
    group = next((g for g in continuous_groups(bars) if any(b.low <= far <= b.high for b in g)), [])
    touch = next((i for i, b in enumerate(group) if b.low <= far <= b.high), None)
    if touch is None:
        return dict(first_contact=None, far_retreat=None, last_push_retreat=None)
    favorable = "high" if side == "LONG" else "low"
    adverse = "low" if side == "LONG" else "high"
    opposite = "SHORT" if side == "LONG" else "LONG"
    anchor = group[touch]
    far_retreat = last_push_retreat = None
    for bar in group[touch + 1:]:
        if far_retreat is None and beyond(bar.close, far, opposite):
            far_retreat = dict(at=bar.end, close=bar.close, threshold=far)
        if beyond(getattr(bar, favorable), getattr(anchor, favorable), side):
            anchor = bar
        elif last_push_retreat is None and beyond(bar.close, getattr(anchor, adverse), opposite):
            last_push_retreat = dict(at=bar.end, close=bar.close, threshold=getattr(anchor, adverse),
                                     anchor_end=anchor.end)
    return dict(first_contact=group[touch].end, far_retreat=far_retreat,
                last_push_retreat=last_push_retreat)


def progress_study(session, market):
    index = input_sources()
    comparisons = {}
    for contract, day, source_id, side, far, role, fingerprint in PROGRESS_CASES:
        series = read_window(session, market, contract, date.fromisoformat(day))
        if digest(series[1]) != fingerprint:
            raise ValueError("LMS_M_PROGRESS_MARKET_CHANGED")
        source = load_source(index, source_id)
        start = at(day + ("T10:37" if contract == "JM2701" else "T09:00"))
        published = datetime.fromisoformat(source["published_at"])
        end = series[1][-1].end
        in_scope = (end + US < published if role == "RETROSPECTIVE_M_RATING" else published + ONE < start)
        if not in_scope:
            raise ValueError("LMS_M_PROGRESS_SOURCE_CLOCK_CHANGED")
        bars = completed(series[1], start, end + 2 * US)
        result = progress_clocks(bars, side, Decimal(far))
        for bar in bars:
            # The selection and decision on each visible prefix must agree with the full result.
            cut = bar.end + US
            expected = {key: value for key, value in result.items() if value is not None
                        and (value["at"] if isinstance(value, dict) else value) + US < cut}
            prefix = progress_clocks([b for b in bars if b.end + US < cut], side, Decimal(far))
            if any(prefix[key] != expected.get(key) for key in prefix):
                raise ValueError("LMS_M_PROGRESS_PREFIX_DRIFT")
        comparisons[contract] = dict(trading_day=day, source=source, role=role, start=start,
                                     position_side=side, reference=Decimal(far), prefix_checks=len(bars),
                                     **result)
    return dict(version="lms405-m-progress-exit-observation-v1", cases=comparisons,
                actual_exit_at=None, confirms_author_rule=False, admitted_author_actions=0,
                author_action_match_rate=None, fills=None, pnl=None, executable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress-comparison", action="store_true")
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
            compare = progress_study if args.progress_comparison else study
            report = compare(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "LMS_M_EXIT_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
