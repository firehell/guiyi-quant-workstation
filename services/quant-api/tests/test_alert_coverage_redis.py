"""Coverage uses real isolated Redis without advancing cursors or creating Events."""
from datetime import UTC, datetime, timedelta
import os
from uuid import uuid4

import pytest

from app.alerts.composition import RedisAlertHeartbeatStore, StreamAlertMessageSource
from app.alerts.registry import HTDY_ALERT_RULE_CODE
from app.alerts.runtime import AlertRuntime
from app.market_data.observation_stream import ObservationEnvelope, ObservationStream


def test_real_journal_snapshot_is_readonly_and_failure_projection_survives_restart():
    from redis import Redis
    port = os.environ.get("GUIYI_TEST_REDIS_PORT")
    if not port:
        pytest.skip("dedicated ephemeral GUIYI_TEST_REDIS_PORT required")
    assert port == "16389"  # This task's newly created disposable instance, never production.
    client = Redis(host="127.0.0.1", port=int(port), db=15)
    prefix = "test:alert-coverage:"+uuid4().hex+":"
    now = datetime(2026, 10, 28, 2, tzinfo=UTC)
    day = now.date()
    class Journal(ObservationStream):
        def key(self, day):
            return prefix+super().key(day)
        def cursor_key(self, consumer, day):
            return prefix+super().cursor_key(consumer, day)
        def registration_key(self, consumer):
            return prefix+super().registration_key(consumer)
        def days(self):
            return (day,)
    class Store(RedisAlertHeartbeatStore):
        _UNRESOLVED_KEY = prefix+"unresolved"
    try:
        journal = Journal(client, kind="completed")
        journal.initialize("alert", day, cursor="0-0")
        for index in range(2):
            end = now+timedelta(minutes=15*index)
            event = ObservationEnvelope(f"obs-{index}",day,end+timedelta(milliseconds=1),
                "live:bar:rb:15m",{"bar_end":end.isoformat(),"contract":"RB2610"}, True,
                confirmed_at=end+timedelta(milliseconds=2))
            journal.append(event)
        source = StreamAlertMessageSource(client)
        source._stream = journal
        snapshot = source.coverage_snapshot()
        assert snapshot["cursor"] == journal.cursor("alert",day) == "0-0"
        assert snapshot["pending_routes"]["rb:15m"]["observation_id"] == "obs-0"
        for index in range(2):
            source.get_message(timeout_seconds=0)
            source.ack_current()
            snapshot = source.coverage_snapshot()
            assert snapshot["routes"]["rb:15m"]["observation_id"] == f"obs-{index}"
        assert snapshot["cursor"] == snapshot["tail"]
        assert snapshot["pending_routes"] == {}
        store = Store(client)
        def runtime():
            return AlertRuntime(session_factory=lambda: None, market_read_factory=lambda _: None,
                sender=None, operational_products=("rb",), taxonomy={}, heartbeat_store=store)
        first = runtime()
        first._record_rule_result(HTDY_ALERT_RULE_CODE, evaluated_bar_at=None,at=now,
            event_created=False,error_type="evaluation_input_invalid",
            coverage_identity=("rb","15m","RB2610",day))
        fresh = runtime()
        fresh._restore_unresolved_coverage()
        assert fresh._coverage_progress[(HTDY_ALERT_RULE_CODE,"rb","15m")]["state"] == "evaluation_failed"
        assert journal.cursor("alert",day) == snapshot["cursor"]
        source.close()
    finally:
        keys = list(client.scan_iter(match=prefix+"*"))
        if keys:
            client.delete(*keys)
        client.close()
