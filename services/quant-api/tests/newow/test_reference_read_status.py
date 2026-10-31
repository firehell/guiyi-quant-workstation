from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.reference_trading.source_identity import ReferenceReadConflict


def test_reference_error_preserves_safe_status_without_returning_old_result(monkeypatch):
    def query(_request):
        raise ReferenceReadConflict('REFERENCE_UPDATE_PENDING',
            saved_through=datetime(2026, 10, 26, 7, tzinfo=UTC),
            requested_through=datetime(2026, 10, 30, 7, tzinfo=UTC))
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *a, **k: SimpleNamespace(query=query))
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).get('/api/v1/market/newow/strategy-detail', params={
            'product': 'jm', 'strategy': 'trend', 'frequency': '60m', 'section': 'reference',
            'reference_part': 'panel', 'reference_mode': 'page_ordinary',
        })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json() == {'detail': {'code': 'REFERENCE_UPDATE_PENDING', 'reference_status': {
        'reason': 'REFERENCE_UPDATE_PENDING', 'result_through': '2026-10-26T07:00:00+00:00',
        'market_through': '2026-10-30T07:00:00+00:00',
    }}}
