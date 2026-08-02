from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.backtests import BacktestRunRequest, BatchBacktestRunRequest
from app.backtest.service import BacktestService
from app.db.base import Base
from app.schemas.backtest import BacktestTaskConfig, FormalBacktestTaskRequest
from app.vnpy_integration.backtest_runner import _validate_standard_rows
from app.vnpy_integration.errors import BacktestConfigurationError


REPO_ROOT = Path(__file__).resolve().parents[3]


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _formal_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_kind": "continuous",
        "instrument_symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "exchange": "DCE",
        "interval": "15m",
        "start": datetime(2024, 1, 2, tzinfo=UTC),
        "end": datetime(2024, 2, 2, tzinfo=UTC),
        "strategy_class_path": "tests.test_backtest_profile_contract:FakeStrategy",
        "strategy_code": "profile_contract_test",
        "strategy_version": "v1",
        "strategy_parameters": {
            "indicator_versions": ["ema21"],
            "formal_policy_ids": ["ema_sma_window_v1"],
            "confirmed_only": True,
            "research_status": "formal_candidate",
        },
    }
    payload.update(overrides)
    return payload


class FakeStrategy:
    pass


def test_binding_snapshot_migration_is_nullable_and_has_no_historical_backfill() -> None:
    migration = (
        REPO_ROOT
        / "services/quant-api/alembic/versions/20260718_0024_backtest_binding_snapshot.py"
    ).read_text(encoding="utf-8")
    assert migration.count('op.add_column("backtest_tasks"') == 1
    assert migration.count('op.add_column("backtest_reports"') == 1
    assert "nullable=True" in migration
    assert "op.execute" not in migration
    assert "server_default" not in migration


def test_formal_request_forbids_profile_file_and_mutable_quality_identity() -> None:
    forbidden_values = (
        {"profile_id": "intraday_research_v1"},
        {"contract_code": "jm.MAIN"},
        {"bar_data_path": "/tmp/escape.parquet"},
        {"auxiliary_bar_data_paths": {"1d": "/tmp/escape.parquet"}},
        {"quality_status": "warning"},
        {"data_role": "primary"},
        {"data_version": "client-selected"},
        {"allow_warning_quality": True},
        {"research_only": True},
    )
    for forbidden in forbidden_values:
        with pytest.raises(ValidationError):
            FormalBacktestTaskRequest.model_validate(
                {**_formal_payload(), **forbidden}
            )


def test_formal_request_rejects_client_paths_with_stable_validation_type() -> None:
    for forbidden in (
        {"bar_data_path": "/tmp/escape.parquet"},
        {"auxiliary_bar_data_paths": {"1d": "/tmp/escape.parquet"}},
    ):
        with pytest.raises(ValidationError) as caught:
            FormalBacktestTaskRequest.model_validate(
                {**_formal_payload(), **forbidden}
            )
        error = caught.value.errors()[0]
        assert error["type"] == "backtest_formal_path_forbidden"
        assert error["ctx"]["code"] == "BACKTEST_FORMAL_PATH_FORBIDDEN"


def test_inline_and_batch_legacy_requests_forbid_warning_and_provider_overrides() -> None:
    inline_payload = {
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
        "start": "2024-01-02",
        "end": "2024-02-02",
    }
    batch_payload = {
        "watchlist_code": "black",
        "period": "15m",
        "start": "2024-01-02",
        "end": "2024-02-02",
    }
    for model, payload in (
        (BacktestRunRequest, inline_payload),
        (BatchBacktestRunRequest, batch_payload),
    ):
        for forbidden in (
            {"allow_warning_quality": True},
            {"provider": "local_parquet"},
        ):
            with pytest.raises(ValidationError):
                model.model_validate({**payload, **forbidden})


def test_low_level_task_persistence_requires_research_only() -> None:
    SessionLocal = _session_factory()
    config = BacktestTaskConfig(
        symbol="jm.MAIN",
        exchange="DCE",
        interval="15m",
        start=datetime(2024, 1, 2, tzinfo=UTC),
        end=datetime(2024, 2, 2, tzinfo=UTC),
        strategy_class_path="tests.test_backtest_profile_contract:FakeStrategy",
        bar_data_path="/tmp/escape.parquet",
    )
    with SessionLocal() as session, pytest.raises(
        BacktestConfigurationError, match="research_only=true"
    ):
        BacktestService(session).create_task(config)


def test_standard_bar_rows_require_explicit_role_and_quality() -> None:
    base = {
        "datetime": datetime(2024, 1, 2),
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "volume": 1,
        "turnover": 1,
        "open_interest": 1,
    }
    with pytest.raises(BacktestConfigurationError, match="required fields"):
        _validate_standard_rows([base])
    with pytest.raises(BacktestConfigurationError, match="data_role=primary"):
        _validate_standard_rows(
            [{**base, "data_role": "validation", "quality_status": "passed"}]
        )
    with pytest.raises(BacktestConfigurationError, match="quality_status=passed"):
        _validate_standard_rows(
            [{**base, "data_role": "primary", "quality_status": "warning"}]
        )
