"""Replay OI2609's June protection and counter-M evidence without inferring author fills."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation, assess_handoff
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from guiyi_quant.lms405.public_conditions import Condition
from lms405_oi_june_case import CONTRACT, DAYS, EARLY_BANDS, EARLY_BASELINE_SHA256, local_time
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_revision_timing import active_revision, geometry, scoped_geometry
from lms405_protection_timeframes import PERIODS, VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import signals
from lms_near405_replay import encoded, sha

BASELINE = Path("output/lms-oi2609-june-20261124/comparison.json")
SOURCES = (
    ("S5305666088472874", "2026-06-03T10:13", "6e77c1c7f9ff89e726200320ce731661c2e834a24a6eb3029e8060095a486cfc"),
    ("S5306128623993006", "2026-06-04T16:51", "5c2a279c35b99c747079a472df1aa664087e507d40931ae721af5c5d30ba7273"),
    ("S5306393997347489", "2026-06-05T10:26", "d3a1e977dc9c20d92f021609e35595c7e6959826008641a0702d2d0f4c933c9d"),
    ("WR2IUYCQHj", "2026-06-05T17:00", "6165a81cfe8cac419d14993511a564fe5e8f696923499d7b571d3aa0e4e19cd7"),
)
PROTECTION_BAND = (Decimal(10273), Decimal(10315))
PREVIOUS_LOW = Decimal(10230)
DAY_OPEN = at("2026-06-05T09:00")


def edge_window(series, edge, *, start, cut):
    """Compare first-below, fresh adjacent-close crossing and open-at-edge paths."""
    minutes = [bar for bar in series[1] if bar.start >= start and bar.end + US < cut]
    runs = strict_runs(minutes, edge, "SHORT")
    first = next(iter(runs), None)
    fresh = next((r["fresh_crossing_known_at"] for r in runs.values()
                  if r["fresh_crossing_known_at"] is not None), None)
    # The fixed windows begin at actual session openings. Equality in the
    # opening print is separate from an adjacent completed close crossing.
    opening = minutes[0] if minutes and minutes[0].start == start else None
    opening_at_edge = opening.end if opening and opening.open == edge and opening.close < edge else None
    groups = {}
    for shape, confirm in VARIANTS:
        starts = {bar.end: bar.start for bar in series[shape]}
        events = signals(series, shape, confirm, side="SHORT", start=start, cut=cut)
        eligible = [dict(row, shape_start=starts[row["shape_end"]], run=runs[row["confirmed_at"]])
                    for row in events if first and row["confirmed_at"] in runs and row["close"] < edge
                    and starts[row["shape_end"]] > first + US]
        groups[f"{shape}m_to_{confirm}m"] = dict(
            after_first_below=next(iter(eligible), None),
            after_fresh_cross_in_same_run=next((row for row in eligible
                if (cross := row["run"]["fresh_crossing_known_at"]) is not None
                and row["shape_start"] > cross and row["run"]["close_count"] >= 2), None),
            after_opening_at_edge_in_same_run=next((row for row in eligible if opening_at_edge is not None
                and row["shape_start"] > opening_at_edge + US
                and row["confirmed_at"] - (row["run"]["close_count"] - 1) * ONE == opening_at_edge), None),
        )
    return dict(edge=edge, first_close_below_at=first, first_fresh_cross_known_at=fresh,
                opening_price=opening.open if opening else None, opening_at_edge_then_close_below_at=opening_at_edge,
                groups=groups)


def handoff_paths(boundary, *, seed_time, morning_cut, report_known):
    # One fixed contrast: the earliest new candidate after the prior-day low broke.
    candidates = [group["after_first_below"] for group in boundary["groups"].values()
                  if group["after_first_below"] is not None]
    candidate = min(candidates, key=lambda row: row["available_at"], default=None)
    results = {}
    for route, units in (("COUNTER_M_FROM_LOCK", Decimal(1)), ("COUNTER_M_AFTER_CLEAR", Decimal(0))):
        request = Handoff(route, Position(CONTRACT, units, units), "LONG", "fixture-prior-long-plan",
                          "fixture-prior-cycle", "fixture-counter-m-task", seed_time, seed_time)

        def public(as_of):
            return assess_handoff(request, (), as_of=as_of, source=SOURCES[-1][0],
                                  source_available_at=report_known, version_405=True)

        row = dict(assumed_position=dict(long=units, short=units),
                   morning_public_assessment=public(morning_cut), later_public_assessment=public(report_known + US),
                   fixture=None)
        if candidate is not None:
            source = "TEST_FIXTURE_OI_M_POLICY"

            def fact(name, observed_at, known_at):
                return Condition(name, request.scope, CONTRACT, True, observed_at, known_at, source, "EVENT_TIME")

            broken = boundary["first_close_below_at"]
            facts = (fact("POSITION_PATH_CONFIRMED", seed_time, seed_time),
                     fact("M_CONFIG_PERMITS", seed_time, seed_time), fact("INTERRUPTION", broken, broken + US),
                     fact("SIGNAL", candidate["confirmed_at"], candidate["available_at"]))
            decide_at = candidate["available_at"] + US
            approval = HandoffConfirmation(request.confirmation_scope(source, seed_time, True),
                                           f"fixture:{route}", True, decide_at, decide_at, "TEST_FIXTURE")
            params = dict(source=source, source_available_at=seed_time, version_405=True,
                          approval=approval, allow_test_fixture=True)
            at_decision = assess_handoff(request, facts, as_of=decide_at, **params)
            after_decision = assess_handoff(request, facts, as_of=decide_at + US, **params)
            if at_decision["after"] is not None or after_decision["after"] is None:
                raise ValueError("OI_HANDOFF_CLOCK_MISMATCH")
            row.update(fixture=after_decision, fixture_candidate=candidate, fixture_interruption_at=broken,
                       fixture_same_time=at_decision)
        results[route] = row
    return results


def study(session, market):
    baseline = verified_json(BASELINE, EARLY_BASELINE_SHA256)
    index = input_sources()
    sources, clocks = {}, []
    for key, displayed, fingerprint in SOURCES:
        source = load_source(index, key)
        stamp = datetime.fromisoformat(source["published_at"])
        if stamp != at(displayed) or source["archive_sha256"] != fingerprint:
            raise ValueError("OI_SOURCE_CHANGED")
        clocks.append(stamp + ONE)
        sources[key] = source | dict(display_minute_available_from=clocks[-1], historical_revision_verified=False)
    early_known, lock_known, morning_known, report_known = clocks
    first, second, last = [read_window(session, market, CONTRACT, day) for day in DAYS]
    hashes = {f"{period}m": sha(json.dumps(
        [[local_time(bar.end), *map(str, ohlc(bar))] for day in (first, second, last) for bar in day[period]],
        separators=(",", ":")).encode()) for period in PERIODS}
    if hashes != baseline["input_ohlc_sha256"] or min(b.low for b in second[1]) != PREVIOUS_LOW:
        raise ValueError("OI_MARKET_INPUT_CHANGED")
    pending = ProtectionBandUpdate(CONTRACT, "EARLY_CHOICE_UNKNOWN", "REVIEW_PENDING", early_known, early_known,
                                   SOURCES[0][0], "LONG")
    # The published old protection area is a comparison reference only. The
    # actual active protection and the counter-M permission remain unknown.
    reference = ProtectionBandUpdate(CONTRACT, "PUBLISHED_PROTECTION_REFERENCE", "PROTECTION", lock_known,
                                     lock_known, SOURCES[1][0], "LONG", *PROTECTION_BAND)
    updates = (pending, reference)
    revisions = {time.isoformat(): active_revision(updates, CONTRACT, time)
                 for clock in (early_known, lock_known) for time in (clock - US, clock, clock + US)}
    def protection_summary(result):
        candidates, contact = result
        return dict(candidate_known_at=candidates, contact_bar_end=contact.end if contact else None)

    early = {key: protection_summary(scoped_geometry(first, area, known_at=early_known, cutoff=at("2026-06-03T15:01")))
             for key, area in EARLY_BANDS.items()}
    june4_review = protection_summary(geometry(second, PROTECTION_BAND, start=second[1][0].start, cutoff=lock_known))
    windows = {"night": (last[1][0].start, DAY_OPEN),
               "morning": (DAY_OPEN, at(SOURCES[2][1])),
               "combined": (last[1][0].start, at(SOURCES[2][1]))}
    paths, checks = {}, 0
    for name, (start, cut) in windows.items():
        paths[name] = {}
        for role, edge in (("published_protection_lower", PROTECTION_BAND[0]), ("previous_completed_day_low", PREVIOUS_LOW)):
            path = edge_window(last, edge, start=start, cut=cut)
            paths[name][role] = path
            test_clocks = {cut}
            for group in path["groups"].values():
                for row in group.values():
                    if row:
                        test_clocks.update((row["available_at"], row["available_at"] + US))
            for clock in test_clocks:
                prefix = {p: [b for b in bars if b.end + US < clock] for p, bars in last.items()}
                if edge_window(prefix, edge, start=start, cut=clock) != edge_window(last, edge, start=start, cut=clock):
                    raise ValueError("OI_PREFIX_DIVERGED")
                checks += 1
    return dict(version="lms405-oi-public-lifecycle-v1", input_ohlc_sha256=hashes, sources=sources,
                protection_reference_band=PROTECTION_BAND, public_reference_clock=revisions,
                early_protection_geometry_not_author_choice=early, june4_protection_geometry_retrospective=june4_review,
                june5_price_and_geometry=paths, prefix_checks=checks,
                conditional_handoff=handoff_paths(paths["morning"]["previous_completed_day_low"], seed_time=lock_known,
                                                  morning_cut=morning_known, report_known=report_known),
                actual_position=None, author_action_at=None, author_signal_at=None, author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("OI_") else "OI_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
