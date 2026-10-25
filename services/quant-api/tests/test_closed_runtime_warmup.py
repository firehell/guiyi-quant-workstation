"""Closed preflight proves idle/calculation without inventing Live authority."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult, ResolvedContractSegment, SeriesPageQuery
from app.market_data.market_feed import MarketFeedService
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.market_read_service import MarketReadService, MarketReadWindowError

NOW = datetime(2026, 10, 25, 4, tzinfo=UTC)
DAY = date(2026, 10, 23)


def phase(kind=MarketPhase.CLOSED, day=None):
    return ProductMarketPhase('jm', kind, day, None, NOW + timedelta(days=10))


@pytest.mark.parametrize('service', ['market-feed', 'live'])
def test_nontrading_warmup_proves_idle_without_day_mapping(monkeypatch, service):
    from app import runtime_deployment as deployment
    from app.db import session as session_module
    from app.market_data import composition, operational_universe, market_phase
    monkeypatch.setattr(session_module, 'SessionLocal', lambda: nullcontext(object()))
    monkeypatch.setattr(composition, 'build_market_data_service', lambda _: SimpleNamespace(
        dominant_segment_for_day=lambda *_: pytest.fail('nontrading day has no mapping')))
    monkeypatch.setattr(operational_universe, 'load_operational_products', lambda: ('jm',))
    monkeypatch.setattr(market_phase, 'MarketPhaseResolver', lambda _: SimpleNamespace(resolve=lambda *_: phase()))
    monkeypatch.setattr(deployment, 'observation_progress', lambda _: {})
    result = deployment.warmup_service(service)
    assert result['proven_closed_idle'] is True
    assert result['natural_bar_verified'] is False


@pytest.mark.parametrize('state', [phase(MarketPhase.UNKNOWN), phase(MarketPhase.TRADING), phase(MarketPhase.BREAK)])
def test_dayless_unknown_or_active_warmup_is_blocked(monkeypatch, state):
    from app import runtime_deployment as deployment
    from app.db import session as session_module
    from app.market_data import composition, operational_universe, market_phase
    monkeypatch.setattr(session_module, 'SessionLocal', lambda: nullcontext(object()))
    monkeypatch.setattr(composition, 'build_market_data_service', lambda _: object())
    monkeypatch.setattr(operational_universe, 'load_operational_products', lambda: ('jm',))
    monkeypatch.setattr(market_phase, 'MarketPhaseResolver', lambda _: SimpleNamespace(resolve=lambda *_: state))
    monkeypatch.setattr(deployment, 'observation_progress', lambda _: {})
    with pytest.raises(deployment.DeploymentError, match='SESSION_UNKNOWN'):
        deployment.warmup_service('live')


def feed_for(state):
    feed = object.__new__(MarketFeedService)
    feed._phases = lambda _: {'jm': state}
    feed._coverage_session_source = lambda *_: pytest.fail('must not infer a nontrading day')
    feed._pending = {}
    feed._provider = None
    feed._known_sessions = {}
    feed._contracts = {}
    feed._channels = set()
    return feed


def test_quiescent_known_nontrading_closed_needs_no_invented_day():
    assert feed_for(phase()).quiescent(NOW)


@pytest.mark.parametrize('state', [phase(MarketPhase.UNKNOWN), phase(MarketPhase.BREAK), replace(phase(), current_session=SessionWindow(NOW-timedelta(minutes=1), NOW+timedelta(minutes=1)))])
def test_quiescent_never_accepts_unknown_active_or_inconsistent_dayless_phase(state):
    assert not feed_for(state).quiescent(NOW)


def test_quiescent_nontrading_closed_still_rejects_buffered_or_grace_input():
    feed = feed_for(phase())
    feed._pending = {'pending': object()}
    assert not feed.quiescent(NOW)
    feed._pending = {}
    feed._known_sessions = {('jm', DAY): (SessionWindow(NOW-timedelta(hours=1), NOW),)}
    feed._contracts = {'jm': 'JM2701'}
    feed._channels = {'bar_JM2701'}
    assert not feed.quiescent(NOW)


class ForbiddenLive:
    def __getattr__(self, name):
        raise AssertionError(f'canonical warmup touched Live: {name}')


class CanonicalSource:
    def __init__(self):
        self.bars = tuple(CanonicalBar(
            bar_end=datetime(2026, 10, 23, tzinfo=UTC)+timedelta(minutes=15*i), trading_day=DAY,
            open=Decimal(100), high=Decimal(101), low=Decimal(99), close=Decimal(100),
            volume=Decimal(10), turnover=Decimal(1000), open_interest=Decimal(20),
        ) for i in range(130))
        self.contract = 'JM2701'
        self.validations = []
        self.replays = []
    def query_page(self, query):
        bars = tuple(bar for bar in self.bars if query.before is None or bar.bar_end < query.before)[-query.limit:]
        return MarketSeriesPageResult({}, bars, (bars[0].bar_end, bars[-1].bar_end) if bars else None, False, None,
                                      (ResolvedContractSegment(self.contract, DAY, DAY),))
    def dominant_segment_for_day(self, symbol, day):
        return SimpleNamespace(contract=self.contract)
    def session_windows(self, **_):
        return (SessionWindow(self.bars[0].bar_end-timedelta(minutes=15), self.bars[-1].bar_end),)
    def validate_actual_dominant_alert_window(self, **kwargs): self.validations.append(kwargs)
    def read_alert_physical_prefix(self, **kwargs):
        self.replays.append(kwargs)
        return tuple(b for b in self.bars if b.bar_end <= kwargs['cutoff'] and (kwargs['after'] is None or b.bar_end > kwargs['after']))
    def validate_contract_replay_coverage(self, **kwargs):
        assert kwargs['bars'][-1].bar_end == kwargs['cutoff']
        assert all(b.bar_end <= kwargs['cutoff'] for b in kwargs['bars'])


def canonical_reader(state=None):
    source = CanonicalSource()
    resolver = SimpleNamespace(resolve=lambda *_: state or phase())
    market = MarketReadService(market_data=source, phase_resolver=resolver, operational_products=('jm',), live_store=ForbiddenLive())
    return market, source


def test_closed_warmup_replays_full_confirmed_physical_prefix_without_redis():
    from app.alerts.evaluators import HtdyOriginalEvaluator, SubingThsEvaluator
    market, source = canonical_reader()
    warmup = market.canonical_warmup_reader(NOW)
    window = warmup.closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'), limit=64)
    assert window is not None and len(window.bars) == 64
    replay = warmup.current_contract_replay_window(window, after=None)
    assert replay.bars == source.bars
    assert replay.cutoff == source.bars[-1].bar_end
    assert source.replays[-1]['contract'] == 'JM2701'
    HtdyOriginalEvaluator().evaluate_candidates(warmup, window)
    SubingThsEvaluator().evaluate_candidates(warmup, window)
    assert source.validations


@pytest.mark.parametrize('drift', ['values', 'owner'])
def test_canonical_warmup_rechecks_values_and_physical_mapping(drift):
    market, source = canonical_reader()
    warmup = market.canonical_warmup_reader(NOW)
    window = warmup.closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'), limit=64)
    if drift == 'values':
        source.bars = (*source.bars[:-1], replace(source.bars[-1], close=Decimal(101)))
    else:
        source.contract = 'JM2705'
    with pytest.raises(MarketReadWindowError, match='CONTRACT_UNAVAILABLE'):
        warmup.assert_window_current(window)


@pytest.mark.parametrize('kind', [MarketPhase.TRADING, MarketPhase.BREAK])
def test_canonical_warmup_does_not_replace_running_window_path(kind):
    market, _ = canonical_reader(phase(kind, DAY))
    assert market.canonical_warmup_reader(NOW).closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m')) is None


def test_canonical_warmup_unknown_phase_is_blocked():
    market, _ = canonical_reader(phase(MarketPhase.UNKNOWN))
    with pytest.raises(MarketReadWindowError, match='PHASE_UNAVAILABLE'):
        market.canonical_warmup_reader(NOW).closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'))


def test_canonical_warmup_quality_drift_fails_closed():
    from app.market_data.market_data_service import MarketDataError
    market, source = canonical_reader()
    warmup = market.canonical_warmup_reader(NOW)
    window = warmup.closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'))
    def unavailable(_): raise MarketDataError('PARTITION_HASH_MISMATCH')
    source.query_page = unavailable
    with pytest.raises(MarketReadWindowError, match='CONTRACT_UNAVAILABLE'):
        warmup.assert_window_current(window)


def test_canonical_warmup_replay_rejects_future_suffix():
    market, source = canonical_reader()
    warmup = market.canonical_warmup_reader(NOW)
    window = warmup.closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'))
    original = source.read_alert_physical_prefix
    source.read_alert_physical_prefix = lambda **kwargs: (*original(**kwargs), replace(source.bars[-1], bar_end=NOW+timedelta(minutes=1)))
    with pytest.raises(MarketReadWindowError, match='CUTOFF_BAR_MISSING'):
        warmup.current_contract_replay_window(window, after=None)


def test_canonical_warmup_rejects_current_session_grace():
    market, source = canonical_reader()
    now = source.bars[-1].bar_end + timedelta(seconds=30)
    with pytest.raises(MarketReadWindowError, match='CONTRACT_UNAVAILABLE'):
        market.canonical_warmup_reader(now).closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'))


def test_known_day_warmup_still_requires_exact_dominant_mapping(monkeypatch):
    from app import runtime_deployment as deployment
    from app.db import session as session_module
    from app.market_data import composition, operational_universe, market_phase
    calls = []
    monkeypatch.setattr(session_module, 'SessionLocal', lambda: nullcontext(object()))
    monkeypatch.setattr(composition, 'build_market_data_service', lambda _: SimpleNamespace(dominant_segment_for_day=lambda *args: calls.append(args)))
    monkeypatch.setattr(operational_universe, 'load_operational_products', lambda: ('jm',))
    monkeypatch.setattr(market_phase, 'MarketPhaseResolver', lambda _: SimpleNamespace(resolve=lambda *_: phase(day=DAY)))
    monkeypatch.setattr(deployment, 'observation_progress', lambda _: {})
    assert deployment.warmup_service('live')['proven_closed_idle'] is True
    assert calls == [('jm', DAY)]


def test_alert_closed_warmup_evaluates_then_discards_without_events_or_transport(monkeypatch):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.alerts import composition
    from app.alerts.evaluators import HtdyOriginalEvaluator
    from app.alerts.models import AlertRule
    from app.alerts.registry import HTDY_ALERT_RULE_CODE
    engine = create_engine('sqlite+pysqlite:///:memory:')
    AlertRule.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add(AlertRule(rule_code=HTDY_ALERT_RULE_CODE, enabled=True, scope_product_frequencies={'jm': ['15m']}))
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda _c, _cursor, statement, *_: statements.append(statement))
    market, _ = canonical_reader()
    closed = []
    runtime = SimpleNamespace(_validate_startup_composition=lambda: None, message_source=SimpleNamespace(close=lambda: closed.append(True)),
                              _session_factory=factory, _market_read_factory=lambda _: market,
                              _evaluators={HTDY_ALERT_RULE_CODE: HtdyOriginalEvaluator()})
    monkeypatch.setattr(composition, 'build_alert_runtime', lambda: runtime)
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(composition, 'datetime', FrozenDateTime)
    assert composition.warmup_alert_runtime() == {'calculated': 1, 'total': 1, 'warming': [], 'natural_signals_verified': False}
    assert closed == [True]
    assert all(not value.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for value in statements)


def test_closed_warmup_rejects_future_published_canonical_instead_of_hiding_it():
    market, source = canonical_reader()
    source.bars = (*source.bars, replace(source.bars[-1], bar_end=NOW+timedelta(minutes=1)))
    with pytest.raises(MarketReadWindowError, match='CUTOFF_BAR_MISSING'):
        market.canonical_warmup_reader(NOW).closed_window(SeriesPageQuery('actual_dominant', 'jm', '15m'))


def test_closed_daily_quality_warmup_keeps_existing_asof_and_policy_contract():
    from app.alerts.registry import SUBING_QUALITY_REWARM_POLICY_V2
    from app.market_data.market_read_service import MarketReadWindow
    market, source = canonical_reader()
    warmup = market.canonical_warmup_reader(NOW)
    bars = source.bars
    window = MarketReadWindow('jm', 'actual_dominant', '1d', DAY, 'JM2701', bars[-1].bar_end,
                              bars, ('JM2701',)*len(bars), input_policy_version=SUBING_QUALITY_REWARM_POLICY_V2)
    calls = []
    def as_of(query, *, as_of):
        calls.append(as_of)
        assert query.frequency.value == '1d'
        return window
    warmup.latest_subing_quality_window_as_of = as_of
    warmup.latest_subing_quality_window = lambda _query, *, trading_day: window
    assert warmup.closed_window(SeriesPageQuery('actual_dominant', 'jm', '1d'), quality_rewarm=True) == window
    assert calls == [NOW]
