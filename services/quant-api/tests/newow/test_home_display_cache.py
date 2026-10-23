from app.market_data.newow.home_display_cache import HomeDisplayCache


def card(product='rb', status='ready'):
    return {'product': product, 'strategies': {s: {f: {'status': status, 'snapshot_token': 'private-owner', 'page_performance': {}, 'snapshot_context': {}} for f in ('1d', '1w')} for s in ('trend', 'oscillation')}}


def test_display_cache_strips_execution_context_and_does_not_mutate_input():
    cache = HomeDisplayCache()
    value = card()
    cache.put(value, '2026-10-23T07:00:00Z')
    result = cache.read()
    assert result['stale'] is True and result['executable'] is False
    fact = result['items'][0]['card']['strategies']['trend']['1d']
    assert 'snapshot_token' not in fact and 'page_performance' not in fact and 'snapshot_context' not in fact
    assert value['strategies']['trend']['1d']['snapshot_token'] == 'private-owner'
    result['items'].clear()
    assert len(cache.read()['items']) == 1


def test_display_cache_bounds_expiry_and_failed_replacement():
    now = [0]
    cache = HomeDisplayCache(max_entries=2, ttl=10, clock=lambda: now[0])
    for product in ('rb', 'cu', 'ag'):
        cache.put(card(product), '2026-10-23T07:00:00Z')
    assert [item['product'] for item in cache.read()['items']] == ['cu', 'ag']
    cache.put(card('ag', 'unavailable'), '2026-10-24T07:00:00Z')
    assert cache.read()['items'][-1]['saved_at'] == '2026-10-23T07:00:00Z'
    now[0] = 10
    assert cache.read()['items'] == []
    tiny = HomeDisplayCache(max_bytes=1)
    tiny.put(card(), '2026-10-23T07:00:00Z')
    assert tiny.read()['items'] == []


def test_display_route_never_opens_database_and_rejects_query(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import market_newow
    from app.db.session import get_db
    cache = HomeDisplayCache()
    cache.put(card(), '2026-10-23T07:00:00Z')
    monkeypatch.setattr(market_newow, '_HOME_DISPLAY_CACHE', cache)
    def forbidden():
        raise AssertionError('display route must not query DB')
    app.dependency_overrides[get_db] = forbidden
    try:
        with TestClient(app) as client:
            result = client.get('/api/v1/market/newow/home-card-display-cache')
            assert result.status_code == 200
            assert result.json()['stale'] is True
            assert result.json()['items'][0]['product'] == 'rb'
            assert client.get('/api/v1/market/newow/home-card-display-cache?products=rb').status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_older_request_finishing_late_cannot_roll_display_back():
    cache = HomeDisplayCache()
    cache.put(card(), '2026-10-23T08:00:00Z')
    cache.put(card(), '2026-10-23T07:00:00Z')
    assert cache.read()['items'][0]['saved_at'] == '2026-10-23T08:00:00Z'
