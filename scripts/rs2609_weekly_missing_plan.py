"""Read-only exact plan for RS2609's four missing complete physical W1 weeks.

No provider, Canonical or Catalog mutation is available from this command.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data import rqdata_adapter
from app.market_data.rqdata_adapter import WEEKLY_AGGREGATION_VERSION, _aggregate_daily_rows
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from app.market_data.weekly_quality import (
    WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2, classify_weekly_source,
    weekly_daily_revision_sha256,
)
from scripts.newow_weekly_recovery import load_private_readonly_settings

CONTRACT = "RS2609"
SYMBOL = "rs"
CUTOFF = datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00")
THROUGH = date(2026, 9, 11)
MISSING_DAYS = tuple(date.fromisoformat(value) for value in (
    "2025-09-30", "2025-12-31", "2026-01-09", "2026-01-16"
))
FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")


class RSPlanError(ValueError):
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


def _identity(partition: CatalogPartition, root: Path) -> dict[str, Any]:
    path = partition.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RSPlanError("PARTITION_PATH_INVALID")
    return {"year": partition.year, "month": partition.month,
            "uri": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes()),
            "quality_sha256": partition.source_quality_sha256,
            "row_count": partition.row_count,
            "coverage_start": partition.coverage_start.isoformat() if partition.coverage_start else None,
            "coverage_end": partition.coverage_end.isoformat() if partition.coverage_end else None,
            "source_coverage_start": partition.source_coverage_start.isoformat() if partition.source_coverage_start else None,
            "source_coverage_end": partition.source_coverage_end.isoformat() if partition.source_coverage_end else None}


def prepare(session: Session, root: Path, root_sha256: str) -> dict[str, Any]:
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    mds = MarketDataService(catalog, store)
    revision = catalog_revision(session, (SYMBOL,), CUTOFF.date(), ("1d", "1w"))
    fact = catalog.contract_fact(SYMBOL, CONTRACT)
    d1_key = DatasetKey("contract", SYMBOL, CONTRACT, "1d")
    w1_key = DatasetKey("contract", SYMBOL, CONTRACT, "1w")
    expected_d1 = mds.expected_contract_replay_endpoints(
        symbol=SYMBOL, contract=CONTRACT, frequency=BarFrequency.D1,
        trading_day=THROUGH, cutoff=CUTOFF)
    expected_w1 = dict((day, end) for end, day in mds.expected_contract_replay_endpoints(
        symbol=SYMBOL, contract=CONTRACT, frequency=BarFrequency.W1,
        trading_day=THROUGH, cutoff=CUTOFF))
    if any(day not in expected_w1 for day in MISSING_DAYS):
        raise RSPlanError("W1_TARGET_CALENDAR_MOVED")
    weeks = {day.isocalendar()[:2] for day in MISSING_DAYS}
    daily: dict[date, CanonicalBar] = {}
    quality_days: set[date] = set()
    d1_parts: dict[tuple[int, int], CatalogPartition] = {}
    for part in catalog.all_partitions(d1_key):
        bars, quality = store.read_catalog_partition_quality(part)
        selected = tuple(bar for bar in bars if bar.trading_day.isocalendar()[:2] in weeks)
        selected_quality = tuple(item for item in quality
                                 if item.trading_day.isocalendar()[:2] in weeks)
        if not selected and not selected_quality:
            continue
        d1_parts[(part.year, part.month)] = part
        for bar in selected:
            if bar.trading_day in daily or bar.trading_day in quality_days:
                raise RSPlanError("D1_ENDPOINT_DUPLICATE")
            daily[bar.trading_day] = bar
        for item in selected_quality:
            if item.trading_day in daily or item.trading_day in quality_days:
                raise RSPlanError("D1_ENDPOINT_DUPLICATE")
            quality_days.add(item.trading_day)
    week_records: list[dict[str, Any]] = []
    additions: dict[date, CanonicalBar] = {}
    for day in MISSING_DAYS:
        points = tuple(point for point in expected_d1
                       if point[1].isocalendar()[:2] == day.isocalendar()[:2])
        if not points or any(d not in daily or d in quality_days for _, d in points):
            raise RSPlanError("D1_COMPLETE_WEEK_INVALID")
        bars = tuple(daily[d] for _, d in points)
        if (tuple((bar.bar_end, bar.trading_day) for bar in bars) != points
                or any(not fact.listed_date <= bar.trading_day < fact.expired_date for bar in bars)
                or any(min(bar.open, bar.high, bar.low, bar.close) <= 0 for bar in bars)):
            raise RSPlanError("D1_NORMAL_PRICE_WEEK_INVALID")
        months = sorted({(d.year, d.month) for _, d in points})
        if any(month not in d1_parts for month in months):
            raise RSPlanError("D1_PARTITION_MISSING")
        daily_revision = weekly_daily_revision_sha256(
            tuple((d1_parts[month].file_path.name,
                   d1_parts[month].source_quality_sha256) for month in months), bars)
        coverage = classify_weekly_source(
            product=SYMBOL, physical_contract=CONTRACT, expected_daily_endpoints=points,
            daily_bars=bars, price_unavailable=(), daily_revision_sha256=daily_revision,
            classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
        if coverage.interruption is not None or coverage.daily_bars != bars:
            raise RSPlanError("D1_WEEK_CLASSIFICATION_INVALID")
        aggregate = _aggregate_daily_rows(tuple(
            (bar.trading_day, {field: getattr(bar, field) for field in FIELDS}) for bar in bars
        ), bar_end=expected_w1[day])
        if aggregate.trading_day != day:
            raise RSPlanError("W1_AGGREGATE_DAY_INVALID")
        additions[day] = aggregate
        week_records.append({"trading_day": day.isoformat(), "bar_end": expected_w1[day].isoformat(),
                             "expected_d1_endpoints": [[end.isoformat(), d.isoformat()] for end, d in points],
                             "d1_revision_sha256": daily_revision,
                             "d1_rows": [{"trading_day": bar.trading_day.isoformat(),
                                          "bar_end": bar.bar_end.isoformat(),
                                          **{field: str(getattr(bar, field)) for field in FIELDS}}
                                         for bar in bars],
                             "candidate_w1": {field: str(getattr(aggregate, field)) for field in FIELDS}})
    by_month: dict[tuple[int, int], list[CanonicalBar]] = defaultdict(list)
    for day, bar in additions.items():
        by_month[(day.year, day.month)].append(bar)
    current_w1 = catalog.all_partitions(w1_key)
    month_records: list[dict[str, Any]] = []
    candidates: dict[tuple[int, int], tuple[CanonicalBar, ...]] = {}
    for (year, month), group in sorted(by_month.items()):
        selected = tuple(part for part in current_w1 if (part.year, part.month) == (year, month))
        if len(selected) > 1:
            raise RSPlanError("W1_PARTITION_IDENTITY_INVALID")
        old = store.read_catalog_partition(selected[0]) if selected else ()
        if len({bar.bar_end for bar in (*old, *group)}) != len(old) + len(group):
            raise RSPlanError("W1_TARGET_ALREADY_PRESENT")
        candidate = tuple(sorted((*old, *group), key=lambda bar: bar.bar_end))
        if (len({bar.trading_day for bar in candidate}) != len(candidate)
                or len(candidate) != len(old) + len(group)):
            raise RSPlanError("W1_MONTH_DIFF_INVALID")
        store._validate(PublishRequest(w1_key, year, month, candidate,
                                       tuple(bar.bar_end for bar in candidate)))
        digest = _candidate_sha(candidate)
        directory = store._month_directory(w1_key, year, month)
        month_records.append({"year": year, "month": month,
                              "old": _identity(selected[0], root) if selected else None,
                              "candidate_uri": (directory.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                              "candidate_sha256": digest,
                              "old_count": len(old), "new_count": len(candidate),
                              "added_days": [bar.trading_day.isoformat() for bar in group],
                              "retained_days": [bar.trading_day.isoformat() for bar in old],
                              "candidate_coverage_start": (candidate[0].bar_end - timedelta(days=7)).isoformat(),
                              "candidate_coverage_end": candidate[-1].bar_end.isoformat()})
        candidates[(year, month)] = candidate
    overlay = _overlay_replay(catalog, store, root, w1_key, candidates, month_records)
    if catalog_revision(session, (SYMBOL,), CUTOFF.date(), ("1d", "1w")) != revision:
        raise RSPlanError("CATALOG_REVISION_MOVED")
    return {"schema_version": "rs2609_missing_w1_plan_v1", "symbol": SYMBOL,
            "contract": CONTRACT, "cutoff": CUTOFF.isoformat(), "through": THROUGH.isoformat(),
            "aggregation_version": WEEKLY_AGGREGATION_VERSION,
            "weekly_classification_version": WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2,
            "canonical_root_sha256": root_sha256, "catalog_revision": revision,
            "planner_source_sha256": _sha(Path(__file__).read_bytes()),
            "aggregation_source_sha256": _sha(Path(rqdata_adapter.__file__).read_bytes()),
            "provider_requests": 0, "production_writes": 0,
            "d1_preimages": [_identity(d1_parts[key], root) for key in sorted(d1_parts)],
            "weeks": week_records, "months": month_records,
            "candidate_overlay_replay": overlay}


def _overlay_replay(catalog: MarketCatalog, store: CanonicalMonthlyStore, root: Path,
                    w1_key: DatasetKey, candidates: dict[tuple[int, int], tuple[CanonicalBar, ...]],
                    records: list[dict[str, Any]]) -> dict[str, Any]:
    class OverlayCatalog:
        def __getattr__(self, name: str) -> Any:
            return getattr(catalog, name)

        def all_partitions(self, key: DatasetKey) -> tuple[CatalogPartition, ...]:
            base = tuple(catalog.all_partitions(key))
            if key != w1_key:
                return base
            result = [part for part in base if (part.year, part.month) not in candidates]
            for record in records:
                year, month = record["year"], record["month"]
                bars = candidates[(year, month)]
                result.append(CatalogPartition(
                    key, year, month,
                    bars[0].bar_end - timedelta(days=7), bars[-1].bar_end,
                    root / record["candidate_uri"], len(bars),
                    bars[0].bar_end - timedelta(days=7), bars[-1].bar_end,
                ))
            return tuple(sorted(result, key=lambda item: (item.year, item.month)))

    class OverlayStore:
        def __getattr__(self, name: str) -> Any:
            return getattr(store, name)

        def read_catalog_partition(self, part: CatalogPartition) -> tuple[CanonicalBar, ...]:
            if part.dataset == w1_key and (part.year, part.month) in candidates:
                return candidates[(part.year, part.month)]
            return store.read_catalog_partition(part)

    mds = MarketDataService(OverlayCatalog(), OverlayStore())
    endpoints = mds.expected_contract_replay_endpoints(
        symbol=SYMBOL, contract=CONTRACT, frequency=BarFrequency.W1,
        trading_day=THROUGH, cutoff=CUTOFF)
    cutoff = next((end for end, day in endpoints if day == THROUGH), None)
    if cutoff is None:
        raise RSPlanError("W1_REPLAY_CUTOFF_INVALID")
    bars, interruptions = mds.query_contract_weekly_replay_quality(
        symbol=SYMBOL, contract=CONTRACT, through=THROUGH, cutoff=cutoff,
        classification_version=WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2)
    if {bar.trading_day for bar in bars} & set(MISSING_DAYS) != set(MISSING_DAYS):
        raise RSPlanError("W1_CANDIDATE_REPLAY_MISSING")
    return {"status": "readable", "normal_bars": len(bars),
            "quality_interruptions": len(interruptions),
            "target_days_readable": [day.isoformat() for day in MISSING_DAYS]}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument("--project-env", type=Path, required=True)
    args = parser.parse_args()
    settings, identity = load_private_readonly_settings(args.project_env)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            packet = prepare(session, root, identity["canonical_root_sha256"])
            output = Path.cwd() / "outputs/rs2609-weekly-missing/prepare.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(_json(packet))
            session.rollback()
            print(json.dumps({"status": "prepared", "packet_sha256": _sha(output.read_bytes()),
                              "output": str(output), "weeks": len(packet["weeks"]),
                              "months": len(packet["months"]), "overlay": packet["candidate_overlay_replay"]},
                             sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RSPlanError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "RS2609_PLAN_FAILED"}))
        raise SystemExit(1) from None
