from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SCRIPTS_ROOT = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from rqdata_sync_common import (  # noqa: E402
    DEFAULT_RESEARCH_PRODUCTS,
    core_products_from_db,
    selected_contracts,
    selected_products,
)

from app.db.base import Base  # noqa: E402
from app.models.data_center import Contract, Instrument  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db_session:
        db_session.add_all(
            [
                Instrument(symbol="rb", name="螺纹", exchange_code="SHFE", category="future", is_active=True),
                Instrument(symbol="ta", name="PTA", exchange_code="CZCE", category="future", is_active=True),
                Instrument(symbol="cu", name="铜", exchange_code="SHFE", category="future", is_active=True),
                Instrument(symbol="m", name="豆粕", exchange_code="DCE", category="future", is_active=True),
            ]
        )
        db_session.add_all(
            [
                Contract(contract_code="RB2501", instrument_symbol="rb", exchange_code="SHFE", name="RB2501", product="rb", status="active", provider="rqdata"),
                Contract(contract_code="TA501", instrument_symbol="ta", exchange_code="CZCE", name="TA501", product="ta", status="active", provider="rqdata"),
                Contract(contract_code="CU2501", instrument_symbol="cu", exchange_code="SHFE", name="CU2501", product="cu", status="active", provider="rqdata"),
                Contract(contract_code="M2501", instrument_symbol="m", exchange_code="DCE", name="M2501", product="m", status="active", provider="rqdata"),
            ]
        )
        db_session.commit()
        yield db_session


def test_default_research_products_include_black_chemical_energy_metals() -> None:
    assert "rb" in DEFAULT_RESEARCH_PRODUCTS
    assert "TA" in DEFAULT_RESEARCH_PRODUCTS
    assert "EG" in DEFAULT_RESEARCH_PRODUCTS
    assert "sc" in DEFAULT_RESEARCH_PRODUCTS
    assert "cu" in DEFAULT_RESEARCH_PRODUCTS
    assert len(DEFAULT_RESEARCH_PRODUCTS) == 25


def test_core_products_from_db_matches_case_insensitive(session) -> None:
    products = core_products_from_db(session)
    assert products == ["rb", "TA", "cu"]


def test_selected_products_defaults_to_core_pool(session) -> None:
    products = selected_products(session, None)
    assert products == ["rb", "TA", "cu"]


def test_selected_products_all_products_returns_full_db(session) -> None:
    products = selected_products(session, None, all_products=True)
    assert sorted(products) == ["cu", "m", "rb", "ta"]


def test_selected_products_explicit_overrides_core_pool(session) -> None:
    products = selected_products(session, ["m"])
    assert products == ["m"]


def test_selected_contracts_defaults_to_core_pool(session) -> None:
    contracts = selected_contracts(session, None, None)
    assert contracts == ["CU2501", "RB2501", "TA501"]


def test_selected_contracts_all_products_returns_all_contracts(session) -> None:
    contracts = selected_contracts(session, None, None, all_products=True)
    assert contracts == ["CU2501", "M2501", "RB2501", "TA501"]


def test_selected_contracts_filters_by_explicit_products(session) -> None:
    contracts = selected_contracts(session, None, ["rb"])
    assert contracts == ["RB2501"]
