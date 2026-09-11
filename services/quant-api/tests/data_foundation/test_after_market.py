from __future__ import annotations

import json
import logging
import io
import os
import multiprocessing
from types import SimpleNamespace
from contextlib import contextmanager, nullcontext
from datetime import date, datetime

import pytest

from app.alerts.notification import (
    ALERT_AUDIENCE_OWNER,
    NotificationDelivery,
    NotificationTransportError,
    ProviderAcceptance,
)
from app.market_data.after_market import AfterMarketUpdater, public_after_market_status
from app.market_data.after_market import AfterMarketResult
from app.guiyi_cli.main import main as guiyi_main
from app.runtime_entry import main as runtime_main
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import MaintenanceResult
from app.market_data.operational_universe import load_active_products


_ACTIVE_PRODUCTS = load_active_products()
_ACTIVE_CONTRACTS = {symbol: f"{symbol.upper()}2601" for symbol in _ACTIVE_PRODUCTS}


@pytest.fixture(autouse=True)
def _restore_after_market_logger_state():
    loggers = tuple(
        logging.getLogger(name)
        for name in ("app.market_data.after_market", "app.runtime_entry")
    )
    disabled_states = tuple(logger.disabled for logger in loggers)
    for logger in loggers:
        logger.disabled = False
    try:
        yield
    finally:
        for logger, was_disabled in zip(loggers, disabled_states, strict=True):
            logger.disabled = was_disabled


class _Coverage:
    def __init__(self, trading_day: date, *, metadata_day: date | None = None) -> None:
        self.trading_day = trading_day
        self.metadata_day = metadata_day or trading_day
        self.complete_day_calls: list[tuple[str, ...]] = []
        self.metadata_day_calls: list[tuple[str, ...]] = []

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        self.complete_day_calls.append(products)
        return self.trading_day

    def latest_metadata_day(self, products: tuple[str, ...]) -> date:
        self.metadata_day_calls.append(products)
        return self.metadata_day


class _Manager:
    def __init__(
        self,
        trading_day: date,
        results: list[MaintenanceResult],
        *,
        metadata_day: date | None = None,
    ) -> None:
        self.coverage = _Coverage(trading_day, metadata_day=metadata_day)
        self._results = results
        self.calls = []
        self.metadata = _Metadata()
        self.catalog = _Catalog(trading_day)

    def update(self, request, *, before_apply=None, observer=None):
        if before_apply is not None:
            before_apply()
        self.calls.append(request)
        return self._results.pop(0)


class _RQData:
    def __init__(self, readiness: list[bool]) -> None:
        self._readiness = readiness
        self.calls: list[date] = []

    def is_future_data_ready(self, trading_day: date) -> bool:
        self.calls.append(trading_day)
        return self._readiness.pop(0)


class _Metadata:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], date]] = []

    def synchronize_current_day(
        self, products: tuple[str, ...], trading_day: date
    ) -> date:
        self.calls.append((products, trading_day))
        return trading_day


class _Catalog:
    def __init__(self, trading_day: date) -> None:
        self.trading_day = trading_day
        self.contracts = dict(_ACTIVE_CONTRACTS)
        self.calls: list[tuple[str, date, date]] = []

    def main_map(self, symbol: str, start: date, end: date):
        self.calls.append((symbol, start, end))
        return [type("MainMapFact", (), {"contract": self.contracts[symbol]})()]


class _LiveStore:
    def __init__(self) -> None:
        self.snapshot = dict(_ACTIVE_CONTRACTS)
        self.subscription_calls: list[date] = []
        self.published: list[dict[str, str]] = []
        self.cleaned: list[date] = []
        self.cleanup_failures = 0

    def subscriptions(self, trading_day: date):
        self.subscription_calls.append(trading_day)
        return self.snapshot

    def publish_state(self, payload: dict[str, str]) -> None:
        self.published.append(payload)

    def cleanup_trading_day(self, trading_day: date) -> None:
        if self.cleanup_failures:
            self.cleanup_failures -= 1
            raise RuntimeError("private redis cleanup detail")
        self.cleaned.append(trading_day)


class _RecordingTransport:
    def __init__(
        self,
        deliveries: list[NotificationDelivery],
        *,
        error: Exception | None = None,
    ) -> None:
        self.deliveries = deliveries
        self.error = error

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        self.deliveries.append(delivery)
        if self.error is not None:
            raise self.error
        return ProviderAcceptance("provider-reference-must-not-persist")


def _result(
    status: str,
    *,
    stop_reason: str | None = None,
    applied: int = 0,
) -> MaintenanceResult:
    return MaintenanceResult(
        action="update",
        status=status,
        through=date(2026, 8, 10),
        planned=0,
        applied=applied,
        blocked=0,
        failed=0,
        provider_requests=0,
        stop_reason=stop_reason,
    )


def _updater(
    tmp_path,
    *,
    trading_day: date,
    readiness: list[bool],
    results: list[MaintenanceResult],
    metadata_day: date | None = None,
    notification_error: Exception | None = None,
    recovery_guard_factory=None,
):
    manager = _Manager(trading_day, results, metadata_day=metadata_day)
    rqdata = _RQData(readiness)
    sleeps: list[float] = []
    notices: list[NotificationDelivery] = []
    live_store = _LiveStore()
    updater = AfterMarketUpdater(
        manager=manager,
        rqdata=rqdata,
        live_store=live_store,
        status_path=tmp_path / "after-market-status.json",
        sleep=sleeps.append,
        notification_transport=_RecordingTransport(
            notices,
            error=notification_error,
        ),
        now=lambda: datetime(2026, 8, 10, 17, 0),
        recovery_guard_factory=recovery_guard_factory or nullcontext,
    )
    return updater, manager, rqdata, sleeps, notices, live_store


def _after_market_guard_process(root, connection):
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    @contextmanager
    def guard():
        connection.send("guard_attempt")
        with after_market_recovery_guard(root=root / "guards", wait=True):
            connection.send("guard_acquired")
            yield

    updater, manager, rqdata, *_ = _updater(
        root, trading_day=date(2026, 8, 10), readiness=[True],
        results=[_result("passed")], recovery_guard_factory=guard,
    )
    original_start = updater._write_current_run
    original_provider = rqdata.is_future_data_ready
    original_update = manager.update

    def start(*args):
        connection.send("current_run")
        original_start(*args)

    def provider(*args):
        connection.send("provider")
        return original_provider(*args)

    def canonical(*args, **kwargs):
        connection.send("canonical")
        assert connection.recv() == "finish"
        return original_update(*args, **kwargs)

    updater._write_current_run = start
    rqdata.is_future_data_ready = provider
    manager.update = canonical
    connection.send(updater.run().status)


def test_global_guard_serializes_after_market_before_any_status_or_provider_write(tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_after_market_guard_process, args=(tmp_path, child))
    try:
        with after_market_recovery_guard(root=tmp_path / "guards"):
            process.start()
            assert parent.poll(10)
            assert parent.recv() == "guard_attempt"
            assert not parent.poll(0.2)
            assert not (tmp_path / "after-market-status.json").exists()
        for expected in ("guard_acquired", "current_run", "provider", "canonical"):
            assert parent.poll(10)
            assert parent.recv() == expected
        with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"):
            with after_market_recovery_guard(root=tmp_path / "guards"):
                pytest.fail("captured recovery must reject an active after-market job")
        parent.send("finish")
        assert parent.poll(10)
        assert parent.recv() == "passed"
        process.join(10)
        assert process.exitcode == 0
        assert _status(tmp_path / "after-market-status.json")["current_run"] is None
        with after_market_recovery_guard(root=tmp_path / "guards"):
            pass
    finally:
        if process.pid is not None and process.is_alive():
            process.terminate()
            process.join(10)
        parent.close()
        child.close()


def test_global_guard_is_held_through_bounded_retry_and_final_status(tmp_path):
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    updater, manager, *_ = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True, True], results=[],
        recovery_guard_factory=lambda: after_market_recovery_guard(root=tmp_path / "guards"),
    )
    stages = []

    def verify_held(stage):
        with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"):
            with after_market_recovery_guard(root=tmp_path / "guards"):
                pytest.fail("whole after-market job must retain the lock")
        stages.append(stage)

    def fail_update(*args, **kwargs):
        verify_held("update")
        raise InfrastructureError("NEXT_TRADING_SESSION_NOT_READY")

    original_status = updater._write_status

    def status(*args):
        verify_held("status")
        original_status(*args)

    manager.update = fail_update
    updater.sleep = lambda seconds: verify_held("retry")
    updater._write_status = status
    assert updater.run().status == "failed"
    assert stages == ["update", "retry", "update", "status"]


def test_production_builder_always_composes_waiting_after_market_guard(tmp_path, monkeypatch):
    import app.market_data.after_market as module
    import app.redis_connections as redis_connections
    from app.market_data.live_recovery_guard import after_market_recovery_guard

    calls = []

    def guard(*, wait):
        calls.append(wait)
        return after_market_recovery_guard(root=tmp_path / "guards", wait=wait)

    monkeypatch.delenv("GUIYI_LIVE_RECOVERY_ENABLED", raising=False)
    monkeypatch.setattr(module, "after_market_recovery_guard", guard)
    monkeypatch.setattr(module, "_market_home_projection_refresh_enabled", lambda: False)
    monkeypatch.setattr(redis_connections, "get_redis_connection", lambda: object())
    manager = SimpleNamespace(provider=SimpleNamespace(client=object()),
                              catalog=SimpleNamespace(canonical_root=tmp_path))
    updater = module.build_after_market_updater(manager, failure_notification=False)
    assert calls == []
    with updater.recovery_guard_factory():
        with pytest.raises(RuntimeError, match="LIVE_RECOVERY_BUSY"):
            with after_market_recovery_guard(root=tmp_path / "guards"):
                pytest.fail("production updater must exclude captured recovery")
    assert calls == [True]


def _status(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _notice_error_codes(notices: list[NotificationDelivery]) -> list[str]:
    return [
        line.removeprefix("error_code=")
        for notice in notices
        for line in notice.content.splitlines()
        if line.startswith("error_code=")
    ]


def test_public_manual_after_market_does_not_grant_failure_notification_capability() -> (
    None
):
    capabilities: list[bool] = []

    class Updater:
        def run(self):
            return AfterMarketResult("failed", date(2026, 8, 10), 1, "UPDATE_FAILED")

    def factory(_manager, *, failure_notification: bool):
        capabilities.append(failure_notification)
        return Updater()

    code = guiyi_main(
        ["data", "after-market"],
        session_factory=_TrackedSessionFactory([]),
        manager_factory=lambda _session: object(),
        after_market_factory=factory,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == 1
    assert capabilities == [False]


def test_supervised_runtime_after_market_grants_one_shot_failure_notification_capability() -> (
    None
):
    capabilities: list[bool] = []

    class Updater:
        def run(self):
            return AfterMarketResult("failed", date(2026, 8, 10), 1, "UPDATE_FAILED")

    def factory(_manager, *, failure_notification: bool):
        capabilities.append(failure_notification)
        return Updater()

    code = runtime_main(
        ["after-market"],
        session_factory=_TrackedSessionFactory([]),
        manager_factory=lambda _session: object(),
        after_market_factory=factory,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == 1
    assert capabilities == [True]


class _TrackedSessionFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.count = 0

    def __call__(self):
        self.count += 1
        return _TrackedSessionContext(f"session-{self.count}", self.events)


class _TrackedSessionContext:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __enter__(self):
        self.events.append(f"enter:{self.name}")
        return self.name

    def __exit__(self, _exc_type, _exc, _traceback):
        self.events.append(f"exit:{self.name}")
        return False


def test_skips_non_trading_day_without_ready_update_or_retry(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 7),
        readiness=[],
        results=[],
    )

    result = updater.run()

    assert result.status == "skipped"
    assert result.trading_day == date(2026, 8, 7)
    assert result.attempts == 0
    assert result.error_code == "NON_TRADING_DAY"
    assert manager.calls == []
    assert rqdata.calls == []
    assert sleeps == []
    assert notices == []
    assert live_store.published == []


def test_uses_calendar_metadata_day_before_current_session_sync(tmp_path) -> None:
    """A stale current-day Session must not make a real trading day look closed."""
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 9),
        metadata_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.trading_day == date(2026, 8, 10)
    assert manager.coverage.metadata_day_calls == [_ACTIVE_PRODUCTS]
    assert manager.coverage.complete_day_calls == []
    assert manager.calls[0].through == date(2026, 8, 10)
    assert manager.calls[0].sync_current_day_metadata is True
    assert rqdata.calls == [date(2026, 8, 10)]
    assert sleeps == []
    assert notices == []


@pytest.mark.parametrize(
    "calendar_error_code",
    ("TRADING_CALENDAR_MISSING", "TRADING_CALENDAR_CONFLICT"),
)
def test_calendar_classification_failure_finishes_without_provider_work(
    tmp_path, calendar_error_code: str,
) -> None:
    updater, manager, rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 9),
        readiness=[],
        results=[],
    )

    def unknown_calendar(_products: tuple[str, ...]) -> date:
        raise InfrastructureError(calendar_error_code)

    manager.coverage.latest_metadata_day = unknown_calendar

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result == AfterMarketResult(
        status="failed",
        trading_day=date(2026, 8, 10),
        attempts=0,
        error_code=calendar_error_code,
    )
    assert status["current_run"] is None
    assert status["last_run"]["status"] == "failed"
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": calendar_error_code,
    }
    assert public_after_market_status(status)["last_run"]["attempts"] == 0
    assert rqdata.calls == []
    assert manager.calls == []
    assert sleeps == []
    assert _notice_error_codes(notices) == [calendar_error_code]
    assert live_store.published == []
    assert live_store.cleaned == []


def test_updates_once_when_first_attempt_is_ready(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.attempts == 1
    assert result.error_code is None
    assert manager.calls[0].products == _ACTIVE_PRODUCTS
    assert manager.calls[0].since is None
    assert manager.calls[0].through == date(2026, 8, 10)
    assert manager.calls[0].apply is True
    assert rqdata.calls == [date(2026, 8, 10)]
    assert sleeps == []
    assert notices == []


def test_schema_v3_persists_current_run_before_business_attempt_and_clears_on_finish(
    tmp_path,
) -> None:
    status_path = tmp_path / "after-market-status.json"
    updater, manager, _rqdata, _sleeps, _notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )
    observed: list[dict[str, object]] = []
    original = manager.coverage.latest_metadata_day

    def observe_current_run(products: tuple[str, ...]) -> date:
        observed.append(_status(status_path))
        return original(products)

    manager.coverage.latest_metadata_day = observe_current_run

    updater.run()

    assert observed == [
        {
            "schema_version": 3,
            "current_run": {
                "scheduled_date": "2026-08-10",
                "started_at": "2026-08-10T17:00:00+08:00",
                "products": list(_ACTIVE_PRODUCTS),
                "attempt": 0,
                "stage": "calendar",
                "updated_at": "2026-08-10T17:00:00+08:00",
                "current_partition": None,
                "current_symbol": None,
                "stage_started_at": "2026-08-10T17:00:00+08:00",
                "elapsed_seconds": 0.0,
                "counters": {},
                "stage_durations": {},
                "retry_at": None,
            },
            "last_run": None,
            "last_successful_trading_day": None,
            "last_failure": None,
        }
    ]
    finalized = _status(status_path)
    assert finalized["schema_version"] == 3
    assert finalized["current_run"] is None
    assert finalized["last_run"]["status"] == "passed"


def test_new_current_run_preserves_previous_v2_failure_notification(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "current_run": None,
                "last_run": {
                    "trading_day": "2026-08-09",
                    "status": "failed",
                    "attempts": 1,
                    "started_at": "2026-08-09T18:05:00+08:00",
                    "finished_at": "2026-08-09T18:06:00+08:00",
                    "products": list(_ACTIVE_PRODUCTS),
                    "error_code": "UPDATE_FAILED",
                    "failure_notification": {
                        "attempted_at": "2026-08-09T18:06:00+08:00",
                        "state": "provider_accepted",
                        "error_type": None,
                    },
                },
                "last_successful_trading_day": "2026-08-08",
                "last_failure": {
                    "trading_day": "2026-08-09",
                    "error_code": "UPDATE_FAILED",
                },
            }
        ),
        encoding="utf-8",
    )
    updater, manager, _rqdata, _sleeps, _notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 7),
        readiness=[],
        results=[],
    )
    observed: list[dict[str, object]] = []
    original = manager.coverage.latest_metadata_day

    def observe(products: tuple[str, ...]) -> date:
        observed.append(_status(status_path))
        return original(products)

    manager.coverage.latest_metadata_day = observe

    updater.run()

    assert observed[0]["last_run"]["failure_notification"] == {
        "attempted_at": "2026-08-09T18:06:00+08:00",
        "state": "provider_accepted",
        "error_type": None,
    }


def test_every_status_write_uses_same_directory_atomic_replace(
    tmp_path, monkeypatch
) -> None:
    status_path = tmp_path / "after-market-status.json"
    updater, *_ = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )
    replacements: list[tuple[object, object]] = []
    real_replace = os.replace

    def record_replace(source, target) -> None:
        replacements.append((source, target))
        assert os.fspath(source) != os.fspath(target)
        assert os.path.dirname(os.fspath(source)) == os.path.dirname(os.fspath(target))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", record_replace)

    updater.run()

    assert len(replacements) >= 2
    assert all(
        os.fspath(target) == os.fspath(status_path) for _, target in replacements
    )


def test_current_day_metadata_is_delegated_to_the_locked_update(tmp_path) -> None:
    updater, manager, _rqdata, _sleeps, _notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )

    updater.run()

    assert manager.metadata.calls == []
    assert manager.calls[0].sync_current_day_metadata is True


def test_does_not_retry_when_rqdata_is_not_ready(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[False, True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "RQDATA_NOT_READY"
    assert rqdata.calls == [date(2026, 8, 10)]
    assert manager.calls == []
    assert sleeps == []
    assert _notice_error_codes(notices) == ["RQDATA_NOT_READY"]
    assert live_store.published == []


def test_does_not_retry_after_provider_quota_failure(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[
            _result("failed", stop_reason="PROVIDER_QUOTA_EXHAUSTED"),
            _result("passed"),
        ],
    )

    result = updater.run()

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert rqdata.calls == [date(2026, 8, 10)]
    assert len(manager.calls) == 1
    assert sleeps == []
    assert _notice_error_codes(notices) == ["PROVIDER_QUOTA_EXHAUSTED"]
    assert live_store.published == []


def test_records_final_failure_and_notifies_once(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[_result("failed"), _result("failed")],
    )

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")
    public_status = public_after_market_status(status)

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "UPDATE_FAILED"
    assert len(manager.calls) == 1
    assert sleeps == []
    assert _notice_error_codes(notices) == ["UPDATE_FAILED"]
    assert public_status["last_run"]["attempts"] == 1
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "UPDATE_FAILED",
    }
    assert "exception" not in json.dumps(status).lower()
    assert "path" not in json.dumps(status).lower()


def test_natural_failure_records_owner_provider_acceptance_without_delivery_claim(
    tmp_path,
) -> None:
    updater, _manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[False],
        results=[],
    )

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result == AfterMarketResult(
        "failed", date(2026, 8, 10), 1, "RQDATA_NOT_READY"
    )
    assert notices == [
        NotificationDelivery(
            audience=ALERT_AUDIENCE_OWNER,
            title="归一量化 盘后运维失败",
            content=(
                "trading_day=2026-08-10\n"
                "error_code=RQDATA_NOT_READY\n"
                "attempts=1\n"
                "系统运维提醒，非交易指令"
            ),
        )
    ]
    assert status["last_run"]["failure_notification"] == {
        "attempted_at": "2026-08-10T17:00:00+08:00",
        "state": "provider_accepted",
        "error_type": None,
    }
    assert "provider-reference-must-not-persist" not in json.dumps(status)


def test_notification_failure_is_recorded_once_without_changing_primary_failure(
    tmp_path,
) -> None:
    updater, _manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[False],
        results=[],
        notification_error=NotificationTransportError(
            "ALERT_NOTIFICATION_TRANSPORT_FAILED"
        ),
    )

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result.status == "failed"
    assert result.error_code == "RQDATA_NOT_READY"
    assert len(notices) == 1
    assert status["last_run"]["status"] == "failed"
    assert status["last_run"]["failure_notification"] == {
        "attempted_at": "2026-08-10T17:00:00+08:00",
        "state": "failed",
        "error_type": "ALERT_NOTIFICATION_TRANSPORT_FAILED",
    }


def test_readiness_failure_logs_only_sanitized_diagnostics(tmp_path, caplog) -> None:
    class FailingRQData:
        def is_future_data_ready(self, _trading_day: date) -> bool:
            try:
                raise RuntimeError("credential-secret-provider-message")
            except RuntimeError as exc:
                raise InfrastructureError("RQDATA_READY_RESPONSE_INVALID") from exc

    updater, _manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[],
        results=[],
    )
    updater.rqdata = FailingRQData()
    caplog.set_level(logging.WARNING, logger="app.market_data.after_market")

    result = updater.run()

    assert result.error_code == "RQDATA_READY_CHECK_FAILED"
    assert result.attempts == 1
    assert _notice_error_codes(notices) == ["RQDATA_READY_CHECK_FAILED"]
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=rqdata_readiness attempt=1 "
        "detail_code=RQDATA_READY_RESPONSE_INVALID exception_type=InfrastructureError",
    ]
    assert "credential-secret-provider-message" not in caplog.text


def test_update_exception_logs_only_sanitized_stage_diagnostics(
    tmp_path, caplog
) -> None:
    updater, manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[],
    )

    def fail_update(_request, *, before_apply=None, observer=None):
        raise RuntimeError("credential-secret-provider-message")

    manager.update = fail_update
    caplog.set_level(logging.WARNING, logger="app.market_data.after_market")

    result = updater.run()

    assert result.error_code == "UPDATE_FAILED"
    assert result.attempts == 1
    assert _notice_error_codes(notices) == ["UPDATE_FAILED"]
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=canonical_update attempt=1 "
        "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=RuntimeError",
    ]
    assert "credential-secret-provider-message" not in caplog.text


def test_next_trading_session_not_ready_is_retried_with_stable_public_code(
    tmp_path, caplog
) -> None:
    updater, manager, _rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[],
    )

    def fail_update(_request, *, before_apply=None, observer=None):
        raise InfrastructureError("NEXT_TRADING_SESSION_NOT_READY")

    manager.update = fail_update
    caplog.set_level(logging.WARNING, logger="app.market_data.after_market")

    result = updater.run()
    public_status = public_after_market_status(
        _status(tmp_path / "after-market-status.json")
    )

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.error_code == "NEXT_TRADING_SESSION_NOT_READY"
    assert public_status["last_run"]["error_code"] == ("NEXT_TRADING_SESSION_NOT_READY")
    assert public_status["last_failure"]["error_code"] == (
        "NEXT_TRADING_SESSION_NOT_READY"
    )
    assert sleeps == [3600]
    assert _notice_error_codes(notices) == ["NEXT_TRADING_SESSION_NOT_READY"]
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=metadata_readiness attempt=1 "
        "detail_code=NEXT_TRADING_SESSION_NOT_READY exception_type=InfrastructureError",
        "after_market_attempt_failed stage=metadata_readiness attempt=2 "
        "detail_code=NEXT_TRADING_SESSION_NOT_READY exception_type=InfrastructureError",
    ]


def test_failed_update_result_logs_sanitized_stop_code(tmp_path, caplog) -> None:
    updater, _manager, _rqdata, _sleeps, _notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[
            _result("failed", stop_reason="PROVIDER_QUOTA_EXHAUSTED"),
            _result("passed"),
        ],
    )
    caplog.set_level(logging.WARNING, logger="app.market_data.after_market")

    result = updater.run()

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=canonical_update_result attempt=1 "
        "detail_code=PROVIDER_QUOTA_EXHAUSTED result_status=failed"
    ]


def test_preserves_whitelisted_maintenance_stop_code_on_final_failure(tmp_path) -> None:
    updater, _manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[
            _result("partial", stop_reason="provider_quota_exhausted"),
            _result("partial", stop_reason="provider_quota_exhausted"),
        ],
    )

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result.attempts == 1
    assert result.error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "PROVIDER_QUOTA_EXHAUSTED",
    }
    assert _notice_error_codes(notices) == ["PROVIDER_QUOTA_EXHAUSTED"]


def test_partial_update_with_committed_partition_is_never_recorded_as_passed(
    tmp_path,
) -> None:
    updater, _manager, _rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[
            _result(
                "partial",
                stop_reason="provider_quota_exhausted",
                applied=1,
            )
        ],
    )

    result = updater.run()
    status = public_after_market_status(
        _status(tmp_path / "after-market-status.json")
    )

    assert result.status == "failed"
    assert result.error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert status["last_run"]["status"] == "failed"
    assert status["last_successful_trading_day"] is None
    assert sleeps == []
    assert _notice_error_codes(notices) == ["PROVIDER_QUOTA_EXHAUSTED"]
    assert live_store.published == []
    assert live_store.cleaned == []


def test_process_interruption_preserves_unfinished_current_run(tmp_path) -> None:
    class SimulatedProcessInterruption(BaseException):
        pass

    updater, manager, _rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[],
    )

    def interrupt(_request, *, before_apply=None, observer=None):
        raise SimulatedProcessInterruption

    manager.update = interrupt

    with pytest.raises(SimulatedProcessInterruption):
        updater.run()

    status = public_after_market_status(
        _status(tmp_path / "after-market-status.json")
    )
    assert status["current_run"]["attempt"] == 1
    assert status["current_run"]["stage"] == "rqdata_readiness"
    assert status["last_run"] is None
    assert sleeps == []
    assert notices == []
    assert live_store.published == []
    assert live_store.cleaned == []


def test_success_clears_previous_last_failure(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": None,
                "last_successful_trading_day": None,
                "last_failure": {
                    "trading_day": "2026-08-09",
                    "error_code": "UPDATE_FAILED",
                },
            }
        ),
        encoding="utf-8",
    )
    updater, *_ = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("noop")],
    )

    updater.run()

    assert _status(status_path)["last_failure"] is None
    assert _status(status_path)["last_successful_trading_day"] == "2026-08-10"


def test_weekend_skip_preserves_unresolved_failure(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    previous_failure = {"trading_day": "2026-08-09", "error_code": "UPDATE_FAILED"}
    status_path.write_text(
        json.dumps(
            {
                "last_run": None,
                "last_successful_trading_day": None,
                "last_failure": previous_failure,
            }
        ),
        encoding="utf-8",
    )
    updater, *_ = _updater(
        tmp_path,
        trading_day=date(2026, 8, 7),
        readiness=[],
        results=[],
    )

    updater.run()

    assert _status(status_path)["last_failure"] == previous_failure


def test_weekend_skip_drops_unsafe_legacy_status_fields(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps(
            {
                "last_run": None,
                "last_successful_trading_day": "/private/secret/canonical",
                "last_failure": {
                    "trading_day": "2026-08-09",
                    "error_code": "UPDATE_FAILED",
                    "exception": "RuntimeError: credential text",
                },
            }
        ),
        encoding="utf-8",
    )
    updater, *_ = _updater(
        tmp_path,
        trading_day=date(2026, 8, 7),
        readiness=[],
        results=[],
    )

    updater.run()
    status_text = status_path.read_text(encoding="utf-8")
    status = json.loads(status_text)

    assert status["last_successful_trading_day"] is None
    assert status["last_failure"] == {
        "trading_day": "2026-08-09",
        "error_code": "UPDATE_FAILED",
    }
    assert "credential" not in status_text
    assert "/private/secret" not in status_text


def test_success_reconciles_rank1_publishes_state_and_cleans_live(tmp_path) -> None:
    updater, manager, _rqdata, _sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.error_code is None
    assert manager.metadata.calls == []
    assert manager.calls[0].sync_current_day_metadata is True
    assert manager.catalog.calls == [
        (symbol, date(2026, 8, 10), date(2026, 8, 10)) for symbol in _ACTIVE_PRODUCTS
    ]
    assert live_store.published == [
        {
            "trading_day": "2026-08-10",
            "reason": "canonical_updated",
        }
    ]
    assert live_store.cleaned == [date(2026, 8, 10)]
    assert notices == []


def test_cleanup_failure_does_not_retry_or_report_success(tmp_path) -> None:
    """Catches a failed Live cleanup being recorded as a completed after-market run."""
    updater, _manager, _rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[_result("passed"), _result("noop")],
    )
    live_store.cleanup_failures = 2

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "UPDATE_FAILED"
    assert sleeps == []
    assert _notice_error_codes(notices) == ["UPDATE_FAILED"]
    assert live_store.published == [
        {
            "trading_day": "2026-08-10",
            "reason": "canonical_updated",
        }
    ]
    assert live_store.cleaned == []
    assert status["last_successful_trading_day"] is None
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "UPDATE_FAILED",
    }


def test_rank1_mismatch_is_a_stable_failure_without_live_cleanup(tmp_path) -> None:
    updater, manager, _rqdata, sleeps, notices, live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[_result("passed"), _result("noop")],
    )
    live_store.snapshot["ag"] = "AG2608"

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error_code == "LIVE_DOMINANT_MISMATCH"
    assert sleeps == []
    assert _notice_error_codes(notices) == ["LIVE_DOMINANT_MISMATCH"]
    assert live_store.published == [
        {
            "trading_day": "2026-08-10",
            "reason": "canonical_updated",
        }
    ]
    assert live_store.cleaned == []
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "LIVE_DOMINANT_MISMATCH",
    }
    assert manager.metadata.calls == []
    assert all(request.sync_current_day_metadata for request in manager.calls)


def test_public_status_rejects_boolean_attempt_count() -> None:
    """Catches JSON booleans being accepted as integer retry counts."""
    payload = public_after_market_status(
        {
            "last_run": {
                "trading_day": "2026-08-10",
                "status": "passed",
                "attempts": True,
                "started_at": "2026-08-10T17:00:00+08:00",
                "finished_at": "2026-08-10T17:05:00+08:00",
                "products": ["j", "jm", "ap", "ag"],
                "error_code": None,
            }
        }
    )

    assert payload == {}


def test_public_status_rejects_zero_attempt_post_apply_failure() -> None:
    payload = public_after_market_status(
        {
            "schema_version": 3,
            "current_run": None,
            "last_run": {
                "trading_day": "2026-08-10",
                "status": "failed",
                "attempts": 0,
                "started_at": "2026-08-10T17:00:00+08:00",
                "finished_at": "2026-08-10T17:05:00+08:00",
                "products": list(_ACTIVE_PRODUCTS),
                "error_code": "COMMIT_OUTCOME_UNKNOWN",
                "failure_notification": None,
            },
            "last_successful_trading_day": None,
            "last_failure": {
                "trading_day": "2026-08-10",
                "error_code": "COMMIT_OUTCOME_UNKNOWN",
            },
        }
    )

    assert payload == {}


def test_public_status_rejects_zero_attempt_failure_from_legacy_schema() -> None:
    payload = public_after_market_status(
        {
            "schema_version": 2,
            "current_run": None,
            "last_run": {
                "trading_day": "2026-08-10",
                "status": "failed",
                "attempts": 0,
                "started_at": "2026-08-10T17:00:00+08:00",
                "finished_at": "2026-08-10T17:05:00+08:00",
                "products": list(_ACTIVE_PRODUCTS),
                "error_code": "UPDATE_FAILED",
                "failure_notification": None,
            },
            "last_successful_trading_day": None,
            "last_failure": {
                "trading_day": "2026-08-10",
                "error_code": "UPDATE_FAILED",
            },
        }
    )

    assert payload == {}


def test_daily_progress_persists_stage_changes_throttles_counts_and_omits_unknown_total(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="app.market_data.after_market")
    from app.market_data.historical_data_manager import MaintenanceProgressEvent
    updater, manager, *_ = _updater(tmp_path, trading_day=date(2026, 8, 10),
                                   readiness=[True], results=[])
    snapshots = []
    ticks = [0.0]
    updater.monotonic = lambda: ticks[0]

    def update(request, *, before_apply=None, observer=None):
        assert request.mode == "daily"
        assert observer is not None
        for phase, state, count, elapsed, tick in [
            ("reading", "started", 0, 0., 0.),
            ("reading", "completed", 1, .2, 1.),
            ("reading", "completed", 2, .3, 5.),
            ("publishing", "completed", 1, .4, 5.1),
        ]:
            ticks[0] = tick
            observer(MaintenanceProgressEvent(phase, state, "au", ("continuous", "au", "MAIN", "1m"),
                                              2026, 8, count, None, elapsed))
            snapshots.append(_status(updater.status_path)["current_run"])
        return _result("passed")

    manager.update = update
    assert updater.run().status == "passed"
    assert snapshots[0]["stage"] == "reading"
    assert snapshots[1]["counters"]["reading"] == {"completed": 0}
    assert snapshots[2]["counters"]["reading"] == {"completed": 2}
    assert snapshots[3]["stage"] == "publishing"
    assert snapshots[3]["stage_durations"]["reading"] == .5
    assert snapshots[3]["attempt"] == 1
    assert public_after_market_status({"schema_version": 3, "current_run": snapshots[3]})
    progress = [record.diagnostic_fields["progress"] for record in caplog.records
                if record.msg == "AFTER_MARKET_PROGRESS"]
    reading = [item for item in progress if item["stage"] == "reading"]
    assert reading == [snapshots[0], snapshots[2]]
    assert next(item for item in progress if item["stage"] == "publishing") == snapshots[3]


def test_progress_persistence_failure_stops_before_live_and_notification(tmp_path, monkeypatch):
    from app.market_data import after_market
    from app.market_data.historical_data_manager import MaintenanceProgressEvent
    updater, manager, _, sleeps, notices, live = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True], results=[])
    real_write = after_market._atomic_write_status

    def write(path, payload):
        if (payload.get("current_run") or {}).get("stage") == "publishing":
            raise OSError("private path")
        real_write(path, payload)

    monkeypatch.setattr(after_market, "_atomic_write_status", write)

    def update(request, *, before_apply=None, observer=None):
        observer(MaintenanceProgressEvent("publishing", "started", "au", None,
                                          None, None, 0, None, 0.))
        pytest.fail("must stop at progress persistence failure")

    manager.update = update
    with pytest.raises(RuntimeError, match="AFTER_MARKET_PROGRESS_UNAVAILABLE") as failure:
        updater.run()
    from app.guiyi_cli.output import exception_error_payload
    assert exception_error_payload(command="data.after-market", exc=failure.value)["error"]["code"] == "AFTER_MARKET_PROGRESS_UNAVAILABLE"
    assert not sleeps and not notices and not live.published and not live.cleaned
    assert _status(updater.status_path)["current_run"] is not None


@pytest.mark.parametrize("failure_stage", ["initial", "intermediate", "terminal"])
def test_status_persistence_failure_is_not_healthy_to_independent_consumer(tmp_path, monkeypatch, failure_stage):
    from app.market_data import after_market
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.session_clock import SHANGHAI
    from app.services import runtime_health
    updater, manager, _, sleeps, notices, _ = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True], results=[_result("passed")])
    updater._write_current_run(datetime(2026, 8, 10, 16, 0, tzinfo=SHANGHAI), load_operational_products())
    updater._write_status(AfterMarketResult("passed", date(2026, 8, 10), 1, None),
                          datetime(2026, 8, 10, 16, 0, tzinfo=SHANGHAI), load_operational_products())
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", lambda *a, **k: (date(2026, 8, 10), True))
    def health():
        component = runtime_health._collect_after_market_health(None, now=datetime(2026, 8, 10, 18, 0, tzinfo=SHANGHAI),
            configured_enabled=True, status_path=updater.status_path)
        return component, runtime_health._overall_status([{"status": "ok"}, component])
    assert health()[1] == "ok"
    real_write = after_market._atomic_write_status
    def write(path, payload):
        current = payload.get("current_run")
        fail = ((failure_stage == "initial" and current and current["stage"] == "calendar")
                or (failure_stage == "intermediate" and current and current["stage"] == "rqdata_readiness")
                or (failure_stage == "terminal" and current is None))
        if fail:
            raise OSError("private status detail")
        real_write(path, payload)
    monkeypatch.setattr(after_market, "_atomic_write_status", write)
    with pytest.raises(RuntimeError, match="AFTER_MARKET_PROGRESS_UNAVAILABLE"):
        updater.run()
    component, overall = health()
    assert overall != "ok"
    assert component["run_state"] != "completed"
    assert not sleeps and not notices
    if failure_stage == "initial":
        assert not manager.coverage.metadata_day_calls


@pytest.mark.parametrize("unsafe", ["symlink", "parent_symlink", "fifo", "hardlink"])
def test_status_invalidation_rejects_unsafe_path_before_start(tmp_path, unsafe):
    import os
    updater, manager, *_ = _updater(tmp_path, trading_day=date(2026, 8, 10), readiness=[], results=[])
    target = tmp_path / "untouched"
    target.write_text("must remain unchanged")
    if unsafe == "symlink":
        updater.status_path.symlink_to(target)
    elif unsafe == "parent_symlink":
        actual = tmp_path / "actual"
        actual.mkdir()
        linked = tmp_path / "linked"
        linked.symlink_to(actual, target_is_directory=True)
        updater.status_path = linked / "status.json"
    elif unsafe == "fifo":
        os.mkfifo(updater.status_path)
    else:
        os.link(target, updater.status_path)
    with pytest.raises(RuntimeError, match="AFTER_MARKET_PROGRESS_UNAVAILABLE"):
        updater.run()
    assert target.read_text() == "must remain unchanged"
    assert not manager.coverage.metadata_day_calls


def test_failed_invalidation_rejects_start_without_claiming_a_new_run(tmp_path, monkeypatch):
    from app.market_data import after_market
    updater, manager, rqdata, sleeps, notices, _ = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[], results=[])
    updater.status_path.write_text('{"previous":"unchanged"}')
    monkeypatch.setattr(after_market.os, "ftruncate", lambda *args: (_ for _ in ()).throw(OSError("private")))
    with pytest.raises(RuntimeError, match="AFTER_MARKET_PROGRESS_UNAVAILABLE"):
        updater.run()
    assert updater._current == {}
    assert updater.status_path.read_text() == '{"previous":"unchanged"}'
    assert not manager.coverage.metadata_day_calls and not rqdata.calls and not sleeps and not notices


def test_v3_health_uses_last_progress_and_rejects_future_updates(tmp_path, monkeypatch):
    from app.services import runtime_health
    from datetime import timedelta
    updater, *_ = _updater(tmp_path, trading_day=date(2026, 8, 10), readiness=[], results=[])
    start = datetime.fromisoformat("2026-08-10T17:00:00+08:00")
    updater._write_current_run(start, _ACTIVE_PRODUCTS)
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", lambda *a, **k: (start.date(), True))
    payload = _status(updater.status_path)
    payload["current_run"]["updated_at"] = (start + timedelta(hours=3)).isoformat()
    updater.status_path.write_text(json.dumps(payload))
    def read(at):
        return runtime_health._collect_after_market_health(None, updater.status_path, now=at, configured_enabled=True)
    assert read(start + timedelta(hours=3, minutes=1))["run_state"] == "running"
    assert read(start + timedelta(hours=2))["run_state"] == "degraded"
    assert read(start + timedelta(hours=6))["run_state"] == "stuck"


def test_logging_failure_cannot_change_business_failure_or_retry(tmp_path, monkeypatch):
    from app.market_data import after_market
    updater, _, _, sleeps, notices, _ = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True],
        results=[_result("failed", stop_reason="PROVIDER_QUOTA_EXHAUSTED")])
    monkeypatch.setattr(after_market._LOGGER, "warning", lambda *a, **k: (_ for _ in ()).throw(OSError("private")))
    monkeypatch.setattr(after_market._LOGGER, "info", lambda *a, **k: (_ for _ in ()).throw(OSError("private")))
    assert updater.run().error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert not sleeps and len(notices) == 1


@pytest.mark.parametrize("failure_type", [ValueError, InfrastructureError])
def test_missing_daily_baseline_is_explicit_history_maintenance_required(tmp_path, failure_type):
    updater, manager, _, sleeps, notices, live = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True], results=[])
    def update(request, **kwargs):
        raise failure_type("HISTORICAL_MAINTENANCE_REQUIRED")
    manager.update = update
    result = updater.run()
    assert result.error_code == "HISTORICAL_MAINTENANCE_REQUIRED"
    assert public_after_market_status(_status(updater.status_path))["last_failure"]["error_code"] == result.error_code
    assert not sleeps and not live.cleaned and len(notices) == 1


def test_public_status_rejects_unknown_schema_v6() -> None:
    payload = public_after_market_status(
        {
            "schema_version": 6,
            "current_run": None,
            "last_run": {
                "trading_day": "2026-08-10",
                "status": "passed",
                "attempts": 1,
                "started_at": "2026-08-10T17:00:00+08:00",
                "finished_at": "2026-08-10T17:05:00+08:00",
                "products": list(_ACTIVE_PRODUCTS),
                "error_code": None,
                "failure_notification": None,
            },
            "last_successful_trading_day": "2026-08-10",
            "last_failure": None,
        }
    )

    assert payload == {}


def test_public_status_rejects_non_string_error_codes() -> None:
    """Malformed local JSON must fail closed instead of breaking a public endpoint."""
    payload = public_after_market_status(
        {
            "last_run": {
                "trading_day": "2026-08-10",
                "status": "failed",
                "attempts": 2,
                "started_at": "2026-08-10T17:00:00+08:00",
                "finished_at": "2026-08-10T17:05:00+08:00",
                "products": ["j", "jm", "ap", "ag"],
                "error_code": ["UPDATE_FAILED"],
            },
            "last_failure": {
                "trading_day": "2026-08-10",
                "error_code": ["UPDATE_FAILED"],
            },
        }
    )

    assert payload == {}


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.update(last_successful_trading_day="invalid"),
        lambda payload: payload.update(
            last_failure={
                "trading_day": "invalid",
                "error_code": "UPDATE_FAILED",
            }
        ),
        lambda payload: payload["last_run"].update(
            failure_notification={
                "attempted_at": "invalid",
                "state": "provider_accepted",
                "error_type": None,
            }
        ),
    ),
)
def test_public_status_rejects_any_present_invalid_v2_public_field(mutate) -> None:
    raw = {
        "schema_version": 2,
        "current_run": None,
        "last_run": {
            "trading_day": "2026-08-24",
            "status": "passed",
            "attempts": 1,
            "started_at": "2026-08-24T18:05:00+08:00",
            "finished_at": "2026-08-24T18:10:00+08:00",
            "products": ["jm"],
            "error_code": None,
            "failure_notification": None,
        },
        "last_successful_trading_day": "2026-08-24",
        "last_failure": None,
    }
    mutate(raw)

    assert public_after_market_status(raw) == {}


def test_commit_outcome_unknown_is_public_and_never_retried(tmp_path, monkeypatch):
    from app.market_data.storage import StorageError

    updater, manager, _, sleeps, notices, live_store = _updater(
        tmp_path, trading_day=date(2026, 8, 10), readiness=[True, True], results=[])
    calls = []

    def unknown(*args, **kwargs):
        calls.append(1)
        raise StorageError("COMMIT_OUTCOME_UNKNOWN")

    monkeypatch.setattr(manager, "update", unknown)
    result = updater.run()
    assert result.error_code == "COMMIT_OUTCOME_UNKNOWN"
    assert result.attempts == 1
    assert calls == [1]
    assert sleeps == []
    assert live_store.published == []
    assert _notice_error_codes(notices) == ["COMMIT_OUTCOME_UNKNOWN"]
    assert public_after_market_status(_status(tmp_path / "after-market-status.json"))["last_failure"]["error_code"] == "COMMIT_OUTCOME_UNKNOWN"


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_natural_writer_preserves_v5_interruption_without_inheriting_success(tmp_path, outcome):
    from tests.data_foundation.test_after_market_closeout import missing_interrupted_status
    raw = missing_interrupted_status()
    updater, manager, _, _, _, live = _updater(tmp_path, trading_day=date(2026, 8, 10),
        readiness=[True], results=[_result(outcome, stop_reason="PROVIDER_QUOTA_EXHAUSTED" if outcome == "failed" else None)])
    # The natural writer is later than the administratively closed run.
    raw["last_interruption"].update(trading_day="2026-08-07", started_at="2026-08-07T18:05:00+08:00",
        closed_at="2026-08-08T08:00:00+08:00", snapshot_checked_at="2026-08-08T08:00:00+08:00")
    raw["last_run"].update(trading_day="2026-08-07", started_at="2026-08-07T18:05:00+08:00",
        finished_at="2026-08-08T08:00:00+08:00")
    raw["last_failure"]["trading_day"] = "2026-08-07"
    raw["last_successful_trading_day"] = "2026-08-06"
    updater.status_path.write_text(json.dumps(raw))
    observed = []
    original = manager.coverage.latest_metadata_day
    def observe(products):
        observed.append(public_after_market_status(_status(updater.status_path)))
        return original(products)
    manager.coverage.latest_metadata_day = observe
    assert updater.run().status == outcome
    current = observed[0]
    assert current["schema_version"] == 5
    assert current["last_interruption"] == raw["last_interruption"]
    assert current["last_run"]["status"] == "interrupted"
    assert current["last_successful_trading_day"] == "2026-08-06"
    final = public_after_market_status(_status(updater.status_path))
    assert final["schema_version"] == 5
    assert final["last_run"]["status"] == outcome
    assert final["last_interruption"] == raw["last_interruption"]
    assert final["last_successful_trading_day"] == ("2026-08-10" if outcome == "passed" else "2026-08-06")


def test_natural_reconciliation_still_rejects_missing_snapshot(tmp_path):
    updater, _, _, _, notices, live = _updater(tmp_path, trading_day=date(2026, 8, 10),
        readiness=[True, True], results=[_result("passed"), _result("passed")])
    live.snapshot = None
    result = updater.run()
    assert result.status == "failed" and result.error_code == "LIVE_DOMINANT_MISMATCH"
    assert live.cleaned == []
    assert len(notices) == 1
    assert _status(updater.status_path)["last_successful_trading_day"] is None
