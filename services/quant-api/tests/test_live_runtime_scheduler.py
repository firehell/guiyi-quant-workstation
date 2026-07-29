from __future__ import annotations

from datetime import UTC, date, datetime
import json
import logging

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveIngestCheckpoint, LiveMinuteBar
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.runtime_scheduler import _verify_polling_trading_day, execute_guarded_cycle, execute_notification_dispatch, main
from app.services.live_signal_event_gate import LiveSignalEventGateError
from app.services.live_runtime import LiveRuntimeCycleService
from app.services.trading_session_clock import SessionWindow, TradingSessionDecision


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


class FakeTargetResolver:
    required_date = None

    def resolve_ready_actual_contract(self, *, product: str, required_date: date):
        self.required_date = required_date
        return {
            "product": product,
            "actual_contract": "JM2609",
            "continuous_contract": "jm.MAIN",
            "dominant_mapping_date": "2026-07-07",
            "trading_parameter_status": {"exchange_code": "DCE"},
        }


class OpenClock:
    def latest_completed_trading_day(self, *, product: str, exchange: str, now: datetime):
        return date(2026, 7, 6)

    def decision(self, *, product: str, exchange: str, now: datetime):
        return TradingSessionDecision(
            product=product,
            exchange=exchange,
            now=now,
            phase="open",
            should_poll=True,
            is_trading_time=True,
            trading_day=date(2026, 7, 7),
            session_name="day",
            session_start=datetime(2026, 7, 7, 9, 0),
            session_end=datetime(2026, 7, 7, 15, 0),
            final_close_at=datetime(2026, 7, 7, 15, 0),
            next_open_at=None,
            reason="fixture",
        )

    def windows_for_trading_day(self, trading_day, *, product: str, exchange: str):
        return [SessionWindow(trading_day=trading_day, name="day", start=datetime(2026, 7, 7, 9, 0), end=datetime(2026, 7, 7, 15, 0))]

    def trading_day_closed(self, trading_day, *, product: str, exchange: str, now: datetime):
        return False

    def expected_minute_count(self, trading_day, *, product: str, exchange: str):
        return 360

    def week_trading_days(self, value, *, exchange: str):
        return [], False


class ClosedClock(OpenClock):
    def decision(self, *, product: str, exchange: str, now: datetime):
        decision = super().decision(product=product, exchange=exchange, now=now)
        return TradingSessionDecision(
            **{
                **decision.__dict__,
                "phase": "closed",
                "should_poll": False,
                "is_trading_time": False,
                "reason": "fixture_closed",
            }
        )


class FakeClient:
    def __init__(self):
        self.calls = []

    def contract_bars(self, contract, start_date, end_date, frequency):
        self.calls.append((contract, start_date, end_date, frequency))
        return pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp("2026-07-07 09:01:00"),
                    "trading_day": "2026-07-07",
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 10,
                    "open_interest": 20,
                }
            ]
        )


def test_live_cycle_writes_only_live_tables() -> None:
    SessionLocal = _session_factory()
    client = FakeClient()
    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=client,
            now=datetime(2026, 7, 7, 9, 3),
            target_resolver=FakeTargetResolver(),
            trading_clock=OpenClock(),
        ).run_once(enabled=True)
        session.commit()

        assert session.scalar(select(func.count()).select_from(LiveMinuteBar)) == 1
        assert session.scalar(select(func.count()).select_from(LiveIngestCheckpoint)) == 1
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0

    assert result.status == "success"
    assert result.actual_contract == "JM2609"
    assert result.required_historical_date == "2026-07-06"
    assert result.dominant_mapping_date == "2026-07-07"
    assert result.writes_historical_active is False
    assert result.writes_signal_event is False
    assert result.sends_notification is False
    assert client.calls[0][2] == date(2026, 7, 7)


def test_live_cycle_rejects_the_superseded_legacy_signal_event_runtime_path() -> None:
    SessionLocal = _session_factory()

    def fail_client():
        raise AssertionError("legacy signal path must fail before ingest")

    with SessionLocal() as session:
        with pytest.raises(
            RuntimeError,
            match="legacy_signal_event_runtime_disabled",
        ):
            LiveRuntimeCycleService(
                session=session,
                client=fail_client,
                now=datetime(2026, 7, 7, 9, 3),
                target_resolver=FakeTargetResolver(),
                trading_clock=OpenClock(),
            ).run_once(enabled=True, persist_signal_events=True)


def test_live_cycle_calls_only_the_independent_htdy_event_handler() -> None:
    SessionLocal = _session_factory()
    calls = []

    class Handler:
        def evaluate_and_persist(
            self,
            *,
            trading_day,
            actual_contract,
            detected_at,
        ):
            calls.append((trading_day, actual_contract, detected_at))
            return {
                "created": 1,
                "changed": 0,
                "unchanged": 0,
                "blocked": 0,
                "event_ids": [71],
            }

    now = datetime(2026, 7, 7, 9, 3)
    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=FakeClient(),
            now=now,
            target_resolver=FakeTargetResolver(),
            trading_clock=OpenClock(),
        ).run_once(
            enabled=True,
            signal_event_handler=Handler(),
        )

    assert calls == [(date(2026, 7, 7), "JM2609", now)]
    assert result.signal_events == {
        "created": 1,
        "changed": 0,
        "unchanged": 0,
        "blocked": 0,
        "event_ids": [71],
    }
    assert result.writes_signal_event is True


def test_htdy_runtime_handler_composes_step2_and_step3_without_legacy_evaluator() -> None:
    from app.services.htdy_runtime_event_handler import HtDyRuntimeEventHandler

    calls = []
    snapshot = object()
    evaluation = object()
    write_result = object()

    class Resolver:
        def resolve(self, **kwargs):
            calls.append(("resolve", kwargs))
            return snapshot

    class Evaluator:
        def evaluate(self, value, **kwargs):
            calls.append(("evaluate", value, kwargs))
            return evaluation

    class Writer:
        def persist(self, value):
            calls.append(("persist", value))
            return write_result

    detected_at = datetime(2026, 7, 7, 9, 3)
    result = HtDyRuntimeEventHandler(
        resolver=Resolver(),
        evaluator=Evaluator(),
        writer=Writer(),
    ).evaluate_and_persist(
        trading_day=date(2026, 7, 7),
        actual_contract="JM2609",
        detected_at=detected_at,
    )

    assert result is write_result
    assert calls == [
        (
            "resolve",
            {
                "trading_day": date(2026, 7, 7),
                "detected_at": detected_at,
                "requested_contract": "JM2609",
            },
        ),
        ("evaluate", snapshot, {"detected_at": detected_at}),
        ("persist", evaluation),
    ]


def test_closed_bar_runtime_handler_skips_partial_and_repeated_bucket(
    caplog,
) -> None:
    """Break caught: evaluating every 1m poll instead of once per 15m close."""

    from types import SimpleNamespace

    caplog.set_level(logging.INFO)

    from app.services.htdy_runtime_event_handler import (
        HtDyClosedBarRuntimeEventHandler,
    )

    close = datetime(2026, 7, 27, 9, 15)
    partial = SimpleNamespace(
        buckets=(
            SimpleNamespace(
                status="partial",
                identity=SimpleNamespace(bucket_end=close),
            ),
        )
    )
    confirmed = SimpleNamespace(
        buckets=(
            SimpleNamespace(
                status="confirmed",
                identity=SimpleNamespace(bucket_end=close),
            ),
        )
    )
    snapshots = iter((partial, confirmed, confirmed))
    calls: list[str] = []

    class Resolver:
        def resolve(self, **kwargs):
            assert kwargs["confirmed_only"] is True
            return next(snapshots)

    class Evaluator:
        def evaluate(self, value, **kwargs):
            calls.append("evaluate")
            return object()

    class Writer:
        def persist(self, value):
            calls.append("persist")
            return SimpleNamespace(
                created=1,
                unchanged=0,
                blocked=0,
                event_ids=(71,),
            )

    handler = HtDyClosedBarRuntimeEventHandler(
        resolver=Resolver(),
        evaluator=Evaluator(),
        writer=Writer(),
    )
    kwargs = {
        "trading_day": date(2026, 7, 27),
        "actual_contract": "JM2609",
        "detected_at": datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
    }

    first = handler.evaluate_and_persist(**kwargs)
    second = handler.evaluate_and_persist(**kwargs)
    third = handler.evaluate_and_persist(**kwargs)

    assert first.created == 0
    assert second.created == 1
    assert third.created == 0
    assert calls == ["evaluate", "persist"]
    summaries = [
        record.message
        for record in caplog.records
        if "htdy_close_evaluation_summary " in record.message
    ]
    assert len(summaries) == 1
    assert '"bucket_status":"confirmed"' in summaries[0]
    assert '"partial_allowed":false' in summaries[0]
    assert '"signal_changed":0' in summaries[0]


def test_closed_bar_runtime_checkpoint_survives_fresh_session_handlers() -> None:
    """Break caught: recreating a handler caused every 20s poll to re-evaluate."""

    from types import SimpleNamespace

    from app.services.htdy_runtime_event_handler import (
        ClosedBarEvaluationCheckpoint,
        HtDyClosedBarRuntimeEventHandler,
    )

    close = datetime(2026, 7, 27, 9, 15)
    snapshot = SimpleNamespace(
        buckets=(
            SimpleNamespace(
                status="confirmed",
                identity=SimpleNamespace(bucket_end=close),
            ),
        )
    )
    calls: list[str] = []

    class Resolver:
        def resolve(self, **_kwargs):
            return snapshot

    class Evaluator:
        def evaluate(self, value, **_kwargs):
            calls.append("evaluate")
            return value

    class Writer:
        def persist(self, _value):
            calls.append("persist")
            return SimpleNamespace(
                created=0,
                unchanged=0,
                blocked=0,
                event_ids=(),
            )

    checkpoint = ClosedBarEvaluationCheckpoint()
    kwargs = {
        "trading_day": date(2026, 7, 27),
        "actual_contract": "JM2609",
        "detected_at": datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
    }
    for _session_poll in range(2):
        handler = HtDyClosedBarRuntimeEventHandler(
            resolver=Resolver(),
            evaluator=Evaluator(),
            writer=Writer(),
            checkpoint=checkpoint,
        )
        handler.evaluate_and_persist(**kwargs)

    assert calls == ["evaluate", "persist"]


def test_closed_bar_runtime_handler_does_not_backfill_before_activation() -> None:
    """A restart may see an old close, but schema-v6 must not evaluate it."""

    from types import SimpleNamespace

    from app.services.htdy_runtime_event_handler import (
        HtDyClosedBarRuntimeEventHandler,
    )

    old_close = datetime(2026, 7, 28, 22, 15)
    allowed_close = datetime(2026, 7, 28, 22, 30)
    snapshots = iter(
        SimpleNamespace(
            buckets=(
                SimpleNamespace(
                    status="confirmed",
                    identity=SimpleNamespace(bucket_end=value),
                ),
            )
        )
        for value in (old_close, allowed_close)
    )
    calls: list[str] = []

    class Resolver:
        def resolve(self, **_kwargs):
            return next(snapshots)

    class Evaluator:
        def evaluate(self, value, **_kwargs):
            calls.append("evaluate")
            return value

    class Writer:
        def persist(self, _value):
            calls.append("persist")
            return SimpleNamespace(
                created=0,
                unchanged=0,
                blocked=0,
                event_ids=(),
            )

    handler = HtDyClosedBarRuntimeEventHandler(
        resolver=Resolver(),
        evaluator=Evaluator(),
        writer=Writer(),
        allowed_bucket_ends={allowed_close},
    )
    kwargs = {
        "trading_day": date(2026, 7, 29),
        "actual_contract": "JM2609",
        "detected_at": datetime(2026, 7, 28, 14, 31, tzinfo=UTC),
    }

    skipped = handler.evaluate_and_persist(**kwargs)
    evaluated = handler.evaluate_and_persist(**kwargs)

    assert skipped.created == 0
    assert evaluated.created == 0
    assert calls == ["evaluate", "persist"]


def test_htdy_runtime_handler_builds_production_snapshot_resolver_with_project_root() -> None:
    from app.core.env import PROJECT_ROOT
    from app.services.htdy_runtime_event_handler import HtDyRuntimeEventHandler

    handler = HtDyRuntimeEventHandler(session=object())

    assert handler.resolver.project_root == PROJECT_ROOT


def test_htdy_runtime_handler_emits_one_bounded_observation_summary(
    caplog,
) -> None:
    from types import SimpleNamespace

    from app.services.htdy_runtime_event_handler import (
        HtDyRuntimeEventHandler,
    )

    bucket = SimpleNamespace(
        status="partial",
        identity=SimpleNamespace(
            bucket_start=datetime(2026, 7, 27, 9, 0),
            bucket_end=datetime(2026, 7, 27, 9, 15),
        ),
    )
    snapshot = SimpleNamespace(
        trading_day=date(2026, 7, 27),
        actual_contract="JM2609",
        snapshot_sha256="a" * 64,
        buckets=(bucket,),
    )
    evaluation = SimpleNamespace(candidates=(object(), object()), blocked=())
    write_result = SimpleNamespace(
        created=1,
        unchanged=1,
        blocked=0,
        event_ids=(71,),
    )

    class Resolver:
        def resolve(self, **kwargs):
            return snapshot

    class Evaluator:
        def evaluate(self, value, **kwargs):
            return evaluation

    class Writer:
        def persist(self, value):
            return write_result

    with caplog.at_level("INFO"):
        HtDyRuntimeEventHandler(
            resolver=Resolver(),
            evaluator=Evaluator(),
            writer=Writer(),
        ).evaluate_and_persist(
            trading_day=date(2026, 7, 27),
            actual_contract="JM2609",
            detected_at=datetime(2026, 7, 27, 9, 3),
        )

    record = next(
        item
        for item in caplog.records
        if item.message.startswith("htdy_observation_summary ")
    )
    payload = __import__("json").loads(
        record.message.removeprefix("htdy_observation_summary ")
    )
    assert payload == {
        "trading_day": "2026-07-27",
        "actual_contract": "JM2609",
        "bucket_start": "2026-07-27T09:00:00",
        "bucket_end": "2026-07-27T09:15:00",
        "bucket_status": "partial",
        "snapshot_sha256": "a" * 64,
        "candidate_count": 2,
        "blocked_count": 0,
        "created": 1,
        "unchanged": 1,
        "changed": 0,
        "latest_event_id": 71,
    }


class StaleClient(FakeClient):
    def contract_bars(self, contract, start_date, end_date, frequency):
        frame = super().contract_bars(contract, start_date, end_date, frequency)
        frame["trading_day"] = "2026-07-06"
        return frame


def test_live_cycle_fails_closed_when_current_trading_day_bar_is_missing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=StaleClient(),
            now=datetime(2026, 7, 7, 9, 3),
            target_resolver=FakeTargetResolver(),
            trading_clock=OpenClock(),
        ).run_once(enabled=True)
        session.commit()

        assert session.scalar(select(func.count()).select_from(LiveMinuteBar)) == 0

    assert result.status == "failed"
    assert result.reason == "current_trading_day_confirmed_bar_missing"
    assert result.ingest is not None
    assert result.ingest["confirmed_candidates"] == 0


def test_closed_market_does_not_construct_rqdata_client() -> None:
    SessionLocal = _session_factory()

    def fail_client():
        raise AssertionError("closed market must not construct RQData client")

    class FailTargetResolver:
        def resolve_ready_actual_contract(self, **kwargs):
            raise AssertionError("closed market must not resolve the next historical live target")

    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=fail_client,
            now=datetime(2026, 7, 7, 12, 0),
            target_resolver=FailTargetResolver(),
            trading_clock=ClosedClock(),
        ).run_once(enabled=True)

    assert result.status == "idle"
    assert result.actual_contract is None
    assert result.required_historical_date is None


def test_scheduler_dry_run_constructs_no_external_clients(capsys) -> None:
    def fail_factory():
        raise AssertionError("dry-run must not construct external dependencies")

    exit_code = main(
        ["--dry-run"],
        environ={"GUIYI_LIVE_RUNTIME_ENABLED": "1"},
        session_factory=fail_factory,
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["would_construct_rqdata_client"] is False
    assert payload["would_open_database"] is False
    assert payload["would_write_live_tables"] is False


def test_scheduler_once_blocks_forbidden_write_flags_before_factories(capsys) -> None:
    def fail_factory():
        raise AssertionError("forbidden flags must stop before external dependencies")

    exit_code = main(
        ["--once", "--confirm-live-write"],
        environ={
            "GUIYI_LIVE_RUNTIME_ENABLED": "true",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
            "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED": "false",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
        },
        session_factory=fail_factory,
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload == {
        "status": "blocked",
        "reason": "forbidden_runtime_flags_enabled",
        "enabled_flags": ["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"],
    }


def test_scheduler_run_requires_signal_gate_packet_before_factories(capsys, monkeypatch) -> None:
    def fail_factory():
        raise AssertionError("missing signal gate must stop before external dependencies")

    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler.start",
        lambda self: (_ for _ in ()).throw(AssertionError("scheduler must not start")),
    )
    exit_code = main(
        ["--run", "--confirm-live-write"],
        environ={
            "GUIYI_LIVE_RUNTIME_ENABLED": "true",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
        },
        session_factory=fail_factory,
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload == {"status": "blocked", "reason": "signal_event_approval_packet_and_hash_required"}


def test_scheduler_run_blocks_wechat_autosend_before_factories(capsys, tmp_path, monkeypatch) -> None:
    def fail_factory():
        raise AssertionError("autosend must stop before external dependencies")

    packet = tmp_path / "packet.json"
    packet.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler.start",
        lambda self: (_ for _ in ()).throw(AssertionError("scheduler must not start")),
    )
    exit_code = main(
        [
            "--run",
            "--confirm-live-write",
            "--approval-packet",
            str(packet),
            "--approval-hash",
            "a" * 64,
        ],
        environ={
            "GUIYI_LIVE_RUNTIME_ENABLED": "true",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": "true",
        },
        session_factory=fail_factory,
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload == {"status": "blocked", "reason": "wechat_autosend_must_be_false"}


def test_scheduler_startup_verifies_gate_without_daily_write_phase(
    monkeypatch,
    tmp_path,
) -> None:
    SessionLocal = _session_factory()
    packet = tmp_path / "service_parent_packet.json"
    packet.write_text("{}", encoding="utf-8")
    phases: list[str] = []

    def gate(session, *, phase, result=None):
        del session, result
        phases.append(phase)
        return {"gate_status": "verified"}

    monkeypatch.setattr(
        "app.runtime_scheduler._build_signal_gate",
        lambda **kwargs: gate,
    )
    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler.start",
        lambda self: None,
    )

    exit_code = main(
        [
            "--run",
            "--confirm-live-write",
            "--approval-packet",
            str(packet),
            "--approval-hash",
            "a" * 64,
        ],
        environ={
            "GUIYI_LIVE_RUNTIME_ENABLED": "true",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
        },
        session_factory=SessionLocal,
        client_factory=lambda: object(),
        redis_factory=lambda: object(),
    )

    assert exit_code == 0
    assert phases == ["verify"]


@pytest.mark.parametrize("schema_version", (6, 7))
def test_scheduler_routes_remaining_window_gate(
    monkeypatch,
    tmp_path,
    schema_version,
) -> None:
    import sys
    from types import SimpleNamespace

    from app.runtime_scheduler import _build_signal_gate

    packet = tmp_path / "remaining_parent.json"
    packet.write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "packet_type": (
                    "htdy_s6_10_remaining_trading_day_parent"
                ),
            }
        ),
        encoding="utf-8",
    )
    expected = object()
    monkeypatch.setitem(
        sys.modules,
        "app.services.htdy_s6_10_remaining_window_runtime_gate",
        SimpleNamespace(build_runtime_gate=lambda **_kwargs: expected),
    )

    assert (
        _build_signal_gate(
            approval_packet=packet,
            approval_hash="a" * 64,
            environ={},
        )
        is expected
    )


def test_scheduler_routes_approval_d_long_running_gate(
    monkeypatch,
    tmp_path,
) -> None:
    import sys
    from types import SimpleNamespace

    from app.runtime_scheduler import _build_signal_gate

    packet = tmp_path / "approval-d-request.json"
    packet.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "request_type": (
                    "htdy_s6_10_approval_d_no_code_promotion"
                ),
            }
        ),
        encoding="utf-8",
    )
    expected = object()
    monkeypatch.setitem(
        sys.modules,
        "app.services.htdy_s6_10_long_running_runtime_gate",
        SimpleNamespace(build_runtime_gate=lambda **_kwargs: expected),
    )

    assert (
        _build_signal_gate(
            approval_packet=packet,
            approval_hash="a" * 64,
            environ={},
        )
        is expected
    )


def test_signal_gate_blocks_wrong_open_trading_day_before_runtime_cycle() -> None:
    class Decision:
        should_poll = True
        trading_day = date(2026, 7, 25)

    with pytest.raises(LiveSignalEventGateError, match="runtime_trading_day_mismatch"):
        _verify_polling_trading_day(Decision(), target_trading_day="2026-07-24")

    class ClosedDecision:
        should_poll = False
        trading_day = None

    _verify_polling_trading_day(ClosedDecision(), target_trading_day="2026-07-24")


class BusyLock:
    def acquire(self, *, blocking: bool):
        return False


class BusyRedis:
    def lock(self, *args, **kwargs):
        return BusyLock()


def test_scheduler_singleton_lock_blocks_duplicate_cycle() -> None:
    def fail_factory():
        raise AssertionError("busy lock must stop before DB/RQData construction")

    result = execute_guarded_cycle(
        product="jm",
        poll_seconds=20,
        session_factory=fail_factory,
        client_factory=fail_factory,
        redis_factory=BusyRedis,
    )

    assert result == {"status": "lock_busy", "product": "jm", "singleton": True}


class AcquiredLock:
    def acquire(self, *, blocking: bool):
        return True

    def release(self):
        return None


class RecordingRedis:
    def __init__(self):
        self.heartbeats = []

    def lock(self, *args, **kwargs):
        return AcquiredLock()

    def setex(self, key, ttl, value):
        self.heartbeats.append(json.loads(value))


def test_signal_gate_post_write_failure_rolls_back_entire_cycle(monkeypatch) -> None:
    SessionLocal = _session_factory()
    connection = RecordingRedis()

    def run_once(self, **kwargs):
        self.session.add(
            SignalNotification(
                dedupe_key="forbidden",
                event_type="signal_created",
                channel="enterprise_wechat",
                status="pending",
                payload={},
            )
        )
        self.session.flush()

        class Result:
            def to_dict(self):
                return {
                    "status": "success",
                    "product": "jm",
                    "trading_day": "2026-07-24",
                    "signal_events": {"created": 1, "changed": 0, "unchanged": 0, "blocked": 0, "event_ids": [1]},
                }

        return Result()

    phases = []

    def gate(session, *, phase, result=None):
        phases.append(phase)
        if phase == "post_write":
            raise LiveSignalEventGateError("forbidden_table_delta")
        return {
            "gate_status": "authorized",
            "authorization_hash": "a" * 64,
            "target_trading_day": "2026-07-24",
            "signal_event_handler": object(),
        }

    monkeypatch.setattr(LiveRuntimeCycleService, "run_once", run_once)
    result = execute_guarded_cycle(
        product="jm",
        poll_seconds=20,
        session_factory=SessionLocal,
        client_factory=lambda: object(),
        redis_factory=lambda: connection,
        signal_events_enabled=True,
        signal_gate=gate,
    )

    assert result["status"] == "failed"
    assert result["error_type"] == "LiveSignalEventGateError"
    assert phases == ["pre_write", "post_write"]
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
    assert connection.heartbeats[-1]["signal_event_gate_status"] == "blocked"


def test_guarded_scheduler_passes_only_gate_authorized_htdy_handler(
    monkeypatch,
) -> None:
    SessionLocal = _session_factory()
    connection = RecordingRedis()
    handler = object()
    captured = {}

    def run_once(self, **kwargs):
        captured.update(kwargs)

        class Result:
            def to_dict(self):
                return {
                    "status": "success",
                    "product": "jm",
                    "trading_day": "2026-07-27",
                    "signal_events": {
                        "created": 0,
                        "changed": 0,
                        "unchanged": 0,
                        "blocked": 0,
                        "event_ids": [],
                    },
                }

        return Result()

    def gate(session, *, phase, result=None):
        return {
            "gate_status": "authorized",
            "authorization_hash": "a" * 64,
            "target_trading_day": "2026-07-27",
            **(
                {"signal_event_handler": handler}
                if phase == "pre_write"
                else {}
            ),
        }

    monkeypatch.setattr(LiveRuntimeCycleService, "run_once", run_once)
    result = execute_guarded_cycle(
        product="jm",
        poll_seconds=20,
        session_factory=SessionLocal,
        client_factory=lambda: object(),
        redis_factory=lambda: connection,
        signal_events_enabled=True,
        signal_gate=gate,
    )

    assert result["status"] == "success"
    assert captured["signal_event_handler"] is handler
    assert captured["persist_signal_events"] is False
    assert "signal_event_handler" not in connection.heartbeats[-1]


@pytest.mark.parametrize("gate_status", ["waiting", "closed"])
def test_guarded_scheduler_keeps_ingest_running_without_s610_handler(
    monkeypatch,
    gate_status,
) -> None:
    SessionLocal = _session_factory()
    connection = RecordingRedis()
    phases = []
    captured = {}

    def run_once(self, **kwargs):
        captured.update(kwargs)

        class Result:
            def to_dict(self):
                return {
                    "status": "success",
                    "product": "jm",
                    "trading_day": "2026-07-28",
                    "signal_events": None,
                }

        return Result()

    def gate(session, *, phase, result=None):
        phases.append(phase)
        assert phase == "pre_write"
        return {
            "gate_status": gate_status,
            "authorization_hash": "a" * 64,
            "target_trading_day": None,
        }

    monkeypatch.setattr(LiveRuntimeCycleService, "run_once", run_once)
    result = execute_guarded_cycle(
        product="jm",
        poll_seconds=20,
        session_factory=SessionLocal,
        client_factory=lambda: object(),
        redis_factory=lambda: connection,
        signal_events_enabled=True,
        signal_gate=gate,
    )

    assert result["status"] == "success"
    assert phases == ["pre_write"]
    assert captured["signal_event_handler"] is None
    assert captured["persist_signal_events"] is False
    assert connection.heartbeats[-1]["signal_event_gate_status"] == gate_status


def test_notification_scheduler_disabled_constructs_no_dependencies() -> None:
    def fail_factory():
        raise AssertionError("disabled notification scheduler must not construct dependencies")

    assert execute_notification_dispatch(
        session_factory=fail_factory,
        queue_factory=fail_factory,
        enabled=False,
    ) == {"status": "disabled", "enabled": False}
