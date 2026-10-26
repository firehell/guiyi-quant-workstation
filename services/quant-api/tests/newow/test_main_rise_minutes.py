"""Current capability expansion leaves frozen contracts and activation independent."""
import pytest
from starlette.requests import Request
from app.api.market_newow import _require_strategy_frequency
from app.market_data.newow.capability_contracts import capability_response
from app.market_data.newow.product_release import CAPABILITY_SCHEMA_VERSION
from app.market_data.newow.product_service import ProductServiceQuery
from app.reference_trading.recording_scope import strategies_for


@pytest.mark.parametrize('frequency', ['5m', '15m', '30m'])
def test_formal_main_rise_minutes_are_supported(frequency):
    assert CAPABILITY_SCHEMA_VERSION == 'newow_product_capabilities_v35'
    assert frequency in capability_response(CAPABILITY_SCHEMA_VERSION)['strategy_frequencies']['main_rise']
    _require_strategy_frequency(Request({'type': 'http', 'state': {}}), 'main_rise', frequency)
    assert ProductServiceQuery('rb', 'main_rise', frequency).frequency.value == frequency
    assert 'main_rise' in strategies_for(frequency)


@pytest.mark.parametrize('frequency', ['5m', '15m', '30m', '60m'])
def test_frozen_preview_main_rise_stays_closed(frequency):
    with pytest.raises(ValueError, match='NEWOW_INVALID_QUERY'):
        _require_strategy_frequency(Request({'type': 'http', 'state': {'intraday_preview_products': frozenset({'rb'})}}), 'main_rise', frequency)
