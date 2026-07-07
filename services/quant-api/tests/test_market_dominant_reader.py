from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import Exchange, Instrument, MainContractMap, MarketDataFile
from app.services.market_dominant_reader import (
    DominantContractReader,
    QuoteContractError,
    validate_quote_contract,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed(session: Session) -> None:
    session.add(Exchange(code="DCE", name="大连商品交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Exchange(code="SHFE", name="上海期货交易所", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(Instrument(symbol="rb", name="螺纹钢", exchange_code="SHFE", is_active=True))
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 6),
                rank=1,
                contract_code="JM2605",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-v1",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 7),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-v2",
            ),
            MainContractMap(
                instrument_symbol="rb",
                trade_date=date(2026, 7, 7),
                rank=1,
                contract_code="RB2510",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="map-rb",
            ),
        ]
    )
    session.add(
        MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="15m",
            start_time=datetime(2026, 4, 1, 9, 15, tzinfo=UTC),
            end_time=datetime(2026, 7, 7, 15, 0, tzinfo=UTC),
            file_path="/tmp/jm2609_15m.parquet",
            row_count=100,
            data_version="jm2609_15m",
            data_role="primary",
            quality_status="passed",
        )
    )
    session.commit()


def test_validate_quote_contract_rejects_main() -> None:
    try:
        validate_quote_contract("jm.MAIN")
        raise AssertionError("expected QuoteContractError")
    except QuoteContractError as exc:
        assert "actual_contract" in str(exc)


def test_list_dominants_uses_latest_mapping_and_coverage() -> None:
    factory = _session_factory()
    with factory() as session:
        _seed(session)
        response = DominantContractReader(session).list_dominants()
        assert response.default_quote_period == "15m"
        assert len(response.items) == 2

        jm = next(item for item in response.items if item.product == "jm")
        assert jm.actual_contract == "JM2609"
        assert jm.dominant_mapping_date == date(2026, 7, 7)
        assert jm.continuous_contract == "jm.MAIN"
        assert jm.quote_ready is True
        assert jm.bars_coverage["15m"].row_count == 100

        rb = next(item for item in response.items if item.product == "rb")
        assert rb.actual_contract == "RB2510"
        assert rb.quote_ready is False


def test_list_dominants_filters_quote_ready_and_search() -> None:
    factory = _session_factory()
    with factory() as session:
        _seed(session)
        ready = DominantContractReader(session).list_dominants(quote_ready=True)
        assert [item.product for item in ready.items] == ["jm"]

        search = DominantContractReader(session).list_dominants(search="螺纹")
        assert len(search.items) == 1
        assert search.items[0].product == "rb"
