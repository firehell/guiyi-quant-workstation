"""Read-only MDS preview with rolled-back candidate files overlaid in memory."""

import json
import sys
from pathlib import Path
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/quant-api"), str(ROOT / "packages/quant-core"), str(ROOT)]
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog, CatalogPartition
from app.market_data.domain import DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from scripts.newow_weekly_recovery import load_private_readonly_settings


class OverlayCatalog:
    def __init__(self, catalog, root, packet):
        self.base = catalog
        self.root = root
        self.packet = packet

    def __getattr__(self, name):
        return getattr(self.base, name)

    def all_partitions(self, key):
        existing = tuple(self.base.all_partitions(key))
        if key.symbol != "pk" or key.frequency.value != "1w":
            return existing
        selected = {(part.year, part.month): part for part in existing}
        for item in self.packet["months"]:
            if item["contract"] != key.series_or_contract:
                continue
            year, month = item["year"], item["month"]
            bars = tuple(CanonicalMonthlyStore(self.root)._read_path(self.root / item["candidate_uri"]))
            selected[(year, month)] = CatalogPartition(
                dataset=key, year=year, month=month,
                coverage_start=bars[0].bar_end - timedelta(days=7), coverage_end=bars[-1].bar_end,
                file_path=self.root / item["candidate_uri"], row_count=len(bars),
                source_coverage_start=bars[0].bar_end - timedelta(days=7), source_coverage_end=bars[-1].bar_end,
            )
        return tuple(selected[key] for key in sorted(selected))


def main():
    settings, _ = load_private_readonly_settings(Path.home() / "Library/Application Support/GuiyiQuant/project.env")
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    packet = json.loads((Path(__file__).parent / "pk-w1-prepare.json").read_bytes())
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
    try:
        with Session(engine, autoflush=False) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            overlay = OverlayCatalog(MarketCatalog(session, root), root, packet)
            mds = MarketDataService(overlay, CanonicalMonthlyStore(root))
            for contract in ("PK2411", "PK2511", "PK2603", "PK2611"):
                days = [date.fromisoformat(change["day"]) for item in packet["months"]
                        if item["contract"] == contract for change in item["changes"]]
                cutoff = max(datetime.fromisoformat(change["bar_end"])
                             for item in packet["months"] if item["contract"] == contract
                             for change in item["changes"])
                try:
                    bars, gaps = mds.query_contract_weekly_replay_quality(
                        symbol="pk", contract=contract, through=max(days),
                        cutoff=cutoff,
                        classification_version="weekly-d1-quality-v2",
                    )
                    print(json.dumps({"contract": contract, "status": "passed", "bars": len(bars),
                                      "target_bars": sum(bar.trading_day in days for bar in bars),
                                      "gaps": [gap.trading_day.isoformat() for gap in gaps]}))
                except Exception as exc:
                    print(json.dumps({"contract": contract, "status": "failed",
                                      "type": type(exc).__name__,
                                      "code": getattr(exc, "code", None),
                                      "reason": getattr(exc, "reason", None),
                                      "context": {k: str(v) for k, v in getattr(exc, "context", {}).items()}}))
            session.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
