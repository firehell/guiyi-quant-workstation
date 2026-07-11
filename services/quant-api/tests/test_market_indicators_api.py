from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def test_market_indicators_returns_unified_ema_with_warmup_window(tmp_path) -> None:
    engine, TestingSessionLocal = _memory_db()
    Base.metadata.create_all(bind=engine)
    start = datetime(2026, 1, 5, 9, 0)
    closes = [float(100 + index) for index in range(70)]

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
        _write_bar_file(path, closes=closes, start=start, period_minutes=15)
        market_file = _market_file(path, start=start, end=start + timedelta(minutes=15 * 69), row_count=len(closes))
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file))
        session.commit()

    with _client(TestingSessionLocal) as client:
        display_start = start + timedelta(minutes=15 * 60)
        display_end = start + timedelta(minutes=15 * 69)
        response = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "indicator_codes": "ema21,ema60",
                "display_start": display_start.isoformat(),
                "display_end": display_end.isoformat(),
                "display_bar_count": 10,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warmup"]["max_warmup_bars"] == 59
    assert payload["warmup"]["read_limit"] == 69
    assert payload["warmup"]["display_bar_count"] == 10
    assert [item["indicator_code"] for item in payload["indicators"]] == ["ema21", "ema60"]
    ema21 = payload["indicators"][0]
    assert ema21["indicator_version"] == "v1"
    assert ema21["warmup_bars"] == 20
    assert ema21["repainting_risk"] == "none"
    assert len(ema21["points"]) == 10
    assert ema21["points"][0]["ready"] is True
    assert ema21["points"][0]["valid"] is True
    assert ema21["points"][-1]["value"] == 159.0


def test_market_indicators_marks_early_visible_points_as_warming_up(tmp_path) -> None:
    engine, TestingSessionLocal = _memory_db()
    Base.metadata.create_all(bind=engine)
    start = datetime(2026, 1, 5, 9, 0)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m_short.parquet"
        _write_bar_file(path, closes=[100.0, 101.0, 102.0, 103.0, 104.0], start=start, period_minutes=15)
        market_file = _market_file(path, start=start, end=start + timedelta(minutes=60), row_count=5)
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file))
        session.commit()

    with _client(TestingSessionLocal) as client:
        response = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "indicator_codes": "ema10",
                "display_start": start.isoformat(),
                "display_end": (start + timedelta(minutes=60)).isoformat(),
                "display_bar_count": 5,
            },
        )

    assert response.status_code == 200
    points = response.json()["indicators"][0]["points"]
    assert len(points) == 5
    assert {point["ready"] for point in points} == {False}
    assert {point["reason"] for point in points} == {"warming_up"}


def test_market_indicators_skips_non_validated_and_unknown_codes(tmp_path) -> None:
    engine, TestingSessionLocal = _memory_db()
    Base.metadata.create_all(bind=engine)
    start = datetime(2026, 1, 5, 9, 0)

    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
        _write_bar_file(path, closes=[float(100 + index) for index in range(30)], start=start, period_minutes=15)
        market_file = _market_file(path, start=start, end=start + timedelta(minutes=15 * 29), row_count=30)
        session.add(market_file)
        session.flush()
        session.add(_quality_report(market_file))
        session.commit()

    with _client(TestingSessionLocal) as client:
        response = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "indicator_codes": "ema21,huo_tian_da_you,htdy,not_real",
                "display_start": start.isoformat(),
                "display_end": (start + timedelta(minutes=15 * 29)).isoformat(),
                "display_bar_count": 30,
            },
        )

    assert response.status_code == 200
    indicators = response.json()["indicators"]
    assert [item["indicator_code"] for item in indicators] == ["ema21"]


def test_market_indicators_rejects_failed_and_validation_sources(tmp_path) -> None:
    engine, TestingSessionLocal = _memory_db()
    Base.metadata.create_all(bind=engine)
    start = datetime(2026, 1, 5, 9, 0)

    with TestingSessionLocal() as session:
        failed_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "failed.parquet"
        validation_path = tmp_path / "parquet" / "canonical" / "bars" / "provider=tqsdk" / "validation.parquet"
        _write_bar_file(failed_path, closes=[float(500 + index) for index in range(30)], start=start, period_minutes=15)
        _write_bar_file(validation_path, closes=[float(900 + index) for index in range(30)], start=start, period_minutes=15)
        session.add(
            _market_file(
                failed_path,
                start=start,
                end=start + timedelta(minutes=15 * 29),
                row_count=30,
                provider="rqdata",
                data_role="primary",
                quality_status="failed",
            )
        )
        session.add(
            _market_file(
                validation_path,
                start=start,
                end=start + timedelta(minutes=15 * 29),
                row_count=30,
                provider="tqsdk",
                data_role="validation",
                quality_status="warning",
            )
        )
        session.commit()

    with _client(TestingSessionLocal) as client:
        response = client.get(
            "/api/v1/market/indicators",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "indicator_codes": "ema21",
                "display_start": start.isoformat(),
                "display_end": (start + timedelta(minutes=15 * 29)).isoformat(),
                "display_bar_count": 30,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warmup"]["source_bar_count"] == 0
    assert payload["indicators"][0]["points"] == []


def _memory_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


class _client:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def __enter__(self) -> TestClient:
        def override_get_db():
            with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        return self.client

    def __exit__(self, *_args) -> None:
        app.dependency_overrides.clear()


def _write_bar_file(path, *, closes: list[float], start: datetime, period_minutes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, close in enumerate(closes):
        timestamp = start + timedelta(minutes=period_minutes * index)
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "indicator-test",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _market_file(
    path,
    *,
    start: datetime,
    end: datetime,
    row_count: int,
    provider: str = "rqdata",
    data_role: str = "primary",
    quality_status: str = "passed",
) -> MarketDataFile:
    return MarketDataFile(
        provider=provider,
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=start.replace(tzinfo=UTC),
        end_time=end.replace(tzinfo=UTC),
        file_path=str(path),
        row_count=row_count,
        data_version=f"{provider}_{data_role}_{quality_status}",
        data_role=data_role,
        quality_status=quality_status,
    )


def _quality_report(market_file: MarketDataFile) -> DataQualityReport:
    return DataQualityReport(
        file_id=market_file.id,
        provider=market_file.provider,
        data_type="bars",
        instrument_symbol=market_file.instrument_symbol,
        contract_code=market_file.contract_code,
        period=market_file.period,
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        status="passed",
        missing_bars=0,
        duplicated_bars=0,
        abnormal_price_count=0,
        abnormal_volume_count=0,
        details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
    )
