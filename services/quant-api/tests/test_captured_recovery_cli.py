import io
import json

import pytest

from app.guiyi_cli.main import main


def _args():
    return ['runtime', 'recover-live-captured', '--trading-day', '2026-09-08',
            '--symbol', 'rs', '--contract', 'RS2609', '--source', '/private/tmp/source.json',
            '--source-sha256', 'a' * 64]


def _run(args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdout=out, stderr=err, **kwargs)
    return code, json.loads(out.getvalue() or err.getvalue())


def test_captured_cli_defaults_to_readonly_and_never_builds_provider():
    calls = []
    def runner(args, *, session_factory):
        calls.append(args.apply)
        return {'status': 'planned', 'readonly': True, 'provider_requests': 0}
    code, payload = _run(_args(), captured_recovery_runner=runner)
    assert code == 0
    assert payload['readonly'] is True and payload['provider_requests'] == 0
    assert calls == [False]


@pytest.mark.parametrize('extra', [
    ['--apply'], ['--plan', '/private/tmp/p.json'],
    ['--apply', '--plan', '/private/tmp/p.json'],
    ['--apply', '--plan', '/private/tmp/p.json', '--plan-sha256', 'bad'],
])
def test_invalid_apply_arguments_are_rejected_before_dependency_access(extra):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid request reached execution')
    code, payload = _run(_args() + extra, captured_recovery_runner=forbidden,
                         session_factory=forbidden)
    assert code == 2
    assert payload['readonly'] is ('--apply' not in extra)


def test_captured_apply_passes_explicit_plan_and_reports_mutation_failure():
    def runner(args, *, session_factory):
        assert args.apply and args.plan_sha256 == 'b' * 64
        raise RuntimeError('password=must-not-leak')
    code, payload = _run(_args() + ['--apply', '--plan', '/private/tmp/p.json',
                                  '--plan-sha256', 'b' * 64], captured_recovery_runner=runner)
    assert code == 1 and payload['readonly'] is False
    assert 'must-not-leak' not in json.dumps(payload)


def test_source_hash_failure_precedes_database_or_runtime_access(tmp_path):
    from app.guiyi_cli.captured_recovery import run_captured_recovery
    from app.guiyi_cli.main import build_parser
    p = tmp_path / 'source.json'
    p.write_text('[]')
    args = build_parser().parse_args(_args())
    args.source = str(p)
    with pytest.raises(ValueError, match='CAPTURED_SOURCE_HASH_INVALID'):
        run_captured_recovery(args, session_factory=lambda: pytest.fail('opened DB'))


def test_bounded_reader_rejects_symlink_and_oversize(tmp_path):
    from app.guiyi_cli.captured_recovery import read_captured_file
    p = tmp_path / 'source.json'
    p.write_bytes(b'x' * 100)
    with pytest.raises(ValueError, match='CAPTURED_FILE_INVALID'):
        read_captured_file(p, max_bytes=99)
    link = tmp_path / 'link.json'
    link.symlink_to(p)
    with pytest.raises(ValueError, match='CAPTURED_FILE_INVALID'):
        read_captured_file(link)
    assert read_captured_file(p) == p.read_bytes()


def test_cli_roundtrip_plan_apply_noop_has_no_provider_or_database_writes(tmp_path, monkeypatch):
    from contextlib import nullcontext, contextmanager
    import hashlib
    from types import SimpleNamespace
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.guiyi_cli.captured_recovery import run_captured_recovery
    from app.guiyi_cli.main import build_parser
    from app.guiyi_cli.output import print_json
    from tests.data_foundation.test_captured_live_recovery import captured_setup

    redis, store, request, source, budget = captured_setup()
    source_path = tmp_path / 'source.json'
    source_path.write_bytes(source)
    args = build_parser().parse_args(_args())
    args.source = str(source_path)
    args.source_sha256 = hashlib.sha256(source).hexdigest()
    engine = create_engine('sqlite:///:memory:')
    monkeypatch.setattr('app.market_data.composition.build_market_read_service',
                        lambda session: SimpleNamespace(_live_store=store))
    monkeypatch.setattr('app.market_data.captured_recovery_runtime.verify_captured_recovery_runtime',
                        lambda **kw: 'verified-test-runtime')
    monkeypatch.setattr('app.guiyi_cli.captured_recovery.disable_captured_client_retry', lambda client: None)
    monkeypatch.setattr('app.guiyi_cli.captured_recovery._request', lambda *a: request)
    monkeypatch.setattr('app.guiyi_cli.captured_recovery._after_market_preflight', lambda *a: None)
    monkeypatch.setattr('app.market_data.rqdata_adapter.RQDataClient',
                        lambda: pytest.fail('provider created'))
    monkeypatch.setattr('app.market_data.live_recovery_guard.recovery_guard',
                        lambda *a: pytest.fail('dry-run created lock'))
    with Session(engine) as session:
        def runner():
            return run_captured_recovery(args, session_factory=lambda: nullcontext(session),
                                         clock=lambda: request.cutoff)
        payload = runner()
        assert session.scalar(text('PRAGMA query_only')) == 1
        out = io.StringIO()
        print_json(payload, out)
        plan_path = tmp_path / 'plan.json'
        plan_path.write_text(out.getvalue())
        args.apply, args.plan = True, str(plan_path)
        args.plan_sha256 = payload['plan']['plan_sha256']
        held = []
        @contextmanager
        def global_guard():
            held.append('after-market')
            try:
                yield
            finally:
                held.pop()
        @contextmanager
        def symbol_guard(*a):
            assert held == ['after-market']
            held.append('rs')
            try:
                yield
            finally:
                held.pop()
        original_eval = redis.eval
        def guarded_eval(*a):
            assert held == ['after-market', 'rs']
            return original_eval(*a)
        monkeypatch.setattr(redis, 'eval', guarded_eval)
        monkeypatch.setattr('app.market_data.live_recovery_guard.after_market_recovery_guard', global_guard, raising=False)
        monkeypatch.setattr('app.market_data.live_recovery_guard.recovery_guard', symbol_guard)
        result = runner()
        assert result['status'] == 'passed' and result['provider_requests'] == 0
        assert not result['runtime_ready'] and not result['notification_sent']
        assert runner()['status'] == 'noop'
        assert json.loads(redis.get(budget))['count'] == 3
        assert not session.new and not session.dirty and redis.published == []


@pytest.mark.parametrize('unsafe', ['running', 'same_day_attempt', 'invalid', 'missing'])
def test_after_market_rejects_unstable_or_changed_consumer(tmp_path, monkeypatch, unsafe):
    from datetime import date
    from app.guiyi_cli.captured_recovery import _after_market_preflight
    monkeypatch.setattr('app.guiyi_cli.captured_recovery.PROJECT_ROOT', tmp_path)
    directory = tmp_path / '.run'
    directory.mkdir()
    payload = {'schema_version': 2, 'current_run': None,
               'last_successful_trading_day': '2026-09-07'}
    if unsafe == 'running':
        payload['current_run'] = {'scheduled_date': '2026-09-08',
                                  'started_at': '2026-09-08T10:05:00Z', 'products': ['rs']}
    elif unsafe == 'same_day_attempt':
        payload['last_run'] = {'trading_day': '2026-09-08'}
    elif unsafe == 'invalid':
        payload = {'schema_version': 2}
    if unsafe != 'missing':
        (directory / 'after-market-status.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='CAPTURED_AFTER_MARKET_REVIEW_REQUIRED'):
        _after_market_preflight(date(2026, 9, 8))


@pytest.mark.parametrize('failure', [None, 'expired', 'wrong_contract', 'holiday', 'scope', 'session', 'day'])
def test_request_uses_authoritative_contract_calendar_session_and_subscription(monkeypatch, failure):
    from datetime import date, datetime, time, UTC, timedelta
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.models import Exchange, Instrument, TradingCalendar, TradingSession
    from app.models.market_tables import Contract
    from app.market_data.live_market import RedisLiveStore
    from tests.data_foundation.test_live_market import FakeRedis
    from app.guiyi_cli.captured_recovery import _request

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 8, 9, tzinfo=UTC)
    day = now.date()
    args = SimpleNamespace(trading_day=day, symbol='rs', contract='RS2609')
    monkeypatch.setattr('app.market_data.operational_universe.load_operational_products',
                        lambda: ('rs',) if failure != 'scope' else ('rb',))
    store = RedisLiveStore(FakeRedis())
    store.set_subscriptions(day, {'rs': 'RS2611' if failure == 'wrong_contract' else 'RS2609'})
    with Session(engine) as session:
        session.add_all([Exchange(code='CZCE', name='CZCE'),
                         Instrument(symbol='rs', name='RS', exchange_code='CZCE', is_active=True),
                         Contract(contract_code='RS2609', instrument_symbol='rs', exchange_code='CZCE',
                                  listed_date=date(2025, 9, 15), provider='rqdata',
                                  expired_date=date(2026, 9, 7) if failure == 'expired' else date(2026, 9, 14))])
        for n in range(-3, 4):
            session.add(TradingCalendar(exchange_code='CZCE', trade_date=day+timedelta(days=n),
                                        is_trading_day=not(n == 0 and failure == 'holiday'),
                                        has_night_session=False))
        if failure != 'session':
            for i, (start, end) in enumerate([(time(9),time(10,15)), (time(10,30),time(11,30)), (time(13,30),time(15))]):
                session.add(TradingSession(exchange_code='CZCE', instrument_symbol='rs',
                            session_name=f'day_{i}', start_time=start, end_time=end, crosses_midnight=False,
                            effective_from=date(2025,1,1), is_active=True))
        session.commit()
        if failure == 'day':
            now += timedelta(days=1)
        if failure:
            with pytest.raises(ValueError):
                _request(session, store, args, now)
        else:
            request = _request(session, store, args, now)
            assert len(request.endpoints()) == 225
            assert request.endpoints()[0].hour == 1 and request.endpoints()[0].minute == 1
            assert request.contract == 'RS2609' and request.snapshot == (('rs','RS2609'),)


def test_captured_client_sends_once_on_unknown_transport_outcome():
    from redis import Redis
    from redis.exceptions import ConnectionError
    from app.guiyi_cli.captured_recovery import disable_captured_client_retry
    client = Redis(host='127.0.0.1', port=1)
    disable_captured_client_retry(client)
    assert client.get_connection_kwargs()['socket_timeout'] == 5
    assert client.get_connection_kwargs()['socket_connect_timeout'] == 3
    attempts = []
    def operation():
        attempts.append(1)
        raise ConnectionError('unknown commit outcome')
    with pytest.raises(ConnectionError):
        client.get_retry().call_with_retry(operation, lambda error: None)
    assert attempts == [1]
