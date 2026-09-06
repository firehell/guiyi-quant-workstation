from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.newow.snapshot_cache import SnapshotCache


class _ForbiddenWriteSession:
    def commit(self):
        raise AssertionError("read-only GET committed")

    def add(self, _value):
        raise AssertionError("read-only GET added a row")

    def flush(self):
        raise AssertionError("read-only GET flushed")


def test_new_get_uses_one_product_frequency_and_no_write_seam(monkeypatch, product_cases):
    _reader, query, fake = product_cases.paged_reader(prefix_bars=90, frequency="1d")
    monkeypatch.setattr(market_newow, "build_market_data_service", lambda _session: fake)
    monkeypatch.setattr(
        market_newow, "build_database_coverage_source", lambda _session: fake.coverage
    )
    monkeypatch.setattr(market_newow, "load_active_products", lambda: ("rb",))
    monkeypatch.setattr(market_newow, "_PRODUCT_CACHE", SnapshotCache(enabled=False))
    app.dependency_overrides[get_db] = _ForbiddenWriteSession
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/newow/strategy-detail",
            params={
                "product": "rb",
                "strategy": "trend",
                "frequency": "1d",
                "section": "chart",
                "from": query.since.isoformat(),
                "through": query.through.isoformat(),
                "as_of": fake.as_of.isoformat(),
            },
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert {(item.symbol, item.frequency.value) for item in fake.actual_requests} == {
        ("rb", "1d")
    }
    assert {(item.symbol, item.frequency.value) for item in fake.physical_page_requests} == {
        ("rb", "1d")
    }
