"""Rebuild the pinned OI2611 missing W1 prefix from Catalog-selected local D1.

Prepare is read only. Apply requires an exact packet digest and an explicit
``--apply``; it never contacts a provider or changes D1 or product scope.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data import rqdata_adapter
from app.market_data.rqdata_adapter import WEEKLY_AGGREGATION_VERSION, _aggregate_daily_rows
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from scripts.newow_weekly_recovery import load_private_readonly_settings

CONTRACT = "OI2611"
CUTOFF = datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00")
MISSING_DAYS = tuple(date.fromisoformat(value) for value in (
    "2025-11-28 2025-12-05 2025-12-12 2025-12-19 2025-12-26 2025-12-31 "
    "2026-01-09 2026-01-16 2026-01-23 2026-01-30 2026-02-06 2026-02-13 "
    "2026-02-27 2026-03-06 2026-03-13 2026-03-20 2026-03-27 2026-04-03 "
    "2026-04-10 2026-04-17 2026-04-24 2026-04-30 2026-05-08 2026-05-15 "
    "2026-05-22 2026-05-29 2026-06-05 2026-06-12 2026-06-18 2026-06-26 "
    "2026-07-03 2026-07-10 2026-07-17 2026-07-24 2026-07-31 2026-08-07 "
    "2026-08-14"
).split())
FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")


class OIRebuildError(ValueError):
    pass


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _candidate_sha(bars: tuple[CanonicalBar, ...]) -> str:
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
                   sink, compression="zstd", use_dictionary=False, version="2.6")
    return _sha(sink.getvalue().to_pybytes())


def _partition_identity(partition: Any, root: Path) -> dict[str, Any]:
    path = partition.file_path
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise OIRebuildError("PARTITION_PATH_INVALID")
    return {"uri": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes()),
            "quality_sha256": partition.source_quality_sha256}


def _merge_month(previous: tuple[CanonicalBar, ...], additions: tuple[CanonicalBar, ...]) -> tuple[CanonicalBar, ...]:
    if not additions or len({bar.bar_end for bar in (*previous, *additions)}) != len(previous) + len(additions):
        raise OIRebuildError("W1_DUPLICATE_ENDPOINT")
    if {bar.trading_day for bar in previous} & {bar.trading_day for bar in additions}:
        raise OIRebuildError("W1_TARGET_ALREADY_PRESENT")
    candidate = tuple(sorted((*previous, *additions), key=lambda bar: bar.bar_end))
    if any(left.bar_end >= right.bar_end for left, right in zip(candidate, candidate[1:])):
        raise OIRebuildError("W1_DUPLICATE_ENDPOINT")
    return candidate


def prepare(session: Session, root: Path, root_sha256: str) -> tuple[dict[str, Any], tuple[tuple[CanonicalBar, ...], ...]]:
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    mds = MarketDataService(catalog, store)
    revision = catalog_revision(session, ("oi",), CUTOFF.date(), ("1d", "1w"))
    d1_key = DatasetKey("contract", "oi", CONTRACT, "1d")
    w1_key = DatasetKey("contract", "oi", CONTRACT, "1w")
    expected_w1 = mds.expected_contract_replay_endpoints(
        symbol="oi", contract=CONTRACT, frequency=w1_key.frequency,
        trading_day=MISSING_DAYS[-1], cutoff=CUTOFF)
    weekly = {day: end for end, day in expected_w1}
    if any(day not in weekly for day in MISSING_DAYS):
        raise OIRebuildError("W1_CALENDAR_TARGET_MOVED")
    expected_d1 = mds.expected_contract_replay_endpoints(
        symbol="oi", contract=CONTRACT, frequency=d1_key.frequency,
        trading_day=MISSING_DAYS[-1], cutoff=CUTOFF)
    needed_weeks = {day.isocalendar()[:2] for day in MISSING_DAYS}
    needed_weeks.add(date(2025, 11, 21).isocalendar()[:2])
    daily: dict[date, CanonicalBar] = {}
    quality: dict[date, Any] = {}
    preimages: list[dict[str, Any]] = []
    for partition in catalog.all_partitions(d1_key):
        if (partition.year, partition.month) not in {(day.year, day.month) for _, day in expected_d1}:
            continue
        bars, facts = store.read_catalog_partition_quality(partition)
        selected_bars = [bar for bar in bars if bar.trading_day.isocalendar()[:2] in needed_weeks]
        selected_facts = [fact for fact in facts if fact.trading_day.isocalendar()[:2] in needed_weeks]
        if selected_bars or selected_facts:
            preimages.append({"year": partition.year, "month": partition.month,
                              **_partition_identity(partition, root)})
        for bar in selected_bars:
            if bar.trading_day in daily:
                raise OIRebuildError("D1_DUPLICATE_ENDPOINT")
            daily[bar.trading_day] = bar
        for fact in selected_facts:
            if fact.trading_day in quality:
                raise OIRebuildError("D1_DUPLICATE_QUALITY")
            quality[fact.trading_day] = fact
    fact = catalog.contract_fact("oi", CONTRACT)
    new_bars: dict[date, CanonicalBar] = {}
    day_evidence: list[dict[str, Any]] = []
    interruption_facts: list[dict[str, str]] = []
    for day in (*MISSING_DAYS, date(2025, 11, 21)):
        points = tuple((end, trading_day) for end, trading_day in expected_d1
                       if trading_day.isocalendar()[:2] == day.isocalendar()[:2])
        if not points:
            raise OIRebuildError("D1_CALENDAR_WEEK_MISSING")
        actual = {(bar.bar_end, bar.trading_day) for bar in daily.values() if bar.trading_day.isocalendar()[:2] == day.isocalendar()[:2]}
        actual |= {(item.bar_end, item.trading_day) for item in quality.values() if item.trading_day.isocalendar()[:2] == day.isocalendar()[:2]}
        if actual != set(points):
            raise OIRebuildError("D1_COMPLETE_WEEK_INVALID")
        if day == date(2025, 11, 21):
            if {item.trading_day for item in quality.values() if item.trading_day.isocalendar()[:2] == day.isocalendar()[:2]} != {date(2025, 11, 17), date(2025, 11, 18), day}:
                raise OIRebuildError("QUALITY_INTERRUPTION_MOVED")
            interruption_facts = [
                {"trading_day": item.trading_day.isoformat(), "classification": item.classification}
                for item in quality.values()
                if item.trading_day.isocalendar()[:2] == day.isocalendar()[:2]
            ]
            if {item["classification"] for item in interruption_facts} != {"NONPOSITIVE_CLOSE"}:
                raise OIRebuildError("QUALITY_INTERRUPTION_MOVED")
            continue
        if any(trading_day in quality for _, trading_day in points):
            raise OIRebuildError("D1_QUALITY_INTERRUPTION")
        week_bars = tuple(daily[trading_day] for _, trading_day in points)
        if any(not fact.listed_date <= bar.trading_day < fact.expired_date for bar in week_bars):
            raise OIRebuildError("D1_LIFECYCLE_INVALID")
        aggregate = _aggregate_daily_rows(tuple((bar.trading_day, {field: getattr(bar, field) for field in FIELDS}) for bar in week_bars), bar_end=weekly[day])
        if aggregate.trading_day != day:
            raise OIRebuildError("W1_AGGREGATE_DAY_INVALID")
        new_bars[day] = aggregate
        day_evidence.append({"week_end": day.isoformat(), "bar_end": weekly[day].isoformat(),
                             "d1_endpoints": [[end.isoformat(), d.isoformat()] for end, d in points],
                             "ohlc": {field: str(getattr(aggregate, field)) for field in FIELDS}})
    by_month: dict[tuple[int, int], list[CanonicalBar]] = defaultdict(list)
    for day, bar in new_bars.items():
        by_month[(day.year, day.month)].append(bar)
    records: list[dict[str, Any]] = []
    candidates: list[tuple[CanonicalBar, ...]] = []
    w1_partitions = catalog.all_partitions(w1_key)
    for (year, month), additions in sorted(by_month.items()):
        selected = tuple(item for item in w1_partitions if (item.year, item.month) == (year, month))
        if len(selected) > 1:
            raise OIRebuildError("W1_PARTITION_IDENTITY_INVALID")
        previous = store.read_catalog_partition(selected[0]) if selected else ()
        candidate = _merge_month(previous, tuple(additions))
        store._validate(PublishRequest(w1_key, year, month, candidate,
                                       tuple(bar.bar_end for bar in candidate)))
        candidate_sha = _candidate_sha(candidate)
        directory = store._month_directory(w1_key, year, month)
        records.append({"year": year, "month": month,
                        "old": _partition_identity(selected[0], root) if selected else None,
                        "candidate_uri": (directory.relative_to(root) / f"part.{candidate_sha}.parquet").as_posix(),
                        "candidate_sha256": candidate_sha,
                        "old_count": len(previous), "new_count": len(candidate),
                        "added_days": [bar.trading_day.isoformat() for bar in additions]})
        candidates.append(candidate)
    interruption = date(2025, 11, 21)
    if any(bar.trading_day == interruption for bar in candidates[0]):
        raise OIRebuildError("QUALITY_WEEK_PRICE_CONFLICT")
    if catalog_revision(session, ("oi",), CUTOFF.date(), ("1d", "1w")) != revision:
        raise OIRebuildError("CATALOG_REVISION_MOVED")
    return ({"schema_version": "oi_weekly_local_rebuild_v1", "contract": CONTRACT,
             "cutoff": CUTOFF.isoformat(), "aggregation_version": WEEKLY_AGGREGATION_VERSION,
             "aggregation_source_sha256": _sha(Path(rqdata_adapter.__file__).read_bytes()),
             "repair_source_sha256": _sha(Path(__file__).read_bytes()),
             "canonical_root_sha256": root_sha256, "catalog_revision": revision,
             "provider_requests": 0, "d1_writes": 0, "week_count": len(MISSING_DAYS),
             "quality_interruption": interruption.isoformat(),
             "quality_facts": sorted(interruption_facts, key=lambda item: item["trading_day"]),
             "d1_preimages": preimages,
             "weeks": day_evidence, "months": records}, tuple(candidates))


def inspect(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    if packet.get("schema_version") != "oi_weekly_local_rebuild_v1" or packet.get("contract") != CONTRACT:
        raise OIRebuildError("PREPARED_SCOPE_INVALID")
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    for source in packet["d1_preimages"]:
        relative = Path(source["uri"])
        if relative.is_absolute() or ".." in relative.parts:
            raise OIRebuildError("D1_PREIMAGE_URI_INVALID")
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or _sha(path.read_bytes()) != source["sha256"]:
            raise OIRebuildError("D1_PREIMAGE_MOVED")
    key = DatasetKey("contract", "oi", CONTRACT, "1w")
    states: list[str] = []
    for record in packet["months"]:
        selected = tuple(item for item in catalog.all_partitions(key) if (item.year, item.month) == (record["year"], record["month"]))
        if len(selected) > 1:
            states.append("other")
            continue
        current = _partition_identity(selected[0], root) if selected else None
        candidate = {"uri": record["candidate_uri"], "sha256": record["candidate_sha256"], "quality_sha256": None}
        if current == record["old"]:
            states.append("old")
        elif current == candidate:
            bars = store.read_catalog_partition(selected[0])
            if len(bars) != record["new_count"] or not set(record["added_days"]).issubset({bar.trading_day.isoformat() for bar in bars}):
                states.append("other")
            else:
                states.append("candidate")
        else:
            states.append("other")
    return {"status": "candidate" if all(item == "candidate" for item in states) else
            "old" if all(item == "old" for item in states) else "mixed_or_unknown", "months": states}


def apply(session: Session, root: Path, root_sha256: str, packet: dict[str, Any]) -> dict[str, Any]:
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise OIRebuildError("MAINTENANCE_BUSY")
    committed = False
    try:
        current, candidates = prepare(session, root, root_sha256)
        if current != packet:
            raise OIRebuildError("PREPARE_IDENTITY_MOVED")
        store = CanonicalMonthlyStore(root)
        key = DatasetKey("contract", "oi", CONTRACT, "1w")
        for record, bars in zip(packet["months"], candidates, strict=True):
            published = store.publish(PublishRequest(key, record["year"], record["month"], bars,
                                                     tuple(bar.bar_end for bar in bars)))
            if published.parquet_path.relative_to(root).as_posix() != record["candidate_uri"]:
                raise OIRebuildError("CANDIDATE_HASH_MISMATCH")
            catalog.register_partition(published)
        try:
            session.commit()
        except Exception as exc:
            raise OIRebuildError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "committed", "months": len(candidates), "weeks": len(MISSING_DAYS)}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("prepare", "inspect", "apply"):
        command = sub.add_parser(mode)
        command.add_argument("--project-env", type=Path, required=True)
        if mode != "prepare":
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--expected-prepared-sha256", required=True)
        if mode == "apply":
            command.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    settings, identity = load_private_readonly_settings(args.project_env)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            if args.mode == "prepare":
                session.execute(text("SET TRANSACTION READ ONLY"))
                packet, _ = prepare(session, root, identity["canonical_root_sha256"])
                output = Path.cwd() / "outputs/oi-weekly-local-rebuild/prepare.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(_json(packet))
                session.rollback()
                print(json.dumps({"status": "prepared", "packet_sha256": _sha(output.read_bytes()), "output": str(output)}))
            else:
                content = args.prepared.read_bytes()
                if _sha(content) != args.expected_prepared_sha256:
                    raise OIRebuildError("PREPARED_HASH_MISMATCH")
                packet = json.loads(content)
                with Session(engine, autoflush=False) as readback:
                    readback.execute(text("SET TRANSACTION READ ONLY"))
                    state = inspect(readback, root, packet)
                    readback.rollback()
                if args.mode == "inspect":
                    print(json.dumps(state, sort_keys=True))
                elif state["status"] == "candidate":
                    print(json.dumps({"status": "already_applied", "readback": state}, sort_keys=True))
                elif state["status"] != "old":
                    raise OIRebuildError("ACTIVE_POINTERS_MIXED_OR_UNKNOWN")
                else:
                    result = apply(session, root, identity["canonical_root_sha256"], packet)
                    with Session(engine, autoflush=False) as readback:
                        readback.execute(text("SET TRANSACTION READ ONLY"))
                        state = inspect(readback, root, packet)
                        readback.rollback()
                    if state["status"] != "candidate":
                        raise OIRebuildError("COMMIT_READBACK_FAILED")
                    print(json.dumps({**result, "readback": state}, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OIRebuildError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "OI_REBUILD_FAILED"}))
        raise SystemExit(1) from None
