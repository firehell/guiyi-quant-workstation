from __future__ import annotations

from datetime import date
from decimal import Decimal
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import FeeMarginRule, FuturesTradingParameter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from backfill_jm_price_tick import backfill_jm_price_tick  # noqa: E402


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_rows(session: Session) -> None:
    session.add_all(
        [
            FuturesTradingParameter(
                contract_code="JM2305",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2023, 3, 1),
                long_margin_ratio=Decimal("0.20"),
                short_margin_ratio=Decimal("0.20"),
                open_commission=Decimal("0.0001"),
                close_commission=Decimal("0.0001"),
                close_today_commission=Decimal("0.00014"),
                commission_type="by_money",
                price_tick=None,
                contract_multiplier=60,
                provider="rqdata",
                data_version="test-v1",
                raw_payload={"order_book_id": "JM2305"},
            ),
            FuturesTradingParameter(
                contract_code="JM2212",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2022, 12, 30),
                price_tick=None,
                provider="rqdata",
                data_version="test-v1",
                raw_payload={},
            ),
            FuturesTradingParameter(
                contract_code="JM2309",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2023, 3, 2),
                price_tick=Decimal("1.0"),
                provider="rqdata",
                data_version="test-v1",
                raw_payload={},
            ),
            FeeMarginRule(
                provider="rqdata",
                exchange_code="DCE",
                instrument_symbol="jm",
                contract_code="JM2305",
                price_tick=None,
                volume_multiple=60,
                margin_rate=Decimal("0.20"),
                open_fee=Decimal("0.0001"),
                close_fee=Decimal("0.0001"),
                close_today_fee=Decimal("0.00014"),
                fee_type="by_money",
                effective_date=date(2023, 3, 1),
                source="rqdata_trading_parameters",
            ),
            FeeMarginRule(
                provider="rqdata",
                exchange_code="DCE",
                instrument_symbol="jm",
                contract_code="JM2309",
                price_tick=Decimal("1.0"),
                effective_date=date(2023, 3, 2),
                source="rqdata_trading_parameters",
            ),
        ]
    )
    session.commit()


def test_backfill_jm_price_tick_dry_run_reports_counts_without_writing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_rows(session)

        result = backfill_jm_price_tick(
            session,
            product="jm",
            start_date=date(2023, 1, 1),
            end_date=date(2025, 12, 31),
            price_tick=Decimal("0.5"),
            source="dce_notice_2015_95",
            apply=False,
        )

        assert result["mode"] == "dry-run"
        assert result["source"] == "dce_notice_2015_95"
        assert result["futures_trading_parameters"]["before_non_null"] == 1
        assert result["futures_trading_parameters"]["eligible_null"] == 1
        assert result["futures_trading_parameters"]["after_non_null"] == 1
        assert result["fee_margin_rules"]["before_non_null"] == 1
        assert result["fee_margin_rules"]["eligible_null"] == 1
        assert result["fee_margin_rules"]["after_non_null"] == 1

        row = session.scalar(select(FuturesTradingParameter).where(FuturesTradingParameter.contract_code == "JM2305"))
        assert row is not None
        assert row.price_tick is None


def test_backfill_jm_price_tick_apply_updates_only_null_rows_in_date_window() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_rows(session)

        result = backfill_jm_price_tick(
            session,
            product="jm",
            start_date=date(2023, 1, 1),
            end_date=date(2025, 12, 31),
            price_tick=Decimal("0.5"),
            source="dce_notice_2015_95",
            apply=True,
        )

        assert result["mode"] == "apply"
        assert result["futures_trading_parameters"]["updated"] == 1
        assert result["futures_trading_parameters"]["after_non_null"] == 2
        assert result["fee_margin_rules"]["updated"] == 1
        assert result["fee_margin_rules"]["after_non_null"] == 2

        jm2305 = session.scalar(select(FuturesTradingParameter).where(FuturesTradingParameter.contract_code == "JM2305"))
        jm2212 = session.scalar(select(FuturesTradingParameter).where(FuturesTradingParameter.contract_code == "JM2212"))
        jm2309 = session.scalar(select(FuturesTradingParameter).where(FuturesTradingParameter.contract_code == "JM2309"))
        fee = session.scalar(select(FeeMarginRule).where(FeeMarginRule.contract_code == "JM2305"))

        assert jm2305 is not None
        assert jm2305.price_tick == Decimal("0.500000")
        assert jm2305.raw_payload["price_tick_backfill"]["source"] == "dce_notice_2015_95"
        assert jm2212 is not None
        assert jm2212.price_tick is None
        assert jm2309 is not None
        assert jm2309.price_tick == Decimal("1.000000")
        assert fee is not None
        assert fee.price_tick == Decimal("0.500000")
