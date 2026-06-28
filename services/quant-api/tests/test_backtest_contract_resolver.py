from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.contract_resolver import (
    MainContractMappingMissingError,
    TradingParameterMissingError,
    resolve_jm_contract,
    resolve_jm_trade_contract_timeline,
)
from app.db.base import Base
from app.models.data_center import (
    Contract,
    Exchange,
    FeeMarginRule,
    FuturesTradingParameter,
    Instrument,
    MainContractMap,
    TradingCalendar,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_reference_data(session: Session) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add_all(
        [
            Contract(
                contract_code="JM2405",
                instrument_symbol="jm",
                exchange_code="DCE",
                name="焦煤2405",
                contract_month="2405",
                contract_multiplier=60,
                maturity_date=date(2024, 5, 15),
                provider="rqdata",
            ),
            Contract(
                contract_code="JM2409",
                instrument_symbol="jm",
                exchange_code="DCE",
                name="焦煤2409",
                contract_month="2024-09",
                contract_multiplier=60,
                maturity_date=date(2024, 9, 15),
                provider="rqdata",
            ),
        ]
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 29), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 4, 30), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 5, 1), is_trading_day=False, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 8, 29), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 8, 30), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2024, 9, 1), is_trading_day=False, provider="rqdata"),
        ]
    )


def _add_mapping(session: Session, trading_day: date, contract_code: str) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=trading_day,
            rank=1,
            contract_code=contract_code,
            rule="volume_open_interest",
            provider="rqdata",
            data_version="test-v1",
        )
    )


def _add_trading_parameter(session: Session, trading_day: date, contract_code: str, *, complete: bool = True) -> None:
    session.add(
        FuturesTradingParameter(
            contract_code=contract_code,
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=trading_day,
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.13"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.00011"),
            close_today_commission=Decimal("0.0002"),
            commission_type="by_money",
            price_tick=Decimal("0.5") if complete else None,
            contract_multiplier=60 if complete else None,
            provider="rqdata",
            data_version="test-v1",
        )
    )


def _add_fee_margin_rule(session: Session, contract_code: str = "JM2405") -> None:
    session.add(
        FeeMarginRule(
            provider="rqdata",
            exchange_code="DCE",
            instrument_symbol="jm",
            contract_code=contract_code,
            price_tick=Decimal("0.5"),
            volume_multiple=60,
            margin_rate=Decimal("0.14"),
            open_fee=Decimal("0.00012"),
            close_fee=Decimal("0.00013"),
            close_today_fee=Decimal("0.00021"),
            fee_type="by_money",
            effective_date=date(2024, 1, 1),
            source="test_fee_rule",
        )
    )


def test_resolves_jm_actual_contract_and_trading_parameters_for_normal_day() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _add_mapping(session, date(2024, 4, 15), "JM2405")
        _add_trading_parameter(session, date(2024, 4, 15), "JM2405")
        session.commit()

        resolved = resolve_jm_contract(session, trading_day=date(2024, 4, 15))

    assert resolved.actual_contract == "JM2405"
    assert resolved.contract_month == "2024-05"
    assert resolved.exchange == "DCE"
    assert resolved.contract_multiplier == 60
    assert resolved.price_tick == 0.5
    assert resolved.margin_ratio == 0.13
    assert resolved.commission_rule.open_fee == 0.0001
    assert resolved.commission_rule.close_fee == 0.00011
    assert resolved.parameter_source == "futures_trading_parameters"
    assert resolved.main_contract_source.provider == "rqdata"
    assert resolved.last_allowed_holding_date == date(2024, 4, 30)


def test_resolves_contract_switch_before_and_after_main_contract_change() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _add_mapping(session, date(2024, 4, 29), "JM2405")
        _add_mapping(session, date(2024, 5, 6), "JM2409")
        _add_trading_parameter(session, date(2024, 4, 29), "JM2405")
        _add_trading_parameter(session, date(2024, 5, 6), "JM2409")
        session.commit()

        timeline = resolve_jm_trade_contract_timeline(
            session,
            entry_time=datetime(2024, 4, 29, 14, 45),
            exit_time=datetime(2024, 5, 6, 9, 15),
        )

    assert timeline.entry.actual_contract == "JM2405"
    assert timeline.exit.actual_contract == "JM2409"
    assert timeline.is_contract_changed is True
    assert timeline.entry.last_allowed_holding_date == date(2024, 4, 30)
    assert timeline.exit.last_allowed_holding_date == date(2024, 8, 30)


def test_resolves_from_fee_margin_rules_when_futures_trading_parameters_missing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _add_mapping(session, date(2024, 4, 16), "JM2405")
        _add_fee_margin_rule(session)
        session.commit()

        resolved = resolve_jm_contract(session, trading_day=date(2024, 4, 16))

    assert resolved.actual_contract == "JM2405"
    assert resolved.contract_multiplier == 60
    assert resolved.price_tick == 0.5
    assert resolved.margin_ratio == 0.14
    assert resolved.commission_rule.open_fee == 0.00012
    assert resolved.parameter_source == "fee_margin_rules"


def test_resolves_mixed_parameters_when_trading_parameter_has_missing_fields() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _add_mapping(session, date(2024, 4, 17), "JM2405")
        _add_trading_parameter(session, date(2024, 4, 17), "JM2405", complete=False)
        _add_fee_margin_rule(session)
        session.commit()

        resolved = resolve_jm_contract(session, trading_day=date(2024, 4, 17))

    assert resolved.contract_multiplier == 60
    assert resolved.price_tick == 0.5
    assert resolved.margin_ratio == 0.13
    assert resolved.commission_rule.open_fee == 0.0001
    assert resolved.parameter_source == "mixed"


def test_missing_main_contract_map_fails_clearly() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.commit()

        with pytest.raises(MainContractMappingMissingError, match="main_contract_map missing.*2024-04-18"):
            resolve_jm_contract(session, trading_day=date(2024, 4, 18))


def test_missing_trading_parameters_and_fee_rules_fails_clearly() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _add_mapping(session, date(2024, 4, 19), "JM2405")
        session.commit()

        with pytest.raises(TradingParameterMissingError, match="futures_trading_parameters and fee_margin_rules both absent"):
            resolve_jm_contract(session, trading_day=date(2024, 4, 19))
