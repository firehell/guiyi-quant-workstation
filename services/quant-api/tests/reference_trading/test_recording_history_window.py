from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from app.market_data.newow.product_reader import NewowProductReader
from app.market_data.market_data_service import MarketDataError
from scripts.newow_history_window import new_plan_since
from scripts import newow_recording_history as script
from scripts.reference_trading_p9_manifest import _newow
from guiyi_quant.newow.product_contracts import ProductStrategy
from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget
from tests.reference_trading.test_historical_refresh import Planner, END


@pytest.mark.parametrize('product,frequency,listed,expected', [
    ('ao', '1d', date(2023, 6, 19), date(2023, 6, 19)),
    ('ao', '1w', date(2023, 6, 19), date(2023, 6, 19)),
    ('pd', '60m', date(2025, 11, 27), date(2025, 11, 27)),
    ('pt', '60m', date(2025, 11, 27), date(2025, 11, 27)),
    ('rb', '1d', date(2009, 3, 27), date(2023, 1, 1)),
    ('rb', '1w', date(2009, 3, 27), date(2023, 1, 1)),
    ('rb', '60m', date(2009, 3, 27), date(2025, 9, 25)),
])
def test_new_plan_floor_uses_only_authoritative_product_start(product, frequency, listed, expected):
    calls = []
    class Coverage:
        def product_start(self, symbol):
            calls.append(symbol)
            return listed
    reader = NewowProductReader(SimpleNamespace(), coverage=Coverage(), active_products=(product,))
    identity = _newow(product, ProductStrategy.TREND, frequency, forward=False)
    assert new_plan_since(identity, reader.historical_storage_start) == expected
    assert calls == [product]


def test_post_listing_rank1_gap_still_fails_in_original_reader():
    listed = date(2023, 6, 19)
    class Market:
        def actual_dominant_segments(self, symbol, since, through):
            assert since == listed and through == date(2023, 6, 30)
            raise MarketDataError('MAIN_CONTRACT_MAP_MISSING')
    reader = NewowProductReader(Market(), coverage=SimpleNamespace(product_start=lambda symbol: listed),
                                active_products=('ao',))
    identity = _newow('ao', ProductStrategy.TREND, '1d', forward=False)
    since = new_plan_since(identity, reader.historical_storage_start)
    with pytest.raises(MarketDataError, match='MAIN_CONTRACT_MAP_MISSING'):
        reader.dependency_owners('ao', since, date(2023, 6, 30))


def test_frozen_plan_bytes_are_not_adjusted_by_new_listing_floor(tmp_path, monkeypatch):
    out = tmp_path / 'ao'
    out.mkdir()
    before = {}
    for frequency in ('1w', '1d', '60m'):
        identity = _newow('ao', ProductStrategy.TREND, frequency, forward=False)
        frozen = Planner().plan(HistoricalReferenceRequest('build', (HistoricalStreamRequest(
            identity, date(2023, 1, 1), END.date(), END),), WorkBudget(1, 500_000, 1800, 512_000_000)))
        file = out / f'trend-{frequency}-plan.json'
        import json
        file.write_text(json.dumps(script.plan_to_dict(frozen), indent=3) + '\n')
        before[file] = file.read_bytes()
    class NoNewPlan:
        def plan(self, request):
            raise AssertionError('must not rewrite a frozen plan')
        @property
        def _reader(self):
            raise AssertionError('must not recalculate frozen query bounds')
    @contextmanager
    def components(**kwargs):
        yield NoNewPlan(), SimpleNamespace()
    monkeypatch.setattr(script, 'open_historical_reference_components', components)
    monkeypatch.setattr(script, 'load_active_products', lambda: ('ao',))
    monkeypatch.setattr(script, 'load_operational_products', lambda: ('ao',))
    monkeypatch.setattr(script, 'validate_product_scope', lambda *args: ('ao',))
    assert script.main(['--product', 'ao', '--output-root', str(tmp_path), '--as-of', END.isoformat(),
                        '--strategy', 'trend']) == 0
    assert all(file.read_bytes() == content for file, content in before.items())


def test_missing_authoritative_listing_start_never_falls_back_to_map_floor():
    identity = _newow('ao', ProductStrategy.TREND, '1d', forward=False)
    with pytest.raises(ValueError, match='HISTORY_LISTING_DATE_UNAVAILABLE'):
        new_plan_since(identity, lambda product: None)


def test_new_script_plans_pass_authoritative_listing_boundary_to_original_planner(tmp_path, monkeypatch):
    from contextlib import nullcontext
    import app.db.readonly
    requests, start_calls = [], []
    class NewPlans(Planner):
        _reader = SimpleNamespace(_newow_for=lambda identity: SimpleNamespace(
            historical_storage_start=lambda product: (start_calls.append(product) or date(2023, 6, 19))))
        def plan(self, request):
            requests.append(request)
            return super().plan(request)
    @contextmanager
    def components(**kwargs):
        yield NewPlans(), SimpleNamespace()
    monkeypatch.setattr(script, 'open_historical_reference_components', components)
    monkeypatch.setattr(script, 'SessionLocal', lambda: nullcontext(SimpleNamespace(scalar=lambda query: None)))
    monkeypatch.setattr(app.db.readonly, 'readonly_transaction', lambda session, **kwargs: nullcontext(session))
    monkeypatch.setattr(script, 'load_active_products', lambda: ('ao',))
    monkeypatch.setattr(script, 'load_operational_products', lambda: ('ao',))
    monkeypatch.setattr(script, 'validate_product_scope', lambda *args: ('ao',))
    assert script.main(['--product', 'ao', '--output-root', str(tmp_path), '--as-of', END.isoformat(),
                        '--strategy', 'trend']) == 0
    assert [request.streams[0].since for request in requests] == [date(2023, 6, 19), date(2023, 6, 19), date(2025, 9, 25)]
    assert start_calls == ['ao', 'ao', 'ao']
