from decimal import Decimal
from types import SimpleNamespace
from dataclasses import replace

from fastapi.testclient import TestClient
from app.main import app
from app.api import market_newow
from app.db.session import get_db

from app.market_data.newow.product_service import ProductServiceQuery
from .test_product_service import _service
from app.market_data.newow.daily_snapshot import DailySnapshot
from guiyi_quant.newow.product_contracts import ProductStrategy, ProductFrequency
from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus, FeatureStatus, EvidenceStatus
from app.market_data.newow.home_cards import project_home_summary


def test_home_summary_uses_full_replay_even_with_one_visible_bar(product_cases):
    service, _, _, clear = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end, chart_limit=1))
    assert hasattr(result.chart.value, 'home_summary'), 'chart must retain a lightweight full-prefix summary'
    summary = result.chart.value.home_summary
    assert summary['state'] == result.chart.value.replay.frames[-1].main_state.value
    assert summary['recent_action']['signal_id'] == clear.signal_id
    assert summary['reference_cost'] is None
    price = result.chart.value.price_reference
    if price.target.raw is not None:
        close = result.chart.value.bars[-1].bar.close
        assert summary['target_space_percent'] == (price.target.raw - close) / close * Decimal(100)
    assert summary['physical_contract'] == clear.physical_contract


def test_home_summary_open_cost_is_eligible_build_price(product_cases):
    service, _, build, _ = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=build.bar_end, chart_limit=1))
    assert hasattr(result.chart.value, 'home_summary'), 'open card must use reference BUILD'
    summary = result.chart.value.home_summary
    assert summary['reference_cost'] == build.reference_price
    assert summary['entry_signal_id'] == build.signal_id


def test_batch_card_is_exact_projection_and_weekly_failure_is_isolated(monkeypatch, product_cases):
    service, _, _, clear = _service(product_cases)
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *_, **kwargs: service)
    monkeypatch.setattr(market_newow, '_build_daily_resolver', lambda *_, **kwargs: SimpleNamespace(resolve=lambda *args: DailySnapshot('rb', ProductStrategy.TREND, ProductFrequency.DAILY, clear.bar_end, clear.trading_day, clear.trading_day, clear.bar_end, 'current')))
    def failed(*args, **kwargs):
        raise ValueError('NEWOW_WEEKLY_STALE')
    monkeypatch.setattr(market_newow, '_build_weekly_resolver', failed)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/market/newow/home-cards?products=rb')
            assert response.status_code == 200
            body = response.json()
            assert body['schema_version'] == 'newow_home_cards_v2'
            trend = body['items'][0]['strategies']['trend']
            assert 'page_performance' not in trend['1d']
            assert trend['1d']['state'] == 'CLEAR'
            assert trend['1d']['recent_action']['signal_id'] == clear.signal_id
            assert trend['1d']['display_as_of'] == body['requested_at']
            assert trend['1d']['page_parity'] is True
            assert trend['1d']['executable'] is False
            assert trend['1d']['formula_versions']
            assert trend['1w'] == {'status': 'unavailable', 'state': None, 'reason_code': 'NEWOW_WEEKLY_STALE'}
            assert 'bars' not in trend['1d'] and 'frames' not in trend['1d']
    finally:
        app.dependency_overrides.clear()


def test_batch_bounds_and_duplicate_queries_fail_before_read(monkeypatch):
    def forbidden(*args):
        raise AssertionError('invalid batch must not read')
    monkeypatch.setattr(market_newow, '_build_daily_resolver', forbidden)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            for query in ['products=rb,rb', 'products=rb&products=ag', 'products=rb&unknown=1', 'products=', 'products=' + ','.join(['rb'] * 13)]:
                assert client.get('/api/v1/market/newow/home-cards?' + query).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_unready_tail_withholds_state_prices_and_cost(product_cases):
    service, _, build, _ = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=build.bar_end))
    chart = result.chart.value
    status = FeatureStatus(FeatureRuntimeStatus.WARMING, EvidenceStatus.ACTIVE_CODE_VERIFIED, 'NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING')
    summary = project_home_summary(chart.replay, chart.replay.frames[-1], status, chart.price_reference)
    assert summary['state'] is None
    assert all(summary[key] is None for key in ('target', 'absorb', 'reference_current', 'reference_cost', 'entry_signal_id', 'target_space_percent'))


def test_open_cost_cannot_borrow_a_different_calculation_segment(product_cases):
    service, _, build, _ = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=build.bar_end))
    chart = result.chart.value
    anchor = chart.replay.frames[-1]
    anchor = replace(anchor, bar=replace(anchor.bar, calculation_segment_id='different-prefix'), actions=())
    summary = project_home_summary(chart.replay, anchor, chart.replay.frames[-1].availability, None)
    assert summary['reference_cost'] is None and summary['recent_action'] is None


def test_display_event_only_belongs_to_anchor_and_guard_uses_trend_ma10(product_cases):
    service, _, build, _ = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=build.bar_end))
    chart = result.chart.value
    anchor = chart.replay.frames[-1]
    summary = project_home_summary(chart.replay, anchor, anchor.availability, chart.price_reference)
    assert summary['display_projection_version'] == 'newow_home_display_v1'
    assert summary['current_event']['signal_id'] == build.signal_id
    assert summary['current_event']['bar_end'] == anchor.bar.bar.bar_end
    assert summary['guard_ma10'] == dict(anchor.main_values)['b']
    # The full replay may contain a recent action; a later confirmed bar is not a new event.
    later = replace(anchor, bar=replace(anchor.bar, bar=replace(anchor.bar.bar, bar_end=anchor.bar.bar.bar_end.replace(hour=23))), actions=())
    summary = project_home_summary(chart.replay, later, later.availability, None)
    assert summary['recent_action']['signal_id'] == build.signal_id
    assert summary['current_event'] is None


def test_home_prices_expose_existing_channel_provenance(product_cases):
    service, _, _, clear = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end, chart_limit=1))
    prices = result.chart.value.price_reference
    summary = result.chart.value.home_summary
    assert summary['price_input_sha256'] == prices.input_sha256
    assert result.meta.input_content_sha256 != prices.input_sha256
    for kind, branch in [('target', 'chart_hhv10'), ('absorb', 'chart_llv10')]:
        value = getattr(prices, kind)
        source = summary['price_sources'][kind]
        if value.raw is None:
            assert source is None
            continue
        assert source['raw'] == value.raw
        assert source['display_value'] == value.display
        assert source['frequency'] == prices.frequency.value
        assert source['bar_end'] == prices.anchor_bar_end
        assert source['physical_contract'] == prices.physical_contract
        assert source['calculation_segment_id'] == prices.calculation_segment_id
        assert source['input_sha256'] == prices.input_sha256
        assert source['formula_version'] == prices.formula_version
        assert source['source_category'] == 'canonical_channel'
        assert source['branch'] == branch


def test_home_absorb_space_and_control_are_existing_confirmed_facts(product_cases):
    service, _, _, clear = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end))
    chart = result.chart.value
    summary = chart.home_summary
    if chart.price_reference.absorb.raw is not None:
        assert summary['absorb_space_percent'] == (chart.price_reference.absorb.raw - chart.bars[-1].bar.close) / chart.bars[-1].bar.close * Decimal(100)
    control = summary['main_force_control']
    assert control['formula_version'] == 'newow_main_force_control_page_v1'
    assert control['bar_end'] == chart.bars[-1].bar.bar_end
    assert control['physical_contract'] == summary['physical_contract']
    assert control['page_parity'] is True and control['executable'] is False


def test_home_reference_summary_reuses_ordinary_page_performance(product_cases):
    from app.market_data.newow.home_cards import project_home_performance
    service, _, build, clear = _service(product_cases)
    result = service.query(ProductServiceQuery('rb', 'trend', '1d', section='reference', performance_since=build.trading_day, performance_through=clear.trading_day, as_of=clear.bar_end))
    summary = project_home_performance(result)
    ordinary = result.reference.value.page_performance['ordinary']
    assert summary['cum_return_percent'] == ordinary['summary']['cumReturn']
    assert summary['trade_count'] == ordinary['summary']['tradeCount']
    assert summary['input_sha256'] == result.reference.value.page_performance['input_sha256']
    assert summary['page_parity'] is True and summary['executable'] is False


def test_home_j_hint_uses_previous_hint_not_main_rise_clear():
    from types import SimpleNamespace
    from app.market_data.newow.home_cards import project_home_j_hint
    def item(j, bdgd, clear=False):
        return SimpleNamespace(j_value=j, state=SimpleNamespace(previous_bdgd=bdgd, previous_was_sell=clear))
    # Prior CLEAR must not hide a public home J hint.
    assert project_home_j_hint([item(110, True, True), item(100, False)]) == 1
    # Adjacent hints are suppressed; a subsequent independent hint is allowed.
    assert project_home_j_hint([item(110, True), item(100, True), item(90, True), item(80, False)]) == 3
    assert project_home_j_hint([item(None, False), item(90, True)]) is None


def test_row_caution_uses_confirmation_window_and_current_owner():
    from types import SimpleNamespace
    from tests.newow.test_oscillation_channel import golden_bars
    from app.market_data.newow.home_cards import project_row_hints
    template = golden_bars()
    closes = [100] * 20 + [110, 108, 104, 103, 109]
    bars = tuple(replace(template[i], open=Decimal(c), high=Decimal(c+1), low=Decimal(c-1), close=Decimal(c)) for i,c in enumerate(closes))
    frames = tuple(SimpleNamespace(bar=SimpleNamespace(bar=bar, calculation_segment_id='owner')) for bar in bars)
    def project(count, ready=True):
        replay = SimpleNamespace(identity=SimpleNamespace(frequency=SimpleNamespace(value='1d')), frames=frames[:count])
        return project_row_hints(replay, frames[count-1], ready)
    assert not [item for item in project(22)['items'] if item['kind'] == 'caution']
    caution = [item for item in project(23)['items'] if item['kind'] == 'caution'][0]
    assert caution['peak_day'] == bars[20].trading_day
    assert caution['event_day'] == bars[22].trading_day
    assert any(item['kind'] == 'caution' for item in project(24)['items'])
    assert not any(item['kind'] == 'caution' for item in project(25)['items'])
    assert project(23, False) is None
    foreign = replace(bars[-1], physical_contract='OTHER')
    anchor = SimpleNamespace(bar=SimpleNamespace(bar=foreign, calculation_segment_id='other'))
    replay = SimpleNamespace(identity=SimpleNamespace(frequency=SimpleNamespace(value='1d')), frames=frames)
    assert project_row_hints(replay, anchor, True) is None


def test_home_never_reads_reference_history(monkeypatch, product_cases):
    service, _, _, clear = _service(product_cases)
    calls = []
    original = service.query
    def query(request):
        calls.append(request.section.value)
        assert request.section.value == 'chart'
        return original(request)
    monkeypatch.setattr(service, 'query', query)
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *_, **kwargs: service)
    monkeypatch.setattr(market_newow, '_build_daily_resolver', lambda *_, **kwargs: SimpleNamespace(resolve=lambda *args: DailySnapshot('rb', ProductStrategy.TREND, ProductFrequency.DAILY, clear.bar_end, clear.trading_day, clear.trading_day, clear.bar_end, 'current')))
    monkeypatch.setattr(market_newow, '_build_weekly_resolver', lambda *_, **kwargs: SimpleNamespace(resolve=lambda *args: DailySnapshot('rb', ProductStrategy.TREND, ProductFrequency.DAILY, clear.bar_end, clear.trading_day, clear.trading_day, clear.bar_end, 'current')))
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/market/newow/home-cards?products=rb').status_code == 200
        assert calls == ['chart'] * 4
    finally:
        app.dependency_overrides.clear()


def test_lazy_performance_is_compact_and_bound_to_chart_token(monkeypatch, product_cases):
    service, reader, build, clear = _service(product_cases)
    resolve_window = reader.resolve_performance_window
    monkeypatch.setattr(reader, 'resolve_performance_window', lambda product, frequency, since, through, as_of: resolve_window(product, frequency, since or build.trading_day, through or clear.trading_day, as_of))
    chart = service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end))
    assert chart.meta.snapshot_token
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *_, **kwargs: service)
    app.dependency_overrides[get_db] = lambda: object()
    params = {'product':'rb', 'strategy':'trend', 'as_of':clear.bar_end.isoformat(), 'snapshot_token':chart.meta.snapshot_token}
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/market/newow/home-card-performance', params=params)
            assert response.status_code == 200, response.json()
            body = response.json()
            assert body['snapshot_token'] == chart.meta.snapshot_token
            expected = service.query(ProductServiceQuery('rb', 'trend', '1d', section='reference', as_of=clear.bar_end, snapshot_token=chart.meta.snapshot_token, history_limit=1))
            from app.market_data.newow.home_cards import project_home_performance
            assert body['performance']['cum_return_percent'] == str(project_home_performance(expected)['cum_return_percent'])
            assert not any(key in body['performance'] for key in ('items','curve','bars','trades'))
            assert client.get('/api/v1/market/newow/home-card-performance', params={**params,'snapshot_token':'foreign'}).status_code == 409
            assert client.get('/api/v1/market/newow/home-card-performance', params={**params,'as_of':'2026-10-09T07:00:00'}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_request_scoped_sharing_reuses_facts_and_auxiliary_inputs_without_changing_values(monkeypatch, product_cases):
    from app.market_data.newow import home_cards
    service, reader, _, clear = _service(product_cases)
    service._reuse_read_inputs = True
    original = home_cards.project_home_inputs
    calls = []
    def shared(replay, anchor):
        calls.append(replay.identity.strategy)
        return original(replay, anchor)
    monkeypatch.setattr(home_cards, 'project_home_inputs', shared)
    values = []
    for strategy in ('trend', 'oscillation'):
        values.append(service.query(ProductServiceQuery('rb', strategy, '1d', as_of=clear.bar_end)).chart.value.home_summary)
    assert len(reader.loads) == 1
    assert len(calls) == 1
    independent, _, _, _ = _service(product_cases)
    for strategy, expected in zip(('trend', 'oscillation'), values, strict=True):
        assert independent.query(ProductServiceQuery('rb', strategy, '1d', as_of=clear.bar_end)).chart.value.home_summary == expected


def test_home_reuses_snapshot_validation_service(monkeypatch, product_cases):
    service, reader, _, clear = _service(product_cases)
    service._reuse_read_inputs = True
    def resolver(*args, **kwargs):
        assert "home_services" in kwargs
        kwargs["home_services"].append(service)
        def resolve(*args):
            service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end))
            return DailySnapshot('rb', ProductStrategy.TREND, ProductFrequency.DAILY, clear.bar_end, clear.trading_day, clear.trading_day, clear.bar_end, 'current')
        return SimpleNamespace(resolve=resolve)
    monkeypatch.setattr(market_newow, '_build_daily_resolver', resolver)
    monkeypatch.setattr(market_newow, '_build_weekly_resolver', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('NEWOW_WEEKLY_STALE')))
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('must reuse verified service')))
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/market/newow/home-cards?products=rb')
        assert response.status_code == 200
        assert response.json()['items'][0]['strategies']['trend']['1d']['state'] == 'CLEAR'
        assert len(reader.loads) == 1
    finally:
        app.dependency_overrides.clear()


def test_conditional_cards_keep_token_identity_and_never_hide_failed_read(monkeypatch, product_cases):
    service, _, _, clear = _service(product_cases)
    result = [service.query(ProductServiceQuery('rb', 'trend', '1d', as_of=clear.bar_end))]
    monkeypatch.setattr(market_newow, '_PRODUCT_CACHE', service._cache)
    calls = []
    def query(request):
        calls.append(request)
        return result[0]
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *_, **kwargs: SimpleNamespace(query=query))
    def resolver(*args, **kwargs):
        return SimpleNamespace(resolve=lambda *args: DailySnapshot('rb', ProductStrategy.TREND, ProductFrequency.DAILY, clear.bar_end, clear.trading_day, clear.trading_day, clear.bar_end, 'current'))
    monkeypatch.setattr(market_newow, '_build_daily_resolver', resolver)
    monkeypatch.setattr(market_newow, '_build_weekly_resolver', resolver)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            path = '/api/v1/market/newow/home-cards?products=rb'
            first = client.get(path)
            assert first.status_code == 200
            headers = {'If-None-Match': first.headers['etag']}
            assert client.get(path, headers=headers).status_code == 304
            assert len(calls) == 8
            # Eviction must transfer a body even when the projected fields
            # still happen to contain the old token.
            service._cache._entries.clear()
            service._cache._tokens.clear()
            assert client.get(path, headers=headers).status_code == 200
            result[0] = replace(result[0], meta=replace(result[0].meta, snapshot_token='new-token-after-expiry'))
            changed = client.get(path, headers=headers)
            assert changed.status_code == 200 and changed.headers['etag'] != first.headers['etag']
            monkeypatch.setattr(market_newow, '_build_weekly_resolver', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('NEWOW_WEEKLY_STALE')))
            failure = client.get(path)
            assert client.get(path, headers={'If-None-Match': failure.headers['etag']}).status_code == 200
    finally:
        app.dependency_overrides.clear()
