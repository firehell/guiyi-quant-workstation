"""Run SR's three W1 consumers against a read-only, in-memory candidate overlay."""

import argparse
import hashlib
from pathlib import Path
from datetime import timedelta, datetime
import sys
sys.path.insert(0, str(Path(__file__).parent))
import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog, CatalogPartition
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.market_data_service import MarketDataService
from app.market_data.domain import DatasetKey
from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.newow import readiness_composition
from sr_repair_batch import prepare
CUTOFF = datetime.fromisoformat("2026-09-18T07:00:00.000001+00:00")
from scripts.newow_weekly_recovery import load_private_readonly_settings
from guiyi_quant.newow.product_contracts import ProductFrequency

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("--project-env", type=Path, required=True)
parser.add_argument("--prepared", type=Path, required=True)
parser.add_argument("--expected-prepared-sha256", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
content = args.prepared.read_bytes()
if hashlib.sha256(content).hexdigest() != args.expected_prepared_sha256:
    raise SystemExit("PREPARED_HASH_MISMATCH")
settings, identity = load_private_readonly_settings(args.project_env)
root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
engine = create_engine(
    normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True
)
with Session(engine, autoflush=False) as session:
    session.execute(text("SET TRANSACTION READ ONLY"))
    packet, candidates = prepare(session, root, identity["canonical_root_sha256"])
    if packet != json.loads(content):
        raise SystemExit("PREPARE_IDENTITY_MOVED")
    catalog = MarketCatalog(session, root)
    store = CanonicalMonthlyStore(root)
    original_parts = catalog.all_partitions
    original_read = store.read_catalog_partition
    by_path = {}
    synthetic = []
    key = DatasetKey("contract", "sr", "SR2303", "1w")
    for record, bars in zip(packet["targets"], candidates, strict=True):
        path = root / record["candidate_w1_partition_uri"]
        by_path[path] = bars
        synthetic.append(
            CatalogPartition(
                key,
                int(record["week_end"][:4]),
                int(record["week_end"][5:7]),
                bars[0].bar_end - timedelta(days=7),
                bars[-1].bar_end,
                path,
                len(bars),
            )
        )

    def all_partitions(selected):
        rows = original_parts(selected)
        if selected != key:
            return rows
        replaced = {(x.year, x.month) for x in synthetic}
        return tuple(
            sorted(
                (x for x in rows if (x.year, x.month) not in replaced),
                key=lambda x: (x.year, x.month),
            )
        ) + tuple(synthetic)

    def read_catalog_partition(partition):
        if partition.file_path in by_path:
            return by_path[partition.file_path]
        return original_read(partition)

    catalog.all_partitions = all_partitions
    store.read_catalog_partition = read_catalog_partition
    market = MarketDataService(catalog, store)
    readiness_composition.build_market_data_service = lambda _: market
    request = ReadinessRequest(
        products=("sr",),
        as_of=CUTOFF,
        matrix=True,
        max_work=100000,
        timeout_seconds=600,
        frequencies=(ProductFrequency.WEEKLY,),
        candidate_weekly=True,
    )
    report = readiness_composition.build_newow_readiness(session, request=request)
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "basis": "read-only in-memory Catalog/Store overlay, no active pointer changed",
                "prepare_sha256": args.expected_prepared_sha256,
                "runner_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "report": report,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "complete": report.get("complete"),
                "cases": [
                    (
                        c["strategy"],
                        c["main"].get("status"),
                        {k: v.get("status") for k, v in c["sections"].items()},
                    )
                    for c in report.get("cases", [])
                    if c["frequency"] == "1w"
                ],
                "dependencies": [
                    (d["contract"], d["status"], d.get("reason"))
                    for d in report.get("dependencies", [])
                    if d["symbol"] == "sr"
                ],
                "output": str(out),
            },
            ensure_ascii=False,
        )
    )
    session.rollback()
engine.dispose()
