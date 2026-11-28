"""Installed PostgreSQL 16 contract for the six additive workstation revisions."""

from hashlib import sha256
from pathlib import Path
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.url import normalize_database_url
from app.runtime_cohort import require

HEAD = "20261128_0060"
MIGRATIONS = {
    "20261124_0055_newow_backtest_results.py": "d198601aedbbbfb84804624bf13b8863b58ec27ee7585efba9c27f3559e9e6e5",
    "20261124_0056_newow_publication_watermark.py": "7e01be93bce40e7cd7c1147c43ade2f6dec94c29d2749fa1c02a724ff82a0de7",
    "20261128_0057_trade_journal.py": "9f0d36621d34b73e537e9c98e3f7596c9b8670f056cee9342f4c787f36ccb4e6",
    "20261128_0058_research_tasks.py": "8c154e3238f9dc16a31126085452f3d52ec9d9a52f435d10d75693967342a4d9",
    "20261128_0059_trade_journal_observations.py": "90e97a9964f96e7101c2fa516d3801e83e6ecc7fcd5bc834a603cf7c061dcbe7",
    "20261128_0060_trade_journal_observation_links.py": "7408a262cadc66003ebd306fb86b4d4c8fe0e2b2eefeccc2b54f8720038d8f70",
}
# PG16 catalogs from the isolated, migrated reference schema. Includes every column,
# default, key, check constraint, foreign key and index for each new table.
TABLES = {
    "newow_backtest_runs": "af0f9d43534f56dfc7294514a23e8ee920c653c27db856eb93c2f7bd5b33a579",
    "trade_journal_summaries": "81e196fac901dcb4c08e7451d44f7be3d0a95283fc29653981ada6c703d29295",
    "trade_journal_plans": "ec55f60aa7bab0c10bf1fa59c4a0bbf4f8fadc0a15009e06fa3b3fc5f6fe39e7",
    "trade_journal_cases": "c1da76b13153f74662f3ceee27023abf99e9a249b113498ffd8f1f5c300e0bf2",
    "trade_journal_observations": "e4c835a5f99bc0c4f84037126e7525d54d1317cceef82b65402b0ae50321fc63",
    "newow_backtest_equity": "c43492ab02de3ba77980043c667917cd7e221ef86f1ae629a34cd10e7beb8624",
    "trade_journal_observation_links": "e861d09bbf547cab5bf23da006b8c1f599d849f98423d7232d8e290dc5a8a6a9",
    "statistics_research_tasks": "f289b584b5ff3c5fe1c029fda146e2a8ab298aa5b92bac2385bb91ee4a97fa30",
    "trade_journal_mutations": "01ac1dfe279753ba8f9cf7d63e5ee2033a2e6f0d553628752217d6af7cbaa401",
    "trade_journal_plan_revisions": "9301deb7c88785ec8a5c0492d379b4cf38921fc78af8d8843b6db54958a6d816",
    "trade_journal_events": "bf88b86ef267757b5d5c77e9d096ff154a3ad90d44569f2157fa37e029950eb6",
    "newow_backtest_trades": "78702fa558abba3e678da43008765abf4f96e2003e7de6612a5bd3a70dfdbe6f",
    "newow_backtest_series": "d3b4df8bc210118563ff2c5cfc6303046e53d876193af176f519ecedd52906f8",
}

LAYOUT = text("""
SELECT t.relname, jsonb_build_object(
  'columns',(SELECT jsonb_agg(jsonb_build_array(a.attname,format_type(a.atttypid,a.atttypmod),
    a.attnotnull,a.attidentity,pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attnum)
    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE a.attrelid=t.oid AND a.attnum>0 AND NOT a.attisdropped),
  'constraints',(SELECT jsonb_agg(jsonb_build_array(k.conname,pg_get_constraintdef(k.oid)) ORDER BY k.conname)
    FROM pg_constraint k WHERE k.conrelid=t.oid),
  'indexes',(SELECT jsonb_agg(pg_get_indexdef(i.indexrelid) ORDER BY pg_get_indexdef(i.indexrelid))
    FROM pg_index i WHERE i.indrelid=t.oid)
)::text FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE n.nspname='public' AND t.relkind IN ('r','p') AND t.relname = ANY(:names) ORDER BY t.relname
""")


def catalog_digest(value):
    # A restored varchar literal array may be deparsed with the cast on each item.
    pattern = r"\(ARRAY\[((?:'[A-Za-z0-9_]+'::character varying)(?:, '[A-Za-z0-9_]+'::character varying)*)\]\)::text\[\]"
    normalized = re.sub(
        pattern,
        lambda m: "ARRAY[" + ", ".join("(" + item + ")::text" for item in m[1].split(", ")) + "]",
        value,
    )
    return sha256(normalized.encode()).hexdigest()


def verify_installed_schema(root: Path, dsn: str):
    folder = root / "services/quant-api/alembic/versions"
    require(
        all(
            sha256((folder / name).read_bytes()).hexdigest() == expected
            for name, expected in MIGRATIONS.items()
        ),
        "WORKSTATION_MIGRATION_SOURCE_DRIFT",
    )
    url = make_url(normalize_database_url(dsn))
    require(url.host == "127.0.0.1" and url.database == "guiyi_quant", "WORKSTATION_CATALOG_UNPROVEN")
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c default_transaction_read_only=on -c statement_timeout=8000",
        },
    )
    try:
        with engine.connect() as db:
            require(
                db.scalar(text("SHOW transaction_read_only")) == "on"
                and db.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
                == [HEAD],
                "WORKSTATION_SCHEMA_NOT_INSTALLED",
            )
            shape = {
                name: catalog_digest(value) for name, value in db.execute(LAYOUT, {"names": list(TABLES)})
            }
            require(shape == TABLES, "WORKSTATION_SCHEMA_LAYOUT_DRIFT")
    finally:
        engine.dispose()
    return HEAD
