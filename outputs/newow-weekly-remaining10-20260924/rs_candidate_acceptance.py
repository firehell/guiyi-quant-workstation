"""Read-only in-memory RS W1 candidate acceptance for the frozen month packet."""

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow import readiness_composition
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.storage import CanonicalMonthlyStore
from guiyi_quant.newow.product_contracts import ProductFrequency
from scripts.newow_weekly_recovery import load_private_readonly_settings

from rs_no_trade_prepare import HERE, candidate_sha, sha


def main() -> None:
    path = HERE / "rs-no-trade-prepare.json"
    content = path.read_bytes()
    packet = json.loads(content)
    settings, root_identity = load_private_readonly_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    if packet["canonical_root_sha256"] != root_identity["canonical_root_sha256"]:
        raise ValueError("CANONICAL_ROOT_MOVED")
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            current = catalog_revision(session, ("pf", "pk", "pl", "pr", "px", "rs", "sf", "sh", "sm", "sr"),
                                       datetime(2026, 9, 18).date(), ("1d", "1w"))
            if current != packet["catalog_revision"]:
                raise ValueError("CATALOG_REVISION_MOVED")
            catalog = MarketCatalog(session, root)
            store = CanonicalMonthlyStore(root)
            original_parts = catalog.all_partitions
            original_window_parts = catalog.partitions
            original_before_parts = catalog.partitions_before
            original_product_parts = catalog.product_partitions
            original_read = store.read_catalog_partition
            overlays = {}
            synthetic = {}
            for record in packet["months"]:
                key = DatasetKey("contract", "rs", record["contract"], "1w")
                matches = [p for p in original_parts(key)
                           if (p.year, p.month) == (record["year"], record["month"])]
                if len(matches) != 1:
                    raise ValueError("OLD_PARTITION_MOVED")
                old = matches[0]
                if (old.file_path.relative_to(root).as_posix() != record["old_partition"]["uri"]
                        or sha(old.file_path.read_bytes()) != record["old_partition"]["sha256"]):
                    raise ValueError("OLD_PARTITION_MOVED")
                changes = {diff["week_end"]: diff for diff in record["diffs"]}
                candidate = []
                for bar in original_read(old):
                    diff = changes.pop(bar.trading_day.isoformat(), None)
                    if diff is not None:
                        if any(str(getattr(bar, field)) != value for field, value in diff["old"].items()):
                            raise ValueError("OLD_ROW_MOVED")
                        bar = replace(bar, **{field: Decimal(value) for field, value in diff["new"].items()})
                    candidate.append(bar)
                if changes or candidate_sha(tuple(candidate)) != record["candidate_sha256"]:
                    raise ValueError("CANDIDATE_HASH_MISMATCH")
                path = root / record["candidate_uri"]
                overlays[path] = tuple(candidate)
                synthetic[(key, record["year"], record["month"])] = CatalogPartition(
                    key, old.year, old.month, old.coverage_start, old.coverage_end, path, len(candidate)
                )

            def all_partitions(key):
                rows = original_parts(key)
                return tuple(synthetic.get((key, p.year, p.month), p) for p in rows)

            def window_partitions(key, start, end):
                rows = original_window_parts(key, start, end)
                return tuple(synthetic.get((key, p.year, p.month), p) for p in rows)

            def before_partitions(key, before):
                rows = original_before_parts(key, before)
                return tuple(synthetic.get((key, p.year, p.month), p) for p in rows)

            def product_partitions(symbol):
                rows = original_product_parts(symbol)
                return tuple(synthetic.get((p.key, p.year, p.month), p) for p in rows)

            def read_partition(part):
                return overlays.get(part.file_path) or original_read(part)

            catalog.all_partitions = all_partitions
            catalog.partitions = window_partitions
            catalog.partitions_before = before_partitions
            catalog.product_partitions = product_partitions
            store.read_catalog_partition = read_partition
            market = MarketDataService(catalog, store)
            readiness_composition.build_market_data_service = lambda _: market
            traced = set()
            def trace(frame, event, arg):
                if event == "exception" and str(arg[1]) == "NEWOW_DATA_IDENTITY_INVALID":
                    key = (frame.f_code.co_filename, frame.f_lineno)
                    if key not in traced:
                        print("candidate_identity_exception", key, flush=True)
                        if frame.f_code.co_filename.endswith("product_service.py") and frame.f_lineno == 594:
                            print("collision", frame.f_locals.get("day_key"), flush=True)
                            gap = frame.f_locals.get("gap")
                            print("gap_kind", type(gap).__name__, "gap_source", getattr(gap, "source_identity", None), flush=True)
                            read = frame.f_locals.get("read")
                            print("colliding_bars", [(str(item.bar.trading_day), item.bar.physical_contract, item.bar.source_identity)
                                  for item in read.replay_bars if str(item.bar.trading_day) == "2025-09-19"], flush=True)
                            print("bar_lists", [(str(freq), [(str(item.bar.trading_day), item.bar.physical_contract)
                                   for item in bars if str(item.bar.trading_day) == "2025-09-19"])
                                   for freq, bars in read.bars_by_frequency.items()], flush=True)
                            print("gap_lists", [(str(freq), [(str(item.trading_day), item.physical_contract, item.segment_id)
                                   for item in gaps if str(item.trading_day) == "2025-09-19"])
                                   for freq, gaps in read.data_interruptions_by_frequency.items()], flush=True)
                        traced.add(key)
                return trace
            sys.settrace(trace)
            report = readiness_composition.build_newow_readiness(
                session,
                request=ReadinessRequest(
                    products=("rs",),
                    as_of=datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00"),
                    matrix=True, max_work=100000, timeout_seconds=600,
                    frequencies=(ProductFrequency.WEEKLY,), candidate_weekly=True,
                ),
            )
            sys.settrace(None)
            result = {"basis": "read-only in-memory Catalog/Store overlay",
                      "prepare_sha256": hashlib.sha256(content).hexdigest(),
                      "runner_sha256": sha(Path(__file__).read_bytes()), "report": report}
            (HERE / "rs-candidate-acceptance.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
            )
            print(json.dumps({"status": report["status"], "complete": report["complete"],
                              "weekly": [(c["strategy"], c["main"]["status"])
                                         for c in report["cases"] if c["frequency"] == "1w"]}))
            session.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
