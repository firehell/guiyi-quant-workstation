from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.historical_data_manager import ContractWarmupRequest
from app.market_data.session_repair import ContractSessionRepairRequest
from app.market_data.storage import PublishRequest, StorageError
from test_historical_data_manager import FakeCoverage, FakeProvider, _manager, session  # noqa: F401

DAY = date(2025, 1, 6)
START = datetime(2025, 1, 3, 13, tzinfo=UTC)
END = START + timedelta(hours=2)
NOW = datetime(2025, 1, 4, tzinfo=UTC)
KEY = DatasetKey('contract', 'jm', 'JM2509', '1m')
H1 = DatasetKey('contract', 'jm', 'JM2509', '60m')


class Coverage(FakeCoverage):
    def contract_session_windows(self, key, day):
        assert key == KEY and day == DAY
        return (SessionWindow(START, END), SessionWindow(datetime(2025, 1, 6, 1, tzinfo=UTC), datetime(2025, 1, 6, 3, tzinfo=UTC)))

    def expected_bar_ends_for_trading_days(self, key, days):
        assert days == (DAY,)
        return self.ends[key.as_tuple()]

    def contract_trading_days(self, fact, start, end):
        return (DAY,)


def bar(at, day=DAY):
    return CanonicalBar(at, day, Decimal(100), Decimal(101), Decimal(99), Decimal(100), Decimal(1), Decimal(100), Decimal(10))


@pytest.fixture
def setup(session, tmp_path):  # noqa: F811
    ends = tuple(START + timedelta(minutes=i) for i in range(1, 121))
    coverage = Coverage({KEY.as_tuple(): ends})
    provider = FakeProvider({KEY.as_tuple(): tuple(bar(t) for t in ends)})
    manager = _manager(session, tmp_path, coverage, provider)
    return manager, provider


def request(**kwargs):
    return ContractSessionRepairRequest('jm', 'JM2509', DAY, END, **kwargs)


def apply(manager, req=None):
    req = req or request()
    plan = manager.contract_session_repair(req, now=NOW)
    return manager.contract_session_repair(replace(req, apply=True, expected_plan_sha256=plan['plan_sha256']), now=NOW)


def test_weekend_plan_and_apply_are_bounded_and_idempotent(setup):
    manager, provider = setup
    plan = manager.contract_session_repair(request(), now=NOW)
    assert plan['status'] == 'planned' and provider.calls == []
    assert plan['missing_1m'] == 120 and plan['missing_60m'] == 2
    result = apply(manager)
    assert result['status'] == 'passed' and result['applied'] == 2
    assert len(provider.calls) == 1
    rows = manager.store.read_catalog_partition(manager.catalog.all_partitions(KEY)[0])
    assert len(rows) == 120 and {b.trading_day for b in rows} == {DAY}
    assert apply(manager)['applied'] == 0 and len(provider.calls) == 1
    with pytest.raises(ValueError, match='CONTRACT_WARMUP_THROUGH_INCOMPLETE'):
        manager.contract_warmup(ContractWarmupRequest('jm', 'JM2509', DAY))


@pytest.mark.parametrize('end,now', [(END, START), (END - timedelta(minutes=1), NOW), (datetime(2025, 1, 6, 3, tzinfo=UTC), datetime(2025, 1, 7, tzinfo=UTC)), (END.replace(tzinfo=None), NOW)])
def test_reject_future_partial_daytime_and_naive(setup, end, now):
    manager, provider = setup
    with pytest.raises(ValueError):
        manager.contract_session_repair(replace(request(), session_end=end), now=now)
    assert provider.calls == [] and manager.catalog.all_partitions(KEY) == ()


def test_keep_other_month_bars_and_old_files(setup):
    manager, _ = setup
    old = bar(datetime(2025, 1, 2, 1, tzinfo=UTC), date(2025, 1, 2))
    old_part = manager.store.publish(PublishRequest(KEY, 2025, 1, (old,), (old.bar_end,)))
    manager.catalog.register_partition(old_part)
    manager.catalog.session.commit()
    old_bytes = old_part.parquet_path.read_bytes()
    assert apply(manager)['status'] == 'passed'
    rows = manager.store.read_catalog_partition(manager.catalog.all_partitions(KEY)[0])
    assert rows[0] == old and len(rows) == 121
    assert old_part.parquet_path.read_bytes() == old_bytes


def test_hash_drift_fails_before_provider(setup):
    manager, provider = setup
    with pytest.raises(ValueError, match='SESSION_REPAIR_PLAN_CHANGED'):
        manager.contract_session_repair(request(apply=True, expected_plan_sha256='a'*64), now=NOW)
    assert provider.calls == []


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'wrong_day', 'bad_ohlc'])
def test_source_errors_never_publish(setup, fault):
    manager, provider = setup
    rows = provider.bars[KEY.as_tuple()]
    if fault == 'missing':
        rows = rows[:-1]
    if fault == 'duplicate':
        rows = (*rows, rows[0])
    if fault == 'wrong_day':
        rows = (replace(rows[0], trading_day=date(2025, 1, 3)), *rows[1:])
    if fault == 'bad_ohlc':
        bad = replace(rows[0])
        object.__setattr__(bad, 'close', Decimal(500))
        rows = (bad, *rows[1:])
    provider.bars[KEY.as_tuple()] = rows
    assert apply(manager)['status'] == 'failed'
    assert manager.catalog.all_partitions(KEY) == ()


def test_h1_conflict_blocks_before_provider(setup):
    manager, provider = setup
    wrong = replace(bar(START + timedelta(hours=1)), close=Decimal('100.5'))
    part = manager.store.publish(PublishRequest(H1, 2025, 1, (wrong,), (wrong.bar_end,)))
    manager.catalog.register_partition(part)
    manager.catalog.session.commit()
    # Complete M1 is already canonical: source may not be overwritten to fit H1.
    rows = provider.bars[KEY.as_tuple()]
    manager.catalog.register_partition(manager.store.publish(PublishRequest(KEY, 2025, 1, rows, tuple(b.bar_end for b in rows))))
    manager.catalog.session.commit()
    assert apply(manager)['status'] == 'failed'
    assert provider.calls == []


def test_derived_failure_keeps_committed_m1_and_reports_partial(setup, monkeypatch):
    manager, _ = setup
    commit = manager._commit_partition
    def fail(partition, target):
        if target.key == H1:
            raise StorageError('TEST_DERIVED_FAILED')
        return commit(partition, target)
    monkeypatch.setattr(manager, '_commit_partition', fail)
    result = apply(manager)
    assert result['status'] == 'partial' and result['applied'] == 1
    assert len(manager.catalog.all_partitions(KEY)) == 1
    assert manager.catalog.all_partitions(H1) == ()


def test_cli_exact_arguments_and_hash_gate():
    from app.guiyi_cli.main import build_parser, CliUsageError
    from app.guiyi_cli.data_commands import build_request
    parser = build_parser()
    args = ['data', 'contract-session-repair', '--symbol', 'jm', '--contract', 'JM2509', '--trading-day', '2025-01-06', '--session-end', END.isoformat()]
    assert build_request(parser.parse_args(args)) == request()
    with pytest.raises(CliUsageError):
        parser.parse_args([*args, '--apply'])
    assert build_request(parser.parse_args([*args, '--apply', '--expected-plan-sha256', 'a'*64])).apply


def test_metadata_drift_after_plan_stops_before_fetch(setup, monkeypatch):
    manager, provider = setup
    plan = manager.contract_session_repair(request(), now=NOW)
    original = manager.coverage.contract_session_windows
    monkeypatch.setattr(manager.coverage, 'contract_session_windows', lambda key, day: (SessionWindow(START + timedelta(minutes=1), END), *original(key, day)[1:]))
    with pytest.raises(ValueError, match='SESSION_REPAIR_PLAN_CHANGED'):
        manager.contract_session_repair(request(apply=True, expected_plan_sha256=plan['plan_sha256']), now=NOW)
    assert provider.calls == []


def test_commit_unknown_is_propagated_without_retry(setup, monkeypatch):
    manager, provider = setup
    def unknown(*args): raise StorageError('COMMIT_OUTCOME_UNKNOWN')
    monkeypatch.setattr(manager, '_commit_partition', unknown)
    with pytest.raises(StorageError, match='COMMIT_OUTCOME_UNKNOWN'):
        apply(manager)
    assert len(provider.calls) == 1 and manager.catalog.all_partitions(H1) == ()


def test_missing_calendar_session_and_lifecycle_fail_closed(setup, monkeypatch):
    manager, provider = setup
    monkeypatch.setattr(manager.coverage, 'contract_trading_days', lambda *args: ())
    with pytest.raises(ValueError, match='SESSION_REPAIR_TRADING_DAY_INVALID'):
        manager.contract_session_repair(request(), now=NOW)
    assert provider.calls == []


def test_existing_m1_value_conflict_never_overwritten(setup):
    manager, provider = setup
    first = replace(provider.bars[KEY.as_tuple()][0], close=Decimal('100.5'))
    manager.catalog.register_partition(manager.store.publish(PublishRequest(KEY, 2025, 1, (first,), (first.bar_end,))))
    manager.catalog.session.commit()
    assert apply(manager)['reason_code'] == 'SESSION_REPAIR_EXISTING_VALUE_CONFLICT'
    assert manager.store.read_catalog_partition(manager.catalog.all_partitions(KEY)[0]) == (first,)


def test_database_authority_preserves_friday_to_monday(session, tmp_path):  # noqa: F811
    from datetime import time
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.models import TradingCalendar, TradingSession
    for day in (date(2025, 1, 2), date(2025, 1, 3), DAY):
        session.add(TradingCalendar(exchange_code='DCE', trade_date=day, is_trading_day=True, has_night_session=True))
    for name, start, end in (('night', time(21), time(23)), ('day', time(9), time(11))):
        session.add(TradingSession(exchange_code='DCE', instrument_symbol='jm', session_name=name, start_time=start, end_time=end, effective_from=DAY, effective_to=DAY, crosses_midnight=False, is_active=True))
    session.add(TradingSession(exchange_code='DCE', instrument_symbol='jm', session_name='day', start_time=time(9), end_time=time(11), effective_from=date(2025,1,3), effective_to=date(2025,1,3), crosses_midnight=False, is_active=True))
    session.commit()
    starts = tmp_path/'starts.csv'
    starts.write_text('product,window_start,note\njm,2025-01-03,test\n')
    floor = tmp_path/'floor.txt'
    floor.write_text('2025-01-03\n')
    coverage = DatabaseCoverageSource(session, starts, history_floor_path=floor, now=lambda: NOW)
    assert coverage.contract_session_windows(KEY, DAY)[0] == SessionWindow(START, END)
    assert coverage.trading_days_for_bar_ends(KEY, (START + timedelta(minutes=1), END)) == (DAY, DAY)


def test_post_commit_observer_failure_escapes_without_false_zero_commit(setup):
    from app.market_data.historical_data_manager import _ObserverFailure
    manager, provider = setup
    def fail(_evidence):
        raise OSError('test evidence persistence failed')
    manager._publication_observer = fail
    with pytest.raises(_ObserverFailure, match='MAINTENANCE_OBSERVER_FAILED'):
        apply(manager)
    assert len(provider.calls) == 1
    assert len(manager.catalog.all_partitions(KEY)) == 1
    assert manager.catalog.all_partitions(H1) == ()
    assert len(manager.publication_evidence) == 1


def test_h1_provenance_binds_actual_minute_input_not_aggregate(setup):
    from app.market_data.session_repair import _hash
    from app.market_data.aggregation import aggregate_from_1m
    manager, provider = setup
    source = provider.bars[KEY.as_tuple()]
    result = apply(manager)
    provenance = manager.store.read_publication_provenance(manager.catalog.all_partitions(H1)[0])
    assert provenance['input_sha256'] == _hash({'plan_sha256': result['plan_sha256'], 'bars': [b.as_record() for b in source]})
    changed = (source[0], replace(source[1], close=Decimal('100.5')), *source[2:])
    sessions = (SessionWindow(START, END),)
    assert aggregate_from_1m(source, target_frequency='60m', sessions=sessions) == aggregate_from_1m(changed, target_frequency='60m', sessions=sessions)
    assert provenance['input_sha256'] != _hash({'plan_sha256': result['plan_sha256'], 'bars': [b.as_record() for b in changed]})


def test_maintenance_busy_never_calls_provider(setup, monkeypatch):
    manager, provider = setup
    plan = manager.contract_session_repair(request(), now=NOW)
    monkeypatch.setattr(manager.catalog, 'acquire_maintenance_lock', lambda: None)
    result = manager.contract_session_repair(request(apply=True, expected_plan_sha256=plan['plan_sha256']), now=NOW)
    assert result['status'] == 'blocked' and provider.calls == []


def test_new_plan_after_proven_derived_failure_reuses_committed_m1(setup, monkeypatch):
    manager, provider = setup
    commit = manager._commit_partition
    def fail(partition, target):
        if target.key == H1:
            raise StorageError('TEST_DERIVED_FAILED')
        return commit(partition, target)
    monkeypatch.setattr(manager, '_commit_partition', fail)
    first = apply(manager)
    assert first['status'] == 'partial'
    monkeypatch.setattr(manager, '_commit_partition', commit)
    result = apply(manager)
    assert result['status'] == 'passed' and result['applied'] == 1
    assert result['missing_1m'] == 0 and len(provider.calls) == 1


def test_later_native_full_day_update_keeps_repaired_night(setup, monkeypatch):
    from app.market_data.aggregation import expected_intraday_ends
    from app.market_data.historical_data_manager import _Target
    manager, provider = setup
    assert apply(manager)['status'] == 'passed'
    old_m1 = manager.store.read_catalog_partition(manager.catalog.all_partitions(KEY)[0])
    old_h1 = manager.store.read_catalog_partition(manager.catalog.all_partitions(H1)[0])
    daytime = SessionWindow(datetime(2025, 1, 6, 1, tzinfo=UTC), datetime(2025, 1, 6, 3, tzinfo=UTC))
    sessions = (SessionWindow(START, END), daytime)
    full_ends = expected_intraday_ends(sessions, '1m')
    day_ends = expected_intraday_ends((daytime,), '1m')
    provider.bars[KEY.as_tuple()] = (*old_m1, *(bar(t) for t in day_ends))
    manager.coverage.ends[KEY.as_tuple()] = full_ends
    monkeypatch.setattr(manager.coverage, 'sessions', lambda *args, **kwargs: sessions)
    h1_ends = expected_intraday_ends(sessions, '60m')
    result = manager._execute_apply('update',
        (_Target(KEY, 2025, 1, full_ends, day_ends, old_m1),),
        (_Target(H1, 2025, 1, h1_ends, tuple(t for t in h1_ends if t > END), old_h1),),
        DAY, weekly_daily_companions=False)
    assert result.status == 'passed'
    assert manager.store.read_catalog_partition(manager.catalog.all_partitions(KEY)[0])[:len(old_m1)] == old_m1
    assert manager.store.read_catalog_partition(manager.catalog.all_partitions(H1)[0])[:len(old_h1)] == old_h1


def test_cli_end_to_end_plan_uses_native_manager(setup):
    import io
    import json
    from app.guiyi_cli.main import main
    from test_cli import _NullContext
    manager, provider = setup
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(['data','contract-session-repair','--symbol','jm','--contract','JM2509','--trading-day',str(DAY),'--session-end',END.isoformat()],
                manager_factory=lambda _db: manager, session_factory=lambda: _NullContext(), stdout=stdout, stderr=stderr)
    assert code == 0 and not stderr.getvalue()
    payload = json.loads(stdout.getvalue())
    assert payload['command'] == 'data.contract-session-repair' and payload['missing_1m'] == 120
    assert payload['provider_requests'] == 0 and provider.calls == []
