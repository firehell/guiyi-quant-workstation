"""Isolated candidate API; no external services or production data."""

import importlib.util
from datetime import UTC, datetime
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def test_preview_entrypoint_exists():
    assert importlib.util.find_spec("app.preview") is not None


@pytest.fixture
def preview(monkeypatch):
    from app.preview import create_preview_app

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    sessions = []

    def session_factory():
        session = Session(engine)
        sessions.append(session)
        return session

    app = create_preview_app(
        enabled=True, as_of="2026-09-03T08:00:00Z", session_factory=session_factory
    )
    return app, sessions, session_factory


def test_default_off_and_invalid_cutoff(monkeypatch):
    from app.preview import create_preview_app

    monkeypatch.delenv("GUIYI_CANDIDATE_PREVIEW", raising=False)
    with pytest.raises(ValueError, match="PREVIEW_DISABLED"):
        create_preview_app()
    for value in (None, "bad", "2026-09-03T08:00:00", "2999-01-01T00:00:00Z"):
        with pytest.raises(ValueError, match="PREVIEW_CUTOFF_INVALID"):
            create_preview_app(enabled=True, as_of=value)


def test_identity_is_current_git_and_lightweight(preview, monkeypatch):
    from app.core.env import PROJECT_ROOT
    from app.market_data import composition
    from app.preview import create_preview_app

    def forbidden(*args, **kwargs):
        pytest.fail("preview constructed a live or maintenance dependency")

    for name in (
        "build_historical_data_manager",
        "build_live_market_service",
        "build_market_read_service",
        "get_redis_connection",
        "HistoricalDataManager",
        "LiveMarketService",
        "RQDataLiveProvider",
        "RedisLiveStore",
    ):
        monkeypatch.setattr(composition, name, forbidden)
    _original, sessions, factory = preview
    app = create_preview_app(
        enabled=True,
        as_of="2026-09-03T08:00:00Z",
        session_factory=factory,
    )
    with TestClient(app) as client:
        response = client.get("/api/preview/identity")
    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["code_sha"]
        == subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    )
    assert payload["as_of"] == "2026-09-03T08:00:00+00:00"
    assert payload["realtime"] is False
    assert sessions == []
    assert not any(
        getattr(route, "path", "").startswith(("/api/alerts", "/api/runtime", "/ws"))
        for route in app.routes
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/runtime/health",
        "/api/alerts/current-events",
        "/api/v1/market/state",
        "/api/v1/market/research/product",
        "/api/v1/market/newow/trend-detail",
        "/api/v1/market/dominants/",
        "/api/v1/market/%64ominants",
        "/docs",
        "/openapi.json",
    ],
)
def test_rejects_unapproved_paths_without_db(preview, path):
    app, sessions, _factory = preview
    response = TestClient(app).get(path)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PREVIEW_ROUTE_FORBIDDEN"
    assert sessions == []


@pytest.mark.parametrize(
    "method", ["post", "put", "patch", "delete", "head", "options"]
)
def test_rejects_methods_without_db(preview, method):
    app, sessions, _factory = preview
    assert (
        getattr(TestClient(app), method)("/api/v1/market/dominants").status_code == 403
    )
    assert sessions == []


def test_market_cutoff_and_readonly_rollback(preview, monkeypatch):
    from app.api import market
    from app.market_data.market_data_service import MarketDataError

    captured = []

    class Reader:
        def query_page(self, query):
            captured.append(query.before)
            raise MarketDataError("DATASET_OR_PARTITION_MISSING")

    def reader(session):
        assert session.scalar(text("PRAGMA query_only")) == 1
        return Reader()

    monkeypatch.setattr(market, "build_market_data_service", reader)
    app, sessions, _factory = preview
    client = TestClient(app)
    base = {"symbol": "rb", "series_kind": "actual_dominant", "frequency": "1d"}
    for before in (None, "2026-09-08T08:00:00Z", "2026-09-01T08:00:00Z"):
        response = client.get(
            "/api/v1/market/bars/page",
            params={**base, **({"before": before} if before else {})},
        )
        assert response.status_code == 409
    assert captured == [datetime(2026, 9, 3, 8, tzinfo=UTC)] * 2 + [
        datetime(2026, 9, 1, 8, tzinfo=UTC)
    ]
    assert all(not session.in_transaction() for session in sessions)
    with sessions[0].get_bind().connect() as connection:
        assert connection.scalar(text("PRAGMA query_only")) == 0


def test_newow_real_query_respects_cutoff(preview, monkeypatch, product_cases):
    from app.api import market_newow
    from app.preview import create_preview_app
    from app.market_data.newow.snapshot_cache import SnapshotCache

    _reader, query, fake = product_cases.paged_reader(prefix_bars=90, frequency="1d")
    monkeypatch.setattr(market_newow, "build_market_data_service", lambda session: fake)
    monkeypatch.setattr(
        market_newow, "build_database_coverage_source", lambda session: fake.coverage
    )
    monkeypatch.setattr(market_newow, "load_active_products", lambda: ("rb",))
    monkeypatch.setattr(market_newow, "_PRODUCT_CACHE", SnapshotCache(enabled=False))
    app = create_preview_app(
        enabled=True,
        as_of=fake.as_of.isoformat(),
        session_factory=preview[2],
    )
    response = TestClient(app).get(
        "/api/v1/market/newow/strategy-detail",
        params={
            "product": "rb",
            "strategy": "trend",
            "frequency": "1d",
            "section": "chart",
            "from": query.since.isoformat(),
            "through": query.through.isoformat(),
            "as_of": "2026-09-08T08:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["meta"]["as_of"]) == fake.as_of
    assert all(
        datetime.fromisoformat(bar["bar_end"]) <= fake.as_of
        for bar in response.json()["chart"]["value"]["bars"]
    )
    assert fake.actual_requests


def test_errors_are_sanitized_and_rollback(preview, monkeypatch):
    from app.api import market

    def broken(session):
        session.execute(text("SELECT 1"))
        raise RuntimeError("sensitive driver details")

    monkeypatch.setattr(market, "build_market_data_service", broken)
    app, sessions, _factory = preview
    response = TestClient(app).get("/api/v1/market/dominants")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "PREVIEW_QUERY_UNAVAILABLE"}}
    assert all(not session.in_transaction() for session in sessions)


def test_database_write_is_rejected_and_not_persisted(preview, monkeypatch):
    from app.api import market

    def attempted_write(session):
        session.execute(text("CREATE TABLE forbidden_preview_write (id integer)"))
        pytest.fail("write was allowed")

    monkeypatch.setattr(market, "build_market_data_service", attempted_write)
    app, sessions, _factory = preview
    response = TestClient(app).get("/api/v1/market/dominants")
    assert response.status_code == 503
    with sessions[0].get_bind().connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE name='forbidden_preview_write'"
                )
            )
            == 0
        )


def test_historical_resolver_uses_fixed_clock(preview, monkeypatch):
    from app.api import market_newow
    from app.market_data.market_data_service import MarketDataError

    captured = []

    def resolver(session, cancelled, now):
        captured.append(now())
        raise MarketDataError("DATASET_OR_PARTITION_MISSING")

    monkeypatch.setattr(market_newow, "_build_historical_resolver", resolver)
    response = TestClient(preview[0]).get(
        "/api/v1/market/newow/historical-snapshot",
        params={"product": "rb", "strategy": "trend", "frequency": "1d"},
    )
    assert response.status_code == 409
    assert captured == [datetime(2026, 9, 3, 8, tzinfo=UTC)]


@pytest.mark.parametrize(
    "query", ["before=bad", "before=2026-09-01T08:00:00", "before=x&before=y"]
)
def test_invalid_cutoff_query_is_rejected_before_database(preview, query):
    app, sessions, _factory = preview
    response = TestClient(app).get("/api/v1/market/bars/page?" + query)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "PREVIEW_QUERY_INVALID"}}
    assert sessions == []
