from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.trader_future_importer import TraderFutureCsvImporter


def test_klines_api_returns_canonical_bars(tmp_path) -> None:
    raw_dir = tmp_path / "trader_Future_data" / "5分钟主力连续"
    raw_dir.mkdir(parents=True)
    (raw_dir / "螺纹-主连-5分钟.csv").write_text(
        "\n".join(
            [
                "Date,Time,Open,Close,High,Low,Volume,Amount",
                "2021-01-04,09:05:00,4000,4010,4020,3990,100,1000",
                "2021-01-04,09:10:00,4010,4020,4030,4000,110,1100",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=tmp_path / "trader_Future_data", parquet_root=tmp_path / "parquet")
        importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        response = client.get(
            "/api/klines",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2021-01-04",
                "end": "2021-01-04",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 2
        assert payload[0]["symbol"] == "rb"
        assert payload[0]["contract"] == "rb.MAIN"
        assert payload[0]["time"].startswith("2021-01-04T09:05:00")
        assert payload[0]["openInterest"] is None

        missing_param = client.get("/api/klines", params={"symbol": "rb", "contract": "rb.MAIN"})
        assert missing_param.status_code == 422

        empty = client.get(
            "/api/klines",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "15m",
                "start": datetime(2021, 1, 4, tzinfo=UTC).isoformat(),
                "end": datetime(2021, 1, 5, tzinfo=UTC).isoformat(),
            },
        )
        assert empty.status_code == 200
        assert empty.json() == []
    finally:
        app.dependency_overrides.clear()


def test_market_workbench_coverage_and_bars_use_canonical_data(tmp_path) -> None:
    raw_dir = tmp_path / "trader_Future_data" / "5分钟主力连续"
    raw_dir.mkdir(parents=True)
    (raw_dir / "螺纹-主连-5分钟.csv").write_text(
        "\n".join(
            [
                "Date,Time,Open,Close,High,Low,Volume,Amount",
                "2026-01-05,09:05:00,3000,3010,3020,2990,100,1000",
                "2026-01-05,09:20:00,3010,3020,3030,3000,110,1100",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=tmp_path / "trader_Future_data", parquet_root=tmp_path / "parquet")
        importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        coverage = client.get("/api/v1/market/workbench/coverage")
        assert coverage.status_code == 200
        payload = coverage.json()
        assert payload["default_selection"]["symbol"] == "rb"
        assert payload["default_selection"]["contract"] == "rb.MAIN"
        assert payload["default_selection"]["period"] == "5m"
        assert payload["items"][0]["quality_status"] == "warning"
        assert payload["items"][0]["row_count"] == 2

        bars = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "rb",
                "contract": "rb.MAIN",
                "period": "5m",
                "start": "2026-01-05",
                "end": "2026-01-05",
            },
        )
        assert bars.status_code == 200
        bars_payload = bars.json()
        assert len(bars_payload["bars"]) == 2
        assert bars_payload["bars"][0]["time"].startswith("2026-01-05T09:05:00")
        assert bars_payload["quality"]["status"] == "warning"
        assert bars_payload["coverage"]["quality_status"] == "warning"

        too_many = client.get(
            "/api/v1/market/bars",
            params={"symbol": "rb", "contract": "rb.MAIN", "period": "5m", "limit": 10001},
        )
        assert too_many.status_code == 422
    finally:
        app.dependency_overrides.clear()
