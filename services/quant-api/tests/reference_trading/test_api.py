from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api import reference_trading as api
from app.main import app
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.presentation import envelope, presentation_point
from tests.reference_trading.test_repository import _digest, _open_batch, _seed_repository


def test_read_only_http_snapshot_cutoff_and_disabled_stream(monkeypatch, tmp_path) -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository(
        sqlite_path=tmp_path / "reference.sqlite",
    )
    evidence = {"bar": "fixture-1", "presentation_v1": envelope([
        presentation_point(
            kind="trade_identity",
            value={"source_action_id": "build-1", "public_trade_id": "public-one"},
            trading_day=date(2026, 9, 19), formula_versions=("v1",),
        ),
    ])}
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed, evidence=evidence))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    # Fixture identity is intentionally synthetic; the HTTP contract is tested
    # independently of the production identity registry.
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    monkeypatch.setattr(api, "_query", HistoricalReferenceQuery(factory))
    client = TestClient(app)
    path = f"/api/v1/reference-trading/streams/{stream.stream_id}/trades"
    params = {
        "since": "2026-09-19", "through": "2026-09-20",
        "cutoff": datetime(2026, 9, 19, 23, tzinfo=UTC).isoformat(),
    }
    first = client.get(path, params=params)
    assert first.status_code == 200, first.text
    value = first.json()
    assert value["items"][0]["status"] == "OPEN"
    assert value["items"][0]["public_reference_trade_id"] == "public-one"
    assert Decimal(value["items"][0]["entry_reference_price"]) == Decimal("3500.123456789")
    assert value["stream"]["readable"] is True
    second = client.get(path, params={**params, "snapshot": value["snapshot"]})
    assert second.status_code == 200
    assert second.json()["snapshot"] == value["snapshot"]
    assert client.get(path, params={**params, "since": "2026-09-20", "snapshot": value["snapshot"]}).status_code == 409
    assert client.get(path, params=[("since", "2026-09-19"), ("since", "2026-09-19"), ("through", "2026-09-20")]).status_code == 422


def test_api_has_no_implicit_build(monkeypatch, tmp_path) -> None:
    repository, factory, stream, _revision, _manifest, _seed = _seed_repository(
        sqlite_path=tmp_path / "reference.sqlite",
    )
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    monkeypatch.setattr(api, "_query", HistoricalReferenceQuery(factory))
    client = TestClient(app)
    response = client.get(
        f"/api/v1/reference-trading/streams/{stream.stream_id}/trades",
        params={"since": date(2026, 9, 19).isoformat(), "through": date(2026, 9, 20).isoformat()},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "NOT_BUILT"
    with factory() as session:
        from app.reference_trading.models import ReferenceStream
        assert session.get(ReferenceStream, stream.stream_id).active_revision_id is None


def test_newow_strategy_detail_preserves_persisted_read_errors(monkeypatch) -> None:
    from app.api import market_newow
    from app.db.session import get_db

    class FakeService:
        def query(self, _request):
            raise QueryConflict("NOT_BUILT")

    monkeypatch.setattr(market_newow, "_build_product_service", lambda *_args, **_kwargs: FakeService())
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/market/newow/strategy-detail", params={
                "product": "rb", "strategy": "trend", "frequency": "1d", "section": "reference",
            })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "NOT_BUILT"}}
