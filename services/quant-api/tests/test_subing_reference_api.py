from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest

from app.api import market_subing_reference
from app.db.session import get_db
from app.main import app
from app.market_data.subing_reference import SubingReferenceService
from app.market_data.market_data_service import MarketDataError
from test_subing_reference_service import Market, Coverage


@pytest.fixture
def client(monkeypatch):
    service = SubingReferenceService(
        Market(),
        coverage=Coverage(),
        active_products={"rb"},
        now=lambda: datetime(2026, 7, 25, 7, tzinfo=UTC),
    )
    monkeypatch.setattr(market_subing_reference, "_build_service", lambda *_: service)
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value
    app.dependency_overrides.clear()


def test_real_projection_response_has_typed_strings_and_stable_pages(client):
    response = client.get("/api/v1/market/rb/subing/reference?limit=2")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["closed_count"] > 1
    assert isinstance(body["items"][0]["entry_reference_price"], str)
    assert body["signals"][0]["direction"] in {"buy", "sell"}
    page = client.get(
        "/api/v1/market/rb/subing/reference",
        params={"limit": 2, "before": body["next_before"], "as_of": body["as_of"]},
    )
    assert page.status_code == 200
    assert page.json()["summary"] == body["summary"]
    assert body["items"] != page.json()["items"]


@pytest.mark.parametrize(
    "suffix",
    [
        "?limit=0",
        "?frequency=5m",
        "?since=2026-07-01&since=2026-07-02",
        "?through=tomorrow",
        "?as_of=2026-07-20T00:00:00",
        "?as_of=2027-01-01T00:00:00Z",
        "?before=bad",
    ],
)
def test_query_validation_is_closed(client, suffix):
    assert client.get("/api/v1/market/rb/subing/reference" + suffix).status_code == 422


def test_errors_do_not_leak_internal_details(client, monkeypatch):
    def fail(*_):
        raise MarketDataError("PRIVATE_CATALOG_PATH")

    monkeypatch.setattr(market_subing_reference, "_build_service", fail)
    response = client.get("/api/v1/market/rb/subing/reference")
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SUBING_REFERENCE_DATA_UNAVAILABLE"}}

    def crash(*_):
        raise RuntimeError("SECRET_INTERNAL_ADDRESS")

    monkeypatch.setattr(market_subing_reference, "_build_service", crash)
    response = client.get("/api/v1/market/rb/subing/reference")
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "SUBING_REFERENCE_INTERNAL_ERROR"}}


def test_budget_and_concurrent_request_are_bounded(client, monkeypatch):
    assert market_subing_reference._GATE.acquire(blocking=False)
    try:
        response = client.get("/api/v1/market/rb/subing/reference")
        assert response.status_code == 503
    finally:
        market_subing_reference._GATE.release()


def test_response_is_read_only(client):
    assert client.post("/api/v1/market/rb/subing/reference").status_code == 405
