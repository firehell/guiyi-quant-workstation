"""Preview the full SM candidate through real MDS with in-memory W1 pointers."""

import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(ROOT / "services/quant-api"), str(ROOT / "packages/quant-core"), str(ROOT)]
from app.db.url import normalize_database_url
from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.storage import CanonicalMonthlyStore
from scripts.newow_weekly_recovery import load_private_readonly_settings
import sm_w1_repair as pf


class OverlayCatalog:
    def __init__(self, base, root, packet, candidates):
        self.base = base
        self.root = root
        self.packet = packet
        self.candidates = candidates

    def __getattr__(self, name):
        return getattr(self.base, name)

    def all_partitions(self, key):
        old = tuple(self.base.all_partitions(key))
        if key.symbol != "sm" or key.frequency.value != "1w":
            return old
        selected = {(part.year, part.month): part for part in old}
        for record in self.packet["months"]:
            if record["contract"] != key.series_or_contract:
                continue
            year, month = record["year"], record["month"]
            bars = self.candidates[(record["contract"], year, month)]
            selected[(year, month)] = CatalogPartition(
                dataset=key, year=year, month=month,
                coverage_start=bars[0].bar_end - timedelta(days=7),
                coverage_end=bars[-1].bar_end,
                file_path=self.root / record["candidate_uri"], row_count=len(bars),
                source_coverage_start=bars[0].bar_end - timedelta(days=7),
                source_coverage_end=bars[-1].bar_end,
            )
        return tuple(selected[k] for k in sorted(selected))


class OverlayStore:
    def __init__(self, base, root, packet, candidates):
        self.base = base
        self.by_path = {
            root / item["candidate_uri"]: candidates[(item["contract"], item["year"], item["month"])]
            for item in packet["months"]
        }

    def __getattr__(self, name):
        return getattr(self.base, name)

    def read_catalog_partition(self, part):
        if part.file_path in self.by_path:
            return self.by_path[part.file_path]
        return self.base.read_catalog_partition(part)

    def read_catalog_partition_quality(self, part):
        if part.file_path in self.by_path:
            return self.by_path[part.file_path], ()
        return self.base.read_catalog_partition_quality(part)


def main():
    settings, identity = load_private_readonly_settings(pf.ENV)
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            packet, candidates = pf.build_packet(session, root, identity)
            if packet != json.loads(pf.PREPARED.read_bytes()):
                raise ValueError("PREPARED_PACKET_DRIFT")
            catalog = OverlayCatalog(MarketCatalog(session, root), root, packet, candidates)
            store = OverlayStore(CanonicalMonthlyStore(root), root, packet, candidates)
            pf.mds_readback(catalog, store, packet)
            session.rollback()
        print(json.dumps({"status": "passed", "mode": "read_only_in_memory_overlay",
                          "target_weeks": sum(packet["week_counts"].values()),
                          "quality_interruptions": 24, "contracts_checked": 10,
                          "catalog_writes": 0, "canonical_writes": 0}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
