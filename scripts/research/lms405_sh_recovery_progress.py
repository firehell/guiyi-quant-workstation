"""Audit old target progress versus fresh recovery after the SH2701 noon snapshot."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed
from lms405_unlock_boundary_comparison import evaluate
from lms_near405_replay import encoded, sha

CONTRACT = "SH2701"
DAY = date(2026, 10, 27)
TARGETS = {"old_strong_target": Decimal(1498), "next_target_near": Decimal(1485), "next_target_far": Decimal(1483)}
BAND = (Decimal(1511), Decimal(1516))
SNAPSHOTS = Path("output/lms405-sh-protection-replacement-20261125/verified.json")
SNAPSHOTS_SHA = "700523eff5ab60c4330cd180b223c58dd3f664feadcc8fa1df8dc67283733286"
RECOVERY_REFERENCE = Path("output/lms405-unlock-boundary-20261125/final.json")
RECOVERY_SHA = "4a0c6c836fc64b0c5c0af5b4310395b5a8c7d9026c14b31ec459f433f715e541"


def target_clocks(minutes, level):
    return dict(first_reach=next((b.end + US for b in minutes if b.low <= level), None),
                first_strict_close=next((b.end + US for b in minutes if b.close < level), None))


def target_gate(shape_start, *, history, current, current_run_start):
    def earlier(value):
        return value is not None and value < shape_start

    return dict(historical_reach=earlier(history["first_reach"]),
                new_reach_after_snapshot=earlier(current["first_reach"]),
                new_strict_close_after_snapshot=earlier(current["first_strict_close"]),
                current_strict_run_started_before_shape=earlier(current_run_start))


def examine(series, *, start, cut, older):
    minutes = completed(series[1], start, cut)
    clocks = {role: target_clocks(minutes, price) for role, price in TARGETS.items()}
    current_runs = {role: strict_runs(minutes, price, "SHORT") for role, price in TARGETS.items()}
    # Track first close in the active run, including open-outside runs, and
    # leave the same-segment fresh crossing requirement on the recovery band.
    base = evaluate(series, start=start, cut=cut, side="SHORT", band=BAND)
    rows = []
    for event in base["candidates"]:
        shape_start = event["shape_end"] - event["shape_minutes"] * ONE
        gates = {}
        for role, runs in current_runs.items():
            run = runs.get(event["confirmed_at"])
            active_start = event["confirmed_at"] - (run["close_count"] - 1) * ONE + US if run else None
            gates[role] = target_gate(shape_start, history=older[role], current=clocks[role],
                                      current_run_start=active_start)
        rows.append(event | dict(shape_start=shape_start, target_gates=gates))
    return dict(clocks=clocks, candidates=rows)


def study(session, market):
    archived = verified_json(SNAPSHOTS, SNAPSHOTS_SHA)["snapshots"]
    photos = {sid: archived[sid] for sid in ("WRoAkcEppg", "U03")}
    index = input_sources()
    sources = {sid: load_source(index, sid) for sid in (
        "A5358325972992140", "WRouYm67Bc", "WRozPmaK10", "WRoCCdf0i5", *photos,
    )}
    for sid, record in photos.items():
        path = ARCHIVE.parent / record["image"]["path"]
        if sha(path.read_bytes()) != record["image"]["sha256"] or record["published_at"] != sources[sid]["published_at"]:
            raise ValueError("SH_PROGRESS_PHOTO_CHANGED")
    frozen = verified_json(RECOVERY_REFERENCE, RECOVERY_SHA)["cases"]["caustic_soda_afternoon"]
    start = datetime.fromisoformat(photos["WRoAkcEppg"]["published_at"]) + ONE
    noon = datetime.fromisoformat(photos["WRoAkcEppg"]["quote_anchor"])
    cut = datetime.fromisoformat(photos["U03"]["quote_anchor"])
    if start != at("2026-10-27T11:35") or cut != at("2026-10-27T15:00"):
        raise ValueError("SH_PROGRESS_SCOPE_CHANGED")
    series = read_window(session, market, CONTRACT, DAY)
    inputs = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
        (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
    ]).encode())) for p, rows in series.items()}
    if inputs != frozen["market_input"]:
        raise ValueError("SH_PROGRESS_MARKET_CHANGED")
    previous = completed(series[1], series[1][0].start, noon)
    older = {role: target_clocks(previous, price) for role, price in TARGETS.items()}
    result = examine(series, start=start, cut=cut, older=older)
    fields = ("target_gates", "shape_start")
    if encoded([{k: v for k, v in row.items() if k not in fields} for row in result["candidates"]]) != encoded(
        frozen["candidates"]
    ):
        raise ValueError("SH_PROGRESS_BASE_CANDIDATES_CHANGED")
    checks = {cut}
    checks.update(row["available_at"] for row in result["candidates"])
    checks.update(t for clocks in result["clocks"].values() for t in clocks.values() if t is not None)
    checks |= {clock + US for clock in checks if clock != cut}
    for clock in sorted(checks):
        prefix = {p: [bar for bar in rows if bar.end + US < clock] for p, rows in series.items()}
        before = examine(prefix, start=start, cut=clock, older=older)
        expected = {role: {k: t if t is not None and t < clock else None for k, t in clocks.items()}
                    for role, clocks in result["clocks"].items()}
        if before["clocks"] != expected or before["candidates"] != [
            row for row in result["candidates"] if row["available_at"] < clock
        ]:
            raise ValueError("SH_PROGRESS_PREFIX_DIVERGED")
    return dict(version="lms405-sh-recovery-progress-v1", contract=CONTRACT, trading_day=DAY,
                scope="RETROSPECTIVE_TARGET_AND_OLD_RESISTANCE_SENSITIVITY", historical_plan_verified=False,
                photos=photos, sources=sources, market=inputs, target_prices=TARGETS, older_target_clocks=older,
                older_target_cutoff=noon, recovery_proxy=BAND, start=start, cutoff=cut, afternoon=result,
                prefix_checks=len(checks), author_account_continuity=None, unshown_close_long_quantity=None,
                author_recovery_permission=None, author_actual_action_at=None, author_action_samples=0,
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
        parser.exit(2, (code if code.isidentifier() and code.startswith("SH_PROGRESS_")
                        else "SH_PROGRESS_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
