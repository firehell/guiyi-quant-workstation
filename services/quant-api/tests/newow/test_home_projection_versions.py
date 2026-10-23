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
    monkeypatch.setattr(module, 'catalog_versions', lambda *_: calls.append(1) or {'rb:1d':'data'})
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
