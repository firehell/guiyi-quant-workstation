"""Compare first-break trials against source-specific participation prerequisites."""

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_study import beyond
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import input_sources
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import signals
from lms405_v_ta_case import identity
from lms_near405_replay import encoded

VERSION = "lms405-breakout-trial-study-v1"
CLOCKS = ((1, 1), (5, 1), (5, 5))


@dataclass(frozen=True)
class Case:
    contract: str
    day: str
    start: str
    cut: str
    direction: str
    edge: str
    source: str
    role: str
    prerequisite: str
    opposite_invalidation: str | None = None
    next_reference: str | None = None
    recap: str | None = None


CASES = {
    "SH_ORIGINAL_SHORT": Case("SH2701", "2026-10-20", "2026-10-20T09:00", "2026-10-20T15:01",
                             "SHORT", "1726", "A5355789916438626", "RANGE_DIVIDER", "UNSPECIFIED",
                             next_reference="1722"),
    "SH_EXPLICIT_NO_CHASE": Case("SH2701", "2026-10-22", "2026-10-22T09:30", "2026-10-22T15:01",
                                "SHORT", "1653", "WRnOnrllRX", "COMPLETED_STRONG_SIDE", "DO_NOT_CHASE",
                                next_reference="1623"),
    "PVC_RIGHT_SHORT": Case("V2701", "2026-10-27", "2026-10-26T21:00", "2026-10-27T15:01",
                            "SHORT", "5055", "A5358325549629506", "ENTRY_REFERENCE", "BREAK_PRESSURE_THEN_SIGNAL",
                            opposite_invalidation="5074", next_reference="5045", recap="WRoCxx1ooa"),
    "PVC_RIGHT_LONG": Case("V2701", "2026-10-28", "2026-10-27T21:00", "2026-10-27T22:14",
                           "LONG", "5195", "A5358686423089344", "ENTRY_REFERENCE", "BREAK_THEN_SIGNAL",
                           next_reference="5232"),
    "RU_STRONG_SIDE": Case("RU2701", "2026-10-27", "2026-10-26T21:00", "2026-10-27T15:01",
                           "SHORT", "19505", "A5358325972992140", "OPEN_STRONG_SIDE", "SPACE_UNIDENTIFIED",
                           next_reference="19370", recap="U05"),
    "JM_M_TRIED": Case("JM2701", "2026-10-23", "2026-10-22T21:00", "2026-10-23T15:01",
                       "LONG", "1397.5", "A5356884629782554", "M_AFTER_PROTECTION_BAND", "BREAK_THEN_SIGNAL",
                       next_reference="1410.5", recap="WRo0OCbeQG"),
    "JM_M_SKIPPED": Case("JM2701", "2026-09-09", "2026-09-09T09:00", "2026-09-09T15:01",
                         "SHORT", "1657", "S5341270434121818", "M_BAND_RETROSPECTIVE", "RECAP_ONLY_SKIP",
                         next_reference="1619"),
}


def price_states(minutes, direction, edge, invalidation=None):
    """Each row depends on this continuous segment's completed prefix only."""
    previous = fresh = setup = touch = rejection = None
    rows = {}
    for bar in minutes:
        if previous is None or previous.end != bar.start:
            previous = fresh = setup = touch = rejection = None
        outside = beyond(bar.close, edge, direction)
        crosses = outside and previous is not None and not beyond(previous.close, edge, direction)
        if crosses:
            fresh = bar.end
        elif not outside:
            fresh = None
        if invalidation is not None:
            invalid = beyond(invalidation, bar.close, direction)
            if invalid or (rejection is not None and not outside):
                setup = touch = rejection = None
            elif setup is None and crosses:
                setup = bar.end
            elif setup is not None and touch is None and bar.low <= edge <= bar.high:
                touch = bar.end
            elif touch is not None and rejection is None and outside:
                rejection = bar.end
        rows[bar.end] = dict(outside=outside, crossing=crosses, active_cross_at=fresh,
                             retest_contact_at=touch, retest_confirmed_at=rejection)
        previous = bar
    return rows


def pattern_states(series, paths, *, direction, start, cut):
    result = {}
    for shape, confirm in CLOCKS:
        rows = []
        for frame in signals(series, shape, confirm, side=direction, start=start, cut=cut):
            state = paths[frame["confirmed_at"]]
            shape_start = frame["shape_end"] - shape * ONE
            crossing, retest = state["active_cross_at"], state["retest_confirmed_at"]
            rows.append(frame | dict(
                shape_start=shape_start, **state,
                cross_known_before_confirmation=bool(crossing is not None and crossing + US < frame["available_at"]),
                retest_known_before_confirmation=bool(retest is not None and retest + US < frame["available_at"]
                                                       and state["outside"]),
                fresh_shape_after_cross=bool(crossing is not None and crossing + US < shape_start),
                fresh_shape_after_retest=bool(retest is not None and retest + US < shape_start and state["outside"]),
            ))
        result[f"{shape}m_to_{confirm}m"] = rows
    return result


def analyze(series, case, start, cut):
    minutes = [bar for bar in series[1] if start <= bar.start and bar.end + US < cut]
    edge = Decimal(case.edge)
    invalidation = Decimal(case.opposite_invalidation) if case.opposite_invalidation else None
    paths = price_states(minutes, case.direction, edge, invalidation)
    patterns = pattern_states(series, paths, direction=case.direction, start=start, cut=cut)

    def first(field):
        return next((key for key, row in paths.items() if row[field]), None)

    first_outside, first_cross = first("outside"), first("crossing")
    geometry = {
        clock: {field: next((row["confirmed_at"] for row in rows if row[field]), None)
                for field in ("cross_known_before_confirmation", "retest_known_before_confirmation",
                              "fresh_shape_after_cross", "fresh_shape_after_retest")}
        for clock, rows in patterns.items()
    }
    reference = Decimal(case.next_reference) if case.next_reference else None
    reference_reach = reference_has_price = None
    if reference is not None:
        reference_reach = next((bar.end for bar in minutes if (
            bar.high >= reference if case.direction == "LONG" else bar.low <= reference
        )), None)
        reference_has_price = next((bar.end for bar in minutes if bar.low <= reference <= bar.high), None)
    return dict(
        first_beyond=first_outside, first_cross=first_cross, first_retest=first("retest_confirmed_at"),
        first_reference_directional_reach=reference_reach,
        first_reference_range_contains=reference_has_price,
        first_beyond_has_fresh_cross=first_outside is not None and first_outside == first_cross,
        patterns=patterns, first_confirmations_by_route=geometry,
        signal_requires_author_permission=True,
    )


def study(session, market):
    index = input_sources()
    results = {}
    for key, case in CASES.items():
        source = load_source(index, case.source)
        available = datetime.fromisoformat(source["published_at"]) + ONE
        recap = load_source(index, case.recap) if case.recap else None
        start, cut = map(at, (case.start, case.cut))
        retrospective = case.prerequisite == "RECAP_ONLY_SKIP"
        if retrospective != (cut <= available):
            raise ValueError("LMS_BREAKOUT_TRIAL_SOURCE_TIME_CONFLICT")
        if not retrospective:
            start = max(start, available + US)
        raw, series = read_pair(session, market, case.contract, (date.fromisoformat(case.day),))
        result = analyze(series, case, start, cut)
        cuts = sorted({instant for instant in (result["first_cross"], result["first_retest"], cut) if instant})
        for instant in cuts:
            prefix = {p: [bar for bar in bars if bar.end + US < instant] for p, bars in series.items()}
            if analyze(series, case, start, instant) != analyze(prefix, case, start, instant):
                raise ValueError("LMS_BREAKOUT_TRIAL_PREFIX_DIVERGED")
        results[key] = dict(contract=case.contract, trading_day=case.day, cutoff_exclusive=cut, start=start,
                            direction=case.direction, level=case.edge, level_role=case.role,
                            research_opposite_invalidation=case.opposite_invalidation,
                            next_reference=case.next_reference,
                            author_precondition=case.prerequisite, source=source, recap=recap,
                            publication_minute_end_proxy=available, retrospective_only=retrospective,
                            market={f"{p}m": identity(values) for p, values in raw.items()},
                            prefix_checks=len(cuts), observed_author_action_at=None, admitted_action=None,
                            **result)
        if key == "JM_M_TRIED":
            results[key]["day_session_only"] = analyze(series, case, at("2026-10-23T09:00"), cut)
        if key in ("PVC_RIGHT_SHORT", "PVC_RIGHT_LONG"):
            results[key]["risk_cap_note"] = "HALF_OF_RISK_ALLOWED_FOR_INEXPERIENCED_PARTICIPANT"
    return dict(version=VERSION, cases=results, historical_source_revisions_verified=False,
                author_action_samples=0, author_match_rate=None, fills=None, pnl=None, executable=False)


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
        parser.exit(2, f"{code if code.startswith('LMS_BREAKOUT_TRIAL_') and code.isidentifier() else 'LMS_BREAKOUT_TRIAL_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
