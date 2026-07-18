from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile
from app.services.profile_binding_validator import ProfileBindingValidationError, validate_profile_binding_target
from app.services.profile_target_resolver import ProfileTargetRange


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_profile(session: Session, *, quality_policy: str = "passed_only") -> DataProfile:
    profile = DataProfile(
        profile_id="intraday_research_v1",
        label="Intraday Research V1",
        description="test",
        contract_roles=["dominant_main"],
        periods=["1d", "5m"],
        quality_policy=quality_policy,
        provider="rqdata",
        config_path="configs/data_profiles/intraday_research_v1.json",
    )
    session.add(profile)
    return profile


def _create_market_file(
    session: Session,
    tmp_path: Path,
    *,
    data_version: str,
    quality_status: str = "passed",
    data_role: str = "primary",
    provider: str = "rqdata",
    period: str = "1d",
) -> MarketDataFile:
    parquet_path = tmp_path / f"jm_MAIN_{period}_{data_version}.parquet"
    pd.DataFrame({"datetime": [datetime(2020, 1, 2)]}).to_parquet(parquet_path, index=False)
    market_file = MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2020, 1, 4, tzinfo=UTC),
        file_path=str(parquet_path),
        row_count=1,
        checksum="a" * 64,
        data_version=data_version,
        data_role=data_role,
        quality_status=quality_status,
    )
    session.add(market_file)
    session.flush()
    return market_file


def test_validate_profile_binding_target_accepts_matching_primary_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="v1")
        session.commit()

        validated = validate_profile_binding_target(
            session,
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            contract_role="dominant_main",
            data_version="v1",
            market_data_file_id=market_file.id,
            project_root=tmp_path,
        )
        assert validated.id == market_file.id


def test_validate_profile_binding_target_rejects_missing_file_id(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="v1",
                market_data_file_id=None,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "market_data_file_required"


def test_validate_profile_binding_target_rejects_period_not_allowed(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="v1", period="1w")
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1w",
                contract_role="dominant_main",
                data_version="v1",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "period_not_allowed"


def test_validate_profile_binding_target_rejects_non_primary_data_role(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="v1", data_role="candidate")
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="v1",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "data_role_not_primary"


def test_validate_profile_binding_target_allows_warning_for_active_entry_policy(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session, quality_policy="active_entry")
        market_file = _create_market_file(session, tmp_path, data_version="v1", quality_status="warning")
        session.commit()

        validated = validate_profile_binding_target(
            session,
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            contract_role="dominant_main",
            data_version="v1",
            market_data_file_id=market_file.id,
            project_root=tmp_path,
        )
        assert validated.quality_status == "warning"


def test_validate_profile_binding_target_rejects_missing_physical_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="v1")
        session.commit()
        Path(market_file.file_path).unlink()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="v1",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
            )
        assert exc_info.value.code == "file_missing"


def test_validate_profile_binding_target_rejects_incomplete_target_coverage(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="narrow_v1")
        market_file.start_time = datetime(2023, 1, 3, tzinfo=UTC)
        market_file.end_time = datetime(2026, 7, 10, tzinfo=UTC)
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="narrow_v1",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
                target_ranges=(ProfileTargetRange(date(2010, 1, 4), date(2026, 7, 10), "test"),),
                require_target_coverage=True,
            )
        assert exc_info.value.code == "target_coverage_incomplete"


def test_validate_profile_binding_target_rejects_checksum_mismatch(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        market_file = _create_market_file(session, tmp_path, data_version="bad_checksum_v1")
        session.commit()

        with pytest.raises(ProfileBindingValidationError) as exc_info:
            validate_profile_binding_target(
                session,
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="1d",
                contract_role="dominant_main",
                data_version="bad_checksum_v1",
                market_data_file_id=market_file.id,
                project_root=tmp_path,
                require_checksum=True,
            )
        assert exc_info.value.code == "checksum_mismatch"
