"""Prepare or apply the two pinned CJ W1 no-trade repairs from existing Canonical D1.

No provider is constructed. Apply needs an exact prepare packet hash and the
existing Market maintenance lock; it never changes D1 or product capability.
"""

from __future__ import annotations

import argparse
from datetime import date
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

_TARGETS = (("CJ2305", 2022, 5, 20), ("CJ2309", 2022, 9, 30))
_FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")
_CUTOFF = date(2026, 9, 18)


class CJRepairError(ValueError):
    pass


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _candidate_sha(bars: tuple[CanonicalBar, ...]) -> str:
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
        sink, compression="zstd", use_dictionary=False, version="2.6",
    )
    return _sha(sink.getvalue().to_pybytes())


def _prepare_target(
    catalog: MarketCatalog, store: CanonicalMonthlyStore, mds: MarketDataService,
    root: Path, contract: str, year: int, month: int, day: int,
) -> tuple[dict[str, Any], tuple[CanonicalBar, ...]]:
    daily_key = DatasetKey("contract", "cj", contract, "1d")
    weekly_key = DatasetKey("contract", "cj", contract, "1w")
    weekly_partitions = tuple(
        item for item in catalog.all_partitions(weekly_key)
        if (item.year, item.month) == (year, month)
    )
    if len(weekly_partitions) != 1:
        raise CJRepairError("W1_PARTITION_IDENTITY_INVALID")
    partition = weekly_partitions[0]
    month_bars = store.read_catalog_partition(partition)
    matches = tuple(bar for bar in month_bars if bar.trading_day == date(year, month, day))
    if len(matches) != 1:
        raise CJRepairError("W1_TARGET_INVALID")
    old = matches[0]
    week = old.trading_day.isocalendar()[:2]
    daily: list[CanonicalBar] = []
    d1_preimages: list[dict[str, Any]] = []
    for item in catalog.all_partitions(daily_key):
        group = tuple(
            bar for bar in store.read_catalog_partition(item)
            if bar.trading_day.isocalendar()[:2] == week
        )
        if group:
            daily.extend(group)
            d1_preimages.append({
                "year": item.year, "month": item.month,
                "file_uri": item.file_path.relative_to(root).as_posix(),
                "sha256": _sha(item.file_path.read_bytes()),
                "source_quality_sha256": item.source_quality_sha256,
            })
    daily.sort(key=lambda bar: bar.bar_end)
    expected = tuple(
        point for point in mds.expected_contract_replay_endpoints(
            symbol="cj", contract=contract, frequency=daily_key.frequency,
            trading_day=old.trading_day, cutoff=old.bar_end,
        ) if point[1].isocalendar()[:2] == week
    )
    if not expected or tuple((bar.bar_end, bar.trading_day) for bar in daily) != expected:
        raise CJRepairError("D1_COMPLETE_WEEK_INVALID")
    fact = catalog.contract_fact("cj", contract)
    if any(not fact.listed_date <= bar.trading_day < fact.expired_date for bar in daily):
        raise CJRepairError("D1_LIFECYCLE_INVALID")
    new = _aggregate_daily_rows(tuple(
        (bar.trading_day, {field: getattr(bar, field) for field in _FIELDS})
        for bar in daily
    ), bar_end=old.bar_end)
    if old == new or old.trading_day != new.trading_day:
        raise CJRepairError("W1_TARGET_DIFF_INVALID")
    candidate = tuple(new if bar == old else bar for bar in month_bars)
    if len(candidate) != len(month_bars) or sum(a != b for a, b in zip(candidate, month_bars)) != 1:
        raise CJRepairError("W1_MONTH_DIFF_INVALID")
    candidate_sha = _candidate_sha(candidate)
    record = {
        "contract": contract, "week_end": old.trading_day.isoformat(),
        "old_w1_partition_uri": partition.file_path.relative_to(root).as_posix(),
        "old_w1_partition_sha256": _sha(partition.file_path.read_bytes()),
        "candidate_w1_partition_sha256": candidate_sha,
        "candidate_w1_partition_uri": (
            partition.file_path.parent.relative_to(root) / f"part.{candidate_sha}.parquet"
        ).as_posix(),
        "month_row_count": len(month_bars), "changed_rows": 1,
        "expected_d1_endpoints": [[end.isoformat(), trading_day.isoformat()] for end, trading_day in expected],
        "d1_preimages": d1_preimages,
        "old_ohlc": {field: str(getattr(old, field)) for field in _FIELDS[:4]},
        "new_ohlc": {field: str(getattr(new, field)) for field in _FIELDS[:4]},
        "unchanged_weekly_fields": ["bar_end", "trading_day", "volume", "turnover", "open_interest"],
    }
    return record, candidate


def prepare(session: Session, root: Path, root_sha256: str) -> tuple[dict[str, Any], tuple[tuple[CanonicalBar, ...], ...]]:
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    mds = MarketDataService(catalog, store)
    revision = catalog_revision(session, ("cj",), _CUTOFF, ("1d", "1w"))
    results = tuple(
        _prepare_target(catalog, store, mds, root, *target) for target in _TARGETS
    )
    if catalog_revision(session, ("cj",), _CUTOFF, ("1d", "1w")) != revision:
        raise CJRepairError("CATALOG_REVISION_MOVED")
    return ({
        "schema_version": "cj_weekly_no_trade_prepare_v1",
        "aggregation_version": WEEKLY_AGGREGATION_VERSION,
        "aggregation_source_sha256": _sha(Path(rqdata_adapter.__file__).read_bytes()),
        "repair_source_sha256": _sha(Path(__file__).read_bytes()),
        "canonical_root_sha256": root_sha256,
        "catalog_revision": revision,
        "provider_requests": 0, "catalog_writes": 0,
        "targets": [record for record, _ in results],
    }, tuple(bars for _, bars in results))


def apply(session: Session, root: Path, root_sha256: str, packet: dict[str, Any]) -> dict[str, Any]:
    catalog = MarketCatalog(session, root)
    lease = catalog.acquire_maintenance_lock()
    if lease is None:
        raise CJRepairError("MAINTENANCE_BUSY")
    committed = False
    try:
        current, candidates = prepare(session, root, root_sha256)
        if current != packet:
            raise CJRepairError("PREPARE_IDENTITY_MOVED")
        store = CanonicalMonthlyStore(root)
        for record, candidate in zip(packet["targets"], candidates, strict=True):
            contract = record["contract"]
            day = date.fromisoformat(record["week_end"])
            key = DatasetKey("contract", "cj", contract, "1w")
            published = store.publish(PublishRequest(
                key, day.year, day.month, candidate,
                tuple(bar.bar_end for bar in candidate),
            ))
            if published.parquet_path.relative_to(root).as_posix() != record["candidate_w1_partition_uri"]:
                raise CJRepairError("CANDIDATE_HASH_MISMATCH")
            catalog.register_partition(published)
            # The candidate must satisfy the same physical D1 quality replay
            # that Newow uses. The old pointer is still recoverable until commit.
            bars, interruptions = MarketDataService(catalog, store).query_contract_weekly_replay_quality(
                symbol="cj", contract=contract, through=day,
                cutoff=next(bar.bar_end for bar in candidate if bar.trading_day == day),
                classification_version="weekly-d1-quality-v2",
            )
            if (not any(bar.trading_day == day for bar in bars)
                    or any(item.trading_day == day for item in interruptions)):
                raise CJRepairError("CANDIDATE_READBACK_INVALID")
        try:
            session.commit()
        except Exception as exc:
            raise CJRepairError("COMMIT_OUTCOME_UNKNOWN") from exc
        committed = True
        return {"status": "committed", "target_count": len(candidates),
                "candidate_uris": [item["candidate_w1_partition_uri"] for item in packet["targets"]]}
    finally:
        if not committed:
            session.rollback()
        lease.release()


def inspect(session: Session, root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Resolve an uncertain commit from active pointers in an independent read."""
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    states: list[str] = []
    for record in packet["targets"]:
        for source in record["d1_preimages"]:
            relative = Path(source["file_uri"])
            if relative.is_absolute() or ".." in relative.parts:
                raise CJRepairError("D1_PREIMAGE_URI_INVALID")
            source_path = root / relative
            if (source_path.is_symlink() or not source_path.resolve().is_relative_to(root.resolve())
                    or _sha(source_path.read_bytes()) != source["sha256"]):
                raise CJRepairError("D1_PREIMAGE_MOVED")
        day = date.fromisoformat(record["week_end"])
        key = DatasetKey("contract", "cj", record["contract"], "1w")
        selected = tuple(
            item for item in catalog.all_partitions(key)
            if (item.year, item.month) == (day.year, day.month)
        )
        if len(selected) != 1:
            states.append("other")
            continue
        uri = selected[0].file_path.relative_to(root).as_posix()
        digest = _sha(selected[0].file_path.read_bytes())
        if uri == record["old_w1_partition_uri"] and digest == record["old_w1_partition_sha256"]:
            states.append("old")
        elif uri == record["candidate_w1_partition_uri"] and digest == record["candidate_w1_partition_sha256"]:
            bars, _ = MarketDataService(catalog, store).query_contract_weekly_replay_quality(
                symbol="cj", contract=record["contract"], through=day,
                cutoff=next(bar.bar_end for bar in store.read_catalog_partition(selected[0])
                            if bar.trading_day == day),
                classification_version="weekly-d1-quality-v2",
            )
            if not any(bar.trading_day == day for bar in bars):
                raise CJRepairError("CANDIDATE_READBACK_INVALID")
            states.append("candidate")
        else:
            states.append("other")
    return {"status": "candidate" if all(item == "candidate" for item in states)
            else "old" if all(item == "old" for item in states) else "mixed_or_unknown",
            "targets": states}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prepare_cmd = commands.add_parser("prepare")
    prepare_cmd.add_argument("--project-env", type=Path, required=True)
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("--project-env", type=Path, required=True)
    apply_cmd.add_argument("--prepared", type=Path, required=True)
    apply_cmd.add_argument("--expected-prepared-sha256", required=True)
    apply_cmd.add_argument("--apply", action="store_true", required=True)
    inspect_cmd = commands.add_parser("inspect")
    inspect_cmd.add_argument("--project-env", type=Path, required=True)
    inspect_cmd.add_argument("--prepared", type=Path, required=True)
    inspect_cmd.add_argument("--expected-prepared-sha256", required=True)
    args = parser.parse_args()
    settings, identity = load_private_readonly_settings(args.project_env)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            if args.mode == "prepare":
                session.execute(text("SET TRANSACTION READ ONLY"))
                packet, _ = prepare(session, root, identity["canonical_root_sha256"])
                output = Path.cwd() / "outputs/cj-weekly-no-trade/prepare.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(_canonical_json(packet))
                session.rollback()
                print(json.dumps({"status": "prepared", "packet_sha256": _sha(output.read_bytes()),
                                  "output": str(output)}))
            else:
                content = args.prepared.read_bytes()
                if _sha(content) != args.expected_prepared_sha256:
                    raise CJRepairError("PREPARED_HASH_MISMATCH")
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
                    raise CJRepairError("ACTIVE_POINTERS_MIXED_OR_UNKNOWN")
                else:
                    result = apply(session, root, identity["canonical_root_sha256"], packet)
                    with Session(engine, autoflush=False) as readback:
                        readback.execute(text("SET TRANSACTION READ ONLY"))
                        state = inspect(readback, root, packet)
                        readback.rollback()
                    if state["status"] != "candidate":
                        raise CJRepairError("COMMIT_READBACK_FAILED")
                    print(json.dumps({**result, "readback": state}, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CJRepairError as exc:
        print(json.dumps({"status": "failed", "error_code": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "error_code": "CJ_REPAIR_FAILED"}))
        raise SystemExit(1) from None
