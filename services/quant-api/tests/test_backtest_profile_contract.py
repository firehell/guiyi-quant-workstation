from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.backtests import BacktestRunRequest, BatchBacktestRunRequest
from app.backtest.service import BacktestService
from app.db.base import Base
from app.models.backtest import BacktestReportModel, Watchlist, WatchlistItem
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.schemas.backtest import BacktestTaskConfig, FormalBacktestTaskRequest
from app.vnpy_integration.errors import BacktestConfigurationError
from app.vnpy_integration.backtest_runner import _validate_standard_rows


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
        "instrument_symbol": "jm",
        "contract_code": "jm.MAIN",
        "exchange": "DCE",
        "interval": "15m",
        "auxiliary_periods": ["1d"],
        "profile_id": "intraday_research_v1",
        "start": datetime(2024, 1, 2, tzinfo=UTC),
        "end": datetime(2024, 2, 2, tzinfo=UTC),
        "strategy_class_path": "tests.test_backtest_profile_contract:FakeStrategy",
        "strategy_code": "profile_contract_test",
    }
    payload.update(overrides)
    return payload


def _seed_asset(
    session: Session,
    tmp_path: Path,
    *,
    period: str,
    quality_status: str = "passed",
    provider: str = "rqdata",
    data_version: str | None = None,
) -> MarketDataFile:
    path = tmp_path / f"jm_MAIN_{period}.parquet"
    pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": datetime(2024, 1, 2),
                "trading_day": datetime(2024, 1, 2).date(),
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1,
                "open_interest": 1,
                "turnover": 1.0,
                "period": period,
                "provider": provider,
                "data_version": data_version or f"version-{period}",
                "source_interval": "1m",
            }
        ]
    ).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period=period,
        start_time=datetime(2024, 1, 1, tzinfo=UTC),
        end_time=datetime(2024, 3, 1, tzinfo=UTC),
        file_path=str(path),
        row_count=1,
        checksum=f"checksum-{period}",
        data_version=data_version or f"version-{period}",
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            contract_role="dominant_main",
            period=period,
            data_version=market_file.data_version,
            market_data_file_id=market_file.id,
            binding_status="active",
            activated_at=datetime.now(UTC),
        )
    )
    return market_file


def _seed_profile(
    session: Session,
    tmp_path: Path,
    *,
    warning_period: str | None = None,
    non_passed_status: str = "warning",
) -> dict[str, MarketDataFile]:
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday Research V1",
            description="formal contract test",
            contract_roles=["dominant_main"],
            periods=["15m", "1d"],
            quality_policy="passed_only",
            provider="rqdata",
            config_path="configs/data_profiles/intraday_research_v1.json",
        )
    )
    files = {
        period: _seed_asset(
            session,
            tmp_path,
            period=period,
            quality_status=non_passed_status if period == warning_period else "passed",
        )
        for period in ("15m", "1d")
    }
    session.commit()
    return files


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


def test_formal_request_forbids_client_paths_and_quality_metadata() -> None:
    for forbidden in (
        {"quality_status": "warning"},
        {"data_role": "primary"},
        {"data_version": "client-selected"},
        {"allow_warning_quality": True},
        {"research_only": True},
        {"request_payload": {"bar_data_path": "/tmp/escape.parquet"}},
    ):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            FormalBacktestTaskRequest.model_validate({**_formal_payload(), **forbidden})


def test_formal_request_rejects_client_paths_with_stable_validation_type() -> None:
    for forbidden in (
        {"bar_data_path": "/tmp/escape.parquet"},
        {"auxiliary_bar_data_paths": {"1d": "/tmp/escape.parquet"}},
    ):
        with pytest.raises(ValidationError) as caught:
            FormalBacktestTaskRequest.model_validate({**_formal_payload(), **forbidden})

        error = caught.value.errors()[0]
        assert error["type"] == "backtest_formal_path_forbidden"
        assert error["ctx"]["code"] == "BACKTEST_FORMAL_PATH_FORBIDDEN"


def test_inline_and_batch_formal_requests_forbid_warning_and_provider_overrides() -> None:
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
    for model, payload in ((BacktestRunRequest, inline_payload), (BatchBacktestRunRequest, batch_payload)):
        for forbidden in ({"allow_warning_quality": True}, {"provider": "local_parquet"}):
            with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
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
    with SessionLocal() as session, pytest.raises(BacktestConfigurationError, match="research_only=true"):
        BacktestService(session).create_task(config)


def test_formal_task_resolves_passed_primary_and_auxiliary_and_freezes_report_snapshot(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        files = _seed_profile(session, tmp_path)
        service = BacktestService(session)
        task = service.create_formal_task(_formal_payload())

        assert task.profile_id == "intraday_research_v1"
        assert task.market_data_file_id == files["15m"].id
        assert task.binding_snapshot["schema_version"] == "backtest_binding_snapshot_v1"
        assert task.binding_snapshot["resolver_name"] == "ProfileLineageResolver"
        assert task.binding_snapshot["resolver_contract_version"] == "backtest_profile_v1"
        assert task.binding_snapshot["quality_policy"] == "passed_only"
        assert task.binding_snapshot["primary"]["market_data_file_id"] == files["15m"].id
        assert task.binding_snapshot["auxiliary"]["1d"]["market_data_file_id"] == files["1d"].id
        assert task.vnpy_setting_json["bar_data_path"] == files["15m"].file_path
        assert task.vnpy_setting_json["auxiliary_bar_data_paths"] == {"1d": files["1d"].file_path}

        service.persist_result(task, {"summary": {"initial_capital": 100000}, "trades": [], "orders": []})
        report = session.scalar(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id))
        assert report is not None
        assert report.profile_id == task.profile_id
        assert report.market_data_file_id == task.market_data_file_id
        assert report.binding_snapshot == task.binding_snapshot
        assert report.binding_snapshot is not task.binding_snapshot


@pytest.mark.parametrize("quality_status", ["warning", "failed", "unchecked"])
def test_formal_task_fails_closed_when_auxiliary_quality_is_not_passed(
    tmp_path: Path,
    quality_status: str,
) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session, tmp_path, warning_period="1d", non_passed_status=quality_status)
        with pytest.raises(BacktestConfigurationError, match="quality") as caught:
            BacktestService(session).create_formal_task(_formal_payload())

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_QUALITY_BLOCKED"


def test_formal_task_fails_closed_when_bound_file_is_missing(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        files = _seed_profile(session, tmp_path)
        Path(files["15m"].file_path).unlink()
        with pytest.raises(BacktestConfigurationError, match="file is missing") as caught:
            BacktestService(session).create_formal_task(_formal_payload())

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_FILE_MISSING"


def test_formal_task_reports_profile_not_found_code() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session, pytest.raises(BacktestConfigurationError) as caught:
        BacktestService(session).create_formal_task(_formal_payload())

    assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_NOT_FOUND"


def test_formal_task_reports_binding_missing_code() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="formal contract test",
                contract_roles=["dominant_main"],
                periods=["15m", "1d"],
                quality_policy="passed_only",
                provider="rqdata",
                config_path="configs/data_profiles/intraday_research_v1.json",
            )
        )
        session.commit()

        with pytest.raises(BacktestConfigurationError) as caught:
            BacktestService(session).create_formal_task(_formal_payload())

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_BINDING_MISSING"


def test_formal_task_reports_market_file_missing_code() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="formal contract test",
                contract_roles=["dominant_main"],
                periods=["15m"],
                quality_policy="passed_only",
                provider="rqdata",
                config_path="configs/data_profiles/intraday_research_v1.json",
            )
        )
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="15m",
                data_version="missing-version",
                market_data_file_id=None,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        with pytest.raises(BacktestConfigurationError) as caught:
            BacktestService(session).create_formal_task(_formal_payload(auxiliary_periods=[]))

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_MARKET_FILE_MISSING"


def test_formal_task_reports_market_file_identity_mismatch_code(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="formal contract test",
                contract_roles=["dominant_main"],
                periods=["15m"],
                quality_policy="passed_only",
                provider="rqdata",
                config_path="configs/data_profiles/intraday_research_v1.json",
            )
        )
        wrong_path = tmp_path / "rb2405_15m.parquet"
        wrong_path.write_bytes(b"PAR1test")
        wrong_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb2405",
            period="15m",
            start_time=datetime(2024, 1, 1, tzinfo=UTC),
            end_time=datetime(2024, 3, 1, tzinfo=UTC),
            file_path=str(wrong_path),
            row_count=1,
            checksum="wrong-identity",
            data_version="wrong-identity",
            data_role="primary",
            quality_status="passed",
        )
        session.add(wrong_file)
        session.flush()
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="15m",
                data_version=wrong_file.data_version,
                market_data_file_id=wrong_file.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        with pytest.raises(BacktestConfigurationError) as caught:
            BacktestService(session).create_formal_task(_formal_payload(auxiliary_periods=[]))

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_IDENTITY_MISMATCH"


def test_formal_task_reports_range_not_covered_code(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session, tmp_path)
        with pytest.raises(BacktestConfigurationError, match="outside") as caught:
            BacktestService(session).create_formal_task(
                _formal_payload(start=datetime(2023, 12, 1, tzinfo=UTC))
            )

        assert getattr(caught.value, "code", None) == "BACKTEST_PROFILE_RANGE_NOT_COVERED"


def test_runner_uses_pinned_task_snapshot_after_active_binding_switch(tmp_path: Path) -> None:
    from app.backtest.runner import BacktestTaskRunner

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        files = _seed_profile(session, tmp_path)
        task = BacktestService(session).create_formal_task(_formal_payload())
        old_path = files["15m"].file_path
        binding = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == "intraday_research_v1",
                ProfileActiveBinding.period == "15m",
            )
        )
        assert binding is not None
        binding.binding_status = "superseded"
        session.flush()
        replacement_root = tmp_path / "replacement"
        replacement_root.mkdir()
        replacement = _seed_asset(session, replacement_root, period="15m", data_version="version-15m-replacement")
        session.commit()

        request = BacktestTaskRunner(session)._request_from_task(task)

        assert str(request.bar_data_path) == old_path
        assert request.bar_data_path != replacement.file_path
        assert task.binding_snapshot["primary"]["market_data_file_id"] == files["15m"].id


def test_runner_records_stable_contract_code_when_formal_snapshot_is_missing(tmp_path: Path) -> None:
    from app.backtest.runner import BacktestTaskRunner

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session, tmp_path)
        task = BacktestService(session).create_formal_task(_formal_payload())
        task.binding_snapshot = None
        session.commit()

        result = BacktestTaskRunner(session, adapter=object()).run(task.id)

        assert result["status"] == "failed"
        assert result["error_type"] == "BACKTEST_PROFILE_IDENTITY_MISMATCH"


def test_standard_bar_rows_require_explicit_role_and_quality() -> None:
    row = {
        "datetime": datetime(2024, 1, 2, tzinfo=UTC),
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "volume": 1,
        "turnover": 1,
        "open_interest": 1,
    }
    with pytest.raises(BacktestConfigurationError, match="data_role, quality_status"):
        _validate_standard_rows([row])


def test_batch_task_freezes_all_assets_and_has_no_single_file_id(tmp_path: Path) -> None:
    from app.services.batch_backtest import create_batch_task

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        files = _seed_profile(session, tmp_path)
        session.add(Watchlist(code="jm-test", name="JM", category="test", is_active=True))
        session.add(
            WatchlistItem(
                watchlist_code="jm-test",
                symbol="jm",
                name="JM",
                exchange_code="DCE",
                default_contract="jm.MAIN",
                is_active=True,
            )
        )
        session.commit()

        task = create_batch_task(
            session,
            {
                "watchlist_code": "jm-test",
                "period": "15m",
                "profile_id": "intraday_research_v1",
                "start": datetime(2024, 1, 2, tzinfo=UTC).isoformat(),
                "end": datetime(2024, 2, 2, tzinfo=UTC).isoformat(),
                "symbols": ["jm"],
            },
        )

        assert task.profile_id == "intraday_research_v1"
        assert task.market_data_file_id is None
        assert task.binding_snapshot["schema_version"] == "backtest_batch_binding_snapshot_v1"
        assert task.binding_snapshot["resolver_name"] == "ProfileLineageResolver"
        assert task.binding_snapshot["resolver_contract_version"] == "backtest_profile_v1"
        assert task.binding_snapshot["quality_policy"] == "passed_only"
        assert task.binding_snapshot["assets"][0]["market_data_file_id"] == files["15m"].id
