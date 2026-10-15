from datetime import UTC, date, datetime
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertObservationCandidate
from app.alerts.models import AlertRule, AlertEvent, SubingSignalAlignment
from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE, SUBING_QUALITY_REWARM_POLICY_V2
from app.alerts.runtime import AlertRuntime, _persist_candidate_and_prepare_notification
from app.alerts.service import AlertService
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow

NOW = datetime(2026, 10, 15, 7, tzinfo=UTC)


def test_0052_additive_migration_preserves_legacy_and_refuses_lossy_downgrade():
    path = Path(__file__).parents[1] / 'alembic/versions/20261015_0052_alert_delivery_v2.py'
    spec = importlib.util.spec_from_file_location('migration0052', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE alert_events (id INTEGER PRIMARY KEY, notification_status VARCHAR(32))'))
        connection.execute(text("INSERT INTO alert_events VALUES (1, NULL)"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.execute(text('SELECT input_policy_version, notification_policy_version FROM alert_events')).one() == (None, None)
        connection.execute(text("UPDATE alert_events SET notification_policy_version='alert_memory_batch_v2' WHERE id=1"))
        with pytest.raises(RuntimeError, match='DOWNGRADE_UNSAFE'):
            module.downgrade()
        assert 'notification_policy_version' in {c['name'] for c in inspect(connection).get_columns('alert_events')}


def test_quality_event_records_input_version_without_enabling_subing_send():
    engine = create_engine('sqlite://')
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    with Session(engine) as session:
        rule = AlertRule(rule_code=SUBING_THS_ALERT_RULE_CODE, enabled=True, scope_product_frequencies={'rb': ['1d']})
        session.add(rule)
        session.commit()
        candidate = AlertObservationCandidate(NOW, date(2026, 10, 15), 'RB2701', ('buy',), SUBING_QUALITY_REWARM_POLICY_V2)
        prepared = _persist_candidate_and_prepare_notification(
            AlertService(session, operational_products=('rb',)), taxonomy={}, rule=rule,
            symbol='rb', frequency='1d', candidate=candidate, processing_now=NOW,
            notification_generation=20,
        )
        assert prepared.event_created and prepared.message is None
        event = session.scalar(select(AlertEvent))
        assert event.input_policy_version == SUBING_QUALITY_REWARM_POLICY_V2
        assert event.notification_policy_version is None
        assert event.notification_attempted_at is None


def test_prime_subing_uses_quality_completed_endpoint_not_generic_price_page():
    engine = create_engine('sqlite://')
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    with Session(engine) as session:
        session.add(AlertRule(rule_code=SUBING_THS_ALERT_RULE_CODE, enabled=True, scope_product_frequencies={'rb': ['1d']}))
        session.commit()
    bar = CanonicalBar(NOW, NOW.date(), '1', '1', '1', '1', '1', None, None)
    window = MarketReadWindow('rb', 'actual_dominant', '1d', NOW.date(), 'RB2701', NOW, (bar,), ('RB2701',), input_policy_version=SUBING_QUALITY_REWARM_POLICY_V2)
    class Reader:
        def latest_subing_quality_window_as_of(self, query, *, as_of):
            assert as_of == NOW
            return window
        def history_page(self, query):
            pytest.fail('generic price discovery bypasses quality policy')
        def assert_window_current(self, value):
            assert value is window
    runtime = AlertRuntime(session_factory=lambda: Session(engine), market_read_factory=lambda s: Reader(),
        evaluators={SUBING_THS_ALERT_RULE_CODE: SimpleNamespace(evaluate_candidates=lambda r, w: ())},
        sender=None, operational_products=('rb',), taxonomy={}, clock=lambda: NOW)
    runtime._prime_canonical_coverage()
    assert runtime._coverage_progress[(SUBING_THS_ALERT_RULE_CODE, 'rb', '1d')]['state'] == 'ok'
    with Session(engine) as session:
        assert session.scalar(select(AlertEvent)) is None


def test_runtime_ack_and_second_event_progress_while_http_is_blocked(tmp_path, monkeypatch):
    from threading import Event
    from sqlalchemy.orm import sessionmaker
    from app.alerts.notification import AlertNotificationDispatcher, ProviderAcceptance
    from app.alerts.registry import HTDY_ALERT_RULE_CODE
    import app.alerts.runtime as runtime_module
    from datetime import timedelta

    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}", connect_args={'check_same_thread': False})
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session:
        session.add_all([
            AlertRule(rule_code=HTDY_ALERT_RULE_CODE, scope_product_frequencies={'rb': ['15m']}),
            AlertRule(rule_code=SUBING_THS_ALERT_RULE_CODE, scope_product_frequencies={}),
        ])
        session.commit()
    entered, release = Event(), Event()
    class Transport:
        def send(self, delivery):
            entered.set()
            assert release.wait(4)
            return ProviderAcceptance('fixture-accepted')
    class Reader:
        def bars_until(self, query, *, trading_day, end, limit):
            bar = CanonicalBar(end, trading_day, '1', '1', '1', '1', '1', None, None)
            return MarketReadWindow('rb', 'actual_dominant', '15m', trading_day, 'RB2701', end, (bar,), ('RB2701',))
        def assert_window_current(self, window):
            pass
    class Evaluator:
        def evaluate_candidates(self, reader, window):
            return (AlertObservationCandidate(window.cutoff, window.trading_day, window.contract, ('buy',)),)
    class Source:
        count = 0
        acked = 0
        current_observation = None
        def subscribe(self, *args):
            pass
        def drain_startup_messages(self):
            return ()
        def get_message(self, *, timeout_seconds):
            self.count += 1
            if self.count == 2:
                assert entered.wait(3)
            end = NOW - timedelta(minutes=15 * (2 - self.count))
            self.current_observation = SimpleNamespace(source_observed_at=NOW, observation_id=f'source-{self.count}')
            return 'live:bar:rb:15m', {'bar_end': end.isoformat(), 'trading_day': NOW.date().isoformat(),
                'open': '1', 'high': '1', 'low': '1', 'close': '1', 'volume': '1', 'turnover': None, 'open_interest': None}
        def ack_current(self):
            self.acked += 1
            if self.acked == 2:
                with sessions() as session:
                    rows = session.scalars(select(AlertEvent).order_by(AlertEvent.id)).all()
                    assert len(rows) == 2
                    assert rows[0].notification_status == 'ATTEMPTED_UNKNOWN'
                    assert rows[1].notification_status == 'HANDOFF_PENDING'
                release.set()
        def close(self):
            release.set()
    source = Source()
    monkeypatch.setattr(runtime_module, 'runtime_heartbeat_identity', lambda: {'runtime_generation': 20})
    runtime = AlertRuntime(session_factory=sessions, market_read_factory=lambda s: Reader(),
        evaluators={HTDY_ALERT_RULE_CODE: Evaluator(), SUBING_THS_ALERT_RULE_CODE: Evaluator()},
        sender=AlertNotificationDispatcher(Transport()), operational_products=('rb',),
        taxonomy={'rb': SimpleNamespace(name='螺纹钢')}, clock=lambda: NOW,
        stop_requested=lambda: source.acked == 2, message_source=source,
        heartbeat_store=SimpleNamespace(write=lambda *a, **kw: None), live_processing_guard=lambda symbol: __import__('contextlib').nullcontext())
    try:
        runtime.run_forever()
        assert source.acked == 2
        assert runtime._notification_generation == 20
    finally:
        release.set()


def test_0052_real_isolated_postgresql_ddl_and_legacy_readback():
    import os
    from uuid import uuid4
    from sqlalchemy.engine import make_url
    url = os.environ.get("GUIYI_ALERT_ISOLATED_TEST_URL")
    if not url:
        pytest.skip("explicit isolated PostgreSQL URL required")
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.port == 15475 and parsed.database == "guiyi_alert_isolated_test"
    engine = create_engine(url)
    schema = "alert_migration_" + uuid4().hex
    path = Path(__file__).parents[1] / 'alembic/versions/20261015_0052_alert_delivery_v2.py'
    spec = importlib.util.spec_from_file_location('migration0052pg', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA " + schema))
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL search_path TO " + schema))
            connection.execute(text('CREATE TABLE alert_events (id INTEGER PRIMARY KEY, notification_status VARCHAR(32))'))
            connection.execute(text("INSERT INTO alert_events VALUES (1, NULL)"))
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            assert connection.execute(text('SELECT input_policy_version, notification_policy_version FROM alert_events')).one() == (None, None)
            connection.execute(text("UPDATE alert_events SET notification_generation=20 WHERE id=1"))
            with pytest.raises(RuntimeError, match='DOWNGRADE_UNSAFE'):
                module.downgrade()
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        engine.dispose()
