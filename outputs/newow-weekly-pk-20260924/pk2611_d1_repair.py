"""Exact PK2611 August 2026 D1 turnover repair from one captured source response."""

import argparse
from datetime import date
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
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from scripts.newow_weekly_d1_then_w1_repair import (
    _align_provider_bar_ends, _provider_bars_from_response,
    overlay_provider_turnover, require_w1_matches_corrected_week,
)
from scripts.newow_weekly_recovery import load_private_readonly_settings

HERE = Path(__file__).parent
ENV = Path.home() / "Library/Application Support/GuiyiQuant/project.env"
RESPONSE = HERE / "source-attempts/pk2611-20260814-001/source-response-0001.json"
PLAN = HERE / "pk2611-20260814-source-plan.json"
RESULT = HERE / "pk2611-source-result.json"
PREPARED = HERE / "pk2611-d1-prepare.json"
KEY = DatasetKey("contract", "pk", "PK2611", "1d")
WKEY = DatasetKey("contract", "pk", "PK2611", "1w")
CUTOFF = date(2026, 9, 18)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def candidate_sha(bars) -> str:
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
                   sink, compression="zstd", use_dictionary=False, version="2.6")
    return sha(sink.getvalue().to_pybytes())


def part_identity(part, root: Path) -> dict:
    path = part.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("PARTITION_PATH_INVALID")
    return {"uri": path.relative_to(root).as_posix(), "sha256": file_sha(path),
            "year": part.year, "month": part.month, "row_count": part.row_count,
            "quality_sha256": part.source_quality_sha256}


def target_parts(catalog):
    d1 = [part for part in catalog.all_partitions(KEY) if (part.year, part.month) == (2026, 8)]
    w1 = [part for part in catalog.all_partitions(WKEY) if (part.year, part.month) == (2026, 8)]
    if len(d1) != 1 or len(w1) != 1:
        raise ValueError("TARGET_PARTITION_INVALID")
    return d1[0], w1[0]


def candidate(catalog, store):
    plan = json.loads(PLAN.read_bytes())
    result = json.loads(RESULT.read_bytes())
    if (plan["request_count"] != 1 or plan["requests"][0]["contract"] != "PK2611"
            or plan["requests"][0]["expected_dates"] != [f"2026-08-{day:02d}" for day in range(10, 15)]
            or result["status"] != "completed"
            or result["plan_sha256"] != plan["plan_sha256"]
            or result["weeks"][0]["repair_target"] != "D1_THEN_W1"
            or result["attempt"]["responses_saved"] != 1
            or result["attempt"]["outcome_unknown"] is not False):
        raise ValueError("SOURCE_VERIFICATION_INVALID")
    response = json.loads(RESPONSE.read_bytes())
    request = response["request"]
    if request != {key: plan["requests"][0][key] for key in ("contract", "method", "start", "end", "expected_dates")}:
        raise ValueError("SOURCE_REQUEST_MISMATCH")
    expected_days = tuple(date.fromisoformat(value) for value in request["expected_dates"])
    d1, w1 = target_parts(catalog)
    old, quality = store.read_catalog_partition_quality(d1)
    weekly, wquality = store.read_catalog_partition_quality(w1)
    if quality or wquality:
        raise ValueError("TARGET_QUALITY_PRESENT")
    provider = _align_provider_bar_ends(_provider_bars_from_response(response, expected_days=expected_days), old)
    new, changed = overlay_provider_turnover(old, provider)
    if not changed or not set(changed).issubset(set(expected_days)):
        raise ValueError("D1_CHANGE_SCOPE_INVALID")
    matching = [bar for bar in weekly if bar.trading_day == date(2026, 8, 14)]
    if len(matching) != 1:
        raise ValueError("W1_TARGET_INVALID")
    require_w1_matches_corrected_week(matching[0], tuple(bar for bar in new if bar.trading_day in expected_days))
    return d1, w1, new, changed


def build_packet(session, root, identity):
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    revision = catalog_revision(session, ("pk",), CUTOFF, ("1d", "1w"))
    plan = json.loads(PLAN.read_bytes())
    result = json.loads(RESULT.read_bytes())
    if revision != plan["catalog_revision"] or revision != result["catalog_revision"]:
        raise ValueError("SOURCE_CATALOG_REVISION_MOVED")
    d1, w1, new, changed = candidate(catalog, store)
    digest = candidate_sha(new)
    return {
        "schema_version": "pk2611_august_d1_turnover_repair_v1",
        "code_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
        "source_sha256": file_sha(Path(__file__)),
        "catalog_revision": revision,
        "canonical_root_sha256": identity["canonical_root_sha256"],
        "project_env_sha256": identity["config_sha256"],
        "source_plan_sha256": file_sha(PLAN),
        "source_result_sha256": file_sha(RESULT),
        "source_response_sha256": file_sha(RESPONSE),
        "provider_requests": 0, "writes": 0,
        "contract": "PK2611", "frequency": "1d", "year": 2026, "month": 8,
        "old_partition": part_identity(d1, root),
        "weekly_evidence": part_identity(w1, root),
        "candidate_sha256": digest,
        "candidate_uri": (d1.file_path.parent.relative_to(root) / f"part.{digest}.parquet").as_posix(),
        "changed_days": [day.isoformat() for day in changed],
        "corrected_turnovers": {day.isoformat(): str(next(bar.turnover for bar in new if bar.trading_day == day))
                                for day in changed},
        "row_count": len(new),
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("mode", choices=("prepare", "dry-run", "inspect", "apply"))
    parser.add_argument("--expected-prepared-sha256")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply != (args.mode == "apply"):
        raise ValueError("APPLY_FLAG_INVALID")
    if ENV.resolve(strict=True) != (Path.home() / "Library/Application Support/GuiyiQuant/project.env").resolve(strict=True):
        raise ValueError("PROJECT_ENV_PATH_INVALID")
    settings, identity = load_private_readonly_settings(ENV)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        if args.mode == "prepare":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                packet = build_packet(session, root, identity)
                session.rollback()
            content = (json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            PREPARED.write_bytes(content)
            print(json.dumps({"status": "prepared", "sha256": sha(content),
                              "changed_days": packet["changed_days"], "partitions": 1}))
            return
        content = PREPARED.read_bytes()
        if sha(content) != args.expected_prepared_sha256:
            raise ValueError("PREPARED_SHA256_MISMATCH")
        packet = json.loads(content)
        if (packet["schema_version"] != "pk2611_august_d1_turnover_repair_v1"
                or packet["contract"] != "PK2611" or packet["frequency"] != "1d"
                or (packet["year"], packet["month"]) != (2026, 8)
                or packet["provider_requests"] != 0 or packet["writes"] != 0
                or packet["source_sha256"] != file_sha(Path(__file__))
                or packet["project_env_sha256"] != identity["config_sha256"]
                or packet["canonical_root_sha256"] != identity["canonical_root_sha256"]):
            raise ValueError("PACKET_IDENTITY_INVALID")
        if args.mode == "inspect":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                catalog = MarketCatalog(session, root)
                d1, w1 = target_parts(catalog)
                observed = part_identity(d1, root)
                observed_w1 = part_identity(w1, root)
                observed_revision = catalog_revision(session, ("pk",), CUTOFF, ("1d", "1w"))
                state = ("old" if observed == packet["old_partition"] else
                         "candidate" if observed["uri"] == packet["candidate_uri"]
                         and observed["sha256"] == packet["candidate_sha256"] else "other")
                if observed_w1 != packet["weekly_evidence"]:
                    state = "other"
                session.rollback()
            print(json.dumps({"status": state,
                              "prepared_catalog_revision": packet["catalog_revision"],
                              "observed_catalog_revision": observed_revision,
                              "observed_sha256": observed["sha256"]}))
            return
        with Session(engine, autoflush=False) as session:
            if args.mode == "dry-run":
                session.execute(text("SET TRANSACTION READ ONLY"))
                fresh = build_packet(session, root, identity)
                if fresh != packet:
                    raise ValueError("DRY_RUN_DRIFT")
                session.rollback()
                print(json.dumps({"status": "dry_run_passed", "sha256": sha(content),
                                  "changed_days": len(packet["changed_days"]), "writes": 0}))
                return
            catalog = MarketCatalog(session, root)
            lease = catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError("MAINTENANCE_LOCK_UNAVAILABLE")
            committed = False
            try:
                fresh = build_packet(session, root, identity)
                if fresh != packet:
                    raise ValueError("APPLY_DRIFT")
                store = CanonicalMonthlyStore(root)
                d1, w1, new, changed = candidate(catalog, store)
                if (part_identity(d1, root) != packet["old_partition"]
                        or part_identity(w1, root) != packet["weekly_evidence"]
                        or candidate_sha(new) != packet["candidate_sha256"]
                        or [day.isoformat() for day in changed] != packet["changed_days"]):
                    raise ValueError("APPLY_PREIMAGE_MISMATCH")
                MarketHomeProjectionStore(market_home_projection_path(root)).invalidate()
                published = store.publish(PublishRequest(KEY, 2026, 8, new,
                                                         tuple(bar.bar_end for bar in new)))
                if (published.parquet_path.relative_to(root).as_posix() != packet["candidate_uri"]
                        or file_sha(published.parquet_path) != packet["candidate_sha256"]):
                    raise ValueError("PUBLISHED_CANDIDATE_INVALID")
                catalog.register_partition(published)
                staged_d1, staged_w1 = target_parts(catalog)
                staged_bars, staged_quality = store.read_catalog_partition_quality(staged_d1)
                staged_week = next(bar for bar in store.read_catalog_partition(staged_w1)
                                   if bar.trading_day == date(2026, 8, 14))
                target_days = {date.fromisoformat(value) for value in
                               json.loads(PLAN.read_bytes())["requests"][0]["expected_dates"]}
                if (part_identity(staged_d1, root)["sha256"] != packet["candidate_sha256"]
                        or staged_quality or len(staged_bars) != len(new)):
                    raise ValueError("PRECOMMIT_D1_READBACK_INVALID")
                require_w1_matches_corrected_week(
                    staged_week, tuple(bar for bar in staged_bars if bar.trading_day in target_days)
                )
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
            catalog = MarketCatalog(session, root)
            store = CanonicalMonthlyStore(root)
            d1, w1 = target_parts(catalog)
            bars, quality = store.read_catalog_partition_quality(d1)
            week_bars = store.read_catalog_partition(w1)
            week = next(bar for bar in week_bars if bar.trading_day == date(2026, 8, 14))
            days = {date.fromisoformat(value) for value in json.loads(PLAN.read_bytes())["requests"][0]["expected_dates"]}
            require_w1_matches_corrected_week(week, tuple(bar for bar in bars if bar.trading_day in days))
            if (part_identity(d1, root)["sha256"] != packet["candidate_sha256"]
                    or len(bars) != packet["row_count"] or quality):
                raise ValueError("POST_COMMIT_READBACK_INVALID")
            session.rollback()
        print(json.dumps({"status": "committed", "sha256": sha(content),
                          "d1_partitions": 1, "changed_days": packet["changed_days"],
                          "w1_writes": 0, "readback": "passed"}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
