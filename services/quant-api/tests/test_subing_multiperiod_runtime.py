"""Runtime wiring evidence with deterministic candidates, not formula evidence."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertObservationCandidate
from app.alerts.models import AlertEvent, AlertRule, SubingSignalAlignment
from app.alerts.registry import SUBING_THS_RULE, SUBING_SIGNAL_FREQUENCIES
from app.alerts.runtime import AlertRuntime
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import CurrentContractReplayWindow, MarketReadWindow, MarketReadWindowError

DAY = date(2026, 10, 9)
END = datetime(2026, 10, 9, 7, tzinfo=UTC)


class RecordingReader:
    def __init__(self, outcome):
        self.outcome = outcome

    def window(self, frequency):
        bar = CanonicalBar(END, DAY, Decimal(149), Decimal(150), Decimal(148), Decimal(149), Decimal(100), None, None)
        return MarketReadWindow('jm', 'actual_dominant', frequency, DAY, 'JM2701', END, (bar,), ('JM2701',))

    def bars_until(self, query, *, trading_day, end, limit):
        assert trading_day == DAY and end == END
        return self.window(query.frequency.value)

    def latest_canonical_window(self, query, *, trading_day, limit):
        assert trading_day == DAY
        return self.window(query.frequency.value)

    def assert_window_current(self, window):
        assert window.contract == 'JM2701'

    def subing_direction_window(self, decision, frequency):
        if self.outcome == 'UNKNOWN' and frequency.value == '1w':
            raise MarketReadWindowError('MARKET_READ_CUTOFF_BAR_MISSING')
        falling = self.outcome == 'FAIL' and frequency.value == '60m'
        bars = tuple(CanonicalBar(END - timedelta(days=49-i), DAY, Decimal(150-i if falling else 100+i), Decimal(151-i if falling else 101+i), Decimal(149-i if falling else 99+i), Decimal(150-i if falling else 100+i), Decimal(100), None, None) for i in range(50))
        return CurrentContractReplayWindow('jm', frequency.value, DAY, 'JM2701', END, None, bars)


class DeterministicEvaluator:
    def evaluate_candidates(self, reader, window):
        return (AlertObservationCandidate(window.cutoff, window.trading_day, window.contract, ('buy',)),)


class ForbiddenSender:
    def __init__(self):
        self.calls = 0

    def send(self, message):
        self.calls += 1
        raise AssertionError('SuBing is recording only')


@pytest.mark.parametrize('outcome', ['PASS', 'FAIL', 'UNKNOWN'])
def test_six_natural_trigger_routes_preserve_raw_events_and_immutable_snapshots_without_sender(outcome):
    engine = create_engine('sqlite://')
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    with Session(engine) as session:
        session.add(AlertRule(rule_code=SUBING_THS_RULE.rule_code, enabled=True, scope_product_frequencies={'jm': list(SUBING_SIGNAL_FREQUENCIES)}))
        session.commit()
    reader = RecordingReader(outcome)
    sender = ForbiddenSender()
    runtime = AlertRuntime(session_factory=lambda: Session(engine), market_read_factory=lambda session: reader, evaluators={SUBING_THS_RULE.rule_code: DeterministicEvaluator()}, sender=sender, operational_products=('jm',), taxonomy={}, clock=lambda: END + timedelta(seconds=9))
    payload = dict(bar_end=END.isoformat(), trading_day=DAY.isoformat(), open='149', high='150', low='148', close='149', volume='100', turnover=None, open_interest=None)
    for frequency in ('5m', '15m', '30m', '60m'):
        runtime.process_message(f'live:bar:jm:{frequency}', payload)
    runtime.process_message('market:state', dict(reason='canonical_updated', trading_day=DAY.isoformat()))
    with Session(engine) as session:
        events = session.scalars(select(AlertEvent).order_by(AlertEvent.frequency)).all()
        assert {event.frequency for event in events} == set(SUBING_SIGNAL_FREQUENCIES)
        assert len(events) == 6
        assert all(event.notification_attempted_at is None for event in events)
        snapshots = {event.id: event.subing_alignment.snapshot for event in events}
        assert all(event.subing_alignment.status == outcome for event in events)
    reader.outcome = 'UNKNOWN' if outcome == 'PASS' else 'PASS'
    for frequency in ('5m', '15m', '30m', '60m'):
        runtime.process_message(f'live:bar:jm:{frequency}', payload)
    runtime.process_message('market:state', dict(reason='canonical_updated', trading_day=DAY.isoformat()))
    with Session(engine) as session:
        stored = session.scalars(select(SubingSignalAlignment)).all()
        assert len(stored) == 6
        assert {item.event_id: item.snapshot for item in stored} == snapshots
    assert sender.calls == 0
    engine.dispose()
