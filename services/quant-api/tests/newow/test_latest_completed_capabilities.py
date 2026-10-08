from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api import market_newow
from app.db.session import get_db
from app.main import app
from app.market_data.newow.product_release import INTRADAY_HISTORY_AS_OF, require_open_frequency
from guiyi_quant.newow.product_contracts import ProductFrequency


def test_v32_publishes_latest_completed_scope_and_strategy_support():
    with TestClient(app) as client:
        response = client.get('/api/v1/market/newow/product-capabilities')
    payload = response.json()
    assert response.status_code == 200
    assert payload['schema_version'] == 'newow_product_capabilities_v32'
    assert payload['latest_completed_frequencies'] == ['1d', '1w', '60m']
    assert payload['strategy_frequencies']['main_rise'] == ['1d', '1w', '60m']
    assert payload['strategy_frequencies']['dual'] == payload['open_frequencies']
    assert len(payload['intraday_products']) == 60
    require_open_frequency(ProductFrequency.HOURLY)


@pytest.mark.parametrize('strategy,frequency,decision,expected,frozen', [
    ('main_rise', '60m', False, '2026-10-01T00:00:00+00:00', False),
    ('trend', '60m', False, '2026-10-01T00:00:00+00:00', False),
    ('trend', '1d', True, '2026-10-01T00:00:00+00:00', False),
    ('trend', '1w', True, '2026-10-01T00:00:00+00:00', False),
    ('trend', '5m', False, INTRADAY_HISTORY_AS_OF.isoformat(), True),
])
def test_detail_uses_current_canonical_only_for_current_scope(monkeypatch, strategy, frequency, decision, expected, frozen):
    captured = []
    builds = []
    class Service:
        def query(self, query):
            captured.append(query)
            raise ValueError('NEWOW_DATA_UNAVAILABLE')
    def build(*args, **kwargs):
        builds.append(kwargs)
        return Service()
    monkeypatch.setattr(market_newow, '_build_product_service', build)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.get('/api/v1/market/newow/strategy-detail', params={
                'product': 'pp', 'strategy': strategy, 'frequency': frequency,
                'section': 'explanation' if decision else 'chart',
                'decision_v2': str(decision).lower(),
                'as_of': INTRADAY_HISTORY_AS_OF.isoformat() if frozen else expected,
            })
        assert len(captured) == 1
        assert captured[0].as_of == datetime.fromisoformat(expected)
        assert builds[0].get('historical_intraday', False) is frozen
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('frequency', ['5m', '15m', '30m'])
def test_non_hourly_main_rise_stays_closed(monkeypatch, frequency):
    def forbidden(*args, **kwargs):
        pytest.fail('closed strategy must not build data readers')
    monkeypatch.setattr(market_newow, '_build_product_service', forbidden)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/market/newow/strategy-detail', params={
                'product': 'pp', 'strategy': 'main_rise', 'frequency': frequency,
            })
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'NEWOW_FREQUENCY_NOT_OPEN'
    finally:
        app.dependency_overrides.clear()
