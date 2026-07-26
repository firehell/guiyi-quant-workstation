from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.actual_contract_semantics as actual_contract_semantics
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


class _RowsSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def scalars(self, _query):
        return self.rows


def _mapping_row(
    *,
    row_id: int,
    contract: str = "JM2609",
    data_version: str,
    created_at: datetime,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        instrument_symbol="jm",
        trade_date=date(2026, 7, 27),
        rank=1,
        contract_code=contract,
        rule="volume_open_interest",
        provider="rqdata",
        data_version=data_version,
        created_at=created_at,
    )


def test_strict_mapping_rejects_different_contracts() -> None:
    session = _RowsSession(
        [
            _mapping_row(
                row_id=1,
                contract="JM2609",
                data_version="v1",
                created_at=datetime(2026, 7, 27, tzinfo=UTC),
            ),
            _mapping_row(
                row_id=2,
                contract="JM2611",
                data_version="v2",
                created_at=datetime(2026, 7, 27, 1, tzinfo=UTC),
            ),
        ]
    )

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_CONFLICT"):
        actual_contract_semantics.load_strict_main_contract_mapping(
            session,
            instrument_symbol="jm",
            trade_date=date(2026, 7, 27),
        )


@pytest.mark.parametrize("invalid_contract", ["", "JM.MAIN"])
def test_strict_mapping_rejects_invalid_row_before_valid_newer_version(
    invalid_contract: str,
) -> None:
    session = _RowsSession(
        [
            _mapping_row(
                row_id=1,
                contract=invalid_contract,
                data_version="v1",
                created_at=datetime(2026, 7, 27, tzinfo=UTC),
            ),
            _mapping_row(
                row_id=2,
                contract="JM2609",
                data_version="v2",
                created_at=datetime(2026, 7, 27, 1, tzinfo=UTC),
            ),
        ]
    )

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_INVALID"):
        actual_contract_semantics.load_strict_main_contract_mapping(
            session,
            instrument_symbol="jm",
            trade_date=date(2026, 7, 27),
        )


def test_strict_mapping_rejects_exact_duplicate_within_one_version() -> None:
    created_at = datetime(2026, 7, 27, tzinfo=UTC)
    session = _RowsSession(
        [
            _mapping_row(
                row_id=1,
                data_version="v1",
                created_at=created_at,
            ),
            _mapping_row(
                row_id=2,
                data_version="v1",
                created_at=created_at,
            ),
        ]
    )

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_DUPLICATE"):
        actual_contract_semantics.load_strict_main_contract_mapping(
            session,
            instrument_symbol="jm",
            trade_date=date(2026, 7, 27),
        )


def test_strict_mapping_selects_latest_same_contract_version_deterministically() -> None:
    session = _RowsSession(
        [
            _mapping_row(
                row_id=1,
                data_version="v1",
                created_at=datetime(2026, 7, 27, tzinfo=UTC),
            ),
            _mapping_row(
                row_id=2,
                data_version="v2",
                created_at=datetime(2026, 7, 27, 1, tzinfo=UTC),
            ),
        ]
    )

    selected = actual_contract_semantics.load_strict_main_contract_mapping(
        session,
        instrument_symbol="jm",
        trade_date=date(2026, 7, 27),
    )

    assert selected is session.rows[1]


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
