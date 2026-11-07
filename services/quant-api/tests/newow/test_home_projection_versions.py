from contextlib import nullcontext
from types import SimpleNamespace

from app.market_data.newow import home_projection_composition as module


def test_catalog_identity_changes_for_same_count_quality_map_session_and_formula(monkeypatch, tmp_path):
    directory = tmp_path / 'data/universe'
    directory.mkdir(parents=True)
    for filename in ('product_window_starts.csv','active_history_floor.txt','active_products.txt','operational_products.txt','retired_products.txt','product_sectors.csv'):
        (directory / filename).write_text('rb,2020-01-01')
    monkeypatch.setattr(module, 'PROJECT_ROOT', tmp_path)
    values = {}
    def rows(_session, table, owner, **kwargs):
        symbols = ('SHFE',) if table.name in {'exchanges', 'trading_calendars'} else ('rb',)
        keys = [(symbol, frequency) for symbol in symbols for frequency in ('1d','1w')] if kwargs.get('extra') else [(symbol,) for symbol in symbols]
        return {key: values.get((table.name, key), 'original') for key in keys}
    monkeypatch.setattr(module, '_digest_rows', rows)
    session = SimpleNamespace(execute=lambda _: [SimpleNamespace(symbol='rb',exchange_code='SHFE')])
    initial = module.catalog_versions(session, ('rb',))
    for table, key in [('market_partitions',('rb','1d')),('main_contract_map',('rb',)),('trading_sessions',('rb',)),('trading_calendars',('SHFE',))]:
        values[(table,key)] = 'same-count-edited-content'
        assert module.catalog_versions(session, ('rb',)) != initial
        values.clear()
    for filename in ('product_sectors.csv', 'active_products.txt', 'active_history_floor.txt'):
        path = directory / filename
        original = path.read_text()
        path.write_text('changed')
        assert module.catalog_versions(session, ('rb',)) != initial
        path.write_text(original)
    monkeypatch.setattr(module, 'HOME_TREND_VERSION', 'changed')
    assert module.catalog_versions(session, ('rb',)) != initial
    monkeypatch.setattr(module, 'HOME_TREND_VERSION', 'guiyi_home_close_ma60_v1')
    monkeypatch.setattr(module, 'METRIC_POLICY_VERSION', 'changed')
    assert module.catalog_versions(session, ('rb',)) != initial
    monkeypatch.setattr(module, 'CAPABILITY_SCHEMA_VERSION', 'changed')
    assert module.catalog_versions(session, ('rb',)) != initial


def test_revision_cache_requires_exact_mvcc_visibility_and_rechecks_target(monkeypatch, tmp_path):
    from datetime import date
    directory = tmp_path / 'data/universe'
    directory.mkdir(parents=True)
    for filename in ('product_window_starts.csv','active_history_floor.txt','active_products.txt','operational_products.txt','retired_products.txt','product_sectors.csv'):
        (directory / filename).write_text('rb,2020-01-01')
    monkeypatch.setattr(module, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(module, '_VERSION_CACHE', None)
    snapshot = ['100:200:150']
    target = [date(2026,10,23)]
    session = SimpleNamespace(scalar=lambda _: snapshot[0], get_bind=lambda: SimpleNamespace(url=SimpleNamespace(render_as_string=lambda **_: 'test-db')))
    monkeypatch.setattr(module, 'SessionLocal', lambda: nullcontext(session))
    monkeypatch.setattr(module, 'readonly_transaction', lambda *_, **__: nullcontext())
    from datetime import UTC, datetime
    monkeypatch.setattr(module, 'build_database_coverage_source', lambda _: SimpleNamespace(latest_complete_day_with_refresh_at=lambda _, **__: (target[0], datetime(2026,10,24,tzinfo=UTC))))
    calls = []
    monkeypatch.setattr(module, 'catalog_versions', lambda *_, **__: calls.append(1) or {'rb:1d':'data'})
    instant = datetime(2026,10,23,8,tzinfo=UTC)
    first = module.current_versions(('rb',), now=instant)
    assert module.current_versions(('rb',), now=instant) == first and len(calls) == 1
    (directory / 'product_sectors.csv').write_text('changed')
    assert module.current_versions(('rb',), now=instant) != first and len(calls) == 2
    # Same xmax but a writer committing changes the in-progress set, hence visibility.
    snapshot[0] = '100:200:'
    module.current_versions(('rb',), now=instant)
    assert len(calls) == 3
    target[0] = date(2026,10,24)
    assert module.current_versions(('rb',), now=datetime(2026,10,24,tzinfo=UTC)) != first and len(calls) == 4


def test_catalog_version_query_fingerprints_every_tuple_and_uses_bound_scope():
    from sqlalchemy.dialects import postgresql
    from app.models import MarketPartition
    captured = []
    session = SimpleNamespace(execute=lambda statement: captured.append(statement) or [])
    table = MarketPartition.__table__
    module._digest_rows(session, table, table.c.dataset_id, filters=(table.c.dataset_id.in_([42]),))
    sql = str(captured[0].compile(dialect=postgresql.dialect()))
    assert 'market_partitions.xmin' in sql and 'market_partitions.ctid' in sql
    assert 'ORDER BY market_partitions.id' in sql and 'row_to_json' not in sql
    assert '42' not in sql  # Scope values remain bound parameters.


def test_completed_day_reuse_expires_at_authoritative_session_end():
    from datetime import datetime, date
    from zoneinfo import ZoneInfo
    from app.market_data.coverage_source import DatabaseCoverageSource
    zone = ZoneInfo('Asia/Shanghai')
    now = [datetime(2026,10,23,14,59,59,tzinfo=zone)]
    close = datetime(2026,10,23,15,0,tzinfo=zone)
    source = object.__new__(DatabaseCoverageSource)
    source._now = lambda: now[0]
    source.session = SimpleNamespace(scalar=lambda _: date(2026,10,23))
    source._exchange = lambda _: 'SHFE'
    source._previous_trading_day = lambda *_: date(2026,10,22)
    source._sessions_for_day = lambda *_: (SimpleNamespace(end=close),)
    day, refresh = source.latest_complete_day_with_refresh_at(('rb',))
    assert day == date(2026,10,22) and refresh == close
    now[0] = close
    assert source.latest_complete_day(('rb',)) == date(2026,10,23)


def test_completed_day_reads_shared_exchange_calendar_once_per_call():
    from datetime import date, datetime, UTC
    from app.market_data.coverage_source import DatabaseCoverageSource
    source = object.__new__(DatabaseCoverageSource)
    calls = []
    source.session = SimpleNamespace(scalar=lambda query: calls.append(query) or date(2026,10,22))
    source._now = lambda: datetime(2026,10,23,tzinfo=UTC)
    source._exchange = lambda _: 'SHFE'
    assert source.latest_complete_day(('rb', 'ag')) == date(2026,10,22)
    assert len(calls) == 1
    source.latest_complete_day(('rb', 'ag'))
    assert len(calls) == 2  # No reuse beyond this authority evaluation.


def test_source_scope_includes_week_calendar_and_all_history_for_warmup():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    scope = module.home_source_scope(datetime(2026, 11, 6, 18, tzinfo=ZoneInfo('Asia/Shanghai')))
    assert scope['version'] == 'home_source_identity_v2'
    assert scope['history_start'] is None
    assert scope['mapping_through'] == scope['session_effective_from_through'] == '2026-11-06'
    assert scope['calendar_through'] == '2026-11-08'
    assert scope['publication_from'] == '2026-06-22'


def test_publication_identity_tracks_authority_not_heartbeat_and_1805_boundary():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.market_data.newow.product_release import CANDIDATE_WEEKLY_PRODUCTS
    product = next(iter(CANDIDATE_WEEKLY_PRODUCTS))
    zone = ZoneInfo('Asia/Shanghai')
    before = datetime(2026, 11, 6, 18, 4, tzinfo=zone)
    after = datetime(2026, 11, 6, 18, 5, tzinfo=zone)
    status = {'last_run': {'trading_day': '2026-11-05', 'products': [product], 'status': 'passed'}}
    first = module.publication_selection_identity((product,), before, status)
    assert first == module.publication_selection_identity((product,), before, {**status, 'heartbeat': 'changed'})
    assert first != module.publication_selection_identity((product,), after, status)
    current = {'current_run': {'scheduled_date': '2026-11-06', 'products': [product]}}
    assert module.publication_selection_identity((product,), after, current) != module.publication_selection_identity((product,), after, {})
    next_day = datetime(2026, 11, 7, tzinfo=zone)
    states = dict(module.publication_selection_identity((product,), next_day, current)[product])
    assert states['2026-11-06'] == 'stale'


def test_catalog_future_preparation_stable_but_historical_and_missing_candidates_invalidate(monkeypatch):
    # Real SQL predicates over SQLite; only PostgreSQL tuple-version hashing is
    # replaced with whole-row hashing, so inserts/deletes/equal-count edits work.
    from datetime import datetime, date, time
    from zoneinfo import ZoneInfo
    from hashlib import sha256
    import json
    from sqlalchemy import create_engine, select, insert, update
    from sqlalchemy.orm import Session
    models = (module.Exchange, module.Instrument, module.Contract, module.TradingCalendar,
              module.TradingSession, module.MainContractMap, module.MarketDataset, module.MarketPartition)
    engine = create_engine('sqlite://')
    for model in models:
        model.__table__.create(engine)
    def digest(session, table, owner, *, filters=(), joins=None, extra=()):
        rows = session.execute(select(owner, *extra, *table.c).select_from(joins if joins is not None else table).where(*filters).order_by(table.c.id)).all()
        grouped = {}
        for row in rows:
            grouped.setdefault(tuple(row[:1 + len(extra)]), []).append(tuple(row[1 + len(extra):]))
        return {key: sha256(json.dumps(value, default=str).encode()).hexdigest() for key, value in grouped.items()}
    monkeypatch.setattr(module, '_digest_rows', digest)
    monkeypatch.setattr(module, 'configuration_identity', lambda: 'fixed-config')
    monkeypatch.setattr(module, '_publication_status', lambda: {})
    now = datetime(2026, 11, 6, 18, tzinfo=ZoneInfo('Asia/Shanghai'))
    with Session(engine) as session:
        session.execute(insert(module.Exchange).values(code='SHFE', name='exchange'))
        session.execute(insert(module.Instrument).values(symbol='rb', name='rebar', exchange_code='SHFE'))
        session.execute(insert(module.MainContractMap).values(symbol='rb', trade_date=date(2026, 11, 5), contract_code='rb2701'))
        session.execute(insert(module.TradingSession).values(exchange_code='SHFE', instrument_symbol='rb', session_name='day', start_time=time(9), end_time=time(15), effective_from=date(2020, 1, 1)))
        session.execute(insert(module.TradingCalendar).values(exchange_code='SHFE', trade_date=date(2026, 11, 6), is_trading_day=True))
        def version():
            return module.catalog_versions(session, ('rb',), now=now)
        baseline = version()
        session.execute(insert(module.MainContractMap).values(symbol='rb', trade_date=date(2026, 11, 9), contract_code='rb2705'))
        session.execute(insert(module.TradingSession).values(exchange_code='SHFE', instrument_symbol='rb', session_name='day', start_time=time(9), end_time=time(15), effective_from=date(2026, 11, 10)))
        assert version() == baseline
        for weekend_day in (7, 8):
            assert module.catalog_versions(session, ('rb',), now=now.replace(day=weekend_day)) == baseline
        session.execute(update(module.MainContractMap).where(module.MainContractMap.trade_date == date(2026, 11, 5)).values(contract_code='rb2612'))
        assert version() != baseline
        baseline = version()
        session.execute(update(module.TradingSession).where(module.TradingSession.effective_from == date(2020, 1, 1)).values(end_time=time(14)))
        assert version() != baseline
        baseline = version()
        # A newest candidate initially missing its owner must invalidate when
        # filled, even though a previous snapshot could use Nov5 history.
        session.execute(insert(module.MainContractMap).values(symbol='rb', trade_date=date(2026, 11, 6), contract_code='rb2701'))
        assert version() != baseline
        baseline = version()
        # Missing physical input becoming available is also a selection
        # dependency, independent of whether any previously consumed row changed.
        dataset_id = session.execute(insert(module.MarketDataset).values(kind='contract', symbol='rb', series_or_contract='rb2701', frequency='1d').returning(module.MarketDataset.id)).scalar_one()
        assert version() != baseline
        baseline = version()
        session.execute(insert(module.MarketPartition).values(dataset_id=dataset_id, year=2026, month=11, file_uri='unread.parquet', row_count=1))
        assert version() != baseline
        baseline = version()
        session.execute(update(module.MarketPartition).values(source_quality=[{'status': 'changed'}], source_quality_sha256='a' * 64))
        assert version() != baseline
        baseline = version()
        # Calendar's future Sunday still participates in ISO-week selection.
        session.execute(insert(module.TradingCalendar).values(exchange_code='SHFE', trade_date=date(2026, 11, 8), is_trading_day=False))
        assert version() != baseline


def test_revision_cache_observes_normalized_publication_without_mvcc_change(monkeypatch):
    from datetime import datetime, date, timedelta
    from zoneinfo import ZoneInfo
    from app.market_data.newow.product_release import CANDIDATE_WEEKLY_PRODUCTS
    product = next(iter(CANDIDATE_WEEKLY_PRODUCTS))
    zone = ZoneInfo('Asia/Shanghai')
    instant = datetime(2026, 11, 6, 18, 4, tzinfo=zone)
    status = {'last_run': {'trading_day': '2026-11-05', 'products': [product], 'status': 'passed'}}
    session = SimpleNamespace(scalar=lambda _: 'same-mvcc', get_bind=lambda: SimpleNamespace(url=SimpleNamespace(render_as_string=lambda **_: 'test-db')))
    monkeypatch.setattr(module, 'SessionLocal', lambda: nullcontext(session))
    monkeypatch.setattr(module, 'readonly_transaction', lambda *_, **__: nullcontext())
    monkeypatch.setattr(module, '_VERSION_CACHE', None)
    monkeypatch.setattr(module, '_publication_status', lambda: status)
    monkeypatch.setattr(module, 'configuration_identity', lambda: 'config')
    monkeypatch.setattr(module, 'build_database_coverage_source', lambda _: SimpleNamespace(latest_complete_day_with_refresh_at=lambda _, **__: (date(2026, 11, 6), instant + timedelta(days=1))))
    calls = []
    def versions(*_, publication, **__):
        calls.append(1)
        return {f'{product}:1w': str(publication)}
    monkeypatch.setattr(module, 'catalog_versions', versions)
    first = module.current_versions((product,), now=instant)
    status['heartbeat'] = 'unrelated'
    assert module.current_versions((product,), now=instant) == first
    assert len(calls) == 1
    after = module.current_versions((product,), now=instant + timedelta(minutes=1))
    assert after != first and len(calls) == 2
    status['current_run'] = {'scheduled_date': '2026-11-06', 'products': [product]}
    assert module.current_versions((product,), now=instant + timedelta(minutes=1)) != after
    assert len(calls) == 3


def test_weekend_empty_scope_expansion_does_not_change_catalog_identity(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Asia/Shanghai')
    monkeypatch.setattr(module, 'configuration_identity', lambda: 'fixed-config')
    monkeypatch.setattr(module, '_publication_status', lambda: {})
    monkeypatch.setattr(module, '_digest_rows', lambda *_, **__: {})
    session = SimpleNamespace(execute=lambda _: [SimpleNamespace(symbol='rb', exchange_code='SHFE')])
    friday = module.catalog_versions(session, ('rb',), now=datetime(2026, 11, 6, 19, tzinfo=zone))
    for day in (7, 8):
        assert module.catalog_versions(session, ('rb',), now=datetime(2026, 11, day, 19, tzinfo=zone)) == friday


def test_weekend_irrelevant_publication_candidates_do_not_change_identity():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.market_data.newow.product_release import CANDIDATE_WEEKLY_PRODUCTS
    product = next(iter(CANDIDATE_WEEKLY_PRODUCTS))
    zone = ZoneInfo('Asia/Shanghai')
    status = {'last_run': {'trading_day': '2026-11-06', 'products': [product], 'status': 'passed'}}
    friday = module.publication_selection_identity((product,), datetime(2026, 11, 6, 19, tzinfo=zone), status)
    for day in (7, 8):
        assert module.publication_selection_identity((product,), datetime(2026, 11, day, 19, tzinfo=zone), status) == friday


def test_weekend_clock_rechecks_catalog_without_invalidating_same_completed_target(monkeypatch):
    from datetime import datetime, date, timedelta
    from zoneinfo import ZoneInfo
    zone = ZoneInfo('Asia/Shanghai')
    session = SimpleNamespace(scalar=lambda _: 'same-mvcc', get_bind=lambda: SimpleNamespace(url=SimpleNamespace(render_as_string=lambda **_: 'test-db')), execute=lambda _: [SimpleNamespace(symbol='rb', exchange_code='SHFE')])
    monkeypatch.setattr(module, 'SessionLocal', lambda: nullcontext(session))
    monkeypatch.setattr(module, 'readonly_transaction', lambda *_, **__: nullcontext())
    monkeypatch.setattr(module, '_VERSION_CACHE', None)
    monkeypatch.setattr(module, '_publication_status', lambda: {})
    monkeypatch.setattr(module, 'configuration_identity', lambda: 'fixed')
    monkeypatch.setattr(module, '_digest_rows', lambda *_, **__: {})
    calls = []
    def target(_, *, now):
        calls.append(now)
        return date(2026, 11, 6), now + timedelta(days=1)
    monkeypatch.setattr(module, 'build_database_coverage_source', lambda _: SimpleNamespace(latest_complete_day_with_refresh_at=target))
    friday = datetime(2026, 11, 6, 19, tzinfo=zone)
    first = module.current_versions(('rb',), now=friday)
    for day in (7, 8):
        assert module.current_versions(('rb',), now=friday.replace(day=day)) == first
    assert len(calls) == 3  # Scope/clock still expires memoized authority checks.
