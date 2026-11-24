from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.newow_trading import build_newow_trading_router


def test_trading_projection_is_opt_in_read_only_and_cursor_bound():
    app = FastAPI()
    calls = []

    def read(resource, **options):
        calls.append((resource, options))
        return {'source': 'offline_fixture', 'account_alias': 'fixture', 'snapshot_seq': 1,
                'status': 'STALE', 'data': [], 'next_after': 2, 'through': 10}

    with TestClient(app) as client:
        assert client.get('/api/v1/newow/trading/status').status_code == 404
    app.include_router(build_newow_trading_router(read))
    with TestClient(app) as client:
        base = '/api/v1/newow/trading'
        assert client.post(f'{base}/orders').status_code == 405
        assert client.get(f'{base}/unsupported').status_code == 404
        payload = client.get(f'{base}/orders', params={'limit': 1}).json()
        assert payload['next_cursor'] == 'orders.2.10' and payload['status'] == 'STALE'
        assert client.get(f'{base}/orders', params={'cursor': payload['next_cursor']}).status_code == 200
        assert client.get(f'{base}/fills', params={'cursor': payload['next_cursor']}).status_code == 400
        assert client.get(f'{base}/account', params={'cursor': payload['next_cursor']}).status_code == 400
    assert calls == [('orders', {'limit': 1, 'after': 0, 'through': None}),
                     ('orders', {'limit': 100, 'after': 2, 'through': 10})]


def test_storage_unavailable_is_distinct_from_empty_projection():
    app = FastAPI()

    def read(resource, **_):
        if resource == 'orders':
            raise RuntimeError('fixture backend private detail')
        return {'source': 'offline_fixture', 'account_alias': 'fixture', 'snapshot_seq': 0,
                'status': 'NOT_AVAILABLE', 'data': None}

    app.include_router(build_newow_trading_router(read))
    with TestClient(app) as client:
        assert client.get('/api/v1/newow/trading/positions').json()['data'] is None
        reply = client.get('/api/v1/newow/trading/orders')
        assert reply.status_code == 503
        assert reply.json() == {'detail': 'P5_PROJECTION_UNAVAILABLE'}


def test_trading_router_reads_an_isolated_postgres_projection(monkeypatch):
    from datetime import UTC, datetime
    import os
    from pathlib import Path
    from uuid import uuid4

    import pytest

    dsn = os.getenv('GUIYI_P5_ISOLATED_DATABASE')
    if not dsn:
        pytest.skip('explicit P5 isolated PostgreSQL required')
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / 'services/newow-vnpy'))
    from store import TradingStore

    alias = 'p5-http-' + uuid4().hex
    app = FastAPI()
    with TradingStore(dsn, alias) as store:
        app.include_router(build_newow_trading_router(store.projection))
        with TestClient(app) as client:
            base = '/api/v1/newow/trading'
            assert client.get(f'{base}/account').json()['status'] == 'NOT_AVAILABLE'
            with store.transaction() as (state, journal):
                state.update(revision='fixture-scope', status='RECONCILING', owners={}, native={
                    'account': {'available': '10'}, 'as_of': datetime.now(UTC).isoformat(), 'positions': [],
                })
                for number in range(3):
                    journal.record('decisions', str(number), {'decision_id': str(number)})
            assert client.get(f'{base}/account').json()['data']['available'] == '10'
            first = client.get(f'{base}/decisions', params={'limit': 2}).json()
            assert first['revision'] == 'fixture-scope'
            assert first['next_cursor'] is not None
            with store.transaction() as (_state, journal):
                journal.record('decisions', '3', {'decision_id': '3'})
            tail = client.get(f'{base}/decisions', params={'cursor': first['next_cursor']}).json()
            assert [record['decision_id'] for record in tail['data']] == ['2']
