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
                                                       resume_token=resume),))

    def advance(self, plan, expected):
        assert expected == plan.plan_hash
        return self.invoke('advance', plan)

    def rebuild(self, plan, expected):
        return self.invoke('rebuild', plan)

    def resume(self, plan, token, expected):
        return self.invoke('resume', plan, token)


def setup(tmp_path, results, routes=None):
    planner, service = Planner(), Service(results)
    @contextmanager
    def components(**kwargs):
        yield planner, service
    runner = HistoricalRefresh(
        routes=lambda: routes or (route(),),
        endpoint=lambda _route, _now: (END, date(2026, 10, 8)),
        components=components, state=RefreshStateStore(tmp_path / 'refresh.json'),
    )
    return runner, planner, service


def test_no_changed_endpoint_never_opens_full_input(tmp_path):
    runner, planner, service = setup(tmp_path, [], (route(watermark=END),))
    runner.tick(now=END)
    assert not planner.requests and not service.calls


def test_one_stream_per_tick_base_order_and_budget(tmp_path):
    routes = (route('main_rise'), route('oscillation'), route('trend'))
    runner, planner, service = setup(tmp_path, [('completed', None, False)] * 3, routes)
    for _ in range(3):
        runner.tick(now=END)
    assert [x[1].streams[0].request.identity.strategy_code for x in service.calls] == [
        'newow_trend', 'newow_oscillation', 'newow_main_rise']
    assert all(x.budget.max_input_bars == 500_000 and x.budget.max_input_bytes == 512_000_000
               and x.budget.max_elapsed_seconds == 1800 and x.budget.max_streams == 1
               for x in planner.requests)


def test_partial_rebuild_resumes_exact_plan_on_next_tick(tmp_path):
    runner, planner, service = setup(tmp_path, [
        ('blocked', 'REBUILD_REQUIRED', False), ('partial', 'INTERRUPTED', True),
        ('completed', None, False)])
    runner.tick(now=END)
    assert len(service.calls) == 1  # rebuild is a separate bounded tick
    runner.tick(now=END)
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
    runner.tick(now=END)
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
def test_real_published_repository_route_is_active_and_not_blocked(tmp_path, request, backend):
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
        manifest = {**batch.dependency_manifest, 'query_since': '2023-01-01'}
        batch.dependency_manifest = manifest
        rev.dependency_digest = manifest_sha256(manifest)
    bootstrap = NewowForwardBootstrap(factory)
    plan = plan_for(bootstrap, identity)
    bootstrap.apply(plan, expected_plan_hash=plan['plan_hash'], now=NOW)
    runner = build_historical_refresh(factory, state_path=tmp_path / 'refresh.json')
    routes = runner._routes()
    assert len(routes) == 1
    assert routes[0].identity == identity
    assert routes[0].reason is None
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
