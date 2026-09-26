"""Read-only exact RS W1 no-trade month candidates from current Catalog D1."""

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.rqdata_adapter import WEEKLY_AGGREGATION_VERSION, _aggregate_daily_rows
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore
from scripts.newow_weekly_recovery import load_private_readonly_settings


HERE = Path(__file__).parent
FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")
CUTOFF = date(2026, 9, 18)
AUDIT_PRODUCTS = ("pf", "pk", "pl", "pr", "px", "rs", "sf", "sh", "sm", "sr")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate_sha(bars) -> str:
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
        sink, compression="zstd", use_dictionary=False, version="2.6",
    )
    return sha(sink.getvalue().to_pybytes())


def identity(part, root: Path) -> dict:
    path = part.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("PARTITION_PATH_INVALID")
    return {
        "year": part.year, "month": part.month,
        "uri": path.relative_to(root).as_posix(),
        "sha256": sha(path.read_bytes()),
        "row_count": part.row_count,
        "quality_sha256": part.source_quality_sha256,
    }


def main() -> None:
    snapshot = json.loads((HERE / "physical-causes.json").read_text())
    if snapshot.get("revision_stable") is not True:
        raise ValueError("SNAPSHOT_REVISION_UNSTABLE")
    targets = defaultdict(set)
    for item in snapshot["contracts"]:
        if item["symbol"] == "rs":
            for issue in item.get("issues", []):
                if issue["kind"] == "STRICT_NO_TRADE_AGGREGATION":
                    targets[item["contract"]].add(date.fromisoformat(issue["week_end"]))
    if sum(map(len, targets.values())) != 133:
        raise ValueError("RS_TARGET_COUNT_MOVED")

    settings, root_identity = load_private_readonly_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    months = []
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            before = catalog_revision(session, AUDIT_PRODUCTS, CUTOFF, ("1d", "1w"))
            if before != snapshot["catalog_revision"]:
                raise ValueError("CATALOG_REVISION_MOVED")
            catalog = MarketCatalog(session, root)
            store = CanonicalMonthlyStore(root)
            mds = MarketDataService(catalog, store)
            for contract in sorted(targets):
                d1_key = DatasetKey("contract", "rs", contract, "1d")
                w1_key = DatasetKey("contract", "rs", contract, "1w")
                needed_weeks = {day.isocalendar()[:2] for day in targets[contract]}
                daily = defaultdict(list)
                d1_sources = defaultdict(list)
                for part in catalog.all_partitions(d1_key):
                    bars, facts = store.read_catalog_partition_quality(part)
                    chosen = [b for b in bars if b.trading_day.isocalendar()[:2] in needed_weeks]
                    if any(f.trading_day.isocalendar()[:2] in needed_weeks for f in facts):
                        raise ValueError("D1_QUALITY_IN_TARGET_WEEK")
                    if chosen:
                        source = identity(part, root)
                        for bar in chosen:
                            week = bar.trading_day.isocalendar()[:2]
                            daily[week].append(bar)
                            if source not in d1_sources[week]:
                                d1_sources[week].append(source)
                found = set()
                for part in catalog.all_partitions(w1_key):
                    selected = {day for day in targets[contract]
                                if (day.year, day.month) == (part.year, part.month)}
                    if not selected:
                        continue
                    old_bars = store.read_catalog_partition(part)
                    replace = {}
                    diffs = []
                    sources = []
                    for day in sorted(selected):
                        matches = [bar for bar in old_bars if bar.trading_day == day]
                        if len(matches) != 1:
                            raise ValueError("W1_TARGET_ROW_INVALID")
                        old = matches[0]
                        week = day.isocalendar()[:2]
                        actual = sorted(daily[week], key=lambda b: b.bar_end)
                        expected = tuple(point for point in mds.expected_contract_replay_endpoints(
                            symbol="rs", contract=contract, frequency=d1_key.frequency,
                            trading_day=day, cutoff=old.bar_end,
                        ) if point[1].isocalendar()[:2] == week)
                        if not expected or tuple((b.bar_end, b.trading_day) for b in actual) != expected:
                            raise ValueError("D1_COMPLETE_WEEK_INVALID")
                        new = _aggregate_daily_rows(tuple(
                            (bar.trading_day, {f: getattr(bar, f) for f in FIELDS})
                            for bar in actual
                        ), bar_end=old.bar_end)
                        changed = [f for f in FIELDS if getattr(old, f) != getattr(new, f)]
                        if not changed or any(f not in ("open", "high", "low", "close") for f in changed):
                            raise ValueError("W1_DIFF_NOT_OHLC_ONLY")
                        replace[day] = new
                        diffs.append({"week_end": day.isoformat(), "changed_fields": changed,
                                      "old": {f: str(getattr(old, f)) for f in changed},
                                      "new": {f: str(getattr(new, f)) for f in changed},
                                      "expected_d1_endpoints": [[e.isoformat(), d.isoformat()] for e, d in expected]})
                        for source in d1_sources[week]:
                            if source not in sources:
                                sources.append(source)
                        found.add(day)
                    candidate = tuple(replace.get(b.trading_day, b) for b in old_bars)
                    digest = candidate_sha(candidate)
                    months.append({
                        "contract": contract, "year": part.year, "month": part.month,
                        "old_partition": identity(part, root),
                        "candidate_sha256": digest,
                        "candidate_uri": (part.file_path.parent.relative_to(root) / f"part.{digest}.parquet").as_posix(),
                        "changed_rows": len(diffs), "retained_rows": len(old_bars) - len(diffs),
                        "d1_preimages": sources, "diffs": diffs,
                    })
                if found != targets[contract]:
                    raise ValueError("W1_TARGETS_NOT_EXHAUSTED")
            after = catalog_revision(session, AUDIT_PRODUCTS, CUTOFF, ("1d", "1w"))
            if before != after:
                raise ValueError("CATALOG_REVISION_MOVED")
            session.rollback()
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            fresh = catalog_revision(session, AUDIT_PRODUCTS, CUTOFF, ("1d", "1w"))
            session.rollback()
        if fresh != before:
            raise ValueError("CATALOG_REVISION_MOVED")
        packet = {
            "schema_version": "rs_weekly_no_trade_prepare_v1",
            "code_sha": snapshot["code_sha"],
            "catalog_revision": before,
            "canonical_root_sha256": root_identity["canonical_root_sha256"],
            "aggregation_version": WEEKLY_AGGREGATION_VERSION,
            "source_sha256": sha(Path(__file__).read_bytes()),
            "provider_requests": 0, "writes": 0,
            "month_count": len(months), "week_count": sum(x["changed_rows"] for x in months),
            "months": months,
        }
        if packet["month_count"] != 64 or packet["week_count"] != 133:
            raise ValueError("RS_BATCH_COUNT_MOVED")
        output = HERE / "rs-no-trade-prepare.json"
        content = (json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        output.write_bytes(content)
        print(json.dumps({"status": "prepared", "months": len(months),
                          "weeks": packet["week_count"], "sha256": sha(content)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
