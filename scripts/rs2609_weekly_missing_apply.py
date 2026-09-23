"""Apply or inspect the pinned RS2609 four-week W1 batch without provider access.

Apply changes three W1 month pointers in one locked Catalog transaction. A
commit uncertainty stops the command; inspect from a new process resolves it.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest, PublishedPartition
from app.market_data import rqdata_adapter
from app.market_data.rqdata_adapter import WEEKLY_AGGREGATION_VERSION
from app.market_data.weekly_quality import WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2
from app.models import MarketPartition
from scripts import rs2609_weekly_missing_plan as planner
from scripts.newow_weekly_recovery import load_private_readonly_settings

EXPECTED_PACKET_SHA256 = "3d4a57ed87bc68904a2724be847214fceab798deaf0de8bdb4403823fcf29a26"
EXPECTED_MONTHS = ((2025, 9), (2025, 12), (2026, 1))
EXPECTED_D1_MONTHS = EXPECTED_MONTHS
EXPECTED_ADDITIONS = {
    (2025, 9): ("2025-09-30",),
    (2025, 12): ("2025-12-31",),
    (2026, 1): ("2026-01-09", "2026-01-16"),
}
FIELDS = planner.FIELDS


class RSApplyError(ValueError):
    pass


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _w1_key() -> DatasetKey:
    return DatasetKey("contract", "rs", "RS2609", "1w")


def _d1_key() -> DatasetKey:
    return DatasetKey("contract", "rs", "RS2609", "1d")


def _validate_scope(packet: dict[str, Any], root: Path) -> None:
    if (_sha(planner._json(packet)) != EXPECTED_PACKET_SHA256
            or packet.get("schema_version") != "rs2609_missing_w1_plan_v1"
            or packet.get("contract") != "RS2609" or packet.get("symbol") != "rs"
            or packet.get("cutoff") != planner.CUTOFF.isoformat()
            or packet.get("through") != planner.THROUGH.isoformat()
            or packet.get("aggregation_version") != WEEKLY_AGGREGATION_VERSION
            or packet.get("weekly_classification_version") != WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2
            or packet.get("canonical_root_sha256") != _sha(str(root).encode())
            or packet.get("planner_source_sha256") != _sha(Path(planner.__file__).read_bytes())
            or packet.get("aggregation_source_sha256") != _sha(Path(rqdata_adapter.__file__).read_bytes())
            or packet.get("provider_requests") != 0 or packet.get("production_writes") != 0):
        raise RSApplyError("PREPARED_SCOPE_INVALID")
    weeks = packet.get("weeks")
    months = packet.get("months")
    d1_images = packet.get("d1_preimages")
    if (not isinstance(weeks, list) or len(weeks) != 4
            or [item.get("trading_day") for item in weeks]
            != [day.isoformat() for day in planner.MISSING_DAYS]
            or not isinstance(months, list) or len(months) != 3
            or [(item.get("year"), item.get("month")) for item in months]
            != list(EXPECTED_MONTHS)
            or not isinstance(d1_images, list)
            or [(item.get("year"), item.get("month")) for item in d1_images]
            != list(EXPECTED_D1_MONTHS)):
        raise RSApplyError("PREPARED_SCOPE_INVALID")
    for record in months:
        key = record["year"], record["month"]
        base = ("kind=contract/symbol=rs/series=RS2609/frequency=1w/"
                f"year={key[0]}/month={key[1]:02d}/")
        digest = record.get("candidate_sha256")
        if (record.get("added_days") != list(EXPECTED_ADDITIONS[key])
                or not _digest(digest)
                or record.get("candidate_uri") != base + f"part.{digest}.parquet"):
            raise RSApplyError("PREPARED_SCOPE_INVALID")
        if key == (2026, 1):
            old = record.get("old")
            if (not isinstance(old, dict) or old.get("uri") != base + "part.parquet"
                    or not _digest(old.get("sha256"))
                    or record.get("old_count") != 1 or record.get("new_count") != 3
                    or record.get("retained_days") != ["2026-01-30"]):
                raise RSApplyError("PREPARED_SCOPE_INVALID")
        elif (record.get("old") is not None or record.get("old_count") != 0
              or record.get("new_count") != 1 or record.get("retained_days") != []):
            raise RSApplyError("PREPARED_SCOPE_INVALID")


def _checked_path(root: Path, relative: str, digest: str) -> Path:
    path = Path(relative)
    if (path.is_absolute() or ".." in path.parts or not _digest(digest)):
        raise RSApplyError("PREIMAGE_URI_INVALID")
    absolute = root / path
    if (absolute.is_symlink() or not absolute.resolve().is_relative_to(root.resolve())
            or _sha(absolute.read_bytes()) != digest):
        raise RSApplyError("PREIMAGE_MOVED")
    return absolute


def _old_partition(root: Path, record: dict[str, Any]) -> CatalogPartition | None:
    image = record["old"]
    if image is None:
        return None
    path = _checked_path(root, image["uri"], image["sha256"])
    if image["quality_sha256"] is not None:
        raise RSApplyError("OLD_W1_QUALITY_INVALID")
    return CatalogPartition(
        _w1_key(), record["year"], record["month"],
        datetime.fromisoformat(image["coverage_start"]) if image["coverage_start"] else None,
        datetime.fromisoformat(image["coverage_end"]) if image["coverage_end"] else None,
        path, image["row_count"],
        datetime.fromisoformat(image["source_coverage_start"])
        if image["source_coverage_start"] else None,
        datetime.fromisoformat(image["source_coverage_end"])
        if image["source_coverage_end"] else None,
    )


def _candidate_bars(root: Path, store: CanonicalMonthlyStore,
                    packet: dict[str, Any], record: dict[str, Any]) -> tuple[CanonicalBar, ...]:
    key = record["year"], record["month"]
    additions: list[CanonicalBar] = []
    for week in packet["weeks"]:
        day = date.fromisoformat(week["trading_day"])
        if (day.year, day.month) != key:
            continue
        values = week["candidate_w1"]
        additions.append(CanonicalBar(
            datetime.fromisoformat(week["bar_end"]), day,
            *(Decimal(values[field]) for field in FIELDS),
        ))
    old = _old_partition(root, record)
    previous = store.read_catalog_partition(old) if old else ()
    if [bar.trading_day.isoformat() for bar in previous] != record["retained_days"]:
        raise RSApplyError("OLD_W1_ROWS_MOVED")
    candidate = tuple(sorted((*previous, *additions), key=lambda bar: bar.bar_end))
    if (len(candidate) != record["new_count"]
            or len({bar.bar_end for bar in candidate}) != len(candidate)
            or [bar.trading_day.isoformat() for bar in additions] != record["added_days"]
            or planner._candidate_sha(candidate) != record["candidate_sha256"]):
        raise RSApplyError("CANDIDATE_IDENTITY_INVALID")
    store._validate(PublishRequest(_w1_key(), key[0], key[1], candidate,
                                   tuple(bar.bar_end for bar in candidate)))
    return candidate


def _active_month(catalog: MarketCatalog, year: int, month: int) -> CatalogPartition | None:
    selected = tuple(part for part in catalog.all_partitions(_w1_key())
                     if (part.year, part.month) == (year, month))
    if len(selected) > 1:
        raise RSApplyError("W1_POINTER_DUPLICATE")
    return selected[0] if selected else None


def _candidate_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {"year": record["year"], "month": record["month"],
            "uri": record["candidate_uri"], "sha256": record["candidate_sha256"],
            "quality_sha256": None, "row_count": record["new_count"],
            "coverage_start": record["candidate_coverage_start"],
            "coverage_end": record["candidate_coverage_end"],
            "source_coverage_start": record["candidate_coverage_start"],
            "source_coverage_end": record["candidate_coverage_end"]}


def inspect(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    _validate_scope(packet, root)
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    current_d1 = {(part.year, part.month): part for part in catalog.all_partitions(_d1_key())}
    for image in packet["d1_preimages"]:
        key = image["year"], image["month"]
        part = current_d1.get(key)
        if part is None or planner._identity(part, root) != image:
            raise RSApplyError("D1_PREIMAGE_MOVED")
    states: list[str] = []
    for record in packet["months"]:
        part = _active_month(catalog, record["year"], record["month"])
        actual = planner._identity(part, root) if part else None
        if actual == record["old"]:
            states.append("old")
        elif actual == _candidate_identity(record):
            expected = _candidate_bars(root, store, packet, record)
            states.append("candidate" if store.read_catalog_partition(part) == expected else "other")
        else:
            states.append("other")
    status = ("candidate" if all(state == "candidate" for state in states)
              else "old" if all(state == "old" for state in states) else "mixed_or_unknown")
    return {"status": status, "months": states}


def _require_candidate_replay(catalog: MarketCatalog, store: CanonicalMonthlyStore) -> dict[str, Any]:
    mds = MarketDataService(catalog, store)
    expected = mds.expected_contract_replay_endpoints(
        symbol="rs", contract="RS2609", frequency=BarFrequency.W1,
        trading_day=planner.THROUGH, cutoff=planner.CUTOFF)
    cutoff = next((end for end, day in expected if day == planner.THROUGH), None)
    if cutoff is None:
        raise RSApplyError("REPLAY_CUTOFF_MOVED")
    bars, interruptions = mds.query_contract_weekly_replay_quality(
        symbol="rs", contract="RS2609", through=planner.THROUGH,
        cutoff=cutoff, classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
    if (len(bars) != 33 or len(interruptions) != 18
            or not set(planner.MISSING_DAYS).issubset({bar.trading_day for bar in bars})):
        raise RSApplyError("CANDIDATE_REPLAY_INVALID")
    return {"normal_bars": len(bars), "quality_interruptions": len(interruptions)}


def apply(session: Session, root: Path, root_sha256: str,
          packet: dict[str, Any]) -> dict[str, Any]:
    _validate_scope(packet, root)
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise RSApplyError("MAINTENANCE_BUSY")
    committed = False
    try:
        current = planner.prepare(session, root, root_sha256)
        if current != packet or inspect(session, root, packet)["status"] != "old":
            raise RSApplyError("PREPARE_IDENTITY_MOVED")
        store = CanonicalMonthlyStore(root)
        for record in packet["months"]:
            bars = _candidate_bars(root, store, packet, record)
            published = store.publish(PublishRequest(
                _w1_key(), record["year"], record["month"], bars,
                tuple(bar.bar_end for bar in bars)))
            if (published.parquet_path.relative_to(root).as_posix() != record["candidate_uri"]
                    or published.row_count != record["new_count"]
                    or published.source_quality_sha256 is not None
                    or published.coverage_start is None or published.coverage_end is None
                    or published.coverage_start.isoformat() != record["candidate_coverage_start"]
                    or published.coverage_end.isoformat() != record["candidate_coverage_end"]
                    or published.source_coverage_start != published.coverage_start
                    or published.source_coverage_end != published.coverage_end):
                raise RSApplyError("CANDIDATE_PUBLICATION_INVALID")
            catalog.register_partition(published)
        if inspect(session, root, packet)["status"] != "candidate":
            raise RSApplyError("CANDIDATE_POINTER_READBACK_INVALID")
        replay = _require_candidate_replay(catalog, store)
        try:
            session.commit()
        except Exception as exc:
            raise RSApplyError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "committed", "months": 3, "weeks": 4, "replay": replay}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def restore(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Controlled incident recovery only; never invoked automatically by apply."""
    _validate_scope(packet, root)
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise RSApplyError("MAINTENANCE_BUSY")
    committed = False
    try:
        if inspect(session, root, packet)["status"] != "candidate":
            raise RSApplyError("RESTORE_POINTERS_MOVED")
        dataset = catalog.dataset_row(_w1_key())
        if dataset is None:
            raise RSApplyError("RESTORE_DATASET_MISSING")
        for record in packet["months"]:
            if record["old"] is None:
                rows = session.scalars(select(MarketPartition).where(
                    MarketPartition.dataset_id == dataset.id,
                    MarketPartition.year == record["year"],
                    MarketPartition.month == record["month"])).all()
                if len(rows) != 1:
                    raise RSApplyError("RESTORE_POINTERS_MOVED")
                session.delete(rows[0])
                session.flush()
            else:
                old = _old_partition(root, record)
                assert old is not None
                catalog.register_partition(PublishedPartition(
                    _w1_key(), old.year, old.month, old.file_path,
                    old.coverage_start, old.coverage_end, old.row_count,
                    old.source_coverage_start, old.source_coverage_end,
                ))
        if inspect(session, root, packet)["status"] != "old":
            raise RSApplyError("RESTORE_READBACK_INVALID")
        try:
            session.commit()
        except Exception as exc:
            raise RSApplyError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "restored", "months": 3}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("inspect", "apply", "restore"):
        command = modes.add_parser(mode)
        command.add_argument("--project-env", type=Path, required=True)
        command.add_argument("--prepared", type=Path, required=True)
        command.add_argument("--expected-prepared-sha256", required=True)
        if mode in ("apply", "restore"):
            command.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    content = args.prepared.read_bytes()
    if (args.expected_prepared_sha256 != EXPECTED_PACKET_SHA256
            or _sha(content) != EXPECTED_PACKET_SHA256):
        raise RSApplyError("PREPARED_HASH_MISMATCH")
    packet = json.loads(content)
    settings, identity = load_private_readonly_settings(args.project_env)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    _validate_scope(packet, root)
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as readback:
            readback.execute(text("SET TRANSACTION READ ONLY"))
            before = inspect(readback, root, packet)
            readback.rollback()
        if args.mode == "inspect":
            result = {"readback": before}
            if before["status"] == "candidate":
                with Session(engine, autoflush=False) as readback:
                    readback.execute(text("SET TRANSACTION READ ONLY"))
                    result["replay"] = _require_candidate_replay(
                        MarketCatalog(readback, root), CanonicalMonthlyStore(root))
                    readback.rollback()
            print(json.dumps(result, sort_keys=True))
        elif args.mode == "apply" and before["status"] == "candidate":
            print(json.dumps({"status": "already_applied", "readback": before}, sort_keys=True))
        elif args.mode == "restore" and before["status"] == "old":
            print(json.dumps({"status": "already_restored", "readback": before}, sort_keys=True))
        else:
            expected = "old" if args.mode == "apply" else "candidate"
            if before["status"] != expected:
                raise RSApplyError("ACTIVE_POINTERS_MIXED_OR_UNKNOWN")
            with Session(engine, autoflush=False) as session:
                outcome = (apply(session, root, identity["canonical_root_sha256"], packet)
                           if args.mode == "apply" else restore(session, root, packet))
            with Session(engine, autoflush=False) as readback:
                readback.execute(text("SET TRANSACTION READ ONLY"))
                after = inspect(readback, root, packet)
                if after["status"] != ("candidate" if args.mode == "apply" else "old"):
                    raise RSApplyError("COMMIT_READBACK_FAILED")
                if args.mode == "apply":
                    outcome["replay"] = _require_candidate_replay(
                        MarketCatalog(readback, root), CanonicalMonthlyStore(root))
                readback.rollback()
            print(json.dumps({**outcome, "readback": after}, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RSApplyError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "RS2609_APPLY_FAILED"}))
        raise SystemExit(1) from None
