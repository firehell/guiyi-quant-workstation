from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

QUANT_API_ROOT = Path(__file__).resolve().parents[2]
DROP_SOURCE = (
    QUANT_API_ROOT
    / "alembic"
    / "versions"
    / "20260808_0035_drop_profile_binding_after_market.py"
)
DROP_REVISION = "20260808_0035"
PARENT_REVISION = "20260808_0034"

DROPPED_TABLES = (
    "profile_active_bindings",
    "data_profiles",
    "after_market_scheduler_checkpoints",
)

KEPT_TABLES = (
    "market_datasets",
    "market_partitions",
    "main_contract_map",
    "data_gaps",
    "market_data_files",
)


def test_profile_binding_drop_remains_before_current_alembic_head() -> None:
    config = Config(str(QUANT_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(QUANT_API_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["20260814_0038"]
    revision = scripts.get_revision(DROP_REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT_REVISION


def test_profile_binding_drop_sql_is_irreversible_and_scoped() -> None:
    source = DROP_SOURCE.read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "DROP TABLE IF EXISTS" in source
    assert "RuntimeError" in source
    for table_name in DROPPED_TABLES:
        assert table_name in source
    for table_name in KEPT_TABLES:
        assert table_name not in source
