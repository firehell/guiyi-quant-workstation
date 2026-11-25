"""Compare carry-forward and fresh recovery paths in an isolated nine-contract replay."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff, HandoffConfirmation, assess_handoff
from guiyi_quant.lms405.public_conditions import Condition
from lms405_counter_m_study import beyond
from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_recovery_confirmation_audit import strict_runs
from lms405_replay import read_session_series
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed
from lms405_unlock_boundary_comparison import evaluate
from lms405_volatility_context import bars_sha
from lms_near405_replay import encoded, sha

DAY = date(2026, 10, 27)
PRIOR_DAY = date(2026, 10, 26)
PATHS = ("near_geometry", "near_after_far_reach", "current_far_before_shape")
SOURCES = {
    "roles": ("lms405-recovery-role-20261125/final.json", "8bfc0bc08da47543c49737b0dee4e89e234ffbe64cbe466db8ab69dae73cfaa1"),
    "seeds": ("lms405-seeded-recovery-clocks-20261125/with-quote-bounds.json",
              "4821f58bb1150db4e9a83994a57da7afdc1f557ce66b5957e55e3727d21646e9"),
    "pvc": ("lms405-pvc-recovery-carry-20261126/reviewed.json", "ec0692372f241cd7a58cd57425954da32beb7ac3771ecbde3ab109ece6d22a2b"),
    "sh": ("lms405-sh-recovery-progress-20261126/verified.json", "09ed30afda94f92089d15f5e10f9e2aa125908bfca30fdb1aa962ae041966d66"),
}


def clock_rows(series, *, start, cut, side, band, earlier_far):
    base = evaluate(series, start=start, cut=cut, side=side, band=band)
    minutes = completed(series[1], start, cut)
    far = band[1] if side == "LONG" else band[0]
    runs = strict_runs(minutes, far, side)
    reached = earlier_far if earlier_far is not None else base["first_far_reach_known_at"]
    results = []
    for event in base["candidates"]:
        shape_start = event["shape_end"] - event["shape_minutes"] * ONE
        near = "NEAR" in event["modes"]
        run = runs.get(event["confirmed_at"])
        fresh = run["fresh_crossing_known_at"] if run else None
        conditions = dict(
            near_geometry=near,
            near_after_far_reach=near and reached is not None and reached < shape_start,
            current_far_before_shape="FAR" in event["modes"] and fresh is not None and fresh < shape_start,
        )
        results.append(event | dict(shape_start=shape_start, conditions=conditions))
    return results


def study_paths(series, *, earlier_far, **window):
    if earlier_far is not None and earlier_far >= window["start"]:
        raise ValueError("PORTFOLIO_PROGRESS_PREWINDOW_CLOCK_REQUIRED")
    args = dict(earlier_far=earlier_far, start=window["start"], side=window["side"], band=window["band"])
    events = clock_rows(series, cut=window["cut"], **args)
    stamps = {row["available_at"] for row in events}
    splits = stamps | {stamp + US for stamp in stamps} | {window["cut"]}
    for cut in sorted(splits):
        prefix = {p: [b for b in rows if b.end + US < cut] for p, rows in series.items()}
        if clock_rows(prefix, cut=cut, **args) != [row for row in events if row["available_at"] < cut]:
            raise ValueError("PORTFOLIO_PROGRESS_PREFIX_DIVERGED")
    return dict(events=events, prefix_checks=len(splits),
                counts={mode: sum(row["conditions"][mode] for row in events) for mode in PATHS})


def first_far_reach(rows, *, edge, side, cutoff):
    field = "high" if side == "LONG" else "low"
    return next((bar.bar_end + US for bar in rows if bar.bar_end + US < cutoff
                 and (getattr(bar, field) == edge or beyond(getattr(bar, field), edge, side))), None)


def fixture_identity(mode, event):
    return f"TEST_FIXTURE:{mode}:{event['shape_minutes']}:{event['confirm_minutes']}:{event['available_at'].isoformat()}"


def simulated_confirmation(request, mode, event):
    source = fixture_identity(mode, event)
    decision_at = event["available_at"] + US
    return HandoffConfirmation(request.confirmation_scope(source, event["available_at"], True),
                               f"{request.before.contract}:{source}", True, decision_at, decision_at, "TEST_FIXTURE")


def position_at(request, event, *, mode, as_of, approval=None):
    before = request.before
    unchanged = dict(long=before.long, short=before.short, hypothetical_signal_at=None, fixture_confirmation_id=None)
    if event is None or not event["conditions"][mode]:
        return unchanged
    source = fixture_identity(mode, event)

    def fact(name, observed, known):
        return Condition(name, request.scope, before.contract, True, observed, known, source, "EVENT_TIME")

    seed_time = request.position_known_at
    known = event["available_at"]
    facts = (fact("POSITION_PATH_CONFIRMED", request.position_since, seed_time),
             fact("ORIGINAL_PLAN_VALID", seed_time, seed_time), fact("SIGNAL", event["confirmed_at"], known))
    result = assess_handoff(request, facts, as_of=as_of, source=source, source_available_at=known,
                            version_405=True, approval=approval, allow_test_fixture=True)
    if result["after"] is None:
        return unchanged
    return dict(long=Decimal(result["after"]["long"]), short=Decimal(result["after"]["short"]),
                hypothetical_signal_at=event["confirmed_at"], fixture_confirmation_id=result["confirmation_id"])


def seeded_compare(seeds, portfolio, series_by_contract):
    marks = tuple(at(f"2026-10-27T{clock}") for clock in ("14:15", "14:30", "14:45", "15:00"))
    results = {}
    for name in ("iron_afternoon", "sh_afternoon"):
        evidence = seeds[name]
        contract = evidence["contract"]
        row = portfolio[contract]
        for photo in evidence["photos"].values():
            image = photo["image"]
            if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
                raise ValueError("PORTFOLIO_PROGRESS_IMAGE_CHANGED")
        start, cut = (datetime.fromisoformat(evidence[key]) for key in ("start", "cut"))
        earlier_far = row["earlier_far_reach"]
        band = tuple(map(Decimal, row["band"]))
        # Iron's newly scoped replay may use completed pre-lunch prices, but never late leg evidence.
        prior_same_day = [b for b in series_by_contract[contract][1] if b.end + US < start and b.low <= band[0]]
        if earlier_far is None and prior_same_day:
            earlier_far = prior_same_day[0].end + US
        result = study_paths(series_by_contract[contract], start=start, cut=cut, side="SHORT", band=band,
                             earlier_far=earlier_far)
        before = evidence["before_visible"]
        seed = Position(contract, Decimal(before["long"]["quantity"]), Decimal(before["short"]["quantity"]))
        handoff = Handoff("RESUME_ORIGINAL", seed, "SHORT", f"{contract}:fixture-plan", f"{contract}:fixture-cycle",
                          None, start, start)
        public = assess_handoff(handoff, (), as_of=cut, source=row["sources"][0]["source_url"],
                                source_available_at=datetime.fromisoformat(row["source_minute_end"]), version_405=None)
        if public["after"] is not None:
            raise ValueError("PORTFOLIO_PROGRESS_UNAUTHORIZED_ACTION")
        candidates = {mode: next((event for event in result["events"] if event["conditions"][mode]), None)
                      for mode in PATHS}
        approvals = {mode: simulated_confirmation(handoff, mode, event) if event is not None else None
                     for mode, event in candidates.items()}
        results[contract] = dict(
            scope="TEST_FIXTURE_USING_VISIBLE_LUNCH_QUANTITIES", earlier_far_reach=earlier_far,
            before_visible=before, at_close_visible=evidence["later_visible"], photos=evidence["photos"],
            public=public, scenario=result,
            fixture_approvals={mode: asdict(approval) if approval else None for mode, approval in approvals.items()},
            at_hypothetical_marks={mark.isoformat(): {
                mode: position_at(handoff, candidates[mode], mode=mode, as_of=mark, approval=approvals[mode])
                for mode in PATHS
            } for mark in marks}, account_continuity=None, author_actual_action=None,
        )
    totals = {}
    for mark in marks:
        when = mark.isoformat()
        totals[when] = {}
        for mode in PATHS:
            positions = [row["at_hypothetical_marks"][when][mode] for row in results.values()]
            totals[when][mode] = dict(gross_lots=sum(p["long"] + p["short"] for p in positions),
                                      absolute_net_lots=sum(abs(p["long"] - p["short"]) for p in positions))
    return dict(cases=results, two_contract_snapshot_totals=totals)


def study(session, market):
    refs = {key: verified_json(Path("output") / path, fingerprint) for key, (path, fingerprint) in SOURCES.items()}
    rows, all_series = {}, {}
    for contract in CONTRACTS:
        frozen = refs["roles"]["portfolio"][contract]
        series = read_window(session, market, contract, DAY)
        all_series[contract] = series
        inputs = {f"{p}m": dict(count=len(bars), sha256=sha(encoded([
            (b.start, b.end, b.open, b.high, b.low, b.close) for b in bars
        ]).encode())) for p, bars in series.items()}
        if inputs != frozen["market_input"]:
            raise ValueError("PORTFOLIO_PROGRESS_MARKET_CHANGED")
        row = {key: frozen[key] for key in ("band", "role", "sources", "source_minute_end", "side_scenario")}
        rows[contract] = row | dict(market=inputs, price_diagnostic=None, current_recovery_authority=None)
        if frozen["band"] is None:
            continue
        band, side = tuple(map(Decimal, frozen["band"])), frozen["side_scenario"]
        start, cut = (datetime.fromisoformat(frozen[key]) for key in ("start", "cutoff_exclusive"))
        previous = read_session_series(session, market, contract[:-4].lower(), contract, "1m", ONE, (PRIOR_DAY,))
        far = band[1] if side == "LONG" else band[0]
        earlier = first_far_reach(previous, edge=far, side=side, cutoff=start)
        if earlier is None:
            # Same trading day can include an earlier session or pre-lunch progress.
            field = "high" if side == "LONG" else "low"
            earlier = next((b.end + US for b in series[1] if b.end + US < start
                            and (getattr(b, field) == far or beyond(getattr(b, field), far, side))), None)
        diag = study_paths(series, start=start, cut=cut, side=side, band=band, earlier_far=earlier)
        strip = [{k: v for k, v in row.items() if k not in ("conditions", "shape_start")} for row in diag["events"]]
        expected = [{k: v for k, v in row.items() if k != "near_admission"} for row in frozen["candidates"]]
        if encoded(strip) != encoded(expected):
            raise ValueError("PORTFOLIO_PROGRESS_FROZEN_CANDIDATES_CHANGED")
        rows[contract].update(price_diagnostic=diag, earlier_far_reach=earlier,
                              prior_day_1m=dict(count=len(previous), ohlc_sha256=bars_sha(previous)))
    return dict(
        version="lms405-portfolio-recovery-progress-v1", day=DAY, history_trading_day=PRIOR_DAY,
        reference_sha256={key: fingerprint for key, (_, fingerprint) in SOURCES.items()},
        portfolio=rows, seeded_position_sensitivity=seeded_compare(refs["seeds"]["cases"], rows, all_series),
        case_controls=dict(pvc_apr27=refs["pvc"]["days"]["2026-04-27"]["candidates"],
                           pvc_author_report=refs["pvc"]["author_april27_report"],
                           sh_target_roles=refs["sh"]["afternoon"]),
        actual_author_recoveries=None, author_action_samples=0, author_match_rate=None,
        executable=False, fills=None, pnl=None,
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
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PORTFOLIO_PROGRESS_")
                        else "PORTFOLIO_PROGRESS_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
