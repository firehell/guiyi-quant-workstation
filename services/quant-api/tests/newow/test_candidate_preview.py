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

    monkeypatch.delenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", raising=False)
    monkeypatch.delenv("GUIYI_AU_PERIOD_PREVIEW", raising=False)
    monkeypatch.delenv("GUIYI_PREVIEW_CANDIDATE_ORIGIN", raising=False)
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


def test_default_weekly_preview_uses_request_clock_and_exposes_exact_route(preview, monkeypatch):
    from app.preview import create_preview_app
    from app.api import market_newow

    monkeypatch.setenv("GUIYI_PREVIEW_DEFAULT_WEEKLY", "1")
    monkeypatch.delenv("GUIYI_PREVIEW_AS_OF", raising=False)
    monkeypatch.delenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", raising=False)
    monkeypatch.delenv("GUIYI_AU_PERIOD_PREVIEW", raising=False)
    app = create_preview_app(enabled=True, session_factory=preview[2])
    seen = []

    class Resolver:
        def resolve(self, product, strategy, frequency):
            seen.append((product, strategy.value, frequency.value))
            raise ValueError("NEWOW_WEEKLY_UNKNOWN")

    monkeypatch.setattr(market_newow, "_build_weekly_resolver", lambda *_args: Resolver())
    with TestClient(app) as client:
        identity = client.get("/api/preview/identity")
        weekly = client.get("/api/v1/market/newow/weekly-snapshot", params={
            "product": "rb", "strategy": "trend", "frequency": "1w",
        })
    assert identity.status_code == 200
    assert identity.json()["as_of"] is None
    assert identity.json()["default_weekly"] is True
    assert weekly.status_code == 409
    assert seen == [("rb", "trend", "1w")]


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


def test_daily_weekly_candidate_capabilities_are_available_without_database(preview):
    app, sessions, _factory = preview

    response = TestClient(app).get("/api/v1/market/newow/product-capabilities")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "newow_product_capabilities_v9"
    assert response.json()["release_stage"] == "daily_weekly_candidate"
    assert response.json()["open_frequencies"] == ["1d", "1w"]
    assert len(response.json()["weekly_products"]) == 60
    assert "au" in response.json()["weekly_products"]
    assert "b" in response.json()["weekly_products"]
    assert response.json()["deferred_frequencies"] == [
        {"frequency": "60m", "reason_code": "NEWOW_HOURLY_RELEASE_PENDING"}
    ]
    assert response.json()["open_sections"] == [
        "chart",
        "auxiliary",
        "reference",
        "comparator",
    ]
    assert sessions == []

    blocked = TestClient(app).get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "b", "strategy": "trend", "frequency": "1w"},
    )
    assert blocked.status_code != 403
    assert blocked.json().get("detail", {}).get("code") != "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"
    history = TestClient(app).get(
        "/api/v1/market/newow/historical-snapshot",
        params={"product": "b", "strategy": "trend", "frequency": "1w"},
    )
    assert history.status_code != 403
    assert history.json().get("detail", {}).get("code") != "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"
    assert len(sessions) == 2


def test_preview_selects_v2_only_for_remaining19_weekly():
    from types import SimpleNamespace
    from app.api.market_newow import _input_quality_policy
    from guiyi_quant.newow.product_identity import InputQualityPolicy

    preview = SimpleNamespace(
        state=SimpleNamespace(candidate_preview_as_of=datetime(2026, 9, 3, tzinfo=UTC))
    )
    production = SimpleNamespace(state=SimpleNamespace())

    assert _input_quality_policy(preview, "b", "1w") is InputQualityPolicy.WEEKLY_V2
    assert _input_quality_policy(preview, "cj", "1w") is InputQualityPolicy.WEEKLY_V2
    assert _input_quality_policy(preview, "au", "1w") is InputQualityPolicy.V1
    assert _input_quality_policy(preview, "b", "1d") is InputQualityPolicy.V1
    assert _input_quality_policy(production, "b", "1w") is InputQualityPolicy.WEEKLY_V2
    assert _input_quality_policy(production, "au", "1w") is InputQualityPolicy.V1
    assert _input_quality_policy(production, "cj", "1w") is InputQualityPolicy.V1


def test_au_period_preview_opens_only_au_without_database(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_AU_PERIOD_PREVIEW", "1")
    app, sessions, _factory = preview
    client = TestClient(app)

    capability = client.get("/api/v1/market/newow/product-capabilities")
    assert capability.status_code == 200
    assert capability.json()["schema_version"] == "newow_product_capabilities_v5"
    assert capability.json()["open_frequencies"] == ["1d", "1w", "60m"]
    assert capability.json()["deferred_frequencies"] == []
    refused = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "jm", "strategy": "trend", "frequency": "60m"},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "PREVIEW_PRODUCT_OUT_OF_SCOPE"
    assert sessions == []


def test_hourly_preview_opens_only_ap_60m_without_database(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", "ap")
    app, sessions, _factory = preview
    client = TestClient(app)

    capability = client.get("/api/v1/market/newow/product-capabilities")
    assert capability.status_code == 200
    assert capability.json()["schema_version"] == "newow_product_capabilities_v7"
    assert capability.json()["release_stage"] == "ap_hourly_candidate"
    assert capability.json()["open_frequencies"] == ["1d", "60m"]
    assert capability.json()["deferred_frequencies"] == [
        {"frequency": "1w", "reason_code": "NEWOW_WEEKLY_RELEASE_PENDING"}
    ]
    for product in ("pd", "pt", "au", "jm"):
        refused_product = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={"product": product, "strategy": "trend", "frequency": "60m"},
        )
        assert refused_product.status_code == 403, product
        assert refused_product.json()["detail"]["code"] == "PREVIEW_PRODUCT_OUT_OF_SCOPE"
    refused_week = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "ap", "strategy": "trend", "frequency": "1w"},
    )
    assert refused_week.status_code == 409
    assert refused_week.json()["detail"]["code"] == "NEWOW_FREQUENCY_NOT_OPEN"
    historical = client.get(
        "/api/v1/market/newow/historical-snapshot",
        params={"product": "pd", "strategy": "trend", "frequency": "60m"},
    )
    assert historical.status_code == 403
    assert historical.json()["detail"]["code"] == "PREVIEW_PRODUCT_OUT_OF_SCOPE"
    assert sessions == []
    admitted = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "ap", "strategy": "trend", "frequency": "60m"},
    )
    assert admitted.status_code != 403
    assert admitted.json().get("detail", {}).get("code") != "PREVIEW_PRODUCT_OUT_OF_SCOPE"


def test_hourly_preview_ignores_leftover_au_env_when_ap_hourly_is_set(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", "ap")
    monkeypatch.setenv("GUIYI_AU_PERIOD_PREVIEW", "1")
    app, sessions, _factory = preview
    client = TestClient(app)

    capability = client.get("/api/v1/market/newow/product-capabilities")
    assert capability.status_code == 200
    assert capability.json()["schema_version"] == "newow_product_capabilities_v7"
    assert capability.json()["release_stage"] == "ap_hourly_candidate"
    assert capability.json()["open_frequencies"] == ["1d", "60m"]
    refused_au = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "au", "strategy": "trend", "frequency": "60m"},
    )
    assert refused_au.status_code == 403
    assert refused_au.json()["detail"]["code"] == "PREVIEW_PRODUCT_OUT_OF_SCOPE"
    refused_week = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "ap", "strategy": "trend", "frequency": "1w"},
    )
    assert refused_week.status_code == 409
    assert refused_week.json()["detail"]["code"] == "NEWOW_FREQUENCY_NOT_OPEN"
    assert sessions == []


def test_hourly_preview_preserves_pd_pt_scope(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", "pd,pt")
    app, sessions, _factory = preview
    client = TestClient(app)

    capability = client.get("/api/v1/market/newow/product-capabilities")
    assert capability.status_code == 200
    assert capability.json()["schema_version"] == "newow_product_capabilities_v6"
    assert capability.json()["release_stage"] == "pd_pt_hourly_candidate"
    assert capability.json()["open_frequencies"] == ["1d", "60m"]
    admitted = client.get(
        "/api/v1/market/newow/strategy-detail",
        params={"product": "pd", "strategy": "trend", "frequency": "60m"},
    )
    assert admitted.status_code != 403
    assert admitted.json().get("detail", {}).get("code") != "NEWOW_FREQUENCY_NOT_OPEN"
    assert capability.json()["deferred_frequencies"] == [
        {"frequency": "1w", "reason_code": "NEWOW_WEEKLY_RELEASE_PENDING"}
    ]


def test_hourly_preview_rejects_mixed_ap_and_pd_pt_scope(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", "ap,pd")
    app, sessions, _factory = preview
    response = TestClient(app).get("/api/v1/market/newow/product-capabilities")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PREVIEW_QUERY_INVALID"
    assert sessions == []


def test_hourly_preview_rejects_partial_pd_pt_scope(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_HOURLY_PREVIEW_PRODUCTS", "pd")
    app, sessions, _factory = preview
    response = TestClient(app).get("/api/v1/market/newow/product-capabilities")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PREVIEW_QUERY_INVALID"
    assert sessions == []


def test_subing_reference_path_is_narrowly_admitted(preview):
    from app.preview import _preview_path_allowed

    assert _preview_path_allowed("/api/v1/market/jm/subing/reference") is True
    for path in (
        "/api/v1/market/JM/subing/reference",
        "/api/v1/market/jm-1/subing/reference",
        "/api/v1/market/jm/subing/reference/",
        "/api/v1/market/jm/subing/other",
    ):
        assert _preview_path_allowed(path) is False


def test_preview_identity_declares_subing_reference_with_the_cutoff_scope(preview):
    app, _sessions, _factory = preview
    response = TestClient(app).get("/api/preview/identity")
    assert response.status_code == 200
    payload = response.json()
    assert "subing_reference" in payload["cutoff_scope"]
    assert payload["candidate_origin"] == "http://127.0.0.1:8010"
    assert payload["status_origin"] == "http://127.0.0.1:8000"


def test_preview_identity_candidate_origin_can_be_overflow_8011(preview, monkeypatch):
    monkeypatch.setenv("GUIYI_PREVIEW_CANDIDATE_ORIGIN", "http://127.0.0.1:8011")
    from app.preview import create_preview_app

    _app, _sessions, factory = preview
    app = create_preview_app(
        enabled=True, as_of="2026-09-03T08:00:00Z", session_factory=factory
    )
    payload = TestClient(app).get("/api/preview/identity").json()
    assert payload["candidate_origin"] == "http://127.0.0.1:8011"


def test_preview_identity_rejects_non_loopback_or_non_overflow_origin(monkeypatch):
    from app.preview import create_preview_app

    monkeypatch.setenv("GUIYI_CANDIDATE_PREVIEW", "1")
    for value in (
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8012",
        "http://0.0.0.0:8011",
        "https://127.0.0.1:8011",
        "http://127.0.0.1:8011/extra",
    ):
        monkeypatch.setenv("GUIYI_PREVIEW_CANDIDATE_ORIGIN", value)
        with pytest.raises(ValueError, match="PREVIEW_CANDIDATE_ORIGIN_INVALID"):
            create_preview_app(enabled=True, as_of="2026-09-03T08:00:00Z")


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


def test_daily_resolver_uses_fixed_preview_clock(preview, monkeypatch):
    from app.api import market_newow
    from app.market_data.market_data_service import MarketDataError

    captured = []

    def resolver(session, cancelled, now):
        captured.append(now())
        raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    monkeypatch.setattr(market_newow, "_build_daily_resolver", resolver)
    response = TestClient(preview[0]).get(
        "/api/v1/market/newow/daily-snapshot",
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
