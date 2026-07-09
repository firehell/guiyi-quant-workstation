from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import FeeMarginRule, FuturesTradingParameter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backfill_jm_price_tick import backfill_jm_price_tick  # noqa: E402


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_price_tick_rows(session) -> None:
    rows = [
        ("JM2609", date(2026, 4, 24), None),
        ("JM2609", date(2026, 4, 27), None),
        ("JM2609", date(2026, 7, 7), Decimal("0.5")),
        ("JM2610", date(2026, 4, 24), None),
    ]
    for contract, trade_date, price_tick in rows:
        session.add(
            FuturesTradingParameter(
                contract_code=contract,
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=trade_date,
                long_margin_ratio=Decimal("0.12"),
                short_margin_ratio=Decimal("0.12"),
                open_commission=Decimal("0.0001"),
                close_commission=Decimal("0.0001"),
                close_today_commission=Decimal("0.0001"),
                commission_type="by_money",
                price_tick=price_tick,
                contract_multiplier=60,
                provider="rqdata",
                data_version="rqdata_structured_v1",
                raw_payload={"contract": contract},
            )
        )
        session.add(
            FeeMarginRule(
                provider="rqdata",
                exchange_code="DCE",
                instrument_symbol="jm",
                contract_code=contract,
                price_tick=price_tick,
                volume_multiple=60,
                margin_rate=Decimal("0.12"),
                open_fee=Decimal("0.0001"),
                close_fee=Decimal("0.0001"),
                close_today_fee=Decimal("0.0001"),
                fee_type="by_money",
                effective_date=trade_date,
                source="rqdata_trading_parameters",
            )
        )
    session.commit()


def test_contract_limited_backfill_updates_only_requested_contract() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_price_tick_rows(session)

        dry_run = backfill_jm_price_tick(
            session,
            product="jm",
            contract="JM2609",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 7, 7),
            price_tick=Decimal("0.5"),
            source="dce_jm_contract_spec_min_tick_0_5_rqdata_jm2609_20260707",
            expected_eligible_null=2,
            apply=False,
        )

        assert dry_run["contract"] == "JM2609"
        assert dry_run["futures_trading_parameters"]["eligible_null"] == 2
        assert dry_run["fee_margin_rules"]["eligible_null"] == 2

        result = backfill_jm_price_tick(
            session,
            product="jm",
            contract="JM2609",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 7, 7),
            price_tick=Decimal("0.5"),
            source="dce_jm_contract_spec_min_tick_0_5_rqdata_jm2609_20260707",
            expected_eligible_null=2,
            apply=True,
        )
        session.commit()

        assert result["futures_trading_parameters"]["updated"] == 2
        assert result["fee_margin_rules"]["updated"] == 2
        assert result["futures_trading_parameters"]["after_non_null"] == 3
        assert result["fee_margin_rules"]["after_non_null"] == 3

        jm2609_rows = list(
            session.scalars(
                select(FuturesTradingParameter)
                .where(FuturesTradingParameter.contract_code == "JM2609")
                .order_by(FuturesTradingParameter.trade_date)
            )
        )
        assert all(row.price_tick == Decimal("0.500000") for row in jm2609_rows)
        assert jm2609_rows[0].raw_payload["price_tick_backfill"] == {
            "stage": "13-F",
            "source": "dce_jm_contract_spec_min_tick_0_5_rqdata_jm2609_20260707",
            "product": "jm",
            "contract": "JM2609",
            "provider": "rqdata",
            "start_date": "2026-04-01",
            "end_date": "2026-07-07",
            "price_tick": "0.5",
        }

        other_contract = session.scalar(select(FuturesTradingParameter).where(FuturesTradingParameter.contract_code == "JM2610"))
        assert other_contract is not None
        assert other_contract.price_tick is None


def test_expected_eligible_null_guard_blocks_unexpected_scope() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_price_tick_rows(session)

        with pytest.raises(ValueError, match="eligible_null guard failed"):
            backfill_jm_price_tick(
                session,
                product="jm",
                contract="JM2609",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 7, 7),
                price_tick=Decimal("0.5"),
                source="dce_jm_contract_spec_min_tick_0_5_rqdata_jm2609_20260707",
                expected_eligible_null=56,
                apply=True,
            )

        assert (
            session.scalar(
                select(FuturesTradingParameter.price_tick).where(
                    FuturesTradingParameter.contract_code == "JM2609",
                    FuturesTradingParameter.trade_date == date(2026, 4, 24),
                )
            )
            is None
        )


def test_contract_limited_backfill_rejects_non_jm_contract() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_price_tick_rows(session)

        with pytest.raises(ValueError, match="only supports JM contracts"):
            backfill_jm_price_tick(
                session,
                product="jm",
                contract="RB2609",
                start_date=date(2026, 4, 1),
                end_date=date(2026, 7, 7),
                price_tick=Decimal("0.5"),
                source="not_used",
                apply=False,
            )
