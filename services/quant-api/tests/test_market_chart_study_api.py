from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import market
from app.compute_runtime import ComputeRuntime
from app.market_data import chart_indicators
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult
from guiyi_quant.compute import REGISTRY


END = datetime(2026, 1, 5, 7, tzinfo=UTC)
PARAMS = {
    "symbol": "rb", "series_kind": "contract", "frequency": "1d", "contract": "RB2605",
    "first": END.isoformat(), "last": END.isoformat(), "count": 1, "studies": "ema10,boll",
}
PATH = "/api/v1/market/indicators/chart-window"


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    def get_test_db():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(market.router)
    app.dependency_overrides[market.get_db] = get_test_db
    with ComputeRuntime(REGISTRY, batch_pending=1) as runtime:
        monkeypatch.setattr(chart_indicators, "_CHART_COMPUTE", runtime)
        with TestClient(app) as client:
            yield client
    engine.dispose()


@pytest.mark.parametrize("profile", [None, "newow"])
def test_chart_study_contract_uses_exact_inclusive_bound(client, monkeypatch, profile):
    params = {**PARAMS, **({"profile": profile} if profile else {})}
    monkeypatch.setattr(market, "retain_chart_study_seed", lambda *args: pytest.fail("unexpected Live seed"))
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
    response = client.get(PATH, params=params)
    assert response.status_code == 200
    assert len(requests) == 2
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
    cached = client.get(PATH, params=params)
    assert cached.json() == payload
    assert len(requests) == 3


def test_cold_chart_study_rejects_a_revision_between_read_and_result(client, monkeypatch):
    first = END - timedelta(days=10)
    versions = iter((100, 130, 130, 130, 130))
    seen = []

    class Historical:
        def query_page_inclusive(self, request):
            changed_price = next(versions)
            seen.append(changed_price)
            bars = tuple(
                CanonicalBar(at, at.date(), price, price, price, price, Decimal(1), None, None)
                for index in range(11)
                for at in (first + timedelta(days=index),)
                for price in (Decimal(changed_price if index == 4 else 100),)
            )
            return MarketSeriesPageResult({}, bars, (first, END), False, None, ())

    monkeypatch.setattr(market, "build_market_data_service", lambda *args, **kwargs: Historical())
    params = {**PARAMS, "first": first.isoformat(), "count": 11, "studies": "ema10"}
    rejected = client.get(PATH, params=params)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "MARKET_CHART_STUDY_WINDOW_MISMATCH"
    assert seen == [100, 130]

    response = client.get(PATH, params=params)
    assert response.status_code == 200
    december, january = response.json()["segments"]
    assert Decimal(december["bars"][4]["close"]) == 130
    assert january["calculation_anchor"] == december["calculation_anchor"]
    assert january["features"][0]["points"][3]["values"]["value"] == 103
    assert seen == [100, 130, 130, 130]
    assert client.get(PATH, params=params).json() == response.json()
    assert seen == [100, 130, 130, 130, 130]


def test_chart_study_timeout_does_not_wait_for_the_compute_worker(client, monkeypatch):
    entered, release = Event(), Event()
    calculate = REGISTRY.calculate

    def blocked_calculation(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return calculate(*args, **kwargs)

    class Historical:
        def query_page_inclusive(self, request):
            bar = CanonicalBar(END, END.date(), *(Decimal(100),) * 4, Decimal(1), None, None)
            return MarketSeriesPageResult({}, (bar,), (END, END), False, None, ())

    monkeypatch.setattr(market, "build_market_data_service", lambda *args, **kwargs: Historical())
    monkeypatch.setattr(market, "_CHART_STUDY_BUDGET_SECONDS", 0.5)
    monkeypatch.setattr(REGISTRY, "calculate", blocked_calculation)
    try:
        response = client.get(PATH, params=PARAMS)
        assert entered.is_set()
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MARKET_CHART_STUDY_BUDGET_EXCEEDED"
        retry = client.get(PATH, params=PARAMS)
        assert retry.status_code == 503
        assert retry.json()["detail"]["code"] == "MARKET_CHART_STUDY_BUSY"
    finally:
        release.set()


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
