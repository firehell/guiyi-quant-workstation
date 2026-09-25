"""Exact SH W1 missing-week and receipt-backed turnover repair."""

import argparse
from collections import defaultdict
from datetime import date, datetime
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
from app.market_data.domain import BarFrequency, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_home_projection import MarketHomeProjectionStore, market_home_projection_path
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.product_reader import _is_strict_no_trade_fact
from app.market_data.rqdata_adapter import WEEKLY_AGGREGATION_VERSION, _aggregate_daily_rows
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from scripts.newow_weekly_recovery import load_private_readonly_settings

HERE = Path(__file__).parent
ENV = Path.home() / "Library/Application Support/GuiyiQuant/project.env"
AUDIT = HERE / "physical-causes.json"
RECEIPTS = ROOT / "outputs/newow-weekly-remaining10-20260924/conflict-receipt-map.json"
PREPARED = HERE / "sh-w1-prepare.json"
CUTOFF = date(2026, 9, 18)
FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def candidate_sha(bars) -> str:
    sink = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([bar.as_record() for bar in bars], schema=CANONICAL_SCHEMA),
                   sink, compression="zstd", use_dictionary=False, version="2.6")
    return sha(sink.getvalue().to_pybytes())


def identity(part, root: Path):
    path = part.file_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("PARTITION_PATH_INVALID")
    return {"year": part.year, "month": part.month,
            "uri": path.relative_to(root).as_posix(), "sha256": file_sha(path),
            "row_count": part.row_count, "quality_sha256": part.source_quality_sha256}


def load_targets():
    audit = json.loads(AUDIT.read_bytes())
    if (audit["products"] != ["sh"] or audit["revision_stable"] is not True
            or audit["provider_requests"] != 0 or audit["writes"] != 0
            or len(audit["contracts"]) != 11
            or any(row["status"] not in {"SCANNED", "NO_OWNED_COMPLETED_WEEK"}
                   for row in audit["contracts"])):
        raise ValueError("AUDIT_SCOPE_INVALID")
    targets = defaultdict(list)
    counts = defaultdict(int)
    for contract in audit["contracts"]:
        for issue in contract["issues"]:
            counts[issue["kind"]] += 1
            if issue["kind"] in {"W1_MISSING_D1_COMPLETE", "D1_W1_VALUE_CONFLICT",
                                 "STRICT_NO_TRADE_AGGREGATION"}:
                targets[contract["contract"]].append(issue)
            elif issue["kind"] != "PROVEN_QUALITY_INTERRUPTION":
                raise ValueError("UNEXPECTED_ISSUE_CLASS")
    if (dict(counts) != {"W1_MISSING_D1_COMPLETE": 162,
                         "D1_W1_VALUE_CONFLICT": 4,
                         "PROVEN_QUALITY_INTERRUPTION": 5}
            or len(targets) != 5):
        raise ValueError("ISSUE_COUNTS_MOVED")
    receipts = json.loads(RECEIPTS.read_bytes())
    evidence = {}
    for row in receipts["rows"]:
        if row["symbol"] != "sh" or not row["all_daily_receipted"]:
            continue
        key = (row["contract"], row["week_end"])
        entries = []
        for part in row["daily_partitions"]:
            for receipt_path in part["matching_receipts"]:
                path = ROOT / receipt_path
                if not path.resolve().is_relative_to(ROOT.resolve()):
                    raise ValueError("RECEIPT_PATH_INVALID")
                receipt = json.loads(path.read_bytes())
                if (receipt["status"] != "passed" or receipt["contract"] != row["contract"]
                        or receipt["frequency"] != "1d" or receipt["result"]["status"] != "passed"
                        or not any(item["year"] == part["year"] and item["month"] == part["month"]
                                   and item["dataset"] == ["contract", "sh", row["contract"], "1d"]
                                   and ("part." + item["file_sha256"] + ".parquet") == part["file"]
                                   for item in receipt["readback"]["catalog_partitions"])):
                    raise ValueError("RECEIPT_READBACK_MISMATCH")
                entries.append({"path": receipt_path, "sha256": file_sha(path)})
        evidence[key] = entries
    if len(evidence) != 4:
        raise ValueError("RECEIPT_COUNT_INVALID")
    return audit, targets, evidence


def build_packet(session, root: Path, config_identity):
    audit, targets, receipt_evidence = load_targets()
    revision = catalog_revision(session, ("sh",), CUTOFF, ("1d", "1w"))
    if revision != audit["catalog_revision"]:
        raise ValueError("CATALOG_REVISION_MOVED")
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    mds = MarketDataService(catalog, store)
    months = []
    candidates = {}
    source_evidence = []
    for contract in sorted(targets):
        d1_key = DatasetKey("contract", "sh", contract, "1d")
        w1_key = DatasetKey("contract", "sh", contract, "1w")
        d1_parts = catalog.all_partitions(d1_key)
        w1_parts = {(part.year, part.month): part for part in catalog.all_partitions(w1_key)}
        by_week = defaultdict(list)
        facts_by_week = defaultdict(list)
        source_by_week = defaultdict(list)
        wanted = {date.fromisoformat(issue["week_end"]).isocalendar()[:2] for issue in targets[contract]}
        for part in d1_parts:
            bars, facts = store.read_catalog_partition_quality(part)
            relevant = [bar for bar in bars if bar.trading_day.isocalendar()[:2] in wanted]
            for fact in facts:
                if fact.trading_day.isocalendar()[:2] in wanted:
                    facts_by_week[fact.trading_day.isocalendar()[:2]].append(fact)
            if relevant:
                source = identity(part, root)
                for bar in relevant:
                    week = bar.trading_day.isocalendar()[:2]
                    by_week[week].append(bar)
                    if source not in source_by_week[week]:
                        source_by_week[week].append(source)
        grouped = defaultdict(list)
        for issue in targets[contract]:
            day = date.fromisoformat(issue["week_end"])
            week = day.isocalendar()[:2]
            weekly_points = [point for point in mds.expected_contract_replay_endpoints(
                symbol="sh", contract=contract, frequency=w1_key.frequency,
                trading_day=day, cutoff=datetime.fromisoformat(audit["as_of"]),
            ) if point[1] == day]
            if len(weekly_points) != 1:
                raise ValueError("W1_ENDPOINT_INVALID")
            week_end = weekly_points[0][0]
            actual = tuple(sorted(by_week[week], key=lambda bar: bar.bar_end))
            expected = tuple(point for point in mds.expected_contract_replay_endpoints(
                symbol="sh", contract=contract, frequency=d1_key.frequency,
                trading_day=day, cutoff=week_end,
            ) if point[1].isocalendar()[:2] == week)
            if (not expected or tuple((bar.bar_end, bar.trading_day) for bar in actual) != expected
                    or facts_by_week[week]):
                raise ValueError("D1_COMPLETE_WEEK_INVALID")
            bar = _aggregate_daily_rows(tuple(
                (item.trading_day, {field: getattr(item, field) for field in FIELDS})
                for item in actual
            ), bar_end=week_end)
            if bar.trading_day != day:
                raise ValueError("AGGREGATE_DAY_INVALID")
            if issue["kind"] == "W1_MISSING_D1_COMPLETE":
                no_trade_days = [item.trading_day.isoformat() for item in actual
                                 if _is_strict_no_trade_fact(item)]
                week_type = ("ALL_NO_TRADE" if len(no_trade_days) == len(actual) else
                             "MIXED_NO_TRADE" if no_trade_days else "NORMAL")
                if (issue["daily_count"] != len(actual)
                        or issue["no_trade_days"] != no_trade_days
                        or issue["missing_week_type"] != week_type):
                    raise ValueError("MISSING_WEEK_FACTS_DRIFT")
            else:
                if issue["expected"] != {field: str(getattr(bar, field)) for field in FIELDS}:
                    raise ValueError("AUDIT_AGGREGATE_DRIFT")
            receipts = []
            if issue["kind"] == "D1_W1_VALUE_CONFLICT":
                if issue["fields"] != ["turnover"]:
                    raise ValueError("CONFLICT_SCOPE_INVALID")
                key = (contract, day.isoformat())
                receipts = receipt_evidence.get(key, [])
                if not receipts:
                    raise ValueError("CONFLICT_RECEIPT_MISSING")
                source_evidence.extend(item for item in receipts if item not in source_evidence)
            grouped[(day.year, day.month)].append((issue, bar, source_by_week[week], receipts,
                                                   [[end.isoformat(), d.isoformat()] for end, d in expected]))
        for (year, month), items in sorted(grouped.items()):
            old_part = w1_parts.get((year, month))
            old_bars = store.read_catalog_partition(old_part) if old_part else ()
            existing = {bar.trading_day: bar for bar in old_bars}
            if len(existing) != len(old_bars):
                raise ValueError("DUPLICATE_OLD_W1_DAY")
            changes = []
            d1_sources = []
            for issue, new_bar, week_sources, receipts, endpoints in items:
                day = new_bar.trading_day
                old_bar = existing.get(day)
                if issue["kind"] == "W1_MISSING_D1_COMPLETE":
                    if old_bar is not None or issue["stored_weekly"]:
                        raise ValueError("MISSING_WEEK_DRIFT")
                    action = "insert"
                elif issue["kind"] == "STRICT_NO_TRADE_AGGREGATION":
                    if old_bar is None or old_bar.bar_end != new_bar.bar_end:
                        raise ValueError("NO_TRADE_WEEK_DRIFT")
                    diff = [field for field in FIELDS if getattr(old_bar, field) != getattr(new_bar, field)]
                    if not diff or any(field not in ("open", "high", "low", "close") for field in diff):
                        raise ValueError("NO_TRADE_DIFF_DRIFT")
                    action = "rebuild_ohlc"
                else:
                    if old_bar is None or old_bar.bar_end != new_bar.bar_end:
                        raise ValueError("CONFLICT_WEEK_DRIFT")
                    diff = [field for field in FIELDS if getattr(old_bar, field) != getattr(new_bar, field)]
                    if diff != ["turnover"]:
                        raise ValueError("CONFLICT_FIELDS_DRIFT")
                    action = "replace_turnover"
                if old_bar is not None and issue["stored"] != {
                    field: str(getattr(old_bar, field)) for field in FIELDS
                }:
                    raise ValueError("AUDIT_STORED_WEEK_DRIFT")
                existing[day] = new_bar
                for source in week_sources:
                    if source not in d1_sources:
                        d1_sources.append(source)
                changes.append({"day": day.isoformat(), "action": action,
                                "bar_end": new_bar.bar_end.isoformat(),
                                "new": {field: str(getattr(new_bar, field)) for field in FIELDS},
                                "old_turnover": str(old_bar.turnover) if old_bar else None,
                                "d1_endpoints": endpoints,
                                "receipt_evidence": receipts})
            new_bars = tuple(sorted(existing.values(), key=lambda bar: bar.bar_end))
            if len({bar.bar_end for bar in new_bars}) != len(new_bars):
                raise ValueError("DUPLICATE_W1_ENDPOINT")
            digest = candidate_sha(new_bars)
            parent = store.month_path(w1_key, year, month).parent
            if old_part and old_part.file_path.parent != parent:
                raise ValueError("OLD_PARTITION_DIRECTORY_INVALID")
            candidate_uri = (parent.relative_to(root) / f"part.{digest}.parquet").as_posix()
            record = {"contract": contract, "year": year, "month": month,
                      "old_partition": identity(old_part, root) if old_part else None,
                      "candidate_sha256": digest, "candidate_uri": candidate_uri,
                      "row_count": len(new_bars), "d1_preimages": d1_sources,
                      "changes": changes}
            months.append(record)
            candidates[(contract, year, month)] = new_bars
    counts = {name: sum(change["action"] == name for row in months for change in row["changes"])
              for name in ("insert", "rebuild_ohlc", "replace_turnover")}
    if len(months) != 43 or counts != {"insert": 162, "rebuild_ohlc": 0,
                                        "replace_turnover": 4}:
        raise ValueError("BATCH_COUNTS_MOVED")
    packet = {"schema_version": "sh_w1_missing_and_turnover_prepare_v1",
              "code_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
              "source_sha256": file_sha(Path(__file__)), "audit_sha256": file_sha(AUDIT),
              "receipt_map_sha256": file_sha(RECEIPTS), "receipt_evidence": source_evidence,
              "project_env_sha256": config_identity["config_sha256"],
              "canonical_root_sha256": config_identity["canonical_root_sha256"],
              "catalog_revision": revision, "aggregation_version": WEEKLY_AGGREGATION_VERSION,
              "provider_requests": 0, "writes": 0, "month_count": len(months),
              "week_counts": counts, "months": months}
    return packet, candidates


def mds_readback(catalog, store, packet):
    mds = MarketDataService(catalog, store)
    targets = defaultdict(set)
    cutoffs = {}
    throughs = {}
    for record in packet["months"]:
        for change in record["changes"]:
            day = date.fromisoformat(change["day"])
            targets[record["contract"]].add(day)
            throughs[record["contract"]] = max(day, throughs.get(record["contract"], day))
            end = datetime.fromisoformat(change["bar_end"])
            cutoffs[record["contract"]] = max(end, cutoffs.get(record["contract"], end))
    audit = json.loads(AUDIT.read_bytes())
    quality_only = [row for row in audit["contracts"]
                    if row["contract"] not in targets
                    and any(issue["kind"] == "PROVEN_QUALITY_INTERRUPTION" for issue in row["issues"])]
    if quality_only:
        raise ValueError("UNEXPECTED_QUALITY_ONLY_CONTRACT")
    interruptions = set()
    for contract, days in targets.items():
        bars, gaps = mds.query_contract_weekly_replay_quality(
            symbol="sh", contract=contract, through=throughs[contract], cutoff=cutoffs[contract],
            classification_version="weekly-d1-quality-v2",
        )
        observed = {bar.trading_day for bar in bars}
        if not days.issubset(observed) or any(gap.trading_day in days for gap in gaps):
            raise ValueError("MDS_TARGET_WEEK_UNAVAILABLE")
        interruptions.update((contract, gap.trading_day) for gap in gaps)
    expected_gaps = {
        (row["contract"], date.fromisoformat(issue["week_end"]))
        for row in audit["contracts"] if row["contract"] in targets
        for issue in row["issues"] if issue["kind"] == "PROVEN_QUALITY_INTERRUPTION"
        and date.fromisoformat(issue["week_end"]) <= throughs[row["contract"]]
    }
    if len(expected_gaps) != 5 or interruptions != expected_gaps:
        raise ValueError("MDS_QUALITY_INTERRUPTION_MOVED")


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("mode", choices=("prepare", "dry-run", "inspect", "apply"))
    parser.add_argument("--expected-prepared-sha256")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply != (args.mode == "apply"):
        raise ValueError("APPLY_FLAG_INVALID")
    settings, config_identity = load_private_readonly_settings(ENV)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        if args.mode == "prepare":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                packet, _ = build_packet(session, root, config_identity)
                session.rollback()
            raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            PREPARED.write_bytes(raw)
            print(json.dumps({"status": "prepared", "sha256": sha(raw),
                              "months": packet["month_count"], "weeks": packet["week_counts"]}))
            return
        raw = PREPARED.read_bytes()
        if sha(raw) != args.expected_prepared_sha256:
            raise ValueError("PREPARED_HASH_MISMATCH")
        packet = json.loads(raw)
        if (packet["schema_version"] != "sh_w1_missing_and_turnover_prepare_v1"
                or packet["source_sha256"] != file_sha(Path(__file__))
                or packet["project_env_sha256"] != config_identity["config_sha256"]
                or packet["canonical_root_sha256"] != config_identity["canonical_root_sha256"]
                or packet["month_count"] != 43
                or packet["week_counts"] != {"insert": 162, "rebuild_ohlc": 0,
                                              "replace_turnover": 4}
                or packet["provider_requests"] != 0 or packet["writes"] != 0):
            raise ValueError("PACKET_IDENTITY_INVALID")
        if args.mode == "inspect":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                catalog = MarketCatalog(session, root)
                states = []
                for record in packet["months"]:
                    key = DatasetKey("contract", "sh", record["contract"], "1w")
                    found = [part for part in catalog.all_partitions(key)
                             if (part.year, part.month) == (record["year"], record["month"])]
                    current = identity(found[0], root) if len(found) == 1 else None
                    if current == record["old_partition"]:
                        states.append("old")
                    elif (current is not None and current["uri"] == record["candidate_uri"]
                          and current["sha256"] == record["candidate_sha256"]):
                        states.append("candidate")
                    else:
                        states.append("other")
                observed_revision = catalog_revision(session, ("sh",), CUTOFF, ("1d", "1w"))
                session.rollback()
            print(json.dumps({"status": "old" if set(states) == {"old"} else
                              "candidate" if set(states) == {"candidate"} else "mixed_or_unknown",
                              "old": states.count("old"), "candidate": states.count("candidate"),
                              "other": states.count("other"),
                              "observed_catalog_revision": observed_revision}))
            return
        if args.mode == "dry-run":
            with Session(engine, autoflush=False) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                fresh, _ = build_packet(session, root, config_identity)
                if fresh != packet:
                    raise ValueError("DRY_RUN_DRIFT")
                session.rollback()
            print(json.dumps({"status": "dry_run_passed", "sha256": sha(raw),
                              "months": packet["month_count"], "weeks": packet["week_counts"], "writes": 0}))
            return
        with Session(engine, autoflush=False) as session:
            catalog = MarketCatalog(session, root)
            lease = catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError("MAINTENANCE_LOCK_UNAVAILABLE")
            committed = False
            try:
                fresh, candidates = build_packet(session, root, config_identity)
                if fresh != packet:
                    raise ValueError("APPLY_DRIFT")
                store = CanonicalMonthlyStore(root)
                MarketHomeProjectionStore(market_home_projection_path(root)).invalidate()
                for record in packet["months"]:
                    key = DatasetKey("contract", "sh", record["contract"], "1w")
                    bars = candidates[(record["contract"], record["year"], record["month"])]
                    published = store.publish(PublishRequest(key, record["year"], record["month"],
                                                             bars, tuple(bar.bar_end for bar in bars)))
                    if (published.parquet_path.relative_to(root).as_posix() != record["candidate_uri"]
                            or file_sha(published.parquet_path) != record["candidate_sha256"]):
                        raise ValueError("PUBLISHED_CANDIDATE_INVALID")
                    catalog.register_partition(published)
                    active = [part for part in catalog.all_partitions(key)
                              if (part.year, part.month) == (record["year"], record["month"])]
                    if (len(active) != 1 or identity(active[0], root)["sha256"] != record["candidate_sha256"]
                            or store.read_catalog_partition(active[0]) != bars):
                        raise ValueError("PRECOMMIT_W1_READBACK_INVALID")
                mds_readback(catalog, store, packet)
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
            for record in packet["months"]:
                key = DatasetKey("contract", "sh", record["contract"], "1w")
                active = [part for part in catalog.all_partitions(key)
                          if (part.year, part.month) == (record["year"], record["month"])]
                if (len(active) != 1 or identity(active[0], root)["sha256"] != record["candidate_sha256"]
                        or len(store.read_catalog_partition(active[0])) != record["row_count"]):
                    raise ValueError("POSTCOMMIT_W1_READBACK_INVALID")
            mds_readback(catalog, store, packet)
            session.rollback()
        print(json.dumps({"status": "committed", "sha256": sha(raw),
                          "months": packet["month_count"], "weeks": packet["week_counts"], "readback": "passed"}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_code":
                          str(exc) if type(exc) is ValueError and str(exc).isupper() else type(exc).__name__}))
        raise SystemExit(1)
