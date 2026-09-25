"""Exact SM2311 Sep 2023 D1/W1 turnover correction, one Catalog transaction."""

import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/quant-api"), str(ROOT / "packages/quant-core"), str(ROOT)]
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.market_home_projection import MarketHomeProjectionStore, market_home_projection_path
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.rqdata_adapter import _aggregate_daily_rows
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from scripts.newow_weekly_d1_then_w1_repair import _align_provider_bar_ends, _provider_bars_from_response, overlay_provider_turnover, realign_weekly_turnover
from scripts.newow_weekly_recovery import load_private_readonly_settings

HERE = Path(__file__).parent
ENV = Path.home() / "Library/Application Support/GuiyiQuant/project.env"
PLAN = HERE / "sm2311-20230901-source-plan.json"
RESULT = HERE / "sm2311-source-result.json"
RESPONSE = HERE / "source-attempts/sm2311-20230901-001/source-response-0001.json"
PREPARED = HERE / "sm2311-paired-prepare.json"
CUTOFF = date(2026, 9, 18)
DAY = date(2023, 9, 1)
FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")
DKEY = DatasetKey("contract", "sm", "SM2311", "1d")
WKEY = DatasetKey("contract", "sm", "SM2311", "1w")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha(path.read_bytes())


def candidate_sha(bars):
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
                   sink, compression="zstd", use_dictionary=False, version="2.6")
    return sha(sink.getvalue().to_pybytes())


def identity(part, root):
    path = part.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("PARTITION_PATH_INVALID")
    return {"uri": path.relative_to(root).as_posix(), "sha256": file_sha(path),
            "year": part.year, "month": part.month, "row_count": part.row_count,
            "quality_sha256": part.source_quality_sha256}


def partitions(catalog):
    def one(key, year, month):
        parts = [p for p in catalog.all_partitions(key) if (p.year, p.month) == (year, month)]
        if len(parts) != 1:
            raise ValueError("TARGET_PARTITION_INVALID")
        return parts[0]
    return one(DKEY, 2023, 8), one(DKEY, 2023, 9), one(WKEY, 2023, 9)


def candidates(catalog, store):
    plan, result, response = (json.loads(p.read_bytes()) for p in (PLAN, RESULT, RESPONSE))
    req = plan["requests"]
    if (plan["request_count"] != 1 or len(req) != 1 or req[0]["contract"] != "SM2311"
            or req[0]["expected_dates"] != ["2023-08-28", "2023-08-29", "2023-08-30", "2023-08-31", "2023-09-01"]
            or result["status"] != "completed" or result["plan_sha256"] != plan["plan_sha256"]
            or result["weeks"][0]["reason"] != "PROVIDER_MATCHES_NEITHER"
            or result["attempt"]["responses_saved"] != 1 or result["attempt"]["outcome_unknown"]
            or response["request"] != {k: req[0][k] for k in ("contract", "method", "start", "end", "expected_dates")}):
        raise ValueError("SOURCE_EVIDENCE_INVALID")
    aug, sep, weekpart = partitions(catalog)
    abars, aq = store.read_catalog_partition_quality(aug)
    sbars, sq = store.read_catalog_partition_quality(sep)
    wbars, wq = store.read_catalog_partition_quality(weekpart)
    if aq or sq or wq or len(sbars) != 20 or len(wbars) != 5:
        raise ValueError("PARTITION_QUALITY_OR_ROWS_MOVED")
    expected = tuple(date.fromisoformat(s) for s in req[0]["expected_dates"])
    old_week = [b for b in wbars if b.trading_day == DAY]
    if len(old_week) != 1:
        raise ValueError("WEEK_INVALID")
    daily = tuple(b for b in (*abars, *sbars) if b.trading_day in expected)
    if tuple(b.trading_day for b in sorted(daily, key=lambda b: b.trading_day)) != expected:
        raise ValueError("DAILY_DATES_INVALID")
    provider = _provider_bars_from_response(response, expected_days=expected)
    aligned = _align_provider_bar_ends(provider, daily)
    aug_provider = tuple(b for b in aligned if b.trading_day.month == 8)
    sep_provider = tuple(b for b in aligned if b.trading_day.month == 9)
    if any(a != b for a, b in zip((b for b in abars if b.trading_day in expected), aug_provider)):
        raise ValueError("AUGUST_SOURCE_DRIFT")
    corrected_sep, changed = overlay_provider_turnover(sbars, sep_provider)
    if changed != (DAY,) or next(b.turnover for b in corrected_sep if b.trading_day == DAY) != Decimal("7919564100"):
        raise ValueError("D1_CHANGE_SCOPE_INVALID")
    corrected_week_days = tuple(sorted((*aug_provider, *sep_provider), key=lambda b: b.bar_end))
    new_week = realign_weekly_turnover(old_week[0], corrected_week_days)
    if new_week.turnover != Decimal("24932701700") or old_week[0].turnover == new_week.turnover:
        raise ValueError("W1_CHANGE_SCOPE_INVALID")
    corrected_wbars = tuple(new_week if b.trading_day == DAY else b for b in wbars)
    return (aug, sep, weekpart), (corrected_sep, corrected_wbars)


def packet(session, root, config):
    catalog, store = MarketCatalog(session, root), CanonicalMonthlyStore(root)
    revision = catalog_revision(session, ("sm",), CUTOFF, ("1d", "1w"))
    plan, result = json.loads(PLAN.read_bytes()), json.loads(RESULT.read_bytes())
    if revision != plan["catalog_revision"] or revision != result["catalog_revision"]:
        raise ValueError("CATALOG_REVISION_MOVED")
    old, new = candidates(catalog, store)
    targets = []
    for key, part, bars in ((DKEY, old[1], new[0]), (WKEY, old[2], new[1])):
        digest = candidate_sha(bars)
        targets.append({"frequency": key.frequency.value, "old": identity(part, root),
                        "candidate_sha256": digest,
                        "candidate_uri": (part.file_path.parent.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                        "row_count": len(bars)})
    return {"schema_version": "sm2311_paired_turnover_repair_v1", "code_sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "source_sha256": file_sha(Path(__file__)),
        "catalog_revision": revision, "project_env_sha256": config["config_sha256"],
        "canonical_root_sha256": config["canonical_root_sha256"], "source_plan_sha256": file_sha(PLAN),
        "source_result_sha256": file_sha(RESULT), "source_response_sha256": file_sha(RESPONSE),
        "provider_requests": 0, "writes": 0, "august_evidence": identity(old[0], root),
        "targets": targets}, new


def readback(catalog, store, expected, root):
    old, new = candidates_after(catalog, store)
    for record, part, bars in zip(expected["targets"], (old[1], old[2]), new):
        if identity(part, root)["sha256"] != record["candidate_sha256"] or bars != store.read_catalog_partition(part):
            raise ValueError("CANDIDATE_READBACK_INVALID")


def candidates_after(catalog, store):
    aug, sep, wpart = partitions(catalog)
    abars, aq = store.read_catalog_partition_quality(aug)
    sbars, sq = store.read_catalog_partition_quality(sep)
    wbars, wq = store.read_catalog_partition_quality(wpart)
    if aq or sq or wq:
        raise ValueError("QUALITY_MOVED")
    days = tuple(b for b in (*abars, *sbars) if date(2023, 8, 28) <= b.trading_day <= DAY)
    week = next(b for b in wbars if b.trading_day == DAY)
    if realign_weekly_turnover(week, days) != week:
        raise ValueError("D1_W1_CONFLICT_REMAINS")
    return (aug, sep, wpart), (sbars, wbars)


def main():
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("mode", choices=("prepare", "dry-run", "inspect", "apply"))
    ap.add_argument("--expected-prepared-sha256")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply != (args.mode == "apply"):
        raise ValueError("APPLY_FLAG_INVALID")
    settings, config = load_private_readonly_settings(ENV)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        if args.mode == "prepare":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                data, _ = packet(session, root, config)
                session.rollback()
            raw = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            PREPARED.write_bytes(raw)
            print(json.dumps({"status": "prepared", "sha256": sha(raw), "partitions": 2}))
            return
        raw = PREPARED.read_bytes()
        if sha(raw) != args.expected_prepared_sha256:
            raise ValueError("PREPARED_SHA256_MISMATCH")
        fixed = json.loads(raw)
        if (fixed["schema_version"] != "sm2311_paired_turnover_repair_v1"
                or fixed["source_sha256"] != file_sha(Path(__file__))
                or fixed["project_env_sha256"] != config["config_sha256"]
                or fixed["canonical_root_sha256"] != config["canonical_root_sha256"]
                or fixed["provider_requests"] != 0 or fixed["writes"] != 0):
            raise ValueError("PACKET_IDENTITY_INVALID")
        if args.mode == "inspect":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                catalog = MarketCatalog(session, root)
                parts = partitions(catalog)
                states = []
                for record, part in zip(fixed["targets"], parts[1:]):
                    observed = identity(part, root)
                    states.append("old" if observed == record["old"] else
                                  "candidate" if observed["sha256"] == record["candidate_sha256"] and observed["uri"] == record["candidate_uri"] else "other")
                session.rollback()
            print(json.dumps({"status": states[0] if len(set(states)) == 1 else "mixed_or_unknown", "states": states}))
            return
        if args.mode == "dry-run":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                fresh, _ = packet(session, root, config)
                if fresh != fixed:
                    raise ValueError("DRY_RUN_DRIFT")
                session.rollback()
            print(json.dumps({"status": "dry_run_passed", "sha256": sha(raw), "writes": 0}))
            return
        with Session(engine, autoflush=False) as session:
            catalog = MarketCatalog(session, root)
            lease = catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError("MAINTENANCE_LOCK_UNAVAILABLE")
            committed = False
            try:
                fresh, new = packet(session, root, config)
                if fresh != fixed:
                    raise ValueError("APPLY_DRIFT")
                store = CanonicalMonthlyStore(root)
                MarketHomeProjectionStore(market_home_projection_path(root)).invalidate()
                for record, key, bars in zip(fixed["targets"], (DKEY, WKEY), new):
                    part = store.publish(PublishRequest(key, 2023, 9, bars, tuple(b.bar_end for b in bars)))
                    if part.parquet_path.relative_to(root).as_posix() != record["candidate_uri"] or file_sha(part.parquet_path) != record["candidate_sha256"]:
                        raise ValueError("PUBLISHED_CANDIDATE_INVALID")
                    catalog.register_partition(part)
                readback(catalog, store, fixed, root)
                try:
                    session.commit()
                except Exception as exc:
                    raise ValueError("COMMIT_OUTCOME_UNKNOWN") from exc
                committed = True
            finally:
                if not committed:
                    session.rollback()
                lease.release()
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            readback(MarketCatalog(session, root), CanonicalMonthlyStore(root), fixed, root)
            session.rollback()
        print(json.dumps({"status": "committed", "sha256": sha(raw), "partitions": 2, "readback": "passed"}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc) if type(exc) is ValueError else type(exc).__name__}))
        raise SystemExit(1)
