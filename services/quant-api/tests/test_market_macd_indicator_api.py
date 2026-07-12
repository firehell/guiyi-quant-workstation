from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import DataQualityReport, MarketDataFile
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def test_web_macd_legacy_policy_vectors_and_prefix_invariance() -> None:
    from guiyi_quant.indicators import macd_series

    closes = _jm_closes(42)
    result = macd_series(closes, 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2, round_digits=6)
    expected = _web_macd_style(closes)

    assert result.indicator_version == "v1-draft"
    assert result.parameters["ema_seed_policy"] == "sma_window"
    assert result.parameters["histogram_scale"] == 2
    assert result.calculation_basis["warmup_bars"] == 33
    assert _values(result.dea.points) == expected["dea"]
    assert _values(result.histogram.points) == expected["histogram"]
    for index, expected_dif in enumerate(expected["dif"]):
        if expected_dif is not None:
            assert result.dif.points[index].value == expected_dif

    prefix = macd_series(closes[:36], 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2, round_digits=6)
    extended = macd_series(closes[:36] + [1500.0, 1490.0], 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2, round_digits=6)
    assert _values(prefix.dif.points) == _values(extended.dif.points[:36])
    assert _values(prefix.dea.points) == _values(extended.dea.points[:36])
    assert _values(prefix.histogram.points) == _values(extended.histogram.points[:36])

    short = macd_series(closes[:20], 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2, round_digits=6)
    assert all(point.value is None for point in short.histogram.points)

    invalid = macd_series(closes[:20] + [None] + closes[21:42], 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2)
    assert invalid.dif.points[20].valid is False
    assert invalid.histogram.points[20].reason == "input_invalid"


def test_market_macd_indicator_api_returns_read_only_web_policy(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    closes = _jm_closes(42)
    with TestingSessionLocal() as session:
        path = tmp_path / "parquet" / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet"
        _write_api_bar_file(path, closes=closes)
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="15m",
            start_time=datetime(2026, 7, 1, 9, 15, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 19, 30, tzinfo=UTC),
            file_path=str(path),
            row_count=len(closes),
            data_version="jm_macd_fixture_v1",
            data_role="primary",
            quality_status="passed",
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
            "/api/v1/market/indicators/macd",
            params={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "start": "2026-07-01",
                "end": "2026-07-01",
                "provider": "rqdata",
                "data_role": "primary",
                "limit": 10000,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        expected = _web_macd_style(closes)
        assert payload["policy"] == "web_macd_legacy_v1"
        assert payload["indicator_version"] == "v1-draft"
        assert payload["parameters"]["ema_seed_policy"] == "sma_window"
        assert payload["parameters"]["histogram_scale"] == 2
        assert payload["basis"]["histogram_formula"] == "(DIF - DEA) * 2"
        assert payload["source_bar_count"] == len(closes)
        assert payload["ready_count"] == sum(1 for value in expected["histogram"] if value is not None)
        assert payload["dif"][25]["value"] is None
        assert payload["dif"][-1]["value"] == expected["dif"][-1]
        assert payload["histogram"][-1]["value"] == expected["histogram"][-1]
        assert payload["histogram"][0]["ready"] is False
        assert payload["coverage"]["quality_status"] == "passed"
        assert payload["request"]["symbol"] == "jm"

        unsupported = client.get(
            "/api/v1/market/indicators/macd",
            params={"symbol": "jm", "contract": "JM2609", "period": "15m", "policy": "quant_core_strategy_legacy_v1"},
        )
        assert unsupported.status_code == 422
    finally:
        app.dependency_overrides.clear()

    with TestingSessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 1
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 1


def _jm_closes(count: int) -> list[float]:
    return [1680.0 + index * 1.7 + (index % 5 - 2) * 4.0 for index in range(count)]


def _write_api_bar_file(path: Path, *, closes: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    start = datetime(2026, 7, 1, 9, 15)
    for index, close in enumerate(closes):
        timestamp = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "datetime": timestamp,
                "trading_day": timestamp.date().isoformat(),
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "open": close - 1.0,
                "high": close + 3.0,
                "low": close - 3.0,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * (100 + index),
                "period": "15m",
                "provider": "rqdata",
                "data_version": "jm_macd_fixture_v1",
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _quality_report(market_file: MarketDataFile, *, status: str) -> DataQualityReport:
    return DataQualityReport(
        file_id=market_file.id,
        provider=market_file.provider,
        data_type="bars",
        instrument_symbol=market_file.instrument_symbol,
        contract_code=market_file.contract_code,
        period=market_file.period,
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        status=status,
        missing_bars=0,
        duplicated_bars=0,
        abnormal_price_count=0,
        abnormal_volume_count=0,
        details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
    )


def _web_macd_style(closes: list[float]) -> dict[str, list[float | None]]:
    fast = _ema_values(closes, 12)
    slow = _ema_values(closes, 26)
    dif_values: list[tuple[int, float]] = []
    for index, (fast_value, slow_value) in enumerate(zip(fast, slow, strict=True)):
        if fast_value is None or slow_value is None:
            continue
        dif_values.append((index, fast_value - slow_value))

    dea_compact = _ema_values([value for _, value in dif_values], 9)
    dif: list[float | None] = [None] * len(closes)
    dea: list[float | None] = [None] * len(closes)
    histogram: list[float | None] = [None] * len(closes)
    for local_index, dea_value in enumerate(dea_compact):
        if dea_value is None:
            continue
        source_index, dif_value = dif_values[local_index]
        dif[source_index] = round(dif_value, 6)
        dea[source_index] = round(dea_value, 6)
        histogram[source_index] = round((dif_value - dea_value) * 2, 6)
    return {"dif": dif, "dea": dea, "histogram": histogram}


def _ema_values(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    multiplier = 2 / (period + 1)
    previous = sum(values[:period]) / period
    result[period - 1] = previous
    for index in range(period, len(values)):
        previous = (values[index] - previous) * multiplier + previous
        result[index] = previous
    return result


def _values(points) -> list[float | None]:
    return [point.value for point in points]
