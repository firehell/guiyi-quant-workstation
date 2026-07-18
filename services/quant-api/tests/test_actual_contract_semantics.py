from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import FeeMarginRule, MainContractMap
from app.services.actual_contract_semantics import (
    load_effective_fee_margin_rule,
    load_effective_main_contract_mapping,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_effective_mapping_rejects_wrong_rule_and_uses_latest_matching_version() -> None:
    with _session() as session:
        session.add_all(
            [
                MainContractMap(instrument_symbol="jm", trade_date=date(2026, 7, 10), rank=1, contract_code="JM2605", rule="other", provider="rqdata", data_version="v9"),
                MainContractMap(instrument_symbol="jm", trade_date=date(2026, 7, 10), rank=1, contract_code="JM2609", rule="volume_open_interest", provider="rqdata", data_version="v1"),
                MainContractMap(instrument_symbol="jm", trade_date=date(2026, 7, 10), rank=1, contract_code="JM2609", rule="volume_open_interest", provider="rqdata", data_version="v2"),
            ]
        )
        session.commit()

        row = load_effective_main_contract_mapping(session, instrument_symbol="jm", trade_date=date(2026, 7, 10))

    assert row is not None
    assert row.contract_code == "JM2609"
    assert row.data_version == "v2"


def test_fee_rule_uses_contract_then_product_and_accepts_null_effective_date() -> None:
    with _session() as session:
        session.add_all(
            [
                FeeMarginRule(provider="rqdata", exchange_code="DCE", instrument_symbol="jm", contract_code=None, price_tick=Decimal("1"), effective_date=None),
                FeeMarginRule(provider="rqdata", exchange_code="DCE", instrument_symbol="jm", contract_code="JM2609", price_tick=Decimal("0.5"), effective_date=None),
            ]
        )
        session.commit()

        exact = load_effective_fee_margin_rule(session, contract_code="JM2609", instrument_symbol="jm", exchange_code="DCE", trade_date=date(2026, 7, 10))
        fallback = load_effective_fee_margin_rule(session, contract_code="JM2701", instrument_symbol="jm", exchange_code="DCE", trade_date=date(2026, 7, 10))

    assert exact is not None and exact.contract_code == "JM2609"
    assert fallback is not None and fallback.contract_code is None
