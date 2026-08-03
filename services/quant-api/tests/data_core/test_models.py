from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.data_core import MarketDataset


def _dataset(frequency: str) -> MarketDataset:
    return MarketDataset(
        provider="rqdata",
        dataset_kind="continuous",
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=frequency,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def test_market_dataset_model_check_accepts_seven_persisted_frequencies() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [_dataset(value) for value in ("1m", "5m", "15m", "30m", "60m", "1d", "1w")]
        )
        session.commit()

        assert {row.frequency for row in session.query(MarketDataset).all()} == {
            "1m",
            "5m",
            "15m",
            "30m",
            "60m",
            "1d",
            "1w",
        }


def test_market_dataset_model_check_rejects_unknown_frequency() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(_dataset("2m"))
        with pytest.raises(IntegrityError):
            session.commit()
