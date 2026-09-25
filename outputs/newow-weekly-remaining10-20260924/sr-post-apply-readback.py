"""Independent read-only proof for the authorized SR2303 W1 month repair."""

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.storage import CanonicalMonthlyStore
from scripts.newow_weekly_recovery import load_private_readonly_settings

here = Path(__file__).resolve().parent
packet = json.loads((here / "sr-prepare.json").read_text())
target = packet["targets"][0]
settings, identity = load_private_readonly_settings(
    Path.home() / "Library/Application Support/GuiyiQuant/project.env"
)
root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
if identity["canonical_root_sha256"] != packet["canonical_root_sha256"]:
    raise ValueError("CANONICAL_ROOT_MOVED")
engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
try:
    with Session(engine, autoflush=False) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        catalog = MarketCatalog(session, root)
        store = CanonicalMonthlyStore(root)
        key = DatasetKey("contract", "sr", "SR2303", "1w")
        parts = [part for part in catalog.all_partitions(key)
                 if (part.year, part.month) == (2022, 3)]
        if len(parts) != 1:
            raise ValueError("W1_POINTER_COUNT_INVALID")
        part = parts[0]
        uri = part.file_path.relative_to(root).as_posix()
        sha = hashlib.sha256(part.file_path.read_bytes()).hexdigest()
        if (uri, sha) != (target["candidate_w1_partition_uri"],
                          target["candidate_w1_partition_sha256"]):
            raise ValueError("W1_POINTER_NOT_CANDIDATE")
        old_path = root / target["old_w1_partition_uri"]
        if hashlib.sha256(old_path.read_bytes()).hexdigest() != target["old_w1_partition_sha256"]:
            raise ValueError("OLD_W1_NOT_RECOVERABLE")
        current = store.read_catalog_partition(part)
        old = store.read_catalog_partition(replace(part, file_path=old_path))
        changed = [(a.trading_day.isoformat(), b.trading_day.isoformat())
                   for a, b in zip(old, current, strict=True) if a != b]
        if len(old) != target["month_row_count"] or len(current) != len(old) or changed != [
            ("2022-03-18", "2022-03-18")
        ]:
            raise ValueError("W1_MONTH_DIFF_INVALID")
        row = next(bar for bar in current if bar.trading_day == date(2022, 3, 18))
        if {k: str(getattr(row, k)) for k in ("open", "high", "low", "close")} != (
            target["new_ohlc"]
        ):
            raise ValueError("W1_VALUE_MISMATCH")
        for source in target["d1_preimages"]:
            path = root / source["file_uri"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("D1_PREIMAGE_MOVED")
        mds = MarketDataService(catalog, store)
        bars, gaps = mds.query_contract_weekly_replay_quality(
            symbol="sr", contract="SR2303", through=date(2022, 3, 18),
            cutoff=row.bar_end, classification_version="weekly-d1-quality-v2",
        )
        if not any(bar.trading_day == row.trading_day for bar in bars) or gaps:
            raise ValueError("MDS_W1_QUALITY_READBACK_INVALID")
        result = {
            "status": "passed", "provider_requests": 0, "writes": 0,
            "catalog_revision": catalog_revision(
                session, ("sr",), date(2026, 9, 18), ("1d", "1w")
            ),
            "active_w1_uri": uri, "active_w1_sha256": sha,
            "old_w1_retained": True, "month_rows": len(current),
            "changed_week_ends": [day for day, _ in changed],
            "d1_preimages_unchanged": True, "mds_quality_readback": "passed",
            "new_ohlc": target["new_ohlc"],
        }
        (here / "sr-post-apply-readback.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))
        session.rollback()
finally:
    engine.dispose()
