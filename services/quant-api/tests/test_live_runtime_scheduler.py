from __future__ import annotations

from datetime import date, datetime
import json

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveIngestCheckpoint, LiveMinuteBar
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.runtime_scheduler import execute_guarded_cycle, execute_notification_dispatch, main
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
    def contract_bars(self, contract, start_date, end_date, frequency):
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
    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=FakeClient(),
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


def test_closed_market_does_not_construct_rqdata_client() -> None:
    SessionLocal = _session_factory()

    def fail_client():
        raise AssertionError("closed market must not construct RQData client")

    with SessionLocal() as session:
        result = LiveRuntimeCycleService(
            session=session,
            client=fail_client,
            now=datetime(2026, 7, 7, 12, 0),
            target_resolver=FakeTargetResolver(),
            trading_clock=ClosedClock(),
        ).run_once(enabled=True)

    assert result.status == "idle"


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


def test_notification_scheduler_disabled_constructs_no_dependencies() -> None:
    def fail_factory():
        raise AssertionError("disabled notification scheduler must not construct dependencies")

    assert execute_notification_dispatch(
        session_factory=fail_factory,
        queue_factory=fail_factory,
        enabled=False,
    ) == {"status": "disabled", "enabled": False}
