"""Assert retired research surfaces are removed from the Market-only API."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
APP_ROOT = Path(__file__).resolve().parents[1] / "app"

RETIRED_GET_PATHS = [
    "/api/dashboard/summary",
    "/api/signals/latest",
    "/api/signals/events",
    "/api/v1/strategies/registry",
    "/api/reviews",
    "/api/watchlists",
    "/api/v1/market/research/panels",
    "/api/v1/data/summary",
    "/api/v1/data/profiles",
    "/api/v1/data/coverage",
]

RETIRED_MODULES = [
    "api/signals.py",
    "api/reviews.py",
    "api/strategies.py",
    "api/dashboard.py",
    "api/watchlists.py",
    "api/futures_research.py",
    "api/data_center.py",
    "repositories/data_center.py",
    "models/signal.py",
    "models/review.py",
    "models/watchlist.py",
    "signal",
    "review",
    "strategy",
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
    assert not any(path.startswith("/api/v1/data") for path in paths)


def test_retired_application_modules_are_deleted() -> None:
    for relative in RETIRED_MODULES:
        assert not (APP_ROOT / relative).exists(), relative


def test_retained_ops_surfaces_still_present() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert any("/market/" in path or path.endswith("/market") for path in paths)
    assert any(path.startswith("/api/runtime") or "/runtime/" in path for path in paths)
    assert "/api/symbols" in paths


def test_data_center_http_unmounted_but_symbols_compat_remains() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/symbols" in paths
    assert "/api/v1/data/summary" not in paths
    assert "/api/v1/data/profiles" not in paths
