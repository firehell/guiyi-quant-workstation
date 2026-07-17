from __future__ import annotations

from datetime import date, time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    Contract,
    Exchange,
    FuturesContractUniverse,
    FuturesTradingParameter,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)
from app.services.rqdata_ingest.full_history_reference_metadata import (
    ReferenceMetadataConfig,
    collect_reference_metadata,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_reference_metadata_is_applicability_aware_and_sessions_are_not_yearly() -> None:
    session = _session()
    session.add(Exchange(code="DCE", name="Dalian"))
    session.add(Instrument(symbol="jm", name="Coking coal", exchange_code="DCE"))
    session.add(
        Contract(
            contract_code="JM1305",
            instrument_symbol="jm",
            exchange_code="DCE",
            product="jm",
            listed_date=date(2013, 3, 22),
            provider="rqdata",
        )
    )
    for trade_date in (date(2013, 3, 22), date(2013, 3, 25)):
        if trade_date == date(2013, 3, 22):
            session.add(
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=trade_date,
                    is_trading_day=True,
                    provider="rqdata",
                )
            )
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=trade_date,
                rank=1,
                contract_code="JM1305",
                provider="rqdata",
                data_version="test",
            )
        )
        session.add(
            FuturesContractUniverse(
                instrument_symbol="jm",
                trade_date=trade_date,
                contract_code="JM1305",
                provider="rqdata",
                data_version="test",
            )
        )
        session.add(
            FuturesTradingParameter(
                contract_code="JM1305",
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=trade_date,
                provider="rqdata",
                data_version="test",
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9),
            end_time=time(15),
            is_active=True,
            provider="rqdata",
        )
    )
    session.commit()

    result = collect_reference_metadata(
        session,
        ReferenceMetadataConfig(
            products=("jm",),
            audit_end=date(2013, 3, 25),
            require_postgresql=False,
            actual_role_products=("jm",),
            continuous_role_products=(),
        ),
    )

    session_rows = [row for row in result.matrix if row["metadata_type"] == "trading_session"]
    continuous_rows = [row for row in result.matrix if row["metadata_type"] == "continuous_contract_map"]
    assert len(session_rows) == 1
    assert session_rows[0]["applicability"] == "not_applicable"
    assert session_rows[0]["status"] == "not_applicable"
    assert session_rows[0]["reason"] == "static_session_not_historical_reference_requirement"
    assert not any(row["gap_category"] == "trading_session_gap" for row in result.gaps)
    assert continuous_rows[0]["applicability"] == "not_applicable"
    assert continuous_rows[0]["status"] == "not_applicable"
    assert any(
        row["reason"] == "blocked_by_trading_calendar"
        for row in result.matrix
        if row["metadata_type"] in {"main_contract_map", "contract_universe", "trading_parameter"}
    )
    assert {gap["gap_category"] for gap in result.gaps} <= {
        "asset_registration_gap",
        "main_contract_map_gap",
        "contract_universe_gap",
        "continuous_contract_map_gap",
        "trading_parameter_gap",
        "trading_calendar_gap",
        "trading_session_gap",
    }


def test_rank1_ranges_come_from_mapping_not_discovered_files() -> None:
    session = _session()
    for trade_date, contract in (
        (date(2026, 7, 6), "A2609"),
        (date(2026, 7, 7), "A2609"),
        (date(2026, 7, 8), "A2701"),
    ):
        session.add(
            MainContractMap(
                instrument_symbol="a",
                trade_date=trade_date,
                rank=1,
                contract_code=contract,
                provider="rqdata",
                data_version="test",
            )
        )
    session.commit()

    result = collect_reference_metadata(
        session,
        ReferenceMetadataConfig(
            products=("a",),
            audit_end=date(2026, 7, 10),
            require_postgresql=False,
            actual_role_products=("a",),
        ),
    )

    assert [(item.contract, item.start, item.end) for item in result.rank1_ranges] == [
        ("A2609", date(2026, 7, 6), date(2026, 7, 7)),
        ("A2701", date(2026, 7, 8), date(2026, 7, 8)),
    ]


def test_direct_postgresql_requirement_fails_closed() -> None:
    session = _session()
    try:
        collect_reference_metadata(
            session,
            ReferenceMetadataConfig(products=("a",), audit_end=date(2026, 7, 10)),
        )
    except RuntimeError as exc:
        assert "ENV_BLOCKED_DB" in str(exc)
    else:
        raise AssertionError("SQLite must not satisfy direct PostgreSQL gate")
