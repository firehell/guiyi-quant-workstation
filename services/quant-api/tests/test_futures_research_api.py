from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import (
    Exchange,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesExFactor,
    FuturesMemberRank,
    FuturesRollYield,
    FuturesTradingParameter,
    FuturesWarehouseStock,
    Instrument,
    MainContractMap,
)


def _memory_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return engine, TestingSessionLocal


def _seed_research_data(session) -> None:
    session.add(Exchange(code="DCE", name="大连商品交易所"))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", category="商品期货"))
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 2),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesExFactor(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            contract_code="JM2609",
            prev_close_spread=Decimal("12.5"),
            prev_close_ratio=Decimal("100.5"),
            provider="rqdata",
            data_version="rqdata_structured_v1",
            raw_payload={"ex_factor": 12.5, "ex_cum_factor": 100.5},
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code="JM2609",
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=date(2026, 6, 1),
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.12"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.0001"),
            price_tick=Decimal("0.5"),
            contract_multiplier=60,
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesWarehouseStock(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            warehouse="",
            quantity=Decimal("1200"),
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesRollYield(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            near_contract="JM2609",
            far_contract="JM2610",
            roll_yield=Decimal("0.001"),
            provider="rqdata",
            data_version="rqdata_structured_v1",
            raw_payload={"yield": 0.001, "annualized_yield_trading": 0.12},
        )
    )
    session.add(
        FuturesContractUniverse(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            contract_code="JM2609",
            sort_order=1,
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesContractUniverse(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            contract_code="JM2610",
            sort_order=2,
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesContinuousContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            continuous_type="front_month",
            contract_code="JM2609",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesMemberRank(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            rank_by="volume",
            member_name="中信期货",
            rank=1,
            volume=Decimal("10000"),
            volume_change=Decimal("500"),
            commodity_id="JM",
            target_type="product",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesMemberRank(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            rank_by="volume",
            member_name="永安期货",
            rank=2,
            volume=Decimal("8000"),
            volume_change=Decimal("-200"),
            commodity_id="JM",
            target_type="product",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesMemberRank(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 2),
            rank_by="volume",
            member_name="中信期货",
            rank=1,
            volume=Decimal("12000"),
            volume_change=Decimal("2000"),
            commodity_id="JM",
            target_type="product",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.add(
        FuturesMemberRank(
            instrument_symbol="jm",
            trade_date=date(2026, 6, 1),
            rank_by="long",
            member_name="国泰君安",
            rank=1,
            volume=Decimal("5000"),
            volume_change=Decimal("100"),
            commodity_id="JM",
            target_type="product",
            provider="rqdata",
            data_version="rqdata_structured_v1",
        )
    )
    session.commit()


def test_research_panels_catalog() -> None:
    _, TestingSessionLocal = _memory_session()
    with TestingSessionLocal() as session:
        _seed_research_data(session)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/v1/market/research/panels", params={"symbol": "jm", "contract": "JM2609"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["symbol"] == "jm"
        panel_ids = {item["panel_id"] for item in payload["panels"]}
        assert "dominant" in panel_ids
        assert "member-rank" in panel_ids
        member_rank = next(item for item in payload["panels"] if item["panel_id"] == "member-rank")
        assert member_rank["enabled"] is True
        trading = next(item for item in payload["panels"] if item["panel_id"] == "trading-parameters")
        assert trading["enabled"] is True
    finally:
        app.dependency_overrides.clear()


def test_research_dominant_panel_returns_chart_and_rows() -> None:
    _, TestingSessionLocal = _memory_session()
    with TestingSessionLocal() as session:
        _seed_research_data(session)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/market/research/dominant",
            params={"symbol": "jm", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["panel_id"] == "dominant"
        assert payload["row_count"] == 2
        assert payload["source"] == "local_postgresql"
        assert payload["chart"]["chart_type"] == "step"
        assert len(payload["chart"]["series"][0]["data"]) == 2
        assert payload["rows"][0]["contract_code"] == "JM2609"
    finally:
        app.dependency_overrides.clear()


def test_research_trading_parameters_requires_contract() -> None:
    _, TestingSessionLocal = _memory_session()
    with TestingSessionLocal() as session:
        _seed_research_data(session)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        missing = client.get(
            "/api/v1/market/research/trading-parameters",
            params={"symbol": "jm", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert missing.status_code == 422

        response = client.get(
            "/api/v1/market/research/trading-parameters",
            params={"symbol": "jm", "contract": "JM2609", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["row_count"] == 1
        assert payload["rows"][0]["long_margin_ratio"] == 0.12
    finally:
        app.dependency_overrides.clear()


def test_research_empty_range_returns_sync_hint() -> None:
    _, TestingSessionLocal = _memory_session()
    with TestingSessionLocal() as session:
        _seed_research_data(session)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/market/research/warehouse-stocks",
            params={"symbol": "jm", "start": "2020-01-01", "end": "2020-01-31"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["row_count"] == 0
        assert payload["empty_reason"] is not None
        assert "rqdata_research_enhancers_sync.py" in payload["empty_reason"]
    finally:
        app.dependency_overrides.clear()


def test_research_member_rank_panel_filters_rank_by_and_builds_snapshot_chart() -> None:
    _, TestingSessionLocal = _memory_session()
    with TestingSessionLocal() as session:
        _seed_research_data(session)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/market/research/member-rank",
            params={"symbol": "jm", "rank_by": "volume", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["panel_id"] == "member-rank"
        assert payload["row_count"] == 3
        assert payload["chart"]["chart_type"] == "bar"
        assert len(payload["chart"]["xAxis"]) == 1
        assert payload["chart"]["xAxis"][0] == "中信期货"
        assert payload["chart"]["series"][0]["data"][0] == 12000
        assert "2026-06-02" in payload["chart"]["series"][0]["name"]

        long_only = client.get(
            "/api/v1/market/research/member-rank",
            params={"symbol": "jm", "rank_by": "long", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert long_only.status_code == 200
        assert long_only.json()["row_count"] == 1
        assert long_only.json()["rows"][0]["member_name"] == "国泰君安"

        empty = client.get(
            "/api/v1/market/research/member-rank",
            params={"symbol": "jm", "rank_by": "short", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert empty.status_code == 200
        assert empty.json()["row_count"] == 0
        assert empty.json()["empty_reason"] is not None
        assert "rqdata_member_rank_sync.py" in empty.json()["empty_reason"]

        invalid = client.get(
            "/api/v1/market/research/member-rank",
            params={"symbol": "jm", "rank_by": "invalid", "start": "2026-06-01", "end": "2026-06-30"},
        )
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
