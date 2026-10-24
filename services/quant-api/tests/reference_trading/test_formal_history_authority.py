"""Public history chooses one Canonical identity and never admits observed fallback."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import market_newow, market_subing_reference
from app.reference_trading.persisted_newow import PersistedNewowReference
from app.reference_trading.query import QueryConflict


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


def test_subing_rejects_prefix_revision_during_presentation_read(monkeypatch):
    from datetime import UTC, date, datetime
    from app.reference_trading import persisted_subing
    from app.market_data.subing_reference import SubingReferenceQuery
    now = datetime(2026, 10, 23, 7, tzinfo=UTC)
    day = date(2026, 10, 23)
    saved = dict(query_since='2025-01-01', reader='subing_reference',
        input_fingerprints=['warmup-old', 'visible-same'],
        calendar_session_effective_fingerprints=['sessions'])
    current = dict(saved)
    service = persisted_subing.PersistedSubingReference.__new__(persisted_subing.PersistedSubingReference)
    service._check_cancelled = lambda: None
    service._market = SimpleNamespace(resolve_read_window=lambda _: (day, day, now, now))
    service._stored_manifest = lambda **kwargs: (object(), saved)
    monkeypatch.setattr(persisted_subing, 'HistoricalStreamRequest', lambda *args: args)
    class Reader:
        def __init__(self, **kwargs): pass
        def plan_stream(self, request): return SimpleNamespace(dependency_manifest=current)
    monkeypatch.setattr(persisted_subing, 'MarketDataHistoricalInputReader', Reader)
    fields = ('closed_count', 'win_count', 'loss_count', 'flat_count', 'open_count',
        'interrupted_count', 'rollover_interrupted_count', 'data_interrupted_count',
        'initial_count', 'win_rate_pct', 'mean_return_pct', 'sum_return_percentage_points')
    def summary(*args, **kwargs):
        # Only the earlier warmup prefix changes; visible presentation remains equal.
        current['input_fingerprints'] = ['warmup-new', 'visible-same']
        return dict.fromkeys(fields, 0)
    service._query = SimpleNamespace(
        streams=lambda **kwargs: [dict(stream_id='saved', formula_versions=['subing-v1'], reference_model_version='v1')],
        trades=lambda *args, **kwargs: dict(snapshot='saved', revision_id='rev', seq=3, items=[], next_cursor=None),
        summary=summary,
        signals=lambda *args, **kwargs: dict(items=[], next_cursor=None),
    )
    with pytest.raises(QueryConflict, match='SOURCE_IDENTITY_UNVERIFIED'):
        service.query(SubingReferenceQuery('rb', day, day, now, None, 50, '15m'))
