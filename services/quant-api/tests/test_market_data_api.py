from datetime import UTC, datetime

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, LiveMinuteBar, MarketDataFile
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def test_klines_api_returns_canonical_bars(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_api_bar_file(
            path,
            provider="rqdata",
            symbol="rb",
            contract="rb.MAIN",
            exchange="SHFE",
            period="5m",
            closes=[4010.0, 4020.0],
            start=datetime(2021, 1, 4, 9, 5),
        )
        market_file = _market_file(
            path,
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            symbol="rb",
            contract="rb.MAIN",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 10, tzinfo=UTC),
        )
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file, status="passed"))
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
        assert payload[0]["openInterest"] == 100.0

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
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "rb_5m.parquet"
        _write_api_bar_file(
            path,
            provider="rqdata",
            symbol="rb",
            contract="rb.MAIN",
            exchange="SHFE",
            period="5m",
            closes=[3010.0, 3020.0],
        )
        market_file = _market_file(path, provider="rqdata", data_role="primary", quality_status="warning", symbol="rb", contract="rb.MAIN")
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file, status="warning"))
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


def test_live_market_api_requires_explicit_live_endpoints_and_keeps_historical_clean(tmp_path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    historical_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm_5m.parquet"
    _write_jm_api_bar_file(historical_path, provider="rqdata", close=1005.0)
    with TestingSessionLocal() as session:
        market_file = _market_file(historical_path, provider="rqdata", data_role="primary", quality_status="passed")
        session.add(market_file)
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=datetime(2026, 7, 7, 9, 1),
                trading_day=datetime(2026, 7, 7).date(),
                open=100,
                high=102,
                low=99,
                close=101,
                volume=10,
                open_interest=100,
                turnover=1000,
                bar_status="confirmed",
                quality_status="warning",
                source_mode="poll_get_price_1m",
                raw_payload={"quality_reasons": ["missing_trading_day"]},
            )
        )
        session.flush()
        session.add(_quality_report(market_file, status="passed"))
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        historical = client.get(
            "/api/v1/market/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1m", "limit": 10},
        )
        assert historical.status_code == 200
        assert historical.json()["bars"] == []

        coverage = client.get("/api/v1/market/live/coverage")
        assert coverage.status_code == 200
        coverage_payload = coverage.json()
        assert coverage_payload["items"][0]["data_type"] == "live_db"
        assert coverage_payload["items"][0]["quality_status"] == "warning"

        live = client.get(
            "/api/v1/market/live/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1m", "limit": 10},
        )
        assert live.status_code == 200
        live_payload = live.json()
        assert len(live_payload["bars"]) == 1
        assert live_payload["bars"][0]["source_mode"] == "poll_get_price_1m"
        assert live_payload["bars"][0]["quality_status"] == "warning"
        assert live_payload["quality"]["status"] == "warning"
        assert live_payload["coverage"]["data_type"] == "live_db"

        unsupported = client.get(
            "/api/v1/market/live/bars",
            params={"symbol": "jm", "contract": "JM2609", "period": "1d", "limit": 10},
        )
        assert unsupported.status_code == 422
    finally:
        app.dependency_overrides.clear()


def _write_api_bar_file(
    path,
    *,
    provider: str,
    symbol: str,
    contract: str,
    exchange: str,
    period: str,
    closes: list[float],
    start: datetime = datetime(2026, 1, 5, 9, 5),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "symbol": symbol,
                "contract": contract,
                "exchange": exchange,
                "datetime": start + pd.Timedelta(minutes=index * 5),
                "trading_day": start.date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 10,
                "open_interest": 100,
                "turnover": close * 10,
                "period": period,
                "provider": provider,
                "data_version": f"{provider}_{symbol}_{period}_test",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_jm_api_bar_file(path, *, provider: str, close: float) -> None:
    _write_api_bar_file(
        path,
        provider=provider,
        symbol="jm",
        contract="jm.MAIN",
        exchange="DCE",
        period="5m",
        closes=[close],
    )


def _market_file(
    path,
    *,
    provider: str,
    data_role: str,
    quality_status: str,
    symbol: str = "jm",
    contract: str = "jm.MAIN",
    start: datetime = datetime(2026, 1, 5, 9, 5, tzinfo=UTC),
    end: datetime = datetime(2026, 1, 5, 9, 10, tzinfo=UTC),
) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period="5m",
        start_time=start,
        end_time=end,
        file_path=str(path),
        row_count=2,
        data_version=f"{provider}_{symbol}_5m_test",
        data_role=data_role,
        quality_status=quality_status,
    )


def _quality_report(market_file: MarketDataFile, *, status: str) -> DataQualityReport:
    return DataQualityReport(
        file_id=market_file.id,
        provider=market_file.provider,
        data_type="bars",
        instrument_symbol=market_file.instrument_symbol,
        contract_code=market_file.contract_code,
        period="5m",
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        status=status,
        missing_bars=0,
        duplicated_bars=0,
        abnormal_price_count=0,
        abnormal_volume_count=0,
        details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
    )
