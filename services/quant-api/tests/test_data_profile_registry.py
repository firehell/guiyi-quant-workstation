from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.services.data_profile_registry import DataProfileRegistry
from app.services.profile_active_switch import rollback_profile_active_binding, switch_profile_active_binding
from app.services.profile_binding_validator import ProfileBindingValidationError, validate_profile_binding_target


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_profile(session: Session, *, periods: list[str] | None = None) -> None:
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday Research V1",
            description="test",
            contract_roles=["dominant_main"],
            periods=periods or ["1d"],
            quality_policy="passed_only",
            provider="rqdata",
            config_path="configs/data_profiles/intraday_research_v1.json",
        )
    )


def _create_market_file(
    session: Session,
    tmp_path: Path,
    *,
    data_version: str,
    quality_status: str = "passed",
    instrument_symbol: str = "jm",
    contract_code: str = "jm.MAIN",
    period: str = "1d",
) -> MarketDataFile:
    parquet_path = tmp_path / f"{instrument_symbol}_{period}_{data_version}.parquet"
    pd.DataFrame({"datetime": [datetime(2020, 1, 2)]}).to_parquet(parquet_path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=instrument_symbol,
        contract_code=contract_code,
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 4, tzinfo=UTC),
        file_path=str(parquet_path),
        row_count=1,
        checksum="a" * 64,
        data_version=data_version,
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    return market_file


def test_registry_lists_profiles_and_resolves_active_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="test_rb_1d", instrument_symbol="rb", contract_code="rb.MAIN")
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="rb",
                contract_code="rb.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="test_rb_1d",
                market_data_file_id=market_file.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        registry = DataProfileRegistry(session, project_root=tmp_path)
        assert len(registry.list_profiles()) == 1
        resolved = registry.resolve_active_market_file(
            profile_id="intraday_research_v1",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="1d",
        )
        assert resolved is not None
        assert resolved.id == market_file.id


def test_switch_profile_active_binding_dry_run(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="next_version")
        session.commit()
        result = switch_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            data_version="next_version",
            market_data_file_id=market_file.id,
            dry_run=True,
            project_root=tmp_path,
        )
    assert result["dry_run"] is True
    assert result["writes_database"] is False
    assert result["validation"]["market_data_file_id"] == market_file.id


def test_three_consecutive_switches_keep_one_active_and_two_superseded(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        file_v1 = _create_market_file(session, tmp_path, data_version="v1")
        file_v2 = _create_market_file(session, tmp_path, data_version="v2")
        file_v3 = _create_market_file(session, tmp_path, data_version="v3")
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="v1",
                market_data_file_id=file_v1.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        for market_file in (file_v2, file_v3):
            switch_profile_active_binding(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                data_version=market_file.data_version,
                market_data_file_id=market_file.id,
                dry_run=False,
                commit=True,
                project_root=tmp_path,
            )

        bindings = list(session.scalars(select(ProfileActiveBinding).order_by(ProfileActiveBinding.id)))
        assert len(bindings) == 3
        assert sum(1 for item in bindings if item.binding_status == "active") == 1
        assert sum(1 for item in bindings if item.binding_status == "superseded") == 2
        active = next(item for item in bindings if item.binding_status == "active")
        assert active.data_version == "v3"


def test_rollback_restores_immediate_predecessor(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        file_v1 = _create_market_file(session, tmp_path, data_version="v1")
        file_v2 = _create_market_file(session, tmp_path, data_version="v2")
        file_v3 = _create_market_file(session, tmp_path, data_version="v3")
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="v1",
                market_data_file_id=file_v1.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        for market_file in (file_v2, file_v3):
            switch_profile_active_binding(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                data_version=market_file.data_version,
                market_data_file_id=market_file.id,
                dry_run=False,
                commit=True,
                project_root=tmp_path,
            )

        active_before = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == "intraday_research_v1",
                ProfileActiveBinding.binding_status == "active",
            )
        )
        assert active_before is not None
        assert active_before.data_version == "v3"

        result = rollback_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            binding_id=active_before.id,
            dry_run=False,
            commit=True,
        )
        assert result["status"] == "rolled_back"
        assert result["rollback_to_binding_id"] is not None

        active_after = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == "intraday_research_v1",
                ProfileActiveBinding.binding_status == "active",
            )
        )
        assert active_after is not None
        assert active_after.data_version == "v2"


def test_rollback_then_switch_again(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        file_v1 = _create_market_file(session, tmp_path, data_version="v1")
        file_v2 = _create_market_file(session, tmp_path, data_version="v2")
        file_v3 = _create_market_file(session, tmp_path, data_version="v3")
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="v1",
                market_data_file_id=file_v1.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        for market_file in (file_v2, file_v3):
            switch_profile_active_binding(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                data_version=market_file.data_version,
                market_data_file_id=market_file.id,
                dry_run=False,
                commit=True,
                project_root=tmp_path,
            )

        active_v3 = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == "intraday_research_v1",
                ProfileActiveBinding.binding_status == "active",
            )
        )
        assert active_v3 is not None
        rollback_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            binding_id=active_v3.id,
            dry_run=False,
            commit=True,
        )

        switch_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            data_version="v3",
            market_data_file_id=file_v3.id,
            dry_run=False,
            commit=True,
            project_root=tmp_path,
        )

        bindings = list(session.scalars(select(ProfileActiveBinding).order_by(ProfileActiveBinding.id)))
        assert sum(1 for item in bindings if item.binding_status == "active") == 1
        active = next(item for item in bindings if item.binding_status == "active")
        assert active.data_version == "v3"


def test_rollback_without_previous_binding_is_noop(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        file_v1 = _create_market_file(session, tmp_path, data_version="v1")
        binding = ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            contract_role="dominant_main",
            period="1d",
            data_version="v1",
            market_data_file_id=file_v1.id,
            binding_status="active",
            activated_at=datetime.now(UTC),
        )
        session.add(binding)
        session.commit()

        result = rollback_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            binding_id=binding.id,
            dry_run=False,
            commit=True,
        )
        assert result["status"] == "no_previous_binding"
        assert result["rollback_to_binding_id"] is None
        assert result["writes_database"] is False

        active = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.id == binding.id,
                ProfileActiveBinding.binding_status == "active",
            )
        )
        assert active is not None


def test_switch_rejects_mismatched_market_data_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="actual_version")
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            switch_profile_active_binding(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                data_version="wrong_version",
                market_data_file_id=market_file.id,
                dry_run=False,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "file_identity_mismatch"


def test_switch_rejects_failed_quality_under_passed_only_policy(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="failed_version", quality_status="failed")
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="failed_version",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "quality_policy_violation"
