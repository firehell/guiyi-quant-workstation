from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.market_data.market_phase import MarketPhase, ProductMarketPhase
import app.market_data.market_feed as feed


@pytest.mark.parametrize("defect", [None, "pending", "cursor", "cleanup", "next_session", "unknown"])
def test_closed_cleaned_requires_existing_cleanup_and_all_journal_fences(monkeypatch, defect):
    now = datetime(2026, 10, 13, 11, tzinfo=UTC)
    day = date(2026, 10, 13)
    class Redis:
        def scan_iter(self, *, match):
            if ':source:' in match:
                return ['live:observations:registered:source:live']
            return ['live:observations:registered:completed:alert', 'live:observations:registered:completed:reference']
    redis = Redis()
    class Journal:
        def __init__(self, _redis, *, kind):
            self.redis = _redis
            self.kind = kind
        def registered_day(self, _consumer):
            return day
        def cursor(self, _consumer, _day):
            return '1-0' if defect == 'cursor' else '2-0'
        def tail(self, _day):
            return '2-0'
    monkeypatch.setattr(feed, 'ObservationStream', Journal)
    service = SimpleNamespace(_products=('rb',), _pending={'pending': 1} if defect == 'pending' else {},
        _provider=None, _input_failure='OBSERVATION_COMMIT_UNKNOWN' if defect == 'unknown' else None,
        _halted=None, closed_cleanup_evidence=lambda *_: None if defect == 'cleanup' else {
            'trading_day': day.isoformat(), 'cleanup_verified': True, 'cleanup_checked_at': now.isoformat()})
    phases = {'rb': ProductMarketPhase('rb', MarketPhase.CLOSED, day, None,
        now if defect == 'next_session' else now + timedelta(hours=2))}
    proof = feed._closed_cleaned_idle_proof(service, Journal(redis, kind='source'), now, phases)
    if defect is None:
        assert proof['status'] == 'CLOSED_CLEANED'
        assert proof['consumer_count'] == 3
        assert proof['natural_bar_verified'] is False
    else:
        assert proof is None


def _passed_status(day, commit):
    from app.market_data.after_market import _evidence_hash
    started = day + 'T18:05:00+08:00'
    checked = day + 'T18:06:00+08:00'
    evidence = dict(trading_day=day, run_started_at=started, attempt=1,
        scope_sha256=_evidence_hash(['rb']), snapshot_sha256='a' * 64, formal_rank1_sha256='a' * 64,
        rank1_matches_snapshot=True, reconciled_at=checked, code_commit=commit, cleanup_verified=True,
        cleanup_checked_at=checked, remaining_bar_keys=0, subscription_present=False,
        canonical_live_exclusion='no_publication')
    return dict(schema_version=3, current_run=None, last_successful_trading_day=day, last_failure=None,
        last_run=dict(trading_day=day, status='passed', attempts=1, started_at=started,
            finished_at=day + 'T18:07:00+08:00', products=['rb'], error_code=None,
            historical_publications=[], live_evidence=evidence))


@pytest.mark.parametrize('mode', ['current', 'retained', 'commit_mismatch', 'other_day', 'readback_failed', 'current_negative'])
def test_cleanup_callback_binds_current_or_verified_retained_source(tmp_path, monkeypatch, mode):
    import json
    from app.market_data.after_market_history import NAME, make_history, publish_history
    import app.market_data.composition as composition
    day = date(2026, 10, 13)
    now = datetime(2026, 10, 13, 11, tzinfo=UTC)
    source_commit = 'a' * 40
    binding_commit = source_commit if mode in {'current', 'readback_failed'} else 'b' * 40
    binding = SimpleNamespace(root=str(tmp_path), commit=binding_commit, generation=19, enabled=True)
    monkeypatch.setattr('app.runtime_bindings.resolve_service_binding', lambda _service: binding)
    directory = tmp_path / '.run'
    directory.mkdir()
    status = _passed_status('2026-10-12' if mode == 'other_day' else day.isoformat(), source_commit)
    raw = json.dumps(status).encode()
    if mode in {'retained', 'other_day', 'current_negative'}:
        publish_history(directory / NAME, make_history(raw, commit=source_commit, products=('rb',), now=now))
    if mode not in {'retained', 'other_day'}:
        if mode == 'current_negative':
            status['last_run']['status'] = 'failed'
            status['last_run']['error_code'] = 'TEST_FAILURE'
        (directory / 'after-market-status.json').write_text(json.dumps(status))
    store = SimpleNamespace(cleanup_readback=lambda _day: dict(remaining_bar_keys=1 if mode == 'readback_failed' else 0,
                                                              subscription_present=False))
    result = composition.build_closed_cleanup_evidence(store, ('rb',))(day, now)
    if mode in {'current', 'retained'}:
        assert result['cleanup_verified'] is True
        assert result['evidence_kind'] == mode
        assert result['source_commit'] == source_commit
    else:
        assert result is None
