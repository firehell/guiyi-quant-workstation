"""Compare recovery clocks between published midday and closing position snapshots."""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_fg_sa_cycle_order import fresh_geometry
from lms405_jm_may_leg_timing import MAY_INDEX, MAY_INDEX_HASH
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_recovery_confirmation_audit import strict_runs
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_trial_to_trend import frozen
from lms_near405_replay import encoded, sha

SH = ("lms405-sh-recovery-progress-20261126/verified.json",
      "09ed30afda94f92089d15f5e10f9e2aa125908bfca30fdb1aa962ae041966d66")
JM = ("lms405-jm-may-recovery-reset-20261126/replay-a.json",
      "d98d06af877829c3f8475664bda86ad0a02e62917894cace4d86da68d3ed1729")
SIGNALS = (("5m_to_5m", 5), ("5m_to_5m", 1), ("5m_to_1m", 1), ("1m_to_1m", 1))
SH_LEVELS = dict(resistance_near="1516", resistance_far="1511", strong_target="1498",
                 extension_near="1485", extension_far="1483")
JM_LEVELS = dict(divide_near="1228.5", divide_far="1223", first_target_near="1216", first_target_far="1214.5",
                 second_target_near="1210.5", second_target_far="1206", third_target_near="1205.5",
                 third_target_far="1196.5")


def scan(series, start, cutoff, levels):
    geometry = fresh_geometry(series, start, cutoff, "SHORT")
    bars = {period: completed(series[period], start, cutoff) for period in (1, 5)}
    result = {}
    for role, price in levels.items():
        edge = Decimal(price)
        runs = {p: strict_runs(rows, edge, "SHORT") for p, rows in bars.items()}
        first_price = {p: next((end + US for end, run in series_runs.items()
                                if run["fresh_crossing_known_at"] is not None and run["close_count"] >= 2), None)
                       for p, series_runs in runs.items()}
        confirmed = {}
        for clock, price_period in SIGNALS:
            rows = []
            for event in geometry[clock]:
                run = runs[price_period].get(event["confirmed_at"])
                if run and run["fresh_crossing_known_at"] is not None and run["close_count"] >= 2:
                    rows.append(event | dict(price_period_minutes=price_period, run=run))
            confirmed[f"{clock}:two_{price_period}m_closes"] = rows
        result[role] = dict(edge=edge, first_fresh_two_close_available=first_price, confirmed=confirmed)
    return dict(levels=result, geometry={name: rows for name, rows in geometry.items()
                                         if name in {clock for clock, _ in SIGNALS}})


def audit_timeframes(series, start, cutoff, levels):
    result = scan(series, start, cutoff, levels)
    clocks = {event["available_at"] for rows in result["geometry"].values() for event in rows}
    clocks.update(t for row in result["levels"].values()
                  for t in row["first_fresh_two_close_available"].values() if t is not None)
    cuts = {cutoff} | clocks | {t + US for t in clocks}
    for cut in sorted(cuts):
        prefix = {p: [bar for bar in rows if bar.end + US < cut] for p, rows in series.items()}

        def before(rows):
            return {name: [event for event in events if event["available_at"] < cut] for name, events in rows.items()}

        expected = dict(geometry=before(result["geometry"]), levels={
            role: dict(edge=row["edge"], confirmed=before(row["confirmed"]), first_fresh_two_close_available={
                period: t if t is not None and t < cut else None
                for period, t in row["first_fresh_two_close_available"].items()
            }) for role, row in result["levels"].items()
        })
        if scan(prefix, start, cut, levels) != expected:
            raise ValueError("SNAPSHOT_RECOVERY_PREFIX_DIVERGED")
    return result | dict(start=start, cutoff_exclusive=cutoff, prefix_checks=len(cuts))


def study(session, market):
    sh = verified_json(Path("output") / SH[0], SH[1])
    jm = verified_json(Path("output") / JM[0], JM[1])
    index = input_sources()
    jm_posts = {row["id"]: row for row in csv.DictReader(frozen(MAY_INDEX, MAY_INDEX_HASH).decode().splitlines())}
    jm_lunch = datetime.fromisoformat(jm_posts["G03"]["published_at"])
    jm_close = datetime.fromisoformat(jm_posts["G04"]["published_at"])
    jm_preceding = load_source(index, "S5300688465954469")
    jm_plan = datetime.fromisoformat(jm_posts["G02"]["published_at"])
    jm_open = at("2026-05-20T21:00")
    if not (datetime.fromisoformat(jm_preceding["published_at"]) < jm_plan < jm_open
            < jm_lunch < at("2026-05-21T15:00") < jm_close):
        raise ValueError("SNAPSHOT_RECOVERY_JM_SOURCE_ORDER_CHANGED")
    sh_photos = sh["photos"]
    for photo in sh_photos.values():
        info = photo["image"]
        if sha((ARCHIVE.parent / info["path"]).read_bytes()) != info["sha256"]:
            raise ValueError("SNAPSHOT_RECOVERY_SH_PHOTO_CHANGED")
    configs = (
        ("SH2701", sh, SH_LEVELS, datetime.fromisoformat(sh["start"]), datetime.fromisoformat(sh["cutoff"])),
        ("JM2609", jm, JM_LEVELS, jm_lunch + ONE, at("2026-05-21T15:00") + 2 * US),
    )
    cases = {}
    for contract, reference, levels, start, cutoff in configs:
        day = date.fromisoformat(reference["trading_day"])
        series = read_window(session, market, contract, day)
        if contract == "SH2701":
            market_id = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
                (b.start, b.end, b.open, b.high, b.low, b.close) for b in rows
            ]).encode())) for p, rows in series.items()}
            source_refs = dict(published=sh["sources"], photo_anchors=sh_photos)
        else:
            market_id = {str(p): dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}
            source_refs = dict(prior_public_recap=jm_preceding,
                               published={key: jm_posts[key] for key in ("G02", "G03", "G04", "G07")})
        if reference["market"] != market_id:
            raise ValueError("SNAPSHOT_RECOVERY_FROZEN_MARKET_CHANGED")
        cases[contract] = dict(
            contract=contract, trading_day=day, market=market_id, sources=source_refs,
            comparison=audit_timeframes(series, start, cutoff, levels),
            contemporaneous_recovery_permission=None, account_continuity=None,
            unshown_closing_protection_quantity=None, observed_author_action_at=None,
        )
    return dict(version="lms405-snapshot-recovery-timeframes-v1", scope="RETROSPECTIVE_PRICE_REFERENCES",
                cases=cases, references={SH[0]: SH[1], JM[0]: JM[1]}, author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("SNAPSHOT_RECOVERY_")
                        else "SNAPSHOT_RECOVERY_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
