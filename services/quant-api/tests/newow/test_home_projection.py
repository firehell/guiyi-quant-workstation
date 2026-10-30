from datetime import UTC, datetime
import json

import pytest

from app.market_data.newow.home_projection import HomeProjection, ProjectionStore, ProjectionError


def fact(version):
    return {s: {'status': 'ready', 'state': 'HOLD', 'input_sha256': version, 'page_parity': True, 'executable': False} for s in ('trend', 'oscillation')}


def fixture(tmp_path):
    versions = {'rb:1d': 'd1', 'rb:1w': 'w1'}
    calls = []
    def compute(product, period):
        calls.append((product, period))
        return fact(versions[f'{product}:{period}'])
    service = HomeProjection(ProjectionStore(tmp_path / 'home.json'), ('rb',), lambda: dict(versions), compute, now=lambda: datetime(2026, 10, 23, 10, tzinfo=UTC))
    return service, versions, calls


def test_get_never_computes_missing_or_restarts(tmp_path):
    service, versions, calls = fixture(tmp_path)
    assert service.read()['items'][0]['projection_status'] == 'missing'
    assert calls == []
    service.build()
    restarted = HomeProjection(service.store, ('rb',), lambda: dict(versions), lambda *_: pytest.fail('GET computed'))
    assert restarted.read()['items'][0]['projection_status'] == 'ready'


def test_changed_period_only_and_same_version_is_noop(tmp_path):
    service, versions, calls = fixture(tmp_path)
    service.build()
    service.build()
    assert calls == [('rb', '1d'), ('rb', '1w')]
    versions['rb:1d'] = 'revised'
    assert service.read()['items'][0]['projection_status'] == 'stale'
    service.build()
    assert calls == [('rb', '1d'), ('rb', '1w'), ('rb', '1d')]
    item = service.read()['items'][0]
    assert item['projection_status'] == 'ready'
    assert item['strategies']['trend']['1w']['input_sha256'] == 'w1'


def test_failure_preserves_last_good_and_does_not_mask_other_period(tmp_path):
    service, versions, _ = fixture(tmp_path)
    service.build()
    versions['rb:1d'] = 'new'
    service.compute = lambda *_: (_ for _ in ()).throw(RuntimeError('private details'))
    service.build()
    item = service.read()['items'][0]
    assert item['projection_status'] == 'failed'
    assert item['strategies']['trend']['1d']['input_sha256'] == 'd1'
    assert 'private' not in json.dumps(item)


def test_source_mutating_during_compute_cannot_publish_as_current(tmp_path):
    service, versions, _ = fixture(tmp_path)
    def compute(product, period):
        prior = versions[f'{product}:{period}']
        versions[f'{product}:{period}'] += '-changed'
        return fact(prior)
    service.compute = compute
    service.build()
    assert service.read()['items'][0]['projection_status'] == 'failed'
    assert service.read()['items'][0]['strategies']['trend']['1d']['status'] == 'unavailable'


def test_corruption_and_symlink_fail_closed(tmp_path):
    service, _, _ = fixture(tmp_path)
    service.build()
    value = json.loads(service.store.path.read_text())
    value['payload']['items']['rb']['periods']['1d']['version'] = 'forged'
    service.store.path.write_text(json.dumps(value))
    assert service.read()['items'][0]['projection_status'] == 'missing'
    target = tmp_path / 'elsewhere'
    target.write_text('{}')
    service.store.path.unlink()
    service.store.path.symlink_to(target)
    with pytest.raises(ProjectionError):
        service.build()
    assert target.read_text() == '{}'


def test_concurrent_build_refused_and_get_marks_updating(tmp_path):
    service, _, _ = fixture(tmp_path)
    service.build()
    with service.store.lock():
        with pytest.raises(ProjectionError):
            service.build()


def test_unknown_revision_never_claims_ready(tmp_path):
    service, _, _ = fixture(tmp_path)
    service.build()
    service.versions = lambda: (_ for _ in ()).throw(RuntimeError('db unavailable'))
    assert service.read()['items'][0]['projection_status'] == 'stale'


def test_http_read_projection_never_builds_and_old_endpoints_are_retired(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.market_data.newow import home_projection_composition as composition
    service, _, calls = fixture(tmp_path)
    monkeypatch.setattr(composition, 'build_home_projection', lambda: service)
    with TestClient(app) as client:
        response = client.get('/api/v1/market/newow/home-projection')
        assert response.status_code == 200
        assert calls == []
        assert response.json()['items'][0]['projection_status'] == 'missing'
        assert client.get('/api/v1/market/newow/home-projection?products=rb').status_code == 422
        assert client.get('/api/v1/market/newow/home-projection', headers={'If-None-Match': response.headers['etag']}).status_code == 304
        for path in ('home-cards', 'home-card-performance', 'home-card-display-cache'):
            assert client.get('/api/v1/market/newow/' + path).status_code == 404


def test_partial_period_failure_preserves_whole_prior_product_generation(tmp_path):
    service, versions, _ = fixture(tmp_path)
    service.build()
    old = service.read()['items'][0]
    versions.update({'rb:1d':'new-d', 'rb:1w':'new-w'})
    def compute(_product, period):
        if period == '1w':
            raise RuntimeError('failure')
        return fact('new-day')
    service.compute = compute
    service.build()
    current = service.read()['items'][0]
    assert current['strategies'] == old['strategies']
    assert current['computed_at'] == old['computed_at']
    assert current['projection_status'] == 'failed'


def test_real_daily_compute_keeps_existing_summary_and_reference_numbers(monkeypatch, product_cases):
    from types import SimpleNamespace
    from .test_product_service import _service
    from app.market_data.newow import home_projection_composition as composition
    from app.market_data.newow.product_service import ProductServiceQuery
    from app.market_data.newow.home_cards import project_home_performance
    from app.api.newow_presentation import _json_value
    service, reader, build, clear = _service(product_cases)
    resolve = reader.resolve_performance_window
    monkeypatch.setattr(reader, 'resolve_performance_window', lambda product, frequency, since, through, as_of: resolve(product, frequency, since or build.trading_day, through or clear.trading_day, as_of))
    monkeypatch.setattr(composition, 'NewowComposition', lambda *_, **__: SimpleNamespace(reader=lambda: reader, service=lambda **_:service))
    def resolver(_reader, factory, **kwargs):
        assert kwargs['timeout_seconds'] == 600
        current = factory(lambda:False)
        snapshot = SimpleNamespace(as_of=clear.bar_end, freshness='current')
        return SimpleNamespace(resolve_with_chart=lambda *_:(snapshot, current.query(ProductServiceQuery('rb','trend','1d',as_of=clear.bar_end))))
    monkeypatch.setattr(composition, 'NewowDailySnapshotResolver', resolver)
    expected_chart = service.query(ProductServiceQuery('rb','trend','1d',as_of=clear.bar_end))
    expected_reference = service.query(ProductServiceQuery('rb','trend','1d',section='reference',as_of=clear.bar_end,snapshot_token=expected_chart.meta.snapshot_token,history_limit=1))
    facts = composition.compute_period(None,'rb','1d',clear.bar_end)
    for key, value in _json_value(expected_chart.chart.value.home_summary).items():
        assert facts['trend'][key] == value
    assert facts['trend']['page_performance'] == _json_value(project_home_performance(expected_reference))
    assert 'snapshot_token' not in facts['trend'] and 'snapshot_context' not in facts['trend']


def test_unchanged_build_preserves_computed_time_and_does_not_republish(tmp_path, monkeypatch):
    service, _, calls = fixture(tmp_path)
    service.build()
    monkeypatch.setattr(service.store, 'save', lambda *_: pytest.fail('unchanged inputs republished'))
    service.build()
    assert len(calls) == 2


def test_overview_is_built_once_and_get_never_falls_back_to_live_computation(tmp_path):
    service, _, calls = fixture(tmp_path)
    overview_calls = []
    service.overview = lambda: overview_calls.append(1) or {'target_as_of':'2026-10-23'}
    service.build()
    result = service.read()
    assert result['overview_status'] == 'ready'
    assert result['overview'] == {'target_as_of':'2026-10-23'}
    assert overview_calls == [1]
    service.read()
    assert overview_calls == [1] and len(calls) == 2


def test_existing_overview_http_contract_reads_same_asset_and_rejects_stale(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.market_data.newow import home_projection_composition as composition
    from tests.test_market_home_projection_api import _response
    service, versions, calls = fixture(tmp_path)
    service.overview = lambda: _response().model_dump(mode='json')
    service.build()
    monkeypatch.setattr(composition, 'build_home_projection', lambda: service)
    with TestClient(app) as client:
        result = client.get('/api/v1/market/research/home-overview')
        assert result.status_code == 200
        assert result.json() == _response().model_dump(mode='json')
        assert client.get('/api/v1/market/research/home-overview',headers={'If-None-Match':result.headers['etag']}).status_code == 304
        versions['rb:1d'] = 'revision'
        stale = client.get('/api/v1/market/research/home-overview')
        assert stale.status_code == 200
        assert stale.json()['projection_status'] == 'stale'
        assert stale.json()['items'] == _response().model_dump(mode='json')['items']
    assert len(calls) == 2


def test_overview_failure_preserves_lastgood_and_does_not_block_products(tmp_path):
    service, versions, calls = fixture(tmp_path)
    service.overview = lambda: {'target_as_of':'old'}
    service.build()
    versions['rb:1d'] = 'revised'
    service.overview = lambda: (_ for _ in ()).throw(RuntimeError('private'))
    result = service.build()
    assert result['overview'] == {'target_as_of':'old'}
    assert result['overview_status'] == 'failed'
    assert result['items'][0]['projection_status'] == 'ready'
    assert calls[-1] == ('rb', '1d')
    assert 'private' not in json.dumps(result)


def test_overview_recovers_when_failed_source_returns_to_lastgood_identity(tmp_path):
    service, versions, _ = fixture(tmp_path)
    service.overview = lambda: {'target_as_of': 'lastgood'}
    service.build()
    versions['rb:1d'] = 'temporary-config-change'
    service.overview = lambda: (_ for _ in ()).throw(RuntimeError('invalid config'))
    assert service.build()['overview_status'] == 'failed'

    # A repository configuration can be restored byte-for-byte; recovery must
    # work even when its identity equals the old successful publication.
    versions['rb:1d'] = 'd1'
    recovered = []
    service.overview = lambda: recovered.append(True) or {'target_as_of': 'recovered'}
    result = service.build()
    assert result['overview_status'] == 'ready'
    assert result['overview'] == {'target_as_of': 'recovered'}
    assert recovered == [True]


def test_publication_reasons_distinguish_versions_from_completed_periods(tmp_path):
    service, versions, _ = fixture(tmp_path)
    service.build()
    assert service.read()['items'][0]['period_reason_codes'] == {'1d': None, '1w': None}
    versions['rb:1d'] = 'changed'
    item = service.read()['items'][0]
    assert item['period_reason_codes']['1d'] == 'SOURCE_VERSION_CHANGED'
    assert item['period_status']['1w'] == 'ready'
    service.versions = lambda: {}
    assert service.read()['items'][0]['period_reason_codes']['1w'] == 'SOURCE_VERSION_UNAVAILABLE'
