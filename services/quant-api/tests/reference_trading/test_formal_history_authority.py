"""Public history chooses one Canonical identity and never admits observed fallback."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import market_newow, market_subing_reference
from app.reference_trading.persisted_newow import PersistedNewowReference
from app.reference_trading.query import QueryConflict
from app.reference_trading.signal_window import query_signal_window
from app.market_data.subing_reference import SubingReferenceError
from test_signal_window import Service, query


@pytest.mark.parametrize('obsolete_mode', ('legacy', 'persisted', 'invalid'))
def test_public_newow_always_composes_saved_history(monkeypatch, obsolete_mode):
    monkeypatch.setenv('REFERENCE_TRADING_READER_MODE', obsolete_mode)
    monkeypatch.setattr(market_newow, 'build_market_data_service', lambda db: object())
    monkeypatch.setattr(market_newow, 'build_database_coverage_source', lambda db: object())
    monkeypatch.setattr(market_newow, 'load_active_products', lambda: ('rb',))
    class Composition:
        def __init__(self, *args, **kwargs): pass
        def service(self, **kwargs): return kwargs['persisted_reference']
    monkeypatch.setattr(market_newow, 'NewowComposition', Composition)
    reader = market_newow._build_product_service(object())
    assert isinstance(reader.__self__, PersistedNewowReference)
    called = []
    reader.__self__._query = SimpleNamespace(streams=lambda **kwargs: called.append(kwargs) or [])
    request = SimpleNamespace(strategy=SimpleNamespace(value='trend'), product='rb', frequency=SimpleNamespace(value='1d'))
    with pytest.raises(QueryConflict, match='NOT_BUILT'):
        reader(request, None, None, object(), None, None, None)
    assert called[0]['mode'] == 'historical_replay'


@pytest.mark.parametrize('code', ('NOT_BUILT', 'SOURCE_IDENTITY_UNVERIFIED', 'STALE_INVALID'))
def test_subing_public_saved_failure_never_calls_on_demand_or_observation(monkeypatch, code):
    monkeypatch.setenv('REFERENCE_TRADING_READER_MODE', 'legacy')
    service = SimpleNamespace(query=lambda *_: pytest.fail('public history fell back to on-demand'))
    monkeypatch.setattr(market_subing_reference, '_build_service', lambda *_: service)
    class Saved:
        def __init__(self, *args): pass
        def query(self, query): raise QueryConflict(code)
    monkeypatch.setattr(market_subing_reference, 'PersistedSubingReference', Saved)
    with pytest.raises(HTTPException) as error:
        market_subing_reference.subing_reference(Request({'type': 'http', 'query_string': b''}),
            'rb', before=None, limit=50, session=object())
    assert error.value.detail['code'] == code
    assert error.value.status_code in (409, 503)


class SavedSignals:
    def streams(self, **kwargs):
        assert kwargs['mode'] == 'historical_replay'
        return [dict(stream_id='saved', formula_versions=['subing_ths_15m_v3'], reference_model_version='saved-model')]
    def signals(self, *args, **kwargs):
        return dict(snapshot='snapshot', revision_id='revision', seq=3, items=[], next_cursor=None)
    def trades(self, *args, **kwargs):
        assert kwargs['snapshot_token'] == 'snapshot'
        return dict(snapshot='snapshot', revision_id='revision', seq=3, items=[], next_cursor=None)


def test_subing_signal_window_requires_current_source_proof_before_saved_points():
    service = Service()
    request = replace(query(service), strategy='subing')
    with pytest.raises(SubingReferenceError, match='SOURCE_IDENTITY_UNVERIFIED'):
        query_signal_window(service, request, persisted_query=SavedSignals())
    seen = []
    result = query_signal_window(service, request, persisted_query=SavedSignals(),
        verify_persisted_source=lambda **kwargs: seen.append(kwargs))
    assert len(seen) == 2 and seen[0]['revision_id'] == 'revision' and seen[0]['seq'] == 3
    assert result['recording_mode'] == 'historical_replay' and result['items'] == []
    def revised(**kwargs): raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        query_signal_window(service, request, persisted_query=SavedSignals(), verify_persisted_source=revised)


def test_subing_signal_source_change_during_read_rejects_even_unchanged_visible_metadata():
    service = Service()
    request = replace(query(service), strategy='subing')
    calls = []
    def prefix_proof(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise QueryConflict('SOURCE_IDENTITY_UNVERIFIED')
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        query_signal_window(service, request, persisted_query=SavedSignals(), verify_persisted_source=prefix_proof)
    assert len(calls) == 2


def test_shared_saved_source_gate_rejects_earlier_prefix_revision(monkeypatch):
    from datetime import UTC, date, datetime
    from app.reference_trading import persisted_subing
    saved = dict(query_since='2025-01-01', reader='subing_reference',
        input_fingerprints=['warmup-old', 'visible-same'],
        calendar_session_effective_fingerprints=['sessions'])
    current = dict(saved)
    service = persisted_subing.PersistedSubingReference.__new__(persisted_subing.PersistedSubingReference)
    service._market = object()
    service._stored_manifest = lambda **kwargs: (object(), saved)
    monkeypatch.setattr(persisted_subing, 'HistoricalStreamRequest', lambda *args: args)
    class Reader:
        def __init__(self, **kwargs): pass
        def plan_stream(self, request): return SimpleNamespace(dependency_manifest=current)
    monkeypatch.setattr(persisted_subing, 'MarketDataHistoricalInputReader', Reader)
    args = dict(stream_id='saved', revision_id='revision', seq=3,
        through=date(2026, 10, 23), as_of=datetime(2026, 10, 23, 7, tzinfo=UTC))
    service.verify_source(**args)
    current['input_fingerprints'] = ['warmup-revised', 'visible-same']
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        service.verify_source(**args)
