from contextlib import contextmanager, nullcontext
from datetime import date
from types import SimpleNamespace

import pytest

from scripts import newow_recording_history as script
from scripts.reference_trading_p9_manifest import _newow
from guiyi_quant.newow.product_contracts import ProductStrategy
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from app.market_data.newow.product_release import candidate_input_quality_policy
from app.reference_trading.planning import HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget
from app.reference_trading.service import BatchReport, StreamBatchReport
from tests.reference_trading.test_historical_refresh import Planner, END


def scope(monkeypatch):
    monkeypatch.setattr(script, 'load_active_products', lambda: ('rb',))
    monkeypatch.setattr(script, 'load_operational_products', lambda: ('rb',))
    monkeypatch.setattr(script, 'validate_product_scope', lambda *args: ('rb',))


@pytest.mark.parametrize('count', [3, 4])
def test_single_daily_plan_only_selected_cells_and_base_first(tmp_path, monkeypatch, count):
    import app.db.readonly
    scope(monkeypatch)
    requests = []
    class Plans(Planner):
        _reader = SimpleNamespace(_newow_for=lambda identity: SimpleNamespace(
            historical_storage_start=lambda product: date(2009, 3, 27)))
        def plan(self, request):
            requests.append(request)
            return super().plan(request)
    @contextmanager
    def components(**kwargs):
        yield Plans(), SimpleNamespace()
    monkeypatch.setattr(script, 'open_historical_reference_components', components)
    monkeypatch.setattr(script, 'SessionLocal', lambda: nullcontext(SimpleNamespace(scalar=lambda query: None)))
    monkeypatch.setattr(app.db.readonly, 'readonly_transaction', lambda session, **kwargs: nullcontext(session))
    args = ['--product', 'rb', '--output-root', str(tmp_path), '--as-of', END.isoformat(), '--frequency', '1d']
    if count == 3:
        args += ['--strategy', 'main_rise', '--strategy', 'trend', '--strategy', 'oscillation']
    assert script.main(args) == 0
    assert len(requests) == count
    assert all(request.streams[0].identity.frequency == '1d' for request in requests)
    assert [request.streams[0].identity.strategy_code for request in requests] == [
        'newow_trend', 'newow_oscillation', 'newow_main_rise', *(['newow_dual_fusion'] if count == 4 else [])]
    assert len(list((tmp_path / 'rb').glob('*-plan.json'))) == count
    assert not list((tmp_path / 'rb').glob('*-1w-*')) and not list((tmp_path / 'rb').glob('*-60m-*'))


@pytest.mark.parametrize('count', [3, 4])
def test_single_daily_apply_does_not_read_unselected_frozen_evidence(tmp_path, monkeypatch, count):
    scope(monkeypatch)
    out = tmp_path / 'rb'
    out.mkdir()
    selected = ('trend', 'oscillation', 'main_rise', 'dual_fusion')[:count]
    for strategy in selected:
        policy = candidate_input_quality_policy('rb', '1d', candidate_weekly=False)
        identity = (build_fusion_stream_identity('rb', '1d', input_quality_policy=policy)
                    if strategy == 'dual_fusion' else _newow('rb', ProductStrategy(strategy), '1d', forward=False))
        frozen = Planner().plan(HistoricalReferenceRequest('rebuild', (HistoricalStreamRequest(
            identity, date(2023, 1, 1), END.date(), END),), WorkBudget(1, 500_000, 1800, 512_000_000)))
        script._atomic_json(out / f'{strategy}-1d-plan.json', script.plan_to_dict(frozen))
    untouched = []
    for frequency in ('1w', '60m'):
        for strategy in ('trend', 'oscillation', 'main_rise', 'dual_fusion'):
            path = out / f'{strategy}-{frequency}-plan.json'
            path.write_bytes(b'unselected evidence must not be opened')
            untouched.append(path)
    calls = []
    class Apply:
        def rebuild(self, plan, expected):
            item = plan.streams[0]
            assert item.request.identity.frequency == '1d'
            calls.append(item.request.identity.strategy_code)
            return BatchReport('completed', (StreamBatchReport(item.request.identity.stream_id,
                'completed', None, 1, 'revision', 'revision', 'batch', None),))
    @contextmanager
    def components(**kwargs):
        yield SimpleNamespace(), Apply()
    monkeypatch.setattr(script, 'open_historical_reference_components', components)
    args = ['--product', 'rb', '--output-root', str(tmp_path), '--as-of', END.isoformat(),
            '--frequency', '1d', '--apply']
    if count == 3:
        args += ['--strategy', 'main_rise', '--strategy', 'trend', '--strategy', 'oscillation']
    assert script.main(args) == 0
    assert len(calls) == count and calls[-1] == ('newow_dual_fusion' if count == 4 else 'newow_main_rise')
    assert all(path.read_bytes() == b'unselected evidence must not be opened' for path in untouched)
    assert len(list(out.glob('*-intent.json'))) == count
    assert len(list(out.glob('*-receipt.json'))) == count


def test_invalid_frequency_fails_before_database_or_components(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('invalid frequency must fail during argument parsing')
    monkeypatch.setattr(script, 'load_active_products', forbidden)
    monkeypatch.setattr(script, 'open_historical_reference_components', forbidden)
    with pytest.raises(SystemExit) as error:
        script.main(['--product', 'rb', '--output-root', str(tmp_path), '--as-of', END.isoformat(), '--frequency', '5m'])
    assert error.value.code == 2
