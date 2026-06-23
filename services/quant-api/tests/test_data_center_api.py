from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import (
    Contract,
    DataDownloadTask,
    DataQualityReport,
    DataSource,
    Exchange,
    Instrument,
    MarketDataFile,
)


def test_data_center_endpoints_return_seeded_records() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        exchange = Exchange(code="SHFE", name="上海期货交易所", country="CN")
        instrument = Instrument(symbol="rb", name="螺纹", exchange_code="SHFE", sector="black")
        contract = Contract(
            contract_code="rb.MAIN",
            instrument_symbol="rb",
            exchange_code="SHFE",
            name="螺纹主力连续",
            status="research",
            provider="trader_future_data",
        )
        source = DataSource(
            name="交易练习者主力连续",
            provider="trader_future_data",
            status="enabled",
            priority=10,
        )
        task = DataDownloadTask(
            task_no="task-test",
            provider="trader_future_data",
            data_type="main_continuous_kline",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="5m",
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            status="success",
            progress=100,
        )
        market_file = MarketDataFile(
            provider="trader_future_data",
            data_type="main_continuous_kline",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="5m",
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            file_path="data/parquet/example.parquet",
            row_count=10,
            quality_status="passed",
            data_version="test",
        )
        quality = DataQualityReport(
            provider="trader_future_data",
            data_type="main_continuous_kline",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            period="5m",
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            status="passed",
        )
        session.add_all([exchange, instrument, contract, source, task, market_file, quality])
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        contracts = client.get("/api/v1/data/contracts")
        assert contracts.status_code == 200
        assert contracts.json()[0]["contract_code"] == "rb.MAIN"

        symbols = client.get("/api/symbols")
        assert symbols.status_code == 200
        assert symbols.json()[0]["symbol"] == "rb.MAIN"

        coverage = client.get("/api/v1/data/coverage")
        assert coverage.status_code == 200
        assert coverage.json()[0]["row_count"] == 10

        tasks = client.get("/api/v1/data/download-tasks")
        assert tasks.status_code == 200
        assert tasks.json()[0]["status"] == "success"
    finally:
        app.dependency_overrides.clear()
