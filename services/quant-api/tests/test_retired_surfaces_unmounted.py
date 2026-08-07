"""Assert retired research surfaces are unmounted from the slim Market-only API."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

RETIRED_GET_PATHS = [
    "/api/dashboard/summary",
    "/api/signals/latest",
    "/api/signals/events",
    "/api/v1/strategies/registry",
    "/api/reviews",
    "/api/watchlists",
    "/api/v1/market/research/panels",
]


def test_retired_http_surfaces_are_unmounted() -> None:
    for path in RETIRED_GET_PATHS:
        response = client.get(path)
        assert response.status_code == 404, path


def test_signal_websocket_route_unmounted() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/ws/signals" not in paths
    assert not any(path.startswith("/api/signals") for path in paths)
    assert "/api/dashboard/summary" not in paths
    assert "/api/reviews" not in paths


def test_retained_ops_surfaces_still_present() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert any("/market/" in path or path.endswith("/market") for path in paths)
    assert any(path.startswith("/api/runtime") or "/runtime/" in path for path in paths)
    assert any(path.startswith("/api/v1/data") or path.startswith("/data/") for path in paths)
