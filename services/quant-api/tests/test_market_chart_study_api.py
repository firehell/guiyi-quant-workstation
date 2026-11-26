from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import market
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult


END = datetime(2026, 1, 5, 7, tzinfo=UTC)
PARAMS = {
    "symbol": "rb", "series_kind": "contract", "frequency": "1d", "contract": "RB2605",
    "first": END.isoformat(), "last": END.isoformat(), "count": 1, "studies": "ema10,boll",
}
PATH = "/api/v1/market/indicators/chart-window"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    def get_test_db():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(market.router)
    app.dependency_overrides[market.get_db] = get_test_db
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_chart_study_contract_uses_exact_inclusive_bound(client, monkeypatch):
    requests = []

    class Historical:
        def query_page_inclusive(self, request):
            requests.append(request)
            bar = CanonicalBar(
                END, date(2026, 1, 5), Decimal(100), Decimal(101), Decimal(99),
                Decimal(100), Decimal(1), None, None,
            )
            return MarketSeriesPageResult({}, (bar,), (END, END), False, None, ())

    monkeypatch.setattr(market, "build_market_data_service", lambda *args, **kwargs: Historical())
    response = client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    assert len(requests) == 1
    assert requests[0].before == END
    assert requests[0].limit == 1
    payload = response.json()
    assert payload["contract"] == "RB2605"
    assert payload["unavailable_reason"] is None
    assert payload["segments"][0]["physical_contract"] == "RB2605"
    features = payload["segments"][0]["features"]
    assert [feature["study"] for feature in features] == ["ema10", "boll"]
    assert len(payload["segments"][0]["bars"][0]["source_bar_sha256"]) == 64
    assert all(feature["points"] == [
        {"status": "WARMING", "values": None, "diagnostic": "LOOKBACK_REQUIRED"},
    ] for feature in features)


def test_chart_study_rejects_invalid_requests_or_busy_and_never_reads_synthetic_owner(client, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("market read must not be called")

    monkeypatch.setattr(market, "build_market_data_service", unexpected)
    invalid = client.get(PATH, params={**PARAMS, "studies": "ema21,ema21"})
    assert invalid.status_code == 422
    invalid = client.get(PATH, params={**PARAMS, "count": 2001})
    assert invalid.status_code == 422
    continuous = {key: value for key, value in PARAMS.items() if key != "contract"}
    response = client.get(PATH, params={**continuous, "series_kind": "continuous"})
    assert response.status_code == 200
    assert response.json()["unavailable_reason"] == "PHYSICAL_OWNER_REQUIRED"
    assert response.json()["segments"] == []
    assert market._CHART_STUDY_GATE.acquire(blocking=False)
    try:
        response = client.get(PATH, params=PARAMS)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MARKET_CHART_STUDY_BUSY"
    finally:
        market._CHART_STUDY_GATE.release()
