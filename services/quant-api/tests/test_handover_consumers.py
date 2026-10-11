"""Consumption boundary tests do not start Runtime or contact providers."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.alerts.composition import StreamAlertMessageSource
from app.reference_trading.live_wake import StreamForwardLiveWake

DAY = date(2026, 10, 9)
OBSERVED = datetime(2026, 10, 9, 1, tzinfo=UTC)


class Stream:
    def __init__(self):
        self.acks = []
        self.envelope = SimpleNamespace(trading_day=DAY, source_observed_at=OBSERVED,
            confirmed_at=OBSERVED, stream_id='1-0', observation_id='observation', channel='live:bar:rb:60m',
            data={}, notification_eligible=True)
    def days(self):
        return (DAY,)
    def cursor(self, consumer, day):
        return '0-0'
    def read(self, consumer, day, count):
        return (self.envelope,)
    def ack(self, consumer, day, **kwargs):
        self.acks.append((consumer, day, kwargs))


def test_alert_source_does_not_ack_until_event_processing_completes():
    source = StreamAlertMessageSource.__new__(StreamAlertMessageSource)
    source._stream = stream = Stream()
    source.current_observation = None
    assert source.get_message(timeout_seconds=0) == ('live:bar:rb:60m', '{}')
    assert stream.acks == []
    assert source.current_observation.source_observed_at == OBSERVED
    source.ack_current()
    assert stream.acks == [('alert', DAY, {'expected_cursor': '0-0', 'next_id': '1-0'})]


def test_missing_alert_cursor_is_not_initialized_or_skipped():
    source = StreamAlertMessageSource.__new__(StreamAlertMessageSource)
    source._stream = stream = Stream()
    def missing(*_args):
        raise RuntimeError('OBSERVATION_CURSOR_MISSING')
    stream.cursor = missing
    with pytest.raises(RuntimeError, match='CURSOR_MISSING'):
        source.get_message(timeout_seconds=0)
    assert stream.acks == []


def test_reference_failed_route_keeps_input_unacked_and_source_time():
    from app.reference_trading.runtime import ForwardReferenceWorker
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    wake = StreamForwardLiveWake.__new__(StreamForwardLiveWake)
    wake.stop_requested = lambda: False
    wake._stream = stream = Stream()
    seen = []
    def read_input(route, kind, bar_end):
        seen.append((route, kind, bar_end))
        assert worker.source_observed_at == OBSERVED and worker.raw_received_at == OBSERVED
        raise ForwardInputUnavailable('LIVE_EVENT_IDENTITY_CONFLICT')
    worker = ForwardReferenceWorker(SimpleNamespace(read_pending_capture=lambda _: None),
        lambda _: SimpleNamespace(), read_input, enabled=True)
    wake._worker = worker
    wake._validated_routes = lambda *_args: (OBSERVED, ('route',))
    with pytest.raises(RuntimeError, match='PROCESSING_BLOCKED'):
        wake.wait(0)
    assert stream.acks == []
    assert wake._worker.source_observed_at is None
    assert wake._worker.raw_received_at is None
    assert seen == [('route', 'live_event', OBSERVED)]
    assert worker._blocked == {'route': 'LIVE_EVENT_IDENTITY_CONFLICT'}


def test_durable_reference_scan_does_not_recapture_live_at_scan_time():
    from app.reference_trading.runtime import ForwardReferenceWorker
    class Repository:
        def enabled_forward_stream_ids(self, **_kwargs):
            return ('live', 'daily')
        def forward_source_context(self, stream_id):
            return (SimpleNamespace(frequency='60m' if stream_id == 'live' else '1d'),)
        def read_pending_capture(self, _stream_id):
            return None
    worker = ForwardReferenceWorker(Repository(), lambda _s: None, lambda *_args: None, enabled=True)
    worker.scan_live = False
    worker.scan()
    assert list(worker._queue) == ['daily']


def test_alert_idle_verified_cursor_cycle_reports_ready_without_event():
    from app.alerts.runtime import AlertRuntime
    stopped = []
    ready = []
    class Source:
        current_observation = None
        def subscribe(self, *_args):
            pass
        def drain_startup_messages(self):
            return ()
        def get_message(self, **_kwargs):
            # A production Stream source validates all cursors before returning idle.
            stopped.append(True)
            return None
        def close(self):
            pass
    runtime = AlertRuntime(session_factory=lambda: None, market_read_factory=lambda _s: None,
        sender=None, operational_products=(), taxonomy={}, message_source=Source(),
        heartbeat_store=SimpleNamespace(), clock=lambda: OBSERVED,
        stop_requested=lambda: bool(stopped), mark_ready=lambda: ready.append(True))
    runtime._validate_startup_composition = lambda: None
    runtime._write_heartbeat = lambda _now: None
    runtime.run_forever()
    assert ready == [True]
