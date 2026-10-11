from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import market_newow
from app.main import app


PRODUCTS = sorted('rb hc i j jm ma ur ta sh v sa au ag sf sm cj jd ap c lh m rm pk sr cf oi p y lc ps fg a b bz eb ec eg l pd pf pg pl pr pt px rs si sc ao ru bu cu ni pb sn al zn fu ss pp'.split())


def test_formal_capability_has_exact_historical_scope():
    with TestClient(app) as client:
        response = client.get('/api/v1/market/newow/product-capabilities')
    data = response.json()
    assert response.status_code == 200
    assert data['schema_version'] == 'newow_product_capabilities_v33'
    assert data['intraday_products'] == PRODUCTS
    assert len(PRODUCTS) == 60
    assert data['intraday_as_of'] is None
    assert data['open_frequencies'] == ['5m', '15m', '30m', '60m', '1d', '1w']
    assert len(data['weekly_products']) == 60


@pytest.mark.parametrize('product', PRODUCTS)
@pytest.mark.parametrize('frequency', ['5m', '15m', '30m', '60m'])
def test_formal_minutes_admit_only_closed_products(product, frequency):
    request = SimpleNamespace(state=SimpleNamespace())
    market_newow._enforce_product_frequency(request, product, frequency)


@pytest.mark.parametrize('product', ['zz'])
@pytest.mark.parametrize('frequency', ['1m', '5m', '15m', '30m', '60m'])
def test_unknown_products_and_one_minute_fail_closed(product, frequency):
    with pytest.raises(ValueError, match='NEWOW_FREQUENCY_NOT_OPEN'):
        market_newow._enforce_product_frequency(SimpleNamespace(state=SimpleNamespace()), product, frequency)


def test_intraday_cutoff_is_not_silently_extended():
    from app.market_data.newow.product_release import released_intraday_as_of
    cutoff = datetime(2026, 9, 24, 7, 0, 0, 1, tzinfo=UTC)
    assert released_intraday_as_of(None) == cutoff
    assert released_intraday_as_of(cutoff) == cutoff
    with pytest.raises(ValueError, match='NEWOW_INVALID_AS_OF'):
        released_intraday_as_of(datetime(2026, 9, 30, 7, tzinfo=UTC))


def test_one_minute_and_main_rise_never_enter_formal_reader():
    with TestClient(app) as client:
        for frequency, strategy in [('1m', 'trend'), ('5m', 'main_rise')]:
            response = client.get('/api/v1/market/newow/strategy-detail', params={
                'product': 'rb', 'frequency': frequency, 'strategy': strategy, 'section': 'chart',
            })
            assert response.status_code == 409


@pytest.mark.parametrize('product', PRODUCTS)
def test_one_minute_remains_closed_for_every_released_product(product):
    with pytest.raises(ValueError, match='NEWOW_FREQUENCY_NOT_OPEN'):
        market_newow._enforce_product_frequency(SimpleNamespace(state=SimpleNamespace()), product, '1m')
