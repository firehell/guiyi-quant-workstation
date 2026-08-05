from __future__ import annotations

import importlib.util

from app.main import app


def test_watchlist_http_api_has_a_neutral_module_owner() -> None:
    """A future backtest deletion must not remove the signal scanner's watchlists."""

    spec = importlib.util.find_spec("app.api.watchlists")

    assert spec is not None


def test_application_keeps_watchlists_and_exposes_no_backtest_routes() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/watchlists" in paths
    assert not any(path.startswith("/api/backtests") for path in paths)
    assert not any(path.startswith("/ws/backtests") for path in paths)
