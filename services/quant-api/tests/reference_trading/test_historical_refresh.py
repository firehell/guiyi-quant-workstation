from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from threading import Event

import pytest
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401

from app.reference_trading.planning import (
    HistoricalReferencePlan, HistoricalStreamPlan, canonical_sha256,
)
from app.reference_trading.service import ResumeToken
from scripts.reference_trading_p9_manifest import _newow
from guiyi_quant.newow.product_contracts import ProductStrategy

from app.reference_trading.historical_refresh import (
    HistoricalRefresh, RefreshRoute, RefreshStateStore, RefreshThread,
)

END = datetime(2026, 10, 8, 7, tzinfo=UTC)


def route(strategy='trend', watermark=None):
    identity = _newow('rb', ProductStrategy(strategy), '1d', forward=False)
    return RefreshRoute(identity, date(2023, 1, 1), watermark or END - timedelta(days=1))


class Planner:
    def __init__(self):
        self.requests = []
        self.source = 'same-source'

    def plan(self, request):
        self.requests.append(request)
        manifest = {'query_since': '2023-01-01', 'proof': self.source}
        digest = canonical_sha256(manifest)
        item = HistoricalStreamPlan(request.streams[0], request.streams[0].since,
                                    END, 1, 10, manifest, digest, digest, self.source)
        plan = HistoricalReferencePlan('historical_reference_plan_v1', request.operation,
                                       (item,), request.budget, 256, '')
        return replace(plan, plan_hash=canonical_sha256(plan))


class Service:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def invoke(self, operation, plan, token=None):
        self.calls.append((operation, plan, token))
        status, reason, resume = next(self.results)
        if resume:
            resume = ResumeToken(plan.plan_hash, plan.streams[0].request.identity.stream_id,
                                 'revision', 1, plan.streams[0].source_token, 'batch')
        return SimpleNamespace(streams=(SimpleNamespace(status=status, reason=reason,
                                                       completed_bars=0, last_batch_key=None,
                                                       resume_token=resume or None),))

    def advance(self, plan, expected):
        assert expected == plan.plan_hash
        return self.invoke('advance', plan)

    def rebuild(self, plan, expected):
        return self.invoke('rebuild', plan)

    def resume(self, plan, token, expected):
        return self.invoke('resume', plan, token)


def setup(tmp_path, results, routes=None, needs_source_verification=None):
    planner, service = Planner(), Service(results)
    @contextmanager
    def components(**kwargs):
        yield planner, service
    runner = HistoricalRefresh(
        routes=lambda: routes or (route(),),
        endpoint=lambda _route, _now: (END, date(2026, 10, 8)),
        components=components, state=RefreshStateStore(tmp_path / 'refresh.json'),
        needs_source_verification=needs_source_verification,
    )
    return runner, planner, service


def test_no_changed_endpoint_never_opens_full_input(tmp_path):
    runner, planner, service = setup(tmp_path, [], (route(watermark=END),))
    runner.tick(now=END)
    assert not planner.requests and not service.calls


def test_same_endpoint_verified_source_change_uses_native_advance(tmp_path):
    checked = []
    def source_changed(item, now, cancelled):
        checked.append((item.identity.stream_id, now, cancelled()))
        return True
    runner, planner, service = setup(
        tmp_path, [('completed', None, False)], (route(watermark=END),),
        needs_source_verification=source_changed,
    )
    runner.tick(now=END)
    assert checked == [(route().identity.stream_id, END, False)]
    assert len(planner.requests) == len(service.calls) == 1
    assert service.calls[0][0] == 'advance'


def test_same_endpoint_verified_source_unchanged_skips_planning(tmp_path):
    checked = []
    runner, planner, service = setup(
        tmp_path, [], (route(watermark=END),),
        needs_source_verification=lambda item, _now, _cancelled: checked.append(item) or False,
    )
    runner.tick(now=END)
    assert len(checked) == 1
    assert not planner.requests and not service.calls


def test_known_canonical_revision_invalidates_only_the_independent_history_and_uses_native_rebuild(tmp_path):
    changed = replace(route(watermark=END), reason='CANONICAL_SOURCE_REVISION_CHANGED')
    runner, planner, service = setup(tmp_path, [('completed', None, False)], (changed,))
    runner.tick(now=END)
    assert len(service.calls) == 1
    assert service.calls[0][0] == 'rebuild'
    assert planner.requests[0].operation == 'rebuild'
    assert planner.requests[0].streams[0].identity.recording_mode.value == 'historical_replay'
    assert not runner.state.read()['routes']


def test_an_unknown_invalid_history_is_not_automatically_rebuilt(tmp_path):
    runner, planner, service = setup(tmp_path, [], (replace(route(), reason='HISTORY_NOT_PUBLISHED'),))
    runner.tick(now=END)
    assert not service.calls and not planner.requests
    assert next(iter(runner.state.read()['routes'].values()))['reason'] == 'HISTORY_NOT_PUBLISHED'


def test_one_stream_per_tick_base_order_and_budget(tmp_path):
    routes = (route('main_rise'), route('oscillation'), route('trend'))
    runner, planner, service = setup(tmp_path, [('completed', None, False)] * 3, routes)
    for _ in range(3):
        runner.tick(now=END)
    assert [x[1].streams[0].request.identity.strategy_code for x in service.calls] == [
        'newow_trend', 'newow_oscillation', 'newow_main_rise']
    assert all(x.budget.max_input_bars == 1_000_000 and x.budget.max_input_bytes == 512_000_000
               and x.budget.max_elapsed_seconds == 1800 and x.budget.max_streams == 1
               for x in planner.requests)


def test_partial_rebuild_resumes_exact_plan_on_next_tick(tmp_path):
    runner, planner, service = setup(tmp_path, [
        ('blocked', 'REBUILD_REQUIRED', False), ('partial', 'INTERRUPTED', True),
        ('completed', None, False)])
    runner.tick(now=END)
    assert [call[0] for call in service.calls] == ['advance', 'rebuild']
    runner.tick(now=END)
    assert [x[0] for x in service.calls] == ['advance', 'rebuild', 'resume']
    assert service.calls[1][1] == service.calls[2][1]
    assert len(planner.requests) == 2


def test_unknown_commit_persists_block_and_never_retries(tmp_path):
    runner, planner, service = setup(tmp_path, [('partial', 'COMMIT_OUTCOME_UNKNOWN', True)])
    runner.tick(now=END)
    runner.tick(now=END)
    assert len(service.calls) == 1
    assert runner.state.read()['routes'][route().identity.stream_id]['reason'] == 'COMMIT_OUTCOME_UNKNOWN'


def test_source_busy_does_not_block_or_execute(tmp_path):
    runner, planner, service = setup(tmp_path, [('completed', None, False)])
    def busy(_request):
        raise ValueError('SOURCE_BUSY')
    planner.plan = busy
    runner.tick(now=END)
    assert not service.calls
    assert runner.state.read()['routes'] == {}


def test_rebuild_source_drift_blocks_before_rebuild_mutation(tmp_path):
    runner, planner, service = setup(tmp_path, [('blocked', 'REBUILD_REQUIRED', False)])
    runner.tick(now=END, cancelled=lambda: bool(service.calls))
    planner.source = 'changed-source'
    runner.tick(now=END)
    assert len(service.calls) == 1
    assert runner.state.read()['routes'][route().identity.stream_id]['reason'] == 'SOURCE_CHANGED'


def test_interrupted_process_inflight_requires_readback_not_resume(tmp_path):
    runner, planner, service = setup(tmp_path, [('completed', None, False)])
    runner.state.write({'version': 'newow_historical_refresh_v1', 'cursor': '', 'routes': {
        route().identity.stream_id: {'status': 'inflight', 'reason': None}}})
    runner.tick(now=END)
    assert not planner.requests and not service.calls
    assert runner.state.read()['routes'][route().identity.stream_id]['reason'] == 'REFRESH_READBACK_REQUIRED'


def test_thread_stop_cancels_without_main_waiting_for_work():
    entered, ended = Event(), Event()
    class Runner:
        def tick(self, *, now, cancelled):
            entered.set()
            while not cancelled():
                ended.wait(.01)
            ended.set()
    thread = RefreshThread(Runner(), interval=.01)
    thread.start()
    assert entered.wait(1)
    thread.stop(timeout=1)
    assert ended.is_set() and not thread.is_alive()


def test_known_service_lock_busy_keeps_exact_plan(tmp_path):
    runner, planner, service = setup(tmp_path, [('failed', 'SOURCE_BUSY', False), ('completed', None, False)])
    runner.tick(now=END)
    runner.tick(now=END)
    assert len(planner.requests) == 1
    assert service.calls[0][1] == service.calls[1][1]


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_actual_strategy_service_advances_same_window(tmp_path, request, backend):
    from newow.product_fixtures import ProductCases
    from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputSnapshot
    from app.reference_trading.service import HistoricalReferenceService, NewowHistoricalPayload
    from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest, HistoricalStreamRequest
    from tests.reference_trading.test_bootstrap import _repository
    from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint
    from app.reference_trading.historical_refresh import BUDGET
    case = ProductCases().primitive_input('trend', '1d')
    identity = _newow(case.identity.product, ProductStrategy.TREND, '1d', forward=False)
    from app.market_data.newow.product_release import candidate_input_quality_policy
    case = replace(case, identity=replace(case.identity, input_quality_policy=
                       candidate_input_quality_policy('rb', '1d', candidate_weekly=False)))
    bars = tuple(HistoricalInputBar(
        item.bar.bar_end, item.bar.trading_day, item.bar.physical_contract, item.bar.segment_id,
        item.calculation_segment_id, item.bar.close,
        strategy_input_fingerprint({'bar_end': item.bar.bar_end, 'source': item.source_bar_sha256}),
        NewowHistoricalPayload(case.identity, item),
    ) for item in case.bars)
    class Input:
        count = len(bars) - 1
        def snapshot(self, request):
            selected = bars[:self.count]
            manifest = {'query_since': selected[0].trading_day.isoformat(),
                        'partitions': [{'bar': item.fingerprint} for item in selected]}
            return HistoricalInputSnapshot(identity, selected[0].trading_day, selected[-1].bar_end,
                                            selected, manifest, f'source-{self.count}', len(selected) * 100)
        def plan_stream(self, request):
            return self.snapshot(request)
        def load_stream(self, request, *, expected_source_token):
            assert expected_source_token == f'source-{self.count}'
            return self.snapshot(request)
        def revalidate(self, request, *, expected_source_token):
            return expected_source_token == f'source-{self.count}'
    reader, repository = Input(), _repository()
    if backend == "postgresql":
        from sqlalchemy.orm import sessionmaker
        from app.reference_trading.repository import ReferenceRepository
        repository = ReferenceRepository(sessionmaker(request.getfixturevalue("reference_postgresql"), expire_on_commit=False))
    cutoff = bars[-1].bar_end
    planner = HistoricalReferencePlanner(reader, repository=repository, now=lambda: cutoff)
    initial = planner.plan(HistoricalReferenceRequest('build', (HistoricalStreamRequest(
        identity, bars[0].trading_day, bars[-2].trading_day, bars[-2].bar_end),), BUDGET))
    built = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    assert built.status == 'completed', built.streams[0].reason
    revision = built.streams[0].active_revision_id
    reader.count += 1
    def routes():
        _, checkpoint = repository.load_checkpoint(identity.stream_id)
        return (RefreshRoute(identity, bars[0].trading_day, checkpoint.computed_through),)
    @contextmanager
    def components(**kwargs):
        yield planner, HistoricalReferenceService(repository, reader,
                      cancelled=kwargs['cancelled'], after_batch=kwargs['after_batch'])
    runner = HistoricalRefresh(routes=routes, endpoint=lambda _r, _n: (cutoff, bars[-1].trading_day),
                               components=components, state=RefreshStateStore(tmp_path / 'refresh.json'))
    runner.tick(now=cutoff)
    stored = repository.read_state(identity.stream_id)
    _, checkpoint = repository.load_checkpoint(identity.stream_id)
    assert checkpoint.computed_through == cutoff
    assert stored.revision_id == revision
    assert stored.dependency_manifest['query_since'] == bars[0].trading_day.isoformat()
    assert runner.state.read()['routes'] == {}
    seq = stored.checkpoint.seq
    runner.tick(now=cutoff)
    assert repository.read_state(identity.stream_id).checkpoint.seq == seq


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
@pytest.mark.parametrize("activate", [False, True])
@pytest.mark.parametrize("reader_version", ["newow_product_reader_prefix_v5", "newow_product_reader_prefix_v4", "newow_product_reader_intraday_v3", "newow_product_reader_v2"])
def test_real_published_repository_route_is_active_and_not_blocked(tmp_path, request, backend, activate, reader_version):
    from app.reference_trading.historical_refresh import build_historical_refresh
    from tests.reference_trading.test_newow_bootstrap import setup_source, plan_for, NOW
    from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
    from app.reference_trading.models import ReferenceRevision, ReferenceBatch
    from app.reference_trading.contracts import manifest_sha256
    engine = request.getfixturevalue("reference_postgresql") if backend == "postgresql" else None
    factory, repo, identity, revision, checkpoint = setup_source(engine)
    with factory.begin() as session:
        rev = session.get(ReferenceRevision, (identity.stream_id, revision))
        batch = session.get(ReferenceBatch, rev.checkpoint_batch_id)
        manifest = {**batch.dependency_manifest, 'query_since': '2023-01-01', 'reader': reader_version}
        batch.dependency_manifest = manifest
        rev.dependency_digest = manifest_sha256(manifest)
    if activate:
        bootstrap = NewowForwardBootstrap(factory)
        plan = plan_for(bootstrap, identity)
        bootstrap.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    runner = build_historical_refresh(factory, state_path=tmp_path / 'refresh.json')
    routes = runner._routes()
    assert len(routes) == 1
    assert routes[0].identity == identity
    assert routes[0].reason == (None if reader_version == "newow_product_reader_prefix_v5" else "INPUT_PROOF_UPGRADE_REQUIRED")
    assert routes[0].since == date(2023, 1, 1)
    assert routes[0].computed_through == checkpoint.computed_through


def test_two_control_threads_cannot_enter_same_state_mutation(tmp_path):
    runner, planner, service = setup(tmp_path, [('completed', None, False)])
    store = RefreshStateStore(runner.state.path)
    with store.exclusive() as acquired:
        assert acquired
        runner.tick(now=END)
    assert not planner.requests and not service.calls


def test_stop_before_start_is_safe():
    thread = RefreshThread(SimpleNamespace())
    thread.stop(timeout=0)
    assert not thread.is_alive()


def test_endpoint_reads_share_product_frequency_and_idle_scan_is_bounded(tmp_path):
    routes = []
    for index in range(20):
        for strategy in ('trend', 'oscillation', 'main_rise'):
            source = route(strategy, watermark=END)
            routes.append(replace(source, identity=replace(source.identity, product=f'p{index}')))
    runner, planner, service = setup(tmp_path, [], routes)
    calls = []
    runner._endpoint = lambda route, now: (calls.append((route.identity.product, route.identity.frequency)) or (END, END.date()))
    runner.tick(now=END)
    assert len(calls) <= 11
    assert len(set(calls)) == len(calls)
    assert not planner.requests and not service.calls


def test_endpoint_maintenance_busy_waits_without_blocking_route(tmp_path, monkeypatch):
    from app.market_data.catalog import MarketCatalog

    runner, item, *_ = _published_endpoint_fixture(tmp_path, monkeypatch, '1d')
    runner._routes = lambda: (item,)
    monkeypatch.setattr(MarketCatalog, 'acquire_maintenance_lock',
                        lambda self, *, caller=None: None)
    with pytest.raises(ValueError, match='SOURCE_BUSY'):
        runner._endpoint(item, END)
    runner.tick(now=END)
    assert item.identity.stream_id not in runner.state.read()['routes']
    assert runner.last_progress['reason'] == 'SOURCE_BUSY'


def test_endpoint_releases_lease_and_keeps_quality_failure_closed(tmp_path, monkeypatch):
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService

    runner, item, *_ = _published_endpoint_fixture(tmp_path, monkeypatch, '1d')
    runner._routes = lambda: (item,)
    releases = []

    class Lease:
        def release(self):
            releases.append(1)

    monkeypatch.setattr(MarketCatalog, 'acquire_maintenance_lock',
                        lambda self, *, caller=None: Lease())

    def missing(self, **_kwargs):
        raise ValueError('PHYSICAL_DATA_MISSING')

    monkeypatch.setattr(MarketDataService, 'published_reference_endpoint', missing)
    with pytest.raises(ValueError, match='PHYSICAL_DATA_MISSING'):
        runner._endpoint(item, END)
    assert releases == [1]
    runner.tick(now=END)
    assert releases == [1, 1]
    assert runner.state.read()['routes'][item.identity.stream_id] == {
        'status': 'blocked', 'reason': 'PHYSICAL_DATA_MISSING'}


def test_endpoint_acquires_maintenance_lease_before_readonly_snapshot(tmp_path, monkeypatch):
    from app.reference_trading.historical_refresh import build_historical_refresh
    import app.db.readonly as readonly
    import app.market_data.composition as composition
    import app.market_data.operational_universe as universe
    import app.market_data.newow.product_release as release
    import app.reference_trading.newow_bootstrap as bootstrap

    order = []

    @contextmanager
    def session_factory():
        order.append('session')
        try:
            yield object()
        finally:
            order.append('session-close')

    @contextmanager
    def read_snapshot(_session, *, timeout_seconds):
        assert timeout_seconds == 15
        order.append('snapshot')
        try:
            yield
        finally:
            order.append('snapshot-close')

    class Lease:
        def release(self):
            order.append('lease-release')

    class Catalog:
        def acquire_maintenance_lock(self, *, caller):
            assert caller == 'reference-endpoint'
            order.append('lease-acquire')
            return Lease()

    def market(_session):
        order.append('market-build')
        return SimpleNamespace(
            catalog=Catalog(),
            published_reference_endpoint=lambda **_kwargs: (
                order.append('query') or (END, END.date())),
        )

    monkeypatch.setattr(readonly, 'readonly_transaction', read_snapshot)
    monkeypatch.setattr(composition, 'build_market_data_service', market)
    monkeypatch.setattr(universe, 'load_operational_products', lambda: ())
    monkeypatch.setattr(universe, 'load_active_products', lambda: ())
    monkeypatch.setattr(bootstrap, 'validate_product_scope', lambda *_args: ('rb',))
    monkeypatch.setattr(release, 'candidate_input_quality_policy',
                        lambda *_args, **_kwargs: SimpleNamespace(value='strict'))
    runner = build_historical_refresh(session_factory, state_path=tmp_path / 'refresh.json')
    assert runner._endpoint(route(), END) == (END, END.date())
    assert order == ['session', 'market-build', 'lease-acquire', 'snapshot',
                     'query', 'snapshot-close', 'lease-release', 'session-close']


@pytest.mark.isolated_postgresql
def test_pg_endpoint_respects_external_maintenance_lease(
    tmp_path, monkeypatch, reference_postgresql,  # noqa: F811
):
    from sqlalchemy.orm import Session, sessionmaker
    from app.market_data.catalog import MarketCatalog
    from app.reference_trading.historical_refresh import build_historical_refresh
    import app.market_data.composition as composition
    import app.reference_trading.newow_bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, 'validate_product_scope', lambda *_args: ('rb',))
    calls = []

    def market(session):
        return SimpleNamespace(
            catalog=MarketCatalog(session, tmp_path),
            published_reference_endpoint=lambda **_kwargs: calls.append(1) or (END, END.date()),
        )

    monkeypatch.setattr(composition, 'build_market_data_service', market)
    runner = build_historical_refresh(sessionmaker(reference_postgresql),
                                      state_path=tmp_path / 'refresh.json')
    with Session(reference_postgresql) as session:
        lease = MarketCatalog(session, tmp_path).acquire_maintenance_lock(caller='test-maintenance')
        assert lease is not None
        try:
            with pytest.raises(ValueError, match='SOURCE_BUSY'):
                runner._endpoint(route(), END)
            assert calls == []
        finally:
            lease.release()
    assert runner._endpoint(route(), END) == (END, END.date())
    assert calls == [1]


@pytest.mark.isolated_postgresql
def test_pg_endpoint_snapshot_starts_after_publication_releases_lease(
    tmp_path, monkeypatch, reference_postgresql,  # noqa: F811
):
    from sqlalchemy import Column, DateTime, Integer, MetaData, Table, insert, select, update
    from sqlalchemy.orm import Session, sessionmaker
    from app.market_data.catalog import MarketCatalog
    from app.reference_trading.historical_refresh import build_historical_refresh
    import app.db.readonly as readonly
    import app.market_data.composition as composition
    import app.reference_trading.newow_bootstrap as bootstrap

    sentinel = Table('reference_endpoint_snapshot_probe', MetaData(),
                     Column('id', Integer, primary_key=True),
                     Column('bar_end', DateTime(timezone=True), nullable=False))
    sentinel.create(reference_postgresql)
    old = END - timedelta(days=1)
    new = END
    with reference_postgresql.begin() as connection:
        connection.execute(insert(sentinel).values(id=1, bar_end=old))

    original_readonly = readonly.readonly_transaction
    observed = []

    @contextmanager
    def capture_snapshot(session, *, timeout_seconds):
        with original_readonly(session, timeout_seconds=timeout_seconds):
            observed.append(session.scalar(select(sentinel.c.bar_end).where(sentinel.c.id == 1)))
            yield

    monkeypatch.setattr(readonly, 'readonly_transaction', capture_snapshot)
    original_lock = MarketCatalog.acquire_maintenance_lock
    publisher_session = Session(reference_postgresql)
    blocker = MarketCatalog(publisher_session, tmp_path).acquire_maintenance_lock(
        caller='test-publication')
    assert blocker is not None
    published = []

    def acquire_after_publication(self, *, caller=None):
        if caller == 'reference-endpoint' and not published:
            with reference_postgresql.begin() as connection:
                connection.execute(update(sentinel).where(sentinel.c.id == 1)
                                   .values(bar_end=new))
            published.append(1)
            blocker.release()
        return original_lock(self, caller=caller)

    monkeypatch.setattr(MarketCatalog, 'acquire_maintenance_lock', acquire_after_publication)
    monkeypatch.setattr(bootstrap, 'validate_product_scope', lambda *_args: ('rb',))

    def market(session):
        def endpoint(**_kwargs):
            value = session.scalar(select(sentinel.c.bar_end).where(sentinel.c.id == 1))
            return value, value.date()
        return SimpleNamespace(catalog=MarketCatalog(session, tmp_path),
                               published_reference_endpoint=endpoint)

    monkeypatch.setattr(composition, 'build_market_data_service', market)
    try:
        runner = build_historical_refresh(sessionmaker(reference_postgresql),
                                          state_path=tmp_path / 'refresh.json')
        assert runner._endpoint(route(), END + timedelta(seconds=1)) == (new, new.date())
        assert observed == [new] and published == [1]
    finally:
        blocker.release()
        publisher_session.close()


def _published_endpoint_fixture(tmp_path, monkeypatch, frequency, *, published_day=8):
    """Real Catalog/Canonical with Oct 9 owner/session ready before publication."""
    from datetime import time
    from decimal import Decimal
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.market_data.catalog import MarketCatalog
    from app.market_data.domain import CanonicalBar, DatasetKey
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
    from app.models import Exchange, Instrument, Contract, TradingCalendar, TradingSession
    from app.reference_trading.historical_refresh import build_historical_refresh
    import app.market_data.composition as composition
    import app.reference_trading.newow_bootstrap as bootstrap

    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = CanonicalMonthlyStore(tmp_path / 'canonical')
    with factory.begin() as session:
        session.add_all([
            Exchange(code='DCE', name='DCE'),
            Instrument(symbol='jm', name='JM', exchange_code='DCE', is_active=True),
            Contract(contract_code='JM2701', instrument_symbol='jm', exchange_code='DCE',
                     listed_date=date(2026, 9, 1), expired_date=date(2027, 1, 31), provider='rqdata'),
            TradingSession(exchange_code='DCE', instrument_symbol='jm', session_name='day',
                           start_time=time(9), end_time=time(10), effective_from=date(2026, 9, 1), is_active=True),
            TradingSession(exchange_code='DCE', instrument_symbol='jm', session_name='night',
                           start_time=time(21), end_time=time(22), effective_from=date(2026, 9, 1), is_active=True),
        ])
        days = [date(2026, 9, 28) + timedelta(days=index) for index in range(12)]
        session.add_all([TradingCalendar(exchange_code='DCE', trade_date=day,
                                        is_trading_day=day.weekday() < 5) for day in days])
        catalog = MarketCatalog(session, store.root)
        catalog.upsert_main_contracts(tuple(('jm', day, 'JM2701') for day in days if day.weekday() < 5))
        day = date(2026, 10, 2 if frequency == '1w' else published_day)
        end = datetime.combine(day, time(2), tzinfo=UTC)
        ends = (end - timedelta(hours=12), end) if frequency == '60m' else (end,)
        bars = tuple(CanonicalBar(at, day, Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                                  Decimal(1), Decimal(10), Decimal(20)) for at in ends)
        partition = store.publish(PublishRequest(DatasetKey('contract', 'jm', 'JM2701', frequency),
                                                 2026, 10, bars, ends))
        catalog.register_partition(partition)
    monkeypatch.setattr(bootstrap, 'validate_product_scope', lambda *_args: ('jm',))
    monkeypatch.setattr(composition, 'build_market_data_service',
                        lambda session: MarketDataService(MarketCatalog(session, store.root), store))
    runner = build_historical_refresh(factory, state_path=tmp_path / 'refresh.json')
    identity = _newow('jm', ProductStrategy.TREND, frequency, forward=False)
    item = RefreshRoute(identity, date(2026, 9, 28), end - timedelta(days=1))
    return runner, item, factory, store, end


@pytest.mark.parametrize('frequency', ['60m', '1d', '1w'])
def test_refresh_discovers_published_endpoint_despite_prepared_next_day_metadata(tmp_path, monkeypatch, frequency):
    runner, item, factory, store, expected = _published_endpoint_fixture(tmp_path, monkeypatch, frequency)
    now = datetime(2026, 10, 8, 14, tzinfo=UTC)  # Oct 9 night Session already started.
    endpoint, trading_day = runner._endpoint(item, now)
    assert endpoint == expected
    assert trading_day == expected.date()
    # The normal strict wall-clock query still refuses unpublished coverage.
    if frequency == '60m':
        from app.market_data.composition import build_market_data_service
        from app.market_data.domain import SeriesPageQuery
        from app.market_data.market_data_service import MarketDataError
        with factory() as session, pytest.raises(MarketDataError, match='MAPPED_CONTRACT_DATASET_MISSING'):
            build_market_data_service(session).query_page(SeriesPageQuery(
                'actual_dominant', 'jm', frequency, before=now + timedelta(microseconds=1), limit=1))


def test_refresh_future_published_endpoint_fails_before_planning(tmp_path, monkeypatch):
    runner, item, *_ = _published_endpoint_fixture(tmp_path, monkeypatch, '60m', published_day=9)
    runner._routes = lambda: (item,)
    calls = []
    runner._components = lambda **kwargs: calls.append(kwargs)
    runner.tick(now=datetime(2026, 10, 8, 14, tzinfo=UTC))
    assert not calls
    assert runner.state.read()['routes'][item.identity.stream_id] == {
        'status': 'blocked', 'reason': 'AUTHORITATIVE_ENDPOINT_UNAVAILABLE'}


def test_published_endpoint_does_not_authorize_missing_middle_history(tmp_path, monkeypatch):
    runner, item, factory, store, latest = _published_endpoint_fixture(tmp_path, monkeypatch, '60m', published_day=9)
    from app.market_data.composition import build_market_data_service
    from app.market_data.domain import SeriesQuery
    from app.market_data.market_data_service import MarketDataError
    assert runner._endpoint(item, latest + timedelta(hours=1))[0] == latest
    with factory() as session, pytest.raises(MarketDataError, match='MAPPED_CONTRACT_DATASET_MISSING'):
        build_market_data_service(session).query(SeriesQuery(
            'actual_dominant', 'jm', '60m', datetime(2026, 10, 8, 1, tzinfo=UTC), latest))


@pytest.mark.parametrize('frequency', ['60m', '1d', '1w'])
def test_refresh_advances_discovery_only_after_catalog_publication(tmp_path, monkeypatch, frequency):
    runner, item, factory, store, old_end = _published_endpoint_fixture(tmp_path, monkeypatch, frequency)
    from app.market_data.catalog import MarketCatalog
    from app.market_data.domain import DatasetKey
    from app.market_data.storage import PublishRequest
    key = DatasetKey('contract', 'jm', 'JM2701', frequency)
    with factory() as session:
        catalog = MarketCatalog(session, store.root)
        old = store.read_catalog_partition(catalog.all_partitions(key)[0])
    endpoint = datetime(2026, 10, 9, 2, tzinfo=UTC)
    ends = (endpoint - timedelta(hours=12), endpoint) if frequency == '60m' else (endpoint,)
    new = tuple(replace(old[-1], bar_end=at, trading_day=date(2026, 10, 9)) for at in ends)
    published = store.publish(PublishRequest(key, 2026, 10, old + new,
                                             tuple(bar.bar_end for bar in old + new)))
    # An immutable file alone is not the active Catalog publication.
    assert runner._endpoint(item, endpoint + timedelta(minutes=1))[0] == old_end
    with factory.begin() as session:
        MarketCatalog(session, store.root).register_partition(published)
    assert runner._endpoint(item, endpoint + timedelta(minutes=1)) == (endpoint, date(2026, 10, 9))


def test_endpoint_preflight_block_is_not_automatically_cleared(tmp_path):
    runner, planner, service = setup(tmp_path, [('completed', None, False)])
    evidence = {'status': 'blocked', 'reason': 'MAPPED_CONTRACT_DATASET_MISSING'}
    runner.state.write({'version': 'newow_historical_refresh_v1', 'cursor': '',
                        'routes': {route().identity.stream_id: evidence}})
    runner.tick(now=END)
    assert not planner.requests and not service.calls
    assert runner.state.read()['routes'][route().identity.stream_id] == evidence


@pytest.mark.parametrize('frequency', ['60m', '1d', '1w'])
def test_health_reports_published_tail_with_prepared_next_day(tmp_path, monkeypatch, frequency):
    _, _, factory, _, expected = _published_endpoint_fixture(tmp_path, monkeypatch, frequency)
    from app.reference_trading.health import read_completed_canonical_endpoints
    with factory() as session:
        values = read_completed_canonical_endpoints(session, [('jm', frequency)],
                                                    datetime(2026, 10, 8, 14, tzinfo=UTC))
    assert values[('jm', frequency)] == {
        'expected_through': expected.isoformat(), 'expected_source': 'canonical_completed',
        'endpoint_status': 'READY', 'endpoint_reason': None}


@pytest.mark.parametrize('frequency', ['60m', '1d', '1w'])
def test_health_rejects_future_published_tail(tmp_path, monkeypatch, frequency):
    _, _, factory, _, expected = _published_endpoint_fixture(tmp_path, monkeypatch, frequency)
    from app.reference_trading.health import read_completed_canonical_endpoints
    with factory() as session:
        values = read_completed_canonical_endpoints(session, [('jm', frequency)],
                                                    expected - timedelta(microseconds=1))
    assert values[('jm', frequency)] == {
        'expected_through': None, 'expected_source': 'canonical_completed',
        'endpoint_status': 'UNKNOWN', 'endpoint_reason': 'COMPLETE_PERIOD_MISSING'}


def test_subing_full_history_uses_separate_bounded_budget(tmp_path):
    from app.reference_trading.subing_activation import subing_identity
    item = RefreshRoute(subing_identity('rb', '5m'), date(2023, 1, 1), END-timedelta(days=1))
    runner, planner, service = setup(tmp_path, [('completed', None, False)], routes=(item,))
    runner.tick(now=END)
    assert len(planner.requests) == 1
    assert planner.requests[0].budget.max_input_bars == 2_000_000
    assert planner.requests[0].budget.max_input_bytes == 8_192_000_000
    assert len(service.calls) == 1


def test_blocked_scan_page_advances_cursor_to_allow_later_history_progress(tmp_path):
    routes = tuple(replace(route(), identity=replace(route().identity, product=f'p{index:03}'))
                   for index in range(40))
    runner, planner, service = setup(tmp_path, [('completed', None, False)], routes)
    blocked = {item.identity.stream_id: {'status': 'blocked', 'reason': 'REFRESH_READBACK_REQUIRED'}
               for item in routes[:32]}
    runner.state.write({'version': 'newow_historical_refresh_v1', 'cursor': '', 'routes': blocked})
    runner.tick(now=END)
    assert not planner.requests and not service.calls
    assert runner.state.read()['cursor'] == routes[31].identity.stream_id
    runner.tick(now=END)
    assert len(service.calls) == 1
    assert service.calls[0][1].streams[0].request.identity == routes[32].identity
    assert runner.state.read()['routes'] == blocked


@pytest.mark.parametrize('frequency', ['5m', '15m', '30m', '60m', '1d', '1w'])
def test_page_history_scope_accepts_current_identity_without_observation_activation(frequency):
    from app.reference_trading.historical_refresh import _history_route_supported
    from guiyi_quant.reference_trading import RecordingMode
    identity = _newow('jm', ProductStrategy.TREND, frequency, forward=False)
    assert _history_route_supported(identity)
    assert not _history_route_supported(replace(identity, formula_versions=('superseded_formula',)))
    assert not _history_route_supported(replace(identity, recording_mode=RecordingMode.FORWARD_OBSERVATION,
                                                observation_policy_version='completed_canonical_v1'))


def test_pending_old_endpoint_finishes_before_fresh_catchup_plan(tmp_path):
    runner, planner, service = setup(tmp_path, [
        ('partial', 'INTERRUPTED', True), ('completed', None, False), ('completed', None, False)])
    runner.tick(now=END)
    frozen = service.calls[0][1]
    latest = END + timedelta(days=1)
    runner._endpoint = lambda _route, _now: (latest, latest.date())
    runner.tick(now=latest)
    assert service.calls[1][0] == 'resume'
    assert service.calls[1][1] == frozen
    assert not runner.state.read()['routes']
    assert len(planner.requests) == 1
    original = planner.plan
    def latest_plan(request):
        plan = original(request)
        revised = replace(plan.streams[0], target_completed_through=latest)
        updated = replace(plan, streams=(revised,), plan_hash='')
        return replace(updated, plan_hash=canonical_sha256(updated))
    planner.plan = latest_plan
    runner._routes = lambda: (replace(route(), computed_through=END),)
    runner.tick(now=latest)
    assert len(planner.requests) == 2
    assert planner.requests[-1].streams[0].as_of == latest
    assert service.calls[-1][1].streams[0].target_completed_through == latest


def test_history_scope_keeps_subing_uppercase_and_rejects_legacy_aliases():
    from app.reference_trading.historical_refresh import _history_route_supported
    from scripts.reference_trading_p9_manifest import _subing
    subing = _subing('jm', '1d', forward=False)
    assert subing.product == 'JM' and _history_route_supported(subing)
    assert not _history_route_supported(replace(subing, product='jm'))
    newow = _newow('jm', ProductStrategy.TREND, '1d', forward=False)
    assert not _history_route_supported(replace(newow, product='JM'))
    assert not _history_route_supported(replace(newow, strategy_code='newow-trend'))


@pytest.mark.parametrize('progressed,expected_wait', [(True, 1), (False, 30)])
def test_refresh_waits_for_new_permission_but_does_not_add_thirty_seconds_per_batch(progressed, expected_wait):
    waits = []
    class Stop:
        stopped = False
        def is_set(self): return self.stopped
        def wait(self, seconds):
            waits.append(seconds)
            self.stopped = True
    runner = SimpleNamespace(last_progress={})
    def tick(**_):
        if progressed:
            runner.last_progress = {'stage': 'committed'}
    runner.tick = tick
    refresh = RefreshThread(runner, interval=1, idle_interval=30)
    refresh._stop = Stop()
    refresh._run()
    assert waits == [expected_wait]


def test_proof_upgrade_rebuilds_even_when_endpoint_has_not_advanced(tmp_path):
    changed = replace(route(watermark=END), reason='INPUT_PROOF_UPGRADE_REQUIRED')
    runner, planner, service = setup(tmp_path, [('completed', None, False)], (changed,))
    runner.tick(now=END)
    assert service.calls[0][0] == 'rebuild'
    assert planner.requests[0].operation == 'rebuild'
    assert runner.state.read()['routes'] == {}
