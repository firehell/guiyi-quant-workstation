from datetime import UTC, datetime

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.trader_future_importer import CHECK_RULE_VERSION, TraderFutureCsvImporter


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


def test_market_bars_filters_provider_and_data_role_for_report_kline(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    rqdata_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_5m.parquet"
    tqsdk_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "jm_5m.parquet"
    _write_jm_api_bar_file(rqdata_path, provider="rqdata", close=1005.0)
    _write_jm_api_bar_file(tqsdk_path, provider="tqsdk", close=9005.0)

    with TestingSessionLocal() as session:
        rqdata_file = _market_file(rqdata_path, provider="rqdata", data_role="primary", quality_status="passed")
        tqsdk_file = _market_file(tqsdk_path, provider="tqsdk", data_role="validation", quality_status="warning")
        session.add_all([rqdata_file, tqsdk_file])
        session.flush()
        session.add_all(
            [
                _quality_report(rqdata_file, status="passed"),
                _quality_report(tqsdk_file, status="warning"),
            ]
        )
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        response = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "5m",
                "provider": "rqdata",
                "data_role": "primary",
                "limit": 10,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["request"]["provider"] == "rqdata"
        assert payload["request"]["data_role"] == "primary"
        assert payload["coverage"]["provider"] == "rqdata"
        assert payload["coverage"]["quality_status"] == "passed"
        assert payload["quality"]["status"] == "passed"
        assert [bar["provider"] for bar in payload["bars"]] == ["rqdata"]
        assert [bar["close"] for bar in payload["bars"]] == [1005.0]

        mismatched = client.get(
            "/api/v1/market/bars",
            params={
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "5m",
                "provider": "tqsdk",
                "data_role": "primary",
                "limit": 10,
            },
        )
        assert mismatched.status_code == 200
        assert mismatched.json()["bars"] == []
    finally:
        app.dependency_overrides.clear()


def _write_jm_api_bar_file(path, *, provider: str, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": datetime(2025, 1, 2, 21, 5),
                "trading_day": datetime(2025, 1, 3).date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 10,
                "open_interest": 100,
                "turnover": close * 10,
                "period": "5m",
                "provider": provider,
                "data_version": f"{provider}_jm_5m_test",
            }
        ]
    ).to_parquet(path, index=False)


def _market_file(path, *, provider: str, data_role: str, quality_status: str) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="5m",
        start_time=datetime(2025, 1, 2, 21, 5, tzinfo=UTC),
        end_time=datetime(2025, 1, 2, 21, 5, tzinfo=UTC),
        file_path=str(path),
        row_count=1,
        data_version=f"{provider}_jm_5m_test",
        data_role=data_role,
        quality_status=quality_status,
    )


def _quality_report(market_file: MarketDataFile, *, status: str) -> DataQualityReport:
    return DataQualityReport(
        file_id=market_file.id,
        provider=market_file.provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="5m",
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        status=status,
        missing_bars=0,
        duplicated_bars=0,
        abnormal_price_count=0,
        abnormal_volume_count=0,
        details={"check_rule_version": CHECK_RULE_VERSION},
    )
