from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.signal import SignalEvent, SignalNotification
from app.services.notification_dispatch import NotificationDispatchService
from app.tasks import notifications as notification_tasks


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def enqueue(self, func: str, event_id: int, **kwargs) -> None:
        self.jobs.append({"func": func, "event_id": event_id, **kwargs})


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_dispatch_enqueues_only_gate_passed_live_event_once() -> None:
    factory = _session_factory()
    queue = FakeQueue()
    with factory() as session:
        live = _event(event_key="live", source_mode="live_confirmed")
        historical = _event(event_key="historical", source_mode="jm_v1b_historical_replay")
        blocked = _event(event_key="blocked", source_mode="live_confirmed", actual_contract="JM.MAIN")
        session.add_all([live, historical, blocked])
        session.commit()

        first = NotificationDispatchService(session, queue).enqueue_due(enabled=True)
        second = NotificationDispatchService(session, queue).enqueue_due(enabled=True)

        assert first.new_enqueued == 1
        assert first.blocked == 1
        assert second.new_enqueued == 0
        assert [job["event_id"] for job in queue.jobs] == [live.id]
        assert queue.jobs[0]["job_id"] == f"live-wechat:{live.id}:attempt:1"
        notification = session.scalar(select(SignalNotification))
        assert notification is not None
        assert notification.status == "pending"
        assert notification.attempt_count == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 1


def test_dispatch_requeues_due_retry_and_stale_pending_only() -> None:
    factory = _session_factory()
    queue = FakeQueue()
    now = datetime.now(UTC)
    with factory() as session:
        due_event = _event(event_key="due", source_mode="live_confirmed")
        future_event = _event(event_key="future", source_mode="live_confirmed")
        stale_event = _event(event_key="stale", source_mode="live_confirmed")
        session.add_all([due_event, future_event, stale_event])
        session.flush()
        due = _notification(due_event, status="retry_pending", attempts=1, next_retry_at=now - timedelta(seconds=1))
        future = _notification(future_event, status="retry_pending", attempts=1, next_retry_at=now + timedelta(minutes=5))
        stale = _notification(stale_event, status="pending", attempts=0)
        stale.created_at = now - timedelta(minutes=2)
        session.add_all([due, future, stale])
        session.commit()

        result = NotificationDispatchService(session, queue, now=now).enqueue_due(enabled=True)

        assert result.retry_enqueued == 2
        assert [job["event_id"] for job in queue.jobs] == [stale_event.id, due_event.id]
        assert {job["job_id"] for job in queue.jobs} == {
            f"live-wechat:{due_event.id}:attempt:2",
            f"live-wechat:{stale_event.id}:attempt:1",
        }
        assert future_event.id not in result.event_ids


def test_disabled_dispatch_has_no_database_or_queue_side_effect() -> None:
    factory = _session_factory()
    queue = FakeQueue()
    with factory() as session:
        session.add(_event(event_key="live", source_mode="live_confirmed"))
        session.commit()
        result = NotificationDispatchService(session, queue).enqueue_due(enabled=False)
        assert result.status == "disabled"
        assert queue.jobs == []
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_notification_task_disabled_does_not_open_database(monkeypatch) -> None:
    monkeypatch.delenv("GUIYI_WECHAT_AUTOSEND_ENABLED", raising=False)

    def fail_session():
        raise AssertionError("disabled notification task must not open database")

    monkeypatch.setattr(notification_tasks, "SessionLocal", fail_session)
    assert notification_tasks.deliver_live_notification_task(7) == {
        "event_id": 7,
        "status": "disabled",
        "attempt_count": 0,
    }


def _event(*, event_key: str, source_mode: str, actual_contract: str = "JM2609") -> SignalEvent:
    return SignalEvent(
        event_key=event_key,
        event_type="signal_created",
        signal_id=1,
        task_no=None,
        source_mode=source_mode,
        strategy_name="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1.0.0",
        watchlist_code="jm_v1b_live",
        symbol="jm",
        contract=actual_contract,
        product="jm",
        continuous_contract="JM.MAIN",
        actual_contract=actual_contract,
        dominant_mapping_date=date(2026, 7, 10),
        exchange="DCE",
        period="15m",
        signal_time=datetime(2026, 7, 10, 1, 30),
        bar_start=datetime(2026, 7, 10, 1, 15),
        bar_end=datetime(2026, 7, 10, 1, 30),
        trigger_price=1234.5,
        provider="rqdata",
        source="live_db_actual_contract",
        direction="long",
        signal_status="entry_signal",
        lifecycle_status="new",
        score_bucket=80,
        data_role="primary",
        quality_status={"status": "passed"},
        payload={"live_observation": {"observation_only": True, "auto_order": False}},
    )


def _notification(
    event: SignalEvent,
    *,
    status: str,
    attempts: int,
    next_retry_at: datetime | None = None,
) -> SignalNotification:
    return SignalNotification(
        event_id=event.id,
        signal_id=event.signal_id,
        task_no=None,
        dedupe_key=f"enterprise_wechat:signal_event:{event.id}",
        event_type=event.event_type,
        channel="enterprise_wechat",
        status=status,
        payload={},
        attempt_count=attempts,
        max_attempts=3,
        next_retry_at=next_retry_at,
    )
