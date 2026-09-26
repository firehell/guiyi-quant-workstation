"""Prepare exact W1 removals contradicted by pinned D1 quality facts.

Prepare and inspect are read only. Apply requires a reviewed packet and an explicit
flag; it never contacts RQData or changes D1. Empty W1 months lose their Catalog
pointer while their historical Parquet file remains on disk.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.source_quality import NonpositiveCloseFact, PriceUnavailableFact
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest, PublishedPartition
from app.market_data.weekly_quality import (
    WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2, classify_weekly_source,
    weekly_daily_revision_sha256,
)
from app.models import MarketPartition
from scripts.newow_weekly_recovery import load_private_readonly_settings

CUTOFF = datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00")
TARGETS = {
    "PF2611": ("2025-11-21", "2025-11-28", "2025-12-05", "2025-12-12",
               "2025-12-19", "2025-12-31", "2026-01-23", "2026-01-30",
               "2026-02-06", "2026-02-13", "2026-02-27"),
    "RS2609": ("2025-11-28", "2026-08-14", "2026-09-04", "2026-09-11"),
}
_MONTH_ACTIONS = {
    ("PF2611", 2025, 11): "remove_pointer",
    ("PF2611", 2025, 12): "replace",
    ("PF2611", 2026, 1): "replace",
    ("PF2611", 2026, 2): "remove_pointer",
    ("RS2609", 2025, 11): "remove_pointer",
    ("RS2609", 2026, 8): "replace",
    ("RS2609", 2026, 9): "remove_pointer",
}


class QualityRepairError(ValueError):
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


def _identity(partition: Any, root: Path) -> dict[str, Any]:
    path = partition.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise QualityRepairError("PARTITION_PATH_INVALID")
    return {"uri": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes()),
            "row_count": partition.row_count,
            "coverage_start": partition.coverage_start.isoformat() if partition.coverage_start else None,
            "coverage_end": partition.coverage_end.isoformat() if partition.coverage_end else None,
            "source_coverage_start": partition.source_coverage_start.isoformat() if partition.source_coverage_start else None,
            "source_coverage_end": partition.source_coverage_end.isoformat() if partition.source_coverage_end else None,
            "quality_sha256": partition.source_quality_sha256}


def _candidate_catalog(bars: tuple[CanonicalBar, ...]) -> dict[str, Any]:
    from datetime import timedelta

    return {"row_count": len(bars),
            "coverage_start": (bars[0].bar_end - timedelta(days=7)).isoformat(),
            "coverage_end": bars[-1].bar_end.isoformat(),
            "source_coverage_start": (bars[0].bar_end - timedelta(days=7)).isoformat(),
            "source_coverage_end": bars[-1].bar_end.isoformat(),
            "quality_sha256": None}


def _prepare_contract(catalog: MarketCatalog, store: CanonicalMonthlyStore,
                      mds: MarketDataService, root: Path, contract: str,
                      target_days: tuple[str, ...] | None = None, cutoff: datetime = CUTOFF
                      ) -> tuple[list[dict[str, Any]], list[tuple[CanonicalBar, ...]], list[dict[str, Any]]]:
    symbol = contract[:2].lower()
    days = tuple(date.fromisoformat(value) for value in (target_days or TARGETS[contract]))
    d1_key = DatasetKey("contract", symbol, contract, "1d")
    w1_key = DatasetKey("contract", symbol, contract, "1w")
    expected_w1 = dict((day, end) for end, day in mds.expected_contract_replay_endpoints(
        symbol=symbol, contract=contract, frequency=w1_key.frequency,
        trading_day=days[-1], cutoff=cutoff))
    expected_d1 = mds.expected_contract_replay_endpoints(
        symbol=symbol, contract=contract, frequency=d1_key.frequency,
        trading_day=days[-1], cutoff=cutoff)
    if any(day not in expected_w1 for day in days):
        raise QualityRepairError("W1_TARGET_CALENDAR_MOVED")
    weeks = {day.isocalendar()[:2] for day in days}
    daily: dict[date, CanonicalBar] = {}
    quality: dict[date, NonpositiveCloseFact | PriceUnavailableFact] = {}
    d1_parts: dict[tuple[int, int], Any] = {}
    d1_preimages: list[dict[str, Any]] = []
    for part in catalog.all_partitions(d1_key):
        bars, facts = store.read_catalog_partition_quality(part)
        selected_bars = [bar for bar in bars if bar.trading_day.isocalendar()[:2] in weeks]
        selected_facts = [fact for fact in facts if fact.trading_day.isocalendar()[:2] in weeks]
        if not selected_bars and not selected_facts:
            continue
        d1_parts[(part.year, part.month)] = part
        d1_preimages.append({"year": part.year, "month": part.month, **_identity(part, root)})
        for bar in selected_bars:
            if bar.trading_day in daily or bar.trading_day in quality:
                raise QualityRepairError("D1_ENDPOINT_DUPLICATE")
            daily[bar.trading_day] = bar
        for fact in selected_facts:
            if fact.trading_day in daily or fact.trading_day in quality:
                raise QualityRepairError("D1_ENDPOINT_DUPLICATE")
            quality[fact.trading_day] = fact
    week_evidence: list[dict[str, Any]] = []
    for day in days:
        points = tuple(point for point in expected_d1
                       if point[1].isocalendar()[:2] == day.isocalendar()[:2])
        bars = tuple(daily[d] for _, d in points if d in daily)
        facts = tuple(quality[d] for _, d in points if d in quality)
        if not points or not facts or not all(isinstance(fact, NonpositiveCloseFact) for fact in facts):
            raise QualityRepairError("D1_QUALITY_PROOF_INVALID")
        months = sorted({(d.year, d.month) for _, d in points})
        if any(month not in d1_parts for month in months):
            raise QualityRepairError("D1_PARTITION_MISSING")
        revision = weekly_daily_revision_sha256(
            tuple((d1_parts[month].file_path.name,
                   d1_parts[month].source_quality_sha256) for month in months), bars)
        coverage = classify_weekly_source(
            product=symbol, physical_contract=contract, expected_daily_endpoints=points,
            daily_bars=bars, price_unavailable=facts, daily_revision_sha256=revision,
            classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
        interruption = coverage.interruption
        if interruption is None or interruption.week_end != expected_w1[day]:
            raise QualityRepairError("W1_INTERRUPTION_PROOF_INVALID")
        week_evidence.append({"week_end": day.isoformat(), "bar_end": expected_w1[day].isoformat(),
                              "expected_d1_endpoints": [[end.isoformat(), d.isoformat()] for end, d in points],
                              "quality_days": [{"day": fact.trading_day.isoformat(),
                                                "classification": fact.classification,
                                                "request_sha256": fact.request_sha256,
                                                "response_sha256": fact.response_sha256} for fact in facts],
                              "source_identity": interruption.source_identity,
                              "daily_revision_sha256": revision})
    by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
    for day in days:
        by_month[(day.year, day.month)].append(day)
    records: list[dict[str, Any]] = []
    candidates: list[tuple[CanonicalBar, ...]] = []
    w1_parts = catalog.all_partitions(w1_key)
    for (year, month), removed in sorted(by_month.items()):
        selected = tuple(part for part in w1_parts if (part.year, part.month) == (year, month))
        if len(selected) != 1:
            raise QualityRepairError("W1_PARTITION_IDENTITY_INVALID")
        part = selected[0]
        previous = store.read_catalog_partition(part)
        removed_set = set(removed)
        if {bar.trading_day for bar in previous if bar.trading_day in removed_set} != removed_set:
            raise QualityRepairError("W1_TARGET_ROWS_MOVED")
        if any(bar.bar_end != expected_w1[bar.trading_day]
               for bar in previous if bar.trading_day in removed_set):
            raise QualityRepairError("W1_TARGET_ENDPOINT_MOVED")
        candidate = tuple(bar for bar in previous if bar.trading_day not in removed_set)
        if len(candidate) != len(previous) - len(removed):
            raise QualityRepairError("W1_MONTH_DIFF_INVALID")
        record: dict[str, Any] = {"contract": contract, "year": year, "month": month,
                 "old": _identity(part, root), "removed_days": [day.isoformat() for day in removed],
                 "retained_days": [bar.trading_day.isoformat() for bar in candidate],
                 "old_count": len(previous), "new_count": len(candidate),
                 "action": "replace" if candidate else "remove_pointer"}
        if candidate:
            store._validate(PublishRequest(w1_key, year, month, candidate,
                                           tuple(bar.bar_end for bar in candidate)))
            digest = _candidate_sha(candidate)
            directory = store._month_directory(w1_key, year, month)
            record.update(candidate_uri=(directory.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                          candidate_sha256=digest, catalog_candidate=_candidate_catalog(candidate))
        records.append(record)
        candidates.append(candidate)
    return records, candidates, [{"contract": contract, "d1_preimages": d1_preimages,
                                  "weeks": week_evidence}]


def _validated_targets(targets: dict[str, Any], cutoff: datetime) -> dict[str, tuple[str, ...]]:
    if (not isinstance(targets, dict) or not 1 <= len(targets) <= 200
            or cutoff.utcoffset() is None or cutoff > datetime.now(cutoff.tzinfo)):
        raise QualityRepairError("PREPARED_SCOPE_INVALID")
    result = {}
    for contract, values in targets.items():
        if (not isinstance(contract, str) or re.fullmatch(r"[A-Z]{2}[0-9]{4}", contract) is None
                or contract[:2].lower() not in {"cj", "pf", "sf", "rs", "pr", "sm", "px", "pk", "sh", "pl", "sr"}
                or not isinstance(values, (list, tuple)) or not values
                or any(not isinstance(value, str) for value in values)):
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
        try:
            days = tuple(date.fromisoformat(value) for value in values)
        except ValueError as exc:
            raise QualityRepairError("PREPARED_SCOPE_INVALID") from exc
        if (tuple(values) != tuple(sorted(set(values)))
                or any(day.isoformat() != value or day > cutoff.date() for day, value in zip(days, values, strict=True))):
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
        result[contract] = tuple(values)
    return dict(sorted(result.items()))


def prepare(session: Session, root: Path, root_sha256: str,
            *, targets: dict[str, Any] | None = None, cutoff: datetime = CUTOFF
            ) -> tuple[dict[str, Any], tuple[tuple[CanonicalBar, ...], ...]]:
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    mds = MarketDataService(catalog, store)
    scope = TARGETS if targets is None else _validated_targets(targets, cutoff)
    products = tuple(sorted({contract[:2].lower() for contract in scope}))
    revision = catalog_revision(session, products, cutoff.date(), ("1d", "1w"))
    prepared = tuple(_prepare_contract(catalog, store, mds, root, contract, tuple(days), cutoff)
                     for contract, days in scope.items())
    if catalog_revision(session, products, cutoff.date(), ("1d", "1w")) != revision:
        raise QualityRepairError("CATALOG_REVISION_MOVED")
    packet = {"schema_version": "pf_rs_weekly_quality_repair_v1",
              "classification_version": WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2,
              "cutoff": cutoff.isoformat(), "canonical_root_sha256": root_sha256,
              "catalog_revision": revision, "repair_source_sha256": _sha(Path(__file__).read_bytes()),
              "provider_requests": 0, "d1_writes": 0,
              "contracts": [source for _, _, sources in prepared for source in sources],
              "months": [record for records, _, _ in prepared for record in records]}
    if targets is not None:
        packet.update(schema_version="newow_weekly_quality_repair_v2",
                      target_scope={key: list(days) for key, days in scope.items()})
    _validate_scope(packet)
    return packet, tuple(candidate for _, candidates, _ in prepared for candidate in candidates)


def _validate_scope(packet: dict[str, Any]) -> None:
    dynamic = packet.get("schema_version") == "newow_weekly_quality_repair_v2"
    if dynamic:
        try:
            cutoff = datetime.fromisoformat(packet["cutoff"])
            targets = _validated_targets(packet["target_scope"], cutoff)
        except (KeyError, ValueError, TypeError) as exc:
            raise QualityRepairError("PREPARED_SCOPE_INVALID") from exc
        actions = {(contract, date.fromisoformat(day).year, date.fromisoformat(day).month): None
                   for contract, days in targets.items() for day in days}
    else:
        targets, actions = TARGETS, _MONTH_ACTIONS
    if ((not dynamic and (packet.get("schema_version") != "pf_rs_weekly_quality_repair_v1"
                         or packet.get("cutoff") != CUTOFF.isoformat()))
            or packet.get("repair_source_sha256") != _sha(Path(__file__).read_bytes())):
        raise QualityRepairError("PREPARED_SCOPE_INVALID")
    sources = packet.get("contracts")
    months = packet.get("months")
    if (not isinstance(sources, list) or len(sources) != len(targets)
            or {source.get("contract") for source in sources} != set(targets)
            or not isinstance(months, list) or len(months) != len(actions)):
        raise QualityRepairError("PREPARED_SCOPE_INVALID")
    for source in sources:
        expected = set(targets[source["contract"]])
        weeks = source.get("weeks")
        if (not isinstance(weeks, list) or len(weeks) != len(expected)
                or {week.get("week_end") for week in weeks} != expected):
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
    seen: set[tuple[str, int, int]] = set()
    for record in months:
        key = (record.get("contract"), record.get("year"), record.get("month"))
        if (key not in actions or key in seen
                or record.get("action") not in {"replace", "remove_pointer"}
                or (not dynamic and record.get("action") != actions[key])):
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
        seen.add(key)
        expected_days = [day for day in targets[key[0]]
                         if (date.fromisoformat(day).year, date.fromisoformat(day).month) == key[1:]]
        if record.get("removed_days") != expected_days:
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
        base = f"kind=contract/symbol={key[0][:2].lower()}/series={key[0]}/frequency=1w/year={key[1]}/month={key[2]:02d}/"
        old = record.get("old")
        if (not isinstance(old, dict) or not isinstance(old.get("uri"), str)
                or not old["uri"].startswith(base)
                or "/" in old["uri"][len(base):]
                or record.get("old_count") != record.get("new_count") + len(expected_days)):
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
        if record["action"] == "replace":
            if (record.get("candidate_uri") != base + f"part.{record.get('candidate_sha256')}.parquet"
                    or record.get("new_count", 0) <= 0):
                raise QualityRepairError("PREPARED_SCOPE_INVALID")
        elif record.get("new_count") != 0 or record.get("retained_days") != []:
            raise QualityRepairError("PREPARED_SCOPE_INVALID")
    if seen != set(actions):
        raise QualityRepairError("PREPARED_SCOPE_INVALID")


def inspect(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    _validate_scope(packet)
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    states: list[str] = []
    for source in packet["contracts"]:
        symbol = source["contract"][:2].lower()
        key = DatasetKey("contract", symbol, source["contract"], "1d")
        active = {(part.year, part.month): part for part in catalog.all_partitions(key)}
        for image in source["d1_preimages"]:
            part = active.get((image["year"], image["month"]))
            if part is None or _identity(part, root) != {k: v for k, v in image.items()
                                                       if k not in ("year", "month")}:
                raise QualityRepairError("D1_PREIMAGE_MOVED")
    for record in packet["months"]:
        contract = record["contract"]
        key = DatasetKey("contract", contract[:2].lower(), contract, "1w")
        selected = tuple(part for part in catalog.all_partitions(key)
                         if (part.year, part.month) == (record["year"], record["month"]))
        if len(selected) > 1:
            states.append("other")
            continue
        current = _identity(selected[0], root) if selected else None
        if current == record["old"]:
            states.append("old")
        elif record["action"] == "remove_pointer" and current is None:
            states.append("candidate")
        elif record["action"] == "replace" and current == {
            "uri": record["candidate_uri"], "sha256": record["candidate_sha256"],
            **record["catalog_candidate"]}:
            bars = store.read_catalog_partition(selected[0])
            states.append("candidate" if [bar.trading_day.isoformat() for bar in bars]
                          == record["retained_days"] else "other")
        else:
            states.append("other")
    return {"status": "candidate" if all(state == "candidate" for state in states) else
            "old" if all(state == "old" for state in states) else "mixed_or_unknown",
            "months": states}


def apply(session: Session, root: Path, root_sha256: str, packet: dict[str, Any]) -> dict[str, Any]:
    _validate_scope(packet)
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise QualityRepairError("MAINTENANCE_BUSY")
    committed = False
    try:
        if packet["canonical_root_sha256"] != root_sha256:
            raise QualityRepairError("CANONICAL_ROOT_MISMATCH")
        current, candidates = (prepare(session, root, root_sha256,
                                      targets=packet["target_scope"], cutoff=datetime.fromisoformat(packet["cutoff"]))
                               if packet.get("schema_version") == "newow_weekly_quality_repair_v2"
                               else prepare(session, root, root_sha256))
        if current != packet:
            raise QualityRepairError("PREPARE_IDENTITY_MOVED")
        store = CanonicalMonthlyStore(root)
        for record, candidate in zip(packet["months"], candidates, strict=True):
            contract = record["contract"]
            key = DatasetKey("contract", contract[:2].lower(), contract, "1w")
            if record["action"] == "replace":
                published = store.publish(PublishRequest(key, record["year"], record["month"],
                                                         candidate, tuple(bar.bar_end for bar in candidate)))
                if published.parquet_path.relative_to(root).as_posix() != record["candidate_uri"]:
                    raise QualityRepairError("CANDIDATE_HASH_MISMATCH")
                observed = {"row_count": published.row_count,
                            "coverage_start": published.coverage_start.isoformat() if published.coverage_start else None,
                            "coverage_end": published.coverage_end.isoformat() if published.coverage_end else None,
                            "source_coverage_start": published.source_coverage_start.isoformat() if published.source_coverage_start else None,
                            "source_coverage_end": published.source_coverage_end.isoformat() if published.source_coverage_end else None,
                            "quality_sha256": published.source_quality_sha256}
                if observed != record["catalog_candidate"]:
                    raise QualityRepairError("CANDIDATE_CATALOG_MISMATCH")
                catalog.register_partition(published)
            else:
                dataset = catalog.dataset_row(key)
                if dataset is None:
                    raise QualityRepairError("W1_PARTITION_IDENTITY_MOVED")
                selected = session.scalars(select(MarketPartition).where(
                    MarketPartition.dataset_id == dataset.id, MarketPartition.year == record["year"],
                    MarketPartition.month == record["month"])).all()
                if len(selected) != 1:
                    raise QualityRepairError("W1_PARTITION_IDENTITY_MOVED")
                session.delete(selected[0])
                session.flush()
            current = tuple(part for part in catalog.all_partitions(key)
                            if (part.year, part.month) == (record["year"], record["month"]))
            if record["action"] == "remove_pointer":
                if current:
                    raise QualityRepairError("CANDIDATE_READBACK_INVALID")
            elif len(current) != 1 or store.read_catalog_partition(current[0]) != candidate:
                raise QualityRepairError("CANDIDATE_READBACK_INVALID")
        try:
            session.commit()
        except Exception as exc:
            raise QualityRepairError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "committed", "months": len(candidates),
                "weeks": sum(len(source["weeks"]) for source in packet["contracts"])}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def restore(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Restore exact old pointers after an independently authorized recovery decision."""
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise QualityRepairError("MAINTENANCE_BUSY")
    committed = False
    try:
        if inspect(session, root, packet)["status"] != "candidate":
            raise QualityRepairError("RESTORE_POINTERS_MOVED")
        for record in packet["months"]:
            old = record["old"]
            relative = Path(old["uri"])
            if relative.is_absolute() or ".." in relative.parts:
                raise QualityRepairError("OLD_URI_INVALID")
            path = root / relative
            if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
                    or _sha(path.read_bytes()) != old["sha256"]
                    or old["quality_sha256"] is not None):
                raise QualityRepairError("OLD_PREIMAGE_MOVED")
            contract = record["contract"]
            key = DatasetKey("contract", contract[:2].lower(), contract, "1w")
            catalog.register_partition(PublishedPartition(
                key, record["year"], record["month"], path,
                datetime.fromisoformat(old["coverage_start"]) if old["coverage_start"] else None,
                datetime.fromisoformat(old["coverage_end"]) if old["coverage_end"] else None,
                old["row_count"],
                datetime.fromisoformat(old["source_coverage_start"])
                if old["source_coverage_start"] else None,
                datetime.fromisoformat(old["source_coverage_end"])
                if old["source_coverage_end"] else None,
            ))
        if inspect(session, root, packet)["status"] != "old":
            raise QualityRepairError("RESTORE_READBACK_INVALID")
        try:
            session.commit()
        except Exception as exc:
            raise QualityRepairError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "restored", "months": len(packet["months"])}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("prepare", "inspect", "apply", "restore"):
        command = sub.add_parser(mode)
        command.add_argument("--project-env", type=Path, required=True)
        if mode == "prepare":
            command.add_argument("--target-scope", type=Path)
            command.add_argument("--expected-target-scope-sha256")
            command.add_argument("--cutoff")
            command.add_argument("--output", type=Path)
        if mode != "prepare":
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--expected-prepared-sha256", required=True)
        if mode in ("apply", "restore"):
            command.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args()
    settings, identity = load_private_readonly_settings(args.project_env)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            if args.mode == "prepare":
                session.execute(text("SET TRANSACTION READ ONLY"))
                if args.target_scope is not None:
                    if not args.cutoff or not args.expected_target_scope_sha256 or args.target_scope.is_symlink():
                        raise QualityRepairError("PREPARED_SCOPE_INVALID")
                    content = args.target_scope.read_bytes()
                    if len(content) > 2 * 1024 * 1024 or _sha(content) != args.expected_target_scope_sha256:
                        raise QualityRepairError("PREPARED_HASH_MISMATCH")
                    packet, _ = prepare(session, root, identity["canonical_root_sha256"],
                                        targets=json.loads(content), cutoff=datetime.fromisoformat(args.cutoff))
                else:
                    if args.cutoff or args.expected_target_scope_sha256:
                        raise QualityRepairError("PREPARED_SCOPE_INVALID")
                    packet, _ = prepare(session, root, identity["canonical_root_sha256"])
                output = args.output or Path.cwd() / "outputs/pf-rs-weekly-quality/prepare.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("xb") as handle:
                    handle.write(_json(packet))
                session.rollback()
                print(json.dumps({"status": "prepared", "packet_sha256": _sha(output.read_bytes()),
                                  "output": str(output)}))
            else:
                content = args.prepared.read_bytes()
                if _sha(content) != args.expected_prepared_sha256:
                    raise QualityRepairError("PREPARED_HASH_MISMATCH")
                packet = json.loads(content)
                with Session(engine, autoflush=False) as readback:
                    readback.execute(text("SET TRANSACTION READ ONLY"))
                    state = inspect(readback, root, packet)
                    readback.rollback()
                if args.mode == "inspect":
                    print(json.dumps(state, sort_keys=True))
                elif args.mode == "restore":
                    if state["status"] == "old":
                        print(json.dumps({"status": "already_restored", "readback": state}, sort_keys=True))
                    elif state["status"] != "candidate":
                        raise QualityRepairError("ACTIVE_POINTERS_MIXED_OR_UNKNOWN")
                    else:
                        result = restore(session, root, packet)
                        with Session(engine, autoflush=False) as readback:
                            readback.execute(text("SET TRANSACTION READ ONLY"))
                            state = inspect(readback, root, packet)
                            readback.rollback()
                        if state["status"] != "old":
                            raise QualityRepairError("COMMIT_READBACK_FAILED")
                        print(json.dumps({**result, "readback": state}, sort_keys=True))
                elif state["status"] == "candidate":
                    print(json.dumps({"status": "already_applied", "readback": state}, sort_keys=True))
                elif state["status"] != "old":
                    raise QualityRepairError("ACTIVE_POINTERS_MIXED_OR_UNKNOWN")
                else:
                    result = apply(session, root, identity["canonical_root_sha256"], packet)
                    with Session(engine, autoflush=False) as readback:
                        readback.execute(text("SET TRANSACTION READ ONLY"))
                        state = inspect(readback, root, packet)
                        readback.rollback()
                    if state["status"] != "candidate":
                        raise QualityRepairError("COMMIT_READBACK_FAILED")
                    print(json.dumps({**result, "readback": state}, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualityRepairError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "QUALITY_REPAIR_FAILED"}))
        raise SystemExit(1) from None
