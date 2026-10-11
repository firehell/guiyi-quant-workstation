from decimal import Decimal
from types import SimpleNamespace
from dataclasses import replace

from fastapi.testclient import TestClient
from app.main import app
from app.api import market_newow
from app.db.session import get_db

from app.market_data.newow.product_service import ProductServiceQuery
from .test_product_service import _service
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
    monkeypatch.setattr(market_newow, '_build_product_service', lambda *_: service)
    monkeypatch.setattr(market_newow, '_build_daily_resolver', lambda *_: SimpleNamespace(resolve=lambda *args: SimpleNamespace(as_of=clear.bar_end, freshness='current')))
    def failed(*args):
        raise ValueError('NEWOW_WEEKLY_STALE')
    monkeypatch.setattr(market_newow, '_build_weekly_resolver', failed)
    app.dependency_overrides[get_db] = lambda: object()
    try:
        with TestClient(app) as client:
            response = client.get('/api/v1/market/newow/home-cards?products=rb')
            assert response.status_code == 200
            body = response.json()
            trend = body['items'][0]['strategies']['trend']
            assert trend['1d']['state'] == 'CLEAR'
            assert trend['1d']['recent_action']['signal_id'] == clear.signal_id
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
