from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.newow.product_service import ProductServiceQuery


def _service_result(product_cases):
    from newow.test_product_service import _service

    service, _reader, _build, clear = _service(product_cases)
    result = service.query(
        ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end, chart_limit=10)
    )
    return result, clear.bar_end


def test_strategy_detail_returns_only_requested_typed_section(
    monkeypatch, product_cases
):
    result, as_of = _service_result(product_cases)
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session: type("Fake", (), {"query": lambda _self, _query: result})(),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "as_of": as_of.isoformat(),
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["section"] == "chart"
    assert body["chart"]["delivery"] == "delivered"
    assert body["reference"] == {
        "delivery": "not_requested",
        "status": None,
        "value": None,
    }
    assert isinstance(body["chart"]["value"]["bars"][0]["close"], str)
    assert body["chart"]["value"]["formal_signal_eligible"] is True


def test_strategy_detail_rejects_unknown_or_cross_section_inputs(monkeypatch):
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session: (_ for _ in ()).throw(
            AssertionError("invalid request reached service")
        ),
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "evidence": "forged",
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "history_limit": 3,
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/market/newow/strategy-detail",
                params={
                    "product": "rb",
                    "strategy": "trend",
                    "frequency": "1d",
                    "as_of": "2026-01-01T00:00:00",
                },
            ).status_code
            == 422
        )
    app.dependency_overrides.clear()


def test_reference_uses_decimal_strings_and_null_empty_closed_metrics(
    monkeypatch, product_cases
):
    from newow.test_product_service import _service

    service, _reader, build, clear = _service(product_cases)
    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=build.trading_day,
            as_of=clear.bar_end,
        )
    )
    monkeypatch.setattr(
        market_newow,
        "_build_product_service",
        lambda _session: type("Fake", (), {"query": lambda _self, _query: result})(),
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "section": "reference",
                "performance_since": build.trading_day.isoformat(),
                "performance_through": build.trading_day.isoformat(),
                "as_of": clear.bar_end.isoformat(),
            },
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    value = response.json()["reference"]["value"]
    assert value["summary"]["closed_count"] == 0
    assert value["summary"]["win_rate_pct"] is None
    assert isinstance(value["items"][0]["entry_reference_price"], str)
    assert value["executable"] is False
    assert value["auto_order"] is False


def test_strategy_detail_maps_future_as_of_and_safe_internal_errors(monkeypatch):
    class Fake:
        def query(self, _query):
            raise RuntimeError("password token SQL /private/path")

    monkeypatch.setattr(
        market_newow, "_build_product_service", lambda _session: Fake(), raising=False
    )
    app.dependency_overrides[get_db] = lambda: object()
    with TestClient(app, raise_server_exceptions=False) as client:
        future = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "as_of": datetime(2100, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
        internal = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": "rb", "strategy": "trend", "frequency": "1d"},
        )
    app.dependency_overrides.clear()
    assert future.status_code == 422
    assert internal.status_code == 500
    assert internal.json() == {"detail": {"code": "NEWOW_INTERNAL_ERROR"}}
    assert "password" not in internal.text
