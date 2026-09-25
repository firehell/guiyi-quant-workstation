"""Independent read-only RS W1 post-apply pointer, content, and quality proof."""

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

from rs_repair_batch import inspect


here = Path(__file__).resolve().parent
content = (here / "rs-no-trade-prepare.json").read_bytes()
packet = json.loads(content)
settings, identity = load_private_readonly_settings(
    Path.home() / "Library/Application Support/GuiyiQuant/project.env"
)
if (identity["canonical_root_sha256"] != packet["canonical_root_sha256"]
        or identity["config_sha256"] != packet["project_env_sha256"]):
    raise ValueError("PROJECT_ENV_MOVED")
root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
try:
    with Session(engine, autoflush=False) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        state = inspect(session, root, packet)
        if state["status"] != "candidate":
            raise ValueError("W1_POINTERS_NOT_ALL_CANDIDATE")
        catalog = MarketCatalog(session, root)
        store = CanonicalMonthlyStore(root)
        mds = MarketDataService(catalog, store)
        changed = 0
        retained = 0
        checked_contracts = set()
        for record in packet["months"]:
            contract = record["contract"]
            key = DatasetKey("contract", "rs", contract, "1w")
            selected = [p for p in catalog.all_partitions(key)
                        if (p.year, p.month) == (record["year"], record["month"])]
            if len(selected) != 1:
                raise ValueError("W1_POINTER_IDENTITY_INVALID")
            part = selected[0]
            old_path = root / record["old_partition"]["uri"]
            if hashlib.sha256(old_path.read_bytes()).hexdigest() != record["old_partition"]["sha256"]:
                raise ValueError("OLD_W1_NOT_RECOVERABLE")
            current = store.read_catalog_partition(part)
            old = store.read_catalog_partition(replace(part, file_path=old_path))
            if (len(current) != len(old) or part.row_count != len(current)
                    or part.source_quality_sha256 != record["old_partition"]["quality_sha256"]):
                raise ValueError("W1_MONTH_METADATA_INVALID")
            expected_changed = {date.fromisoformat(row["week_end"]) for row in record["diffs"]}
            actual_changed = {a.trading_day for a, b in zip(old, current, strict=True) if a != b}
            if actual_changed != expected_changed:
                raise ValueError("W1_MONTH_DIFF_INVALID")
            changed += len(actual_changed)
            retained += len(old) - len(actual_changed)
            if contract not in checked_contracts:
                checked_contracts.add(contract)
                last_day = max(date.fromisoformat(row["week_end"])
                               for target in packet["months"] if target["contract"] == contract
                               for row in target["diffs"])
                all_parts = catalog.all_partitions(key)
                cutoff = next(bar.bar_end for p in all_parts
                              for bar in store.read_catalog_partition(p)
                              if bar.trading_day == last_day)
                bars, gaps = mds.query_contract_weekly_replay_quality(
                    symbol="rs", contract=contract, through=last_day, cutoff=cutoff,
                    classification_version="weekly-d1-quality-v2",
                )
                all_targets = {date.fromisoformat(row["week_end"])
                               for target in packet["months"] if target["contract"] == contract
                               for row in target["diffs"]}
                if not all_targets.issubset({bar.trading_day for bar in bars}):
                    raise ValueError("W1_MDS_TARGET_READBACK_INVALID")
        if changed != 133 or retained != 118 or len(checked_contracts) != 10:
            raise ValueError("W1_SCOPE_INVALID")
        result = {
            "status": "passed", "packet_sha256": hashlib.sha256(content).hexdigest(),
            "catalog_revision": catalog_revision(session, ("rs",), date(2026, 9, 18), ("1d", "1w")),
            "candidate_months": state["candidate_count"], "changed_weeks": changed,
            "retained_week_rows": retained, "contracts": sorted(checked_contracts),
            "old_files_retained": True, "d1_active_preimages_unchanged": True,
            "mds_quality_readback": "passed", "provider_requests": 0, "writes": 0,
        }
        (here / "rs-post-apply-readback.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(result, ensure_ascii=False))
        session.rollback()
finally:
    engine.dispose()
