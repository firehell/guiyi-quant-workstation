from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.research_newow_futures import router
from app.newow_futures_research.store import publish_packet
from research.test_newow_futures_store import packet

PREFIX = '/api/v1/research/newow-futures'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('GUIYI_NEWOW_FUTURES_RESULTS_ROOT', str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_profiles_and_missing_results_are_explicit(client, tmp_path):
    profiles = client.get(PREFIX + '/profiles').json()
    assert len(profiles['profiles']) == 48
    assert profiles['products'] == ['JM', 'RB', 'AL', 'TA']
    assert all(row['auto_order'] is False for row in profiles['profiles'])
    assert client.get(PREFIX + '/runs').json()['runs'] == []
    result = client.get(PREFIX + '/snapshot?product=jm&strategy=trend&frequency=5m')
    assert result.status_code == 404
    assert result.json()['detail']['code'] == 'RESULT_NOT_FOUND'
    assert client.get(PREFIX + '/snapshot?product=cu&strategy=trend&frequency=5m').json()['detail']['code'] == 'RESEARCH_NOT_COVERED'
    assert list(tmp_path.iterdir()) == []


def test_snapshot_is_bounded_hash_bound_with_complete_summary(client, tmp_path):
    p = packet()
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    stamps = [(start + timedelta(minutes=i * 5)).isoformat() for i in range(2010)]
    p['chart']['bars'] = [{'bar_end': at, 'close': '1'} for at in stamps]
    p['chart']['frames'] = [{'bar_end': at, 'side': 'LONG'} for at in stamps]
    p['reference']['actions'] = [{'at': at, 'bar_end': at, 'action': 'ENTER'} for at in stamps]
    p['reference']['trades'] = [{'id': str(i)} for i in range(150)]
    p['reference']['equity'] = [{'at': at, 'value': '100000'} for at in stamps]
    p['summary']['closed_trades'] = 150
    frozen = publish_packet(tmp_path, p)
    snapshot = client.get(PREFIX + '/snapshot?product=jm&strategy=trend&frequency=5m').json()
    assert snapshot['run_id'] == frozen['run_id']
    assert snapshot['schema_version'] == 1
    assert snapshot['sha256'] == frozen['sha256']
    assert len(snapshot['chart']['bars']) == len(snapshot['chart']['frames']) == 2000
    assert all(row['bar_end'] >= stamps[10] for row in snapshot['reference']['actions'])
    assert len(snapshot['reference']['trades']) == len(snapshot['reference']['equity']) == 100
    assert snapshot['summary']['closed_trades'] == 150
    assert snapshot['preview']['reference_trades_total'] == 150
    assert 'fills' not in snapshot and 'decisions' not in snapshot
    detail = client.get(PREFIX + '/runs/' + frozen['run_id']).json()
    assert detail == snapshot
    assert client.get(PREFIX + '/runs/' + frozen['run_id'], params={'sha256': '0' * 64}).status_code == 409


def test_pages_enforce_boundaries_and_match_identity(client, tmp_path):
    p = packet()
    p['fills'] = [{'id': str(i)} for i in range(101)]
    p['reference']['trades'] = [{'id': 'reference'}]
    frozen = publish_packet(tmp_path, p)
    path = PREFIX + '/runs/' + frozen['run_id']
    first = client.get(path + '/fills?limit=100').json()
    assert first['total'] == 101 and first['next_offset'] == 100
    second = client.get(path + '/fills?offset=100&limit=100').json()
    assert second['items'] == [{'id': '100'}] and second['next_offset'] is None
    assert second['sha256'] == frozen['sha256']
    assert client.get(path + '/reference-trades').json()['items'] == [{'id': 'reference'}]
    assert client.get(path + '/fills?limit=201').status_code == 422
    assert client.get(path + '/fills?offset=-1').status_code == 422
    assert client.get(path + '/fills?offset=102').status_code == 422
    assert client.get(path + '/unsupported').status_code == 422
    assert client.get(PREFIX + '/runs/not-a-run').status_code == 422
    assert client.post(path + '/fills').status_code == 405


def test_runs_latest_selection_and_no_fallback(client, tmp_path):
    first = publish_packet(tmp_path, packet())
    other = packet()
    other['metadata']['as_of'] = '2026-10-20T11:00:00+08:00'
    second = publish_packet(tmp_path, other)
    runs = client.get(PREFIX + '/runs?limit=1').json()
    assert runs['total'] == 2 and len(runs['runs']) == 1
    assert runs['runs'][0]['run_id'] == second['run_id']
    assert client.get(PREFIX + '/snapshot?product=jm&strategy=trend&frequency=5m').json()['run_id'] == second['run_id']
    assert client.get(PREFIX + '/snapshot?product=rb&strategy=trend&frequency=5m').status_code == 404
    assert client.get(PREFIX + '/snapshot?product=jm&strategy=trend&frequency=1m').status_code == 422
    assert first['run_id'] != second['run_id']


def test_equity_curve_reads_whole_window_and_preserves_global_extrema(client, tmp_path):
    p = packet()
    at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    values = ['100000', '100100', '99900', '150000', '100000', '50000', '100000', '100001']
    p['equity'] = [{'at': (at + timedelta(days=i)).isoformat(), 'value': value} for i, value in enumerate(values)]
    frozen = publish_packet(tmp_path, p)
    response = client.get(PREFIX + '/runs/' + frozen['run_id'] + '/equity-curve',
                          params={'sha256': frozen['sha256'], 'max_points': 4})
    assert response.status_code == 200
    curve = response.json()
    assert curve['total_points'] == 8 and curve['sampled']
    assert {point['value'] for point in curve['points']} == {'100000', '150000', '50000', '100001'}
    assert client.get(PREFIX + '/runs/' + frozen['run_id'] + '/equity-curve', params={'sha256': '0' * 64}).status_code == 409


def test_minute_protective_close_keeps_actual_time_and_maps_enclosing_chart_bar(client, tmp_path):
    p = packet()
    stamps = ['2026-10-19T09:45:00+08:00', '2026-10-19T09:50:00+08:00']
    p['chart']['bars'] = [{'bar_end': at, 'physical_contract': 'JM2701', 'close': '100'} for at in stamps]
    p['reference']['actions'] = [{'at': '2026-10-19T09:47:00+08:00', 'bar_end': '2026-10-19T09:47:00+08:00',
                                  'action': 'CLOSE', 'physical_contract': 'JM2701', 'price': '100'}]
    receipt = publish_packet(tmp_path, p)
    action = client.get(PREFIX + '/runs/' + receipt['run_id']).json()['reference']['actions'][0]
    assert action['at'] == '2026-10-19T09:47:00+08:00'
    assert action['display_bar_end'] == stamps[1]


def test_generation_time_breaks_same_data_cutoff_tie(client, tmp_path):
    early, late = packet(), packet()
    early['metadata']['generated_at'] = '2026-10-20T01:00:00+00:00'
    late['metadata']['generated_at'] = '2026-10-20T02:00:00+00:00'
    publish_packet(tmp_path, early)
    result = publish_packet(tmp_path, late)
    latest = client.get(PREFIX + '/snapshot?product=jm&strategy=trend&frequency=5m').json()
    assert latest['run_id'] == result['run_id']
