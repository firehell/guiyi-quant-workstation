"""Inspect or apply one pinned RS W1 no-trade repair packet.

Apply is an external data mutation and requires separate owner authorization.
No provider client is constructed. The approved packet is recomputed from D1
under the maintenance lease before any Canonical file is published.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data import rqdata_adapter
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from scripts.newow_weekly_recovery import load_private_readonly_settings

import rs_no_trade_prepare_current as preparation


class RSRepairError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(root: Path, uri: str) -> Path:
    relative = Path(uri)
    if relative.is_absolute() or ".." in relative.parts:
        raise RSRepairError("PARTITION_URI_INVALID")
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RSRepairError("PARTITION_PATH_INVALID")
    return path


def _partition(catalog: MarketCatalog, record: dict):
    key = DatasetKey("contract", "rs", record["contract"], "1w")
    found = tuple(
        part for part in catalog.all_partitions(key)
        if (part.year, part.month) == (record["year"], record["month"])
    )
    if len(found) != 1:
        raise RSRepairError("W1_PARTITION_IDENTITY_INVALID")
    return key, found[0]


def inspect(session: Session, root: Path, packet: dict) -> dict:
    catalog = MarketCatalog(session, root)
    states = []
    for record in packet["months"]:
        for source in record["d1_preimages"]:
            path = _safe_path(root, source["uri"])
            if _sha(path) != source["sha256"]:
                raise RSRepairError("D1_PREIMAGE_MOVED")
            daily_key = DatasetKey("contract", "rs", record["contract"], "1d")
            selected = tuple(
                part for part in catalog.all_partitions(daily_key)
                if (part.year, part.month) == (source["year"], source["month"])
            )
            if (len(selected) != 1
                    or selected[0].file_path != path
                    or selected[0].source_quality_sha256 != source["quality_sha256"]):
                raise RSRepairError("D1_ACTIVE_POINTER_MOVED")
        _, part = _partition(catalog, record)
        uri = part.file_path.relative_to(root).as_posix()
        digest = _sha(part.file_path)
        old = record["old_partition"]
        if uri == old["uri"] and digest == old["sha256"]:
            states.append("old")
        elif uri == record["candidate_uri"] and digest == record["candidate_sha256"]:
            states.append("candidate")
        else:
            states.append("other")
    status = "candidate" if all(item == "candidate" for item in states) else (
        "old" if all(item == "old" for item in states) else "mixed_or_unknown"
    )
    return {"status": status, "old_count": states.count("old"),
            "candidate_count": states.count("candidate"), "other_count": states.count("other")}


def _candidate(store: CanonicalMonthlyStore, part, record: dict):
    changes = {row["week_end"]: row for row in record["diffs"]}
    if len(changes) != record["changed_rows"]:
        raise RSRepairError("W1_TARGET_COUNT_INVALID")
    old_bars = store.read_catalog_partition(part)
    result = []
    for bar in old_bars:
        diff = changes.pop(bar.trading_day.isoformat(), None)
        if diff is not None:
            if any(str(getattr(bar, field)) != value for field, value in diff["old"].items()):
                raise RSRepairError("W1_OLD_ROW_MOVED")
            bar = replace(bar, **{field: Decimal(value) for field, value in diff["new"].items()})
        result.append(bar)
    candidate = tuple(result)
    if (changes or len(candidate) != record["changed_rows"] + record["retained_rows"]
            or preparation.candidate_sha(candidate) != record["candidate_sha256"]):
        raise RSRepairError("W1_CANDIDATE_INVALID")
    return candidate


def _recompute_packet(packet_bytes: bytes) -> None:
    packet = json.loads(packet_bytes)
    if _sha(Path(preparation.__file__)) != packet["source_sha256"]:
        raise RSRepairError("PREPARE_SOURCE_MOVED")
    if _sha(Path(__file__)) != packet["repair_source_sha256"]:
        raise RSRepairError("REPAIR_SOURCE_MOVED")
    if _sha(Path(rqdata_adapter.__file__)) != packet["aggregation_source_sha256"]:
        raise RSRepairError("AGGREGATION_SOURCE_MOVED")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    if head != packet["code_sha"]:
        raise RSRepairError("CODE_HEAD_MOVED")
    original_here = preparation.HERE
    try:
        with tempfile.TemporaryDirectory(prefix="guiyi-rs-prepare-") as temporary:
            preparation.HERE = Path(temporary)
            preparation.main()
            fresh = (Path(temporary) / "rs-no-trade-prepare.json").read_bytes()
    finally:
        preparation.HERE = original_here
    if fresh != packet_bytes:
        raise RSRepairError("PREPARE_IDENTITY_MOVED")


def apply(session: Session, root: Path, packet: dict, packet_bytes: bytes) -> dict:
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise RSRepairError("MAINTENANCE_BUSY")
    committed = False
    try:
        _recompute_packet(packet_bytes)
        state = inspect(session, root, packet)
        if state["status"] != "old":
            raise RSRepairError("ACTIVE_POINTERS_NOT_ALL_OLD")
        revision = catalog_revision(session, ("rs",), date(2026, 9, 18), ("1d", "1w"))
        if revision != packet["catalog_revision"]:
            raise RSRepairError("CATALOG_REVISION_MOVED")
        store = CanonicalMonthlyStore(root)
        for record in packet["months"]:
            key, part = _partition(catalog, record)
            candidate = _candidate(store, part, record)
            published = store.publish(PublishRequest(
                key, record["year"], record["month"], candidate,
                tuple(bar.bar_end for bar in candidate),
            ))
            if (published.parquet_path.relative_to(root).as_posix() != record["candidate_uri"]
                    or _sha(published.parquet_path) != record["candidate_sha256"]):
                raise RSRepairError("PUBLISHED_CANDIDATE_MISMATCH")
            catalog.register_partition(published)
            day = date.fromisoformat(record["diffs"][-1]["week_end"])
            cutoff = next(bar.bar_end for bar in candidate if bar.trading_day == day)
            bars, interruptions = MarketDataService(catalog, store).query_contract_weekly_replay_quality(
                symbol="rs", contract=record["contract"], through=day, cutoff=cutoff,
                classification_version="weekly-d1-quality-v2",
            )
            target_days = {date.fromisoformat(row["week_end"]) for row in record["diffs"]}
            if (not target_days.issubset({bar.trading_day for bar in bars})
                    or {day.isocalendar()[:2] for day in target_days}.intersection(
                        {(item.iso_year, item.iso_week) for item in interruptions}
                    )):
                raise RSRepairError("W1_TARGET_READBACK_INVALID")
        try:
            session.commit()
        except Exception as exc:
            raise RSRepairError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "committed", "month_count": len(packet["months"]),
                "week_count": packet["week_count"]}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument("mode", choices=("inspect", "dry-run", "apply"))
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--expected-prepared-sha256", required=True)
    parser.add_argument("--project-env", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.mode == "apply" and not args.apply:
        raise RSRepairError("EXPLICIT_APPLY_REQUIRED")
    if args.mode != "apply" and args.apply:
        raise RSRepairError("READ_ONLY_MODE_CANNOT_APPLY")
    content = args.prepared.read_bytes()
    if hashlib.sha256(content).hexdigest() != args.expected_prepared_sha256:
        raise RSRepairError("PREPARED_HASH_MISMATCH")
    packet = json.loads(content)
    if (packet["schema_version"] != "rs_weekly_no_trade_prepare_v1"
            or packet["month_count"] != 64 or packet["week_count"] != 133
            or len(packet["months"]) != 64 or packet["provider_requests"] != 0):
        raise RSRepairError("PREPARED_SCOPE_INVALID")
    expected_env = Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    if args.project_env.resolve(strict=True) != expected_env.resolve(strict=True):
        raise RSRepairError("PROJECT_ENV_PATH_INVALID")
    settings, identity = load_private_readonly_settings(args.project_env)
    if (identity["canonical_root_sha256"] != packet["canonical_root_sha256"]
            or identity["config_sha256"] != packet["project_env_sha256"]):
        raise RSRepairError("PROJECT_ENV_MOVED")
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        if args.mode != "apply":
            if args.mode == "dry-run":
                _recompute_packet(content)
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                result = inspect(session, root, packet)
                if args.mode == "dry-run":
                    if result["status"] != "old":
                        raise RSRepairError("ACTIVE_POINTERS_NOT_ALL_OLD")
                    catalog = MarketCatalog(session, root)
                    store = CanonicalMonthlyStore(root)
                    for record in packet["months"]:
                        _, part = _partition(catalog, record)
                        _candidate(store, part, record)
                    result["validated_months"] = len(packet["months"])
                    result["validated_weeks"] = packet["week_count"]
                session.rollback()
        else:
            with Session(engine, autoflush=False) as session:
                result = apply(session, root, packet, content)
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                result["readback"] = inspect(session, root, packet)
                session.rollback()
            if result["readback"]["status"] != "candidate":
                raise RSRepairError("COMMIT_READBACK_FAILED")
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RSRepairError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "RS_REPAIR_FAILED"}))
        raise SystemExit(1) from None
