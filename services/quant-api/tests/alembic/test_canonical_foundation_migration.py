from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


def test_canonical_foundation_migration_is_new_irreversible_head() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20260808_0036_converge_canonical_data_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_foundation_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.revision == "20260808_0036"
    assert migration.down_revision == "20260808_0035"
    assert set(migration.RETIRED_TABLES) == {
        "data_sources",
        "data_download_tasks",
        "market_data_files",
        "data_quality_reports",
        "fee_margin_rules",
        "futures_trading_parameters",
        "futures_ex_factors",
        "futures_warehouse_stocks",
        "futures_roll_yields",
        "futures_member_ranks",
        "futures_basis",
        "futures_contract_universe",
        "futures_continuous_contract_map",
    }
    assert "contract_specs" in inspect.getsource(migration.upgrade)
    assert "uq_trading_sessions_identity" in inspect.getsource(migration.upgrade)
    assert "SET LOCAL lock_timeout" in inspect.getsource(migration.upgrade)
    assert "actual_dominant" not in inspect.getsource(migration.upgrade)
    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()
