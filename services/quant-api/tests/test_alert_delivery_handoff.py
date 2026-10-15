from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from time import monotonic, sleep

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from app.alerts.delivery_handoff import (
    BoundedNotificationHandoff,
    NOTIFICATION_POLICY_VERSION,
    FrozenHandoff,
    notification_batch_key,
)
from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.alerts.notification import (
    AlertNotificationDispatcher,
    AlertNotificationMessage,
    ProviderAcceptance,
)
from app.alerts.registry import HTDY_ALERT_RULE_CODE


def message(symbol="AO", frequency="60m"):
    now = datetime(2026, 10, 15, 7, tzinfo=UTC)
    return AlertNotificationMessage(
        HTDY_ALERT_RULE_CODE,
        symbol,
        symbol,
        symbol + "2701",
        frequency,
        now,
        now,
        ("buy",),
        now,
    )


def test_prepared_batch_freezes_payload_and_member_identity():
    sent = []

    class Transport:
        def send(self, delivery):
            sent.append(delivery)

    dispatcher = AlertNotificationDispatcher(Transport())
    prepared = dispatcher.prepare_batch((message(), message("AL")), event_ids=(11, 12))
    assert "Event 11" in prepared.delivery.content
    assert "Event 12" in prepared.delivery.content
    dispatcher.send_prepared_batch(prepared)
    assert sent == [prepared.delivery]


def test_batch_cannot_cross_frequency_or_bar():
    dispatcher = AlertNotificationDispatcher(None)
    with pytest.raises(ValueError, match="BATCH_KEY"):
        dispatcher.prepare_batch((message(), message(frequency="30m")))
    assert notification_batch_key(
        FrozenHandoff(1, message(), "one", 19)
    ) != notification_batch_key(FrozenHandoff(2, message(frequency="30m"), "two", 19))


@pytest.fixture
def store(tmp_path):
    import os
    from uuid import uuid4
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    url = os.environ.get("GUIYI_ALERT_ISOLATED_TEST_URL")
    schema = "alert_v2_" + uuid4().hex
    if url:
        parsed = make_url(url)
        assert parsed.host == "127.0.0.1" and parsed.port == 15475 and parsed.database == "guiyi_alert_isolated_test"
        engine = create_engine(url, connect_args={"options": "-c search_path=" + schema})
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA " + schema))
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'receipts.db'}",
            connect_args={"check_same_thread": False},
        )
    Base.metadata.create_all(engine, tables=[AlertRule.__table__, AlertEvent.__table__])
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session:
        session.add(AlertRule(id=1, rule_code=HTDY_ALERT_RULE_CODE))
        session.commit()
    try:
        yield sessions
    finally:
        if url:
            with engine.begin() as connection:
                connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        engine.dispose()


def seed(sessions, event_id, msg=None, status="HANDOFF_PENDING"):
    msg = msg or message(str(event_id))
    with sessions() as session:
        session.add(
            AlertEvent(
                id=event_id,
                rule_id=1,
                symbol=msg.symbol,
                contract=msg.contract,
                frequency=msg.frequency,
                bar_end=msg.bar_end,
                detected_at=msg.detected_at,
                result_codes=list(msg.result_codes),
                source_observed_at=msg.source_observed_at,
                source_observation_id=f"obs-{event_id}",
                notification_status=status,
                notification_policy_version=NOTIFICATION_POLICY_VERSION,
                notification_claimed_at=msg.detected_at,
                notification_generation=19,
            )
        )
        session.commit()
    return FrozenHandoff(event_id, msg, f"obs-{event_id}", 19)


def status(sessions, event_id):
    with sessions() as session:
        row = session.get(AlertEvent, event_id)
        return row.notification_status


def eventually(predicate):
    end = monotonic() + 3
    while monotonic() < end:
        if predicate():
            return
        sleep(0.005)
    assert predicate()


def handoff(store, transport, **kw):
    return BoundedNotificationHandoff(
        session_factory=store,
        sender=AlertNotificationDispatcher(transport),
        assert_owned=lambda: None,
        clock=lambda: message().detected_at,
        generation=19,
        coalesce_seconds=0.05,
        **kw,
    )


def test_same_bar_batch_claims_all_before_single_http(store):
    calls = []

    class Transport:
        def send(self, delivery):
            assert [status(store, n) for n in (1, 2)] == ["ATTEMPTED_UNKNOWN"] * 2
            calls.append(delivery)
            return ProviderAcceptance("receipt")

    worker = handoff(store, Transport())
    worker.start()
    try:
        worker.submit(seed(store, 1))
        worker.submit(seed(store, 2))
        eventually(lambda: status(store, 2) == "PROVIDER_ACCEPTED")
        assert len(calls) == 1
        with store() as session:
            rows = [session.get(AlertEvent, n) for n in (1, 2)]
            assert rows[0].notification_batch_id == rows[1].notification_batch_id
            assert all(
                row.notification_attempted_at and row.notification_finished_at
                for row in rows
            )
    finally:
        worker.close_and_drain()


def test_blocked_http_does_not_block_admission_and_overflow_is_terminal(store):
    entered, release = Event(), Event()

    class Transport:
        def send(self, delivery):
            entered.set()
            assert release.wait(3)
            return ProviderAcceptance("receipt")

    worker = handoff(store, Transport(), capacity=2)
    worker.start()
    try:
        worker.submit(seed(store, 1))
        assert entered.wait(2)
        assert worker.submit(seed(store, 2))
        assert not worker.submit(seed(store, 3))
        assert status(store, 3) == "OVERFLOW_NO_SEND"
        done = Event()
        closer = Thread(target=lambda: (worker.close_and_drain(), done.set()))
        closer.start()
        eventually(lambda: status(store, 2) == "DRAIN_CANCELLED_NO_SEND")
        assert not done.is_set()
        release.set()
        closer.join(3)
        assert done.is_set()
        assert status(store, 1) == "PROVIDER_ACCEPTED"
        with store() as session:
            assert session.get(AlertEvent, 2).notification_attempted_at is None
    finally:
        release.set()
        worker.close_and_drain()


def test_expiry_uses_each_member_original_source_time(store):
    calls = []

    class Transport:
        def send(self, delivery):
            calls.append(delivery)
            return ProviderAcceptance()

    worker = handoff(store, Transport())
    worker.start()
    try:
        old = replace(
            message("OLD"),
            source_observed_at=message().detected_at - timedelta(seconds=31),
        )
        worker.submit(seed(store, 1, old))
        worker.submit(seed(store, 2))
        eventually(lambda: status(store, 2) == "PROVIDER_ACCEPTED")
        assert status(store, 1) == "EXPIRED_NO_SEND"
        assert len(calls) == 1 and "OLD" not in calls[0].content
    finally:
        worker.close_and_drain()


def test_restart_only_closes_orphans_and_does_not_retry_attempted(store):
    seed(store, 1)
    seed(store, 2, status="ATTEMPTED_UNKNOWN")

    class Transport:
        def send(self, delivery):
            pytest.fail("restart must never resend")

    worker = handoff(store, Transport())
    worker.start()
    worker.close_and_drain()
    assert status(store, 1) == "LOST_HANDOFF_NO_SEND"
    assert status(store, 2) == "ATTEMPTED_UNKNOWN"


def test_transport_failure_is_terminal_and_not_retried(store):
    calls = []

    class Transport:
        def send(self, delivery):
            calls.append(delivery)
            raise TimeoutError("private provider text")

    results = []
    worker = handoff(store, Transport(), on_result=lambda *args: results.append(args))
    worker.start()
    try:
        worker.submit(seed(store, 1))
        eventually(lambda: status(store, 1) == "FAILED_OR_UNKNOWN")
    finally:
        worker.close_and_drain()
    assert len(calls) == 1
    assert results == [
        ((1,), "ATTEMPTED_UNKNOWN", None),
        ((1,), "FAILED_OR_UNKNOWN", "UNKNOWN"),
    ]


def test_receipt_identity_mismatch_fails_closed_before_http(store):
    class Transport:
        def send(self, delivery):
            pytest.fail("mismatched event cannot send")

    worker = handoff(store, Transport())
    worker.start()
    item = seed(store, 1)
    worker.submit(replace(item, message=replace(item.message, result_codes=("sell",))))
    eventually(lambda: worker.fatal_error is not None)
    with pytest.raises(RuntimeError, match="HANDOFF_FATAL"):
        worker.check_health()
    with pytest.raises(RuntimeError, match="HANDOFF_FATAL"):
        worker.close_and_drain()
    assert status(store, 1) == "HANDOFF_PENDING"


def test_payload_split_has_disjoint_complete_event_members(store):
    import re

    calls = []

    class Transport:
        def send(self, delivery):
            assert len(delivery.content.encode("utf-8")) <= 16000
            calls.append(delivery)
            return ProviderAcceptance()

    worker = handoff(store, Transport())
    items = tuple(
        seed(store, n, replace(message(str(n)), product_name="量" * 2000))
        for n in range(1, 9)
    )
    worker._deliver(items)
    members = [
        int(value)
        for call in calls
        for value in re.findall(r"Event (\d+)\n", call.content)
    ]
    assert sorted(members) == list(range(1, 9))
    assert len(calls) > 1
    assert all(status(store, n) == "PROVIDER_ACCEPTED" for n in range(1, 9))


def test_post_claim_deadline_recheck_never_calls_http(store):
    class Transport:
        def send(self, delivery):
            pytest.fail("commit exhausted the deadline")

    now = message().detected_at
    worker = handoff(store, Transport())

    def on_result(ids, receipt_status, diagnostic):
        if receipt_status == "ATTEMPTED_UNKNOWN":
            worker._clock = lambda: now + timedelta(seconds=31)

    worker._on_result = on_result
    item = seed(store, 1)
    worker._deliver((item,))
    assert status(store, 1) == "CLAIM_EXPIRED_NO_SEND"


def test_result_commit_failure_stays_unknown_and_halts_worker(store):
    from contextlib import contextmanager

    sent = Event()

    class Transport:
        def send(self, delivery):
            sent.set()
            return ProviderAcceptance("receipt")

    @contextmanager
    def failing_sessions():
        with store() as session:
            original = session.commit

            def commit():
                if sent.is_set():
                    raise RuntimeError("simulated commit unknown")
                original()

            session.commit = commit
            yield session

    worker = handoff(store, Transport())
    worker._sessions = failing_sessions
    worker.start()
    worker.submit(seed(store, 1))
    eventually(lambda: worker.fatal_error is not None)
    assert sent.is_set() and status(store, 1) == "ATTEMPTED_UNKNOWN"
    with pytest.raises(RuntimeError, match="HANDOFF_FATAL"):
        worker.close_and_drain()
    replacement = handoff(store, Transport())
    replacement.start()
    replacement.close_and_drain()
    assert status(store, 1) == "ATTEMPTED_UNKNOWN"


def test_terminal_preimage_mismatch_is_fatal_and_reports_no_success(store):
    results = []
    worker = handoff(store, None, on_result=lambda *args: results.append(args))
    item = seed(store, 1)
    with store() as session:
        session.get(AlertEvent, 1).notification_generation = 18
        session.commit()
    with pytest.raises(RuntimeError, match="RECEIPT_IDENTITY_INVALID"):
        worker._terminal((item,), "OVERFLOW_NO_SEND")
    assert worker.fatal_error is not None
    assert status(store, 1) == "HANDOFF_PENDING"
    assert not results


def test_terminal_rowcount_conflict_rolls_back_and_closes_admission(store):
    from contextlib import contextmanager
    from types import SimpleNamespace

    worker = handoff(store, None)
    item = seed(store, 1)

    @contextmanager
    def conflict_sessions():
        with store() as session:
            original = session.execute

            def execute(statement, *args, **kwargs):
                result = original(statement, *args, **kwargs)
                return SimpleNamespace(rowcount=0) if statement.is_update else result

            session.execute = execute
            yield session

    worker._sessions = conflict_sessions
    with pytest.raises(RuntimeError, match="TERMINAL_CONFLICT"):
        worker._terminal((item,), "OVERFLOW_NO_SEND")
    assert worker.fatal_error is not None
    assert status(store, 1) == "HANDOFF_PENDING"


def test_payload_reports_actual_handoff_delay(store):
    calls = []

    class Transport:
        def send(self, delivery):
            calls.append(delivery)
            return ProviderAcceptance()

    worker = handoff(store, Transport())
    item = seed(store, 1)
    worker._clock = lambda: message().detected_at + timedelta(seconds=17)
    worker._deliver((item,))
    assert "处理延迟：17.0秒" in calls[0].content
    assert item.message.notification_checked_at is None
