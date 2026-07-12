from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.services.data_profile_registry import DataProfileRegistry
from app.services.profile_active_switch import switch_profile_active_binding


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_profile(session: Session) -> None:
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday Research V1",
            description="test",
            contract_roles=["dominant_main"],
            periods=["1d"],
            quality_policy="passed_only",
            provider="rqdata",
            config_path="configs/data_profiles/intraday_research_v1.json",
        )
    )


def test_registry_lists_profiles_and_resolves_active_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    parquet_path = tmp_path / "rb_MAIN_1d.parquet"
    pd.DataFrame({"datetime": [datetime(2020, 1, 2)]}).to_parquet(parquet_path, index=False)

    with SessionLocal() as session:
        _seed_profile(session)
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="1d",
            start_time=datetime(2020, 1, 2, tzinfo=UTC),
            end_time=datetime(2020, 1, 4, tzinfo=UTC),
            file_path=str(parquet_path),
            row_count=1,
            checksum="a" * 64,
            data_version="test_rb_1d",
            data_role="primary",
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
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


def test_switch_profile_active_binding_dry_run() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session)
        session.commit()
        result = switch_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1m",
            data_version="next_version",
            market_data_file_id=None,
            dry_run=True,
        )
    assert result["dry_run"] is True
    assert result["writes_database"] is False
