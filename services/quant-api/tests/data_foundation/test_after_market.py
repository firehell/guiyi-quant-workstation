from __future__ import annotations

import json
import logging
import io
from datetime import date, datetime

import pytest

from app.market_data.after_market import AfterMarketUpdater, public_after_market_status
from app.market_data.after_market import AfterMarketResult
from app.guiyi_cli.main import (
    _execution_review_roll_marker_state,
    main as guiyi_main,
)
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import MaintenanceResult
from app.market_data.operational_universe import load_active_products


_ACTIVE_PRODUCTS = load_active_products()
_ACTIVE_CONTRACTS = {symbol: f"{symbol.upper()}2601" for symbol in _ACTIVE_PRODUCTS}


@pytest.fixture(autouse=True)
def _restore_after_market_logger_state():
    loggers = tuple(
        logging.getLogger(name)
        for name in ("app.market_data.after_market", "app.guiyi_cli.main")
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

    def update(self, request):
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

    def synchronize_current_day(self, products: tuple[str, ...], trading_day: date) -> date:
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


def _result(status: str, *, stop_reason: str | None = None) -> MaintenanceResult:
    return MaintenanceResult(
        action="update",
        status=status,
        through=date(2026, 8, 10),
        planned=0,
        applied=0,
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
):
    manager = _Manager(trading_day, results, metadata_day=metadata_day)
    rqdata = _RQData(readiness)
    sleeps: list[float] = []
    notices: list[str] = []
    live_store = _LiveStore()
    updater = AfterMarketUpdater(
        manager=manager,
        rqdata=rqdata,
        live_store=live_store,
        status_path=tmp_path / "after-market-status.json",
        sleep=sleeps.append,
        notifier=notices.append,
        now=lambda: datetime(2026, 8, 10, 17, 0),
    )
    return updater, manager, rqdata, sleeps, notices, live_store


def _status(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("market_status", ("skipped", "failed"))
def test_after_market_followup_does_not_run_for_non_passed_result(
    market_status: str,
) -> None:
    events: list[str] = []
    sessions = _TrackedSessionFactory(events)

    class Updater:
        def run(self):
            events.append("market_run")
            return AfterMarketResult(market_status, date(2026, 8, 10), 1, None)

    code = guiyi_main(
        ["data", "after-market"],
        session_factory=sessions,
        manager_factory=lambda session: events.append(f"manager:{session}") or object(),
        after_market_factory=lambda _manager: Updater(),
        execution_review_roll_marker_state=lambda: "enabled",
        roll_reconciler_factory=lambda _session: pytest.fail(
            "reconciler must not be built"
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == (0 if market_status == "skipped" else 1)
    assert events == ["enter:session-1", "manager:session-1", "market_run", "exit:session-1"]


@pytest.mark.parametrize("marker_state", ("disabled", "invalid"))
def test_after_market_passed_with_disabled_marker_uses_only_market_session(
    marker_state: str,
) -> None:
    events: list[str] = []
    sessions = _TrackedSessionFactory(events)

    class Updater:
        def run(self):
            events.append("market_run")
            return AfterMarketResult("passed", date(2026, 8, 10), 1, None)

    code = guiyi_main(
        ["data", "after-market"],
        session_factory=sessions,
        manager_factory=lambda session: events.append(f"manager:{session}") or object(),
        after_market_factory=lambda _manager: Updater(),
        execution_review_roll_marker_state=lambda: marker_state,
        roll_reconciler_factory=lambda _session: pytest.fail(
            "reconciler must not be built"
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == 0
    assert events == ["enter:session-1", "manager:session-1", "market_run", "exit:session-1"]


def test_after_market_passed_with_enabled_marker_reconciles_in_new_session() -> None:
    events: list[str] = []
    sessions = _TrackedSessionFactory(events)

    class Updater:
        def run(self):
            events.append("market_run")
            return AfterMarketResult("passed", date(2026, 8, 10), 1, None)

    class Reconciler:
        def reconcile_open_episodes(self):
            events.append("reconcile")
            return ()

    code = guiyi_main(
        ["data", "after-market"],
        session_factory=sessions,
        manager_factory=lambda session: events.append(f"manager:{session}") or object(),
        after_market_factory=lambda _manager: Updater(),
        execution_review_roll_marker_state=lambda: events.append("marker") or "enabled",
        roll_reconciler_factory=lambda session: (
            events.append(f"reconciler:{session}") or Reconciler()
        ),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == 0
    assert events == [
        "enter:session-1",
        "manager:session-1",
        "market_run",
        "exit:session-1",
        "marker",
        "enter:session-2",
        "reconciler:session-2",
        "reconcile",
        "exit:session-2",
    ]


def test_after_market_reconcile_exception_preserves_passed_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    sessions = _TrackedSessionFactory(events)

    class Updater:
        def run(self):
            events.append("market_run")
            return AfterMarketResult("passed", date(2026, 8, 10), 1, None)

    class Reconciler:
        def reconcile_open_episodes(self):
            events.append("reconcile")
            raise RuntimeError("private database detail")

    stdout = io.StringIO()
    caplog.set_level(logging.WARNING, logger="app.guiyi_cli.main")
    code = guiyi_main(
        ["data", "after-market"],
        session_factory=sessions,
        manager_factory=lambda _session: object(),
        after_market_factory=lambda _manager: Updater(),
        execution_review_roll_marker_state=lambda: "enabled",
        roll_reconciler_factory=lambda _session: Reconciler(),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "passed"
    assert events == [
        "enter:session-1",
        "market_run",
        "exit:session-1",
        "enter:session-2",
        "reconcile",
        "exit:session-2",
    ]
    assert [record.message for record in caplog.records] == [
        "EXECUTION_REVIEW_ROLL_FOLLOWUP_FAILED"
    ]


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


def test_execution_review_roll_marker_reader_is_exact_and_default_off(tmp_path) -> None:
    assert _execution_review_roll_marker_state(tmp_path) == "disabled"
    marker = tmp_path / ".run/execution-review-roll-enabled"
    marker.parent.mkdir()
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o600)
    assert _execution_review_roll_marker_state(tmp_path) == "enabled"

    marker.write_bytes(b"enabled")
    assert _execution_review_roll_marker_state(tmp_path) == "invalid"
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o644)
    assert _execution_review_roll_marker_state(tmp_path) == "invalid"


def test_skips_non_trading_day_without_ready_update_or_retry(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
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


def test_retries_once_after_data_is_not_ready(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[False, True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.attempts == 2
    assert rqdata.calls == [date(2026, 8, 10), date(2026, 8, 10)]
    assert len(manager.calls) == 1
    assert sleeps == [3600]
    assert notices == []


def test_retries_once_after_first_update_failure(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[_result("failed", stop_reason="PROVIDER_QUOTA_EXHAUSTED"), _result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.attempts == 2
    assert len(manager.calls) == 2
    assert sleeps == [3600]
    assert notices == []


def test_records_final_failure_and_notifies_once(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[_result("failed"), _result("failed")],
    )

    result = updater.run()
    status = _status(tmp_path / "after-market-status.json")

    assert result.status == "failed"
    assert result.attempts == 2
    assert result.error_code == "UPDATE_FAILED"
    assert len(manager.calls) == 2
    assert sleeps == [3600]
    assert notices == ["UPDATE_FAILED"]
    assert status["last_failure"] == {"trading_day": "2026-08-10", "error_code": "UPDATE_FAILED"}
    assert "exception" not in json.dumps(status).lower()
    assert "path" not in json.dumps(status).lower()


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
    assert notices == ["RQDATA_READY_CHECK_FAILED"]
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=rqdata_readiness attempt=1 "
        "detail_code=RQDATA_READY_RESPONSE_INVALID exception_type=InfrastructureError",
        "after_market_attempt_failed stage=rqdata_readiness attempt=2 "
        "detail_code=RQDATA_READY_RESPONSE_INVALID exception_type=InfrastructureError",
    ]
    assert "credential-secret-provider-message" not in caplog.text


def test_update_exception_logs_only_sanitized_stage_diagnostics(tmp_path, caplog) -> None:
    updater, manager, _rqdata, _sleeps, notices, _live_store = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True, True],
        results=[],
    )

    def fail_update(_request):
        raise RuntimeError("credential-secret-provider-message")

    manager.update = fail_update
    caplog.set_level(logging.WARNING, logger="app.market_data.after_market")

    result = updater.run()

    assert result.error_code == "UPDATE_FAILED"
    assert notices == ["UPDATE_FAILED"]
    assert [record.message for record in caplog.records] == [
        "after_market_attempt_failed stage=canonical_update attempt=1 "
        "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=RuntimeError",
        "after_market_attempt_failed stage=canonical_update attempt=2 "
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

    def fail_update(_request):
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
    assert public_status["last_run"]["error_code"] == (
        "NEXT_TRADING_SESSION_NOT_READY"
    )
    assert public_status["last_failure"]["error_code"] == (
        "NEXT_TRADING_SESSION_NOT_READY"
    )
    assert sleeps == [3600]
    assert notices == ["NEXT_TRADING_SESSION_NOT_READY"]
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

    assert result.status == "passed"
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

    assert result.error_code == "PROVIDER_QUOTA_EXHAUSTED"
    assert status["last_failure"] == {
        "trading_day": "2026-08-10",
        "error_code": "PROVIDER_QUOTA_EXHAUSTED",
    }
    assert notices == ["PROVIDER_QUOTA_EXHAUSTED"]


def test_success_clears_previous_last_failure(tmp_path) -> None:
    status_path = tmp_path / "after-market-status.json"
    status_path.write_text(
        json.dumps({"last_run": None, "last_successful_trading_day": None, "last_failure": {"trading_day": "2026-08-09", "error_code": "UPDATE_FAILED"}}),
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
        json.dumps({"last_run": None, "last_successful_trading_day": None, "last_failure": previous_failure}),
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
        (symbol, date(2026, 8, 10), date(2026, 8, 10))
        for symbol in _ACTIVE_PRODUCTS
    ]
    assert live_store.published == [{"trading_day": "2026-08-10"}]
    assert live_store.cleaned == [date(2026, 8, 10)]
    assert notices == []


def test_cleanup_failure_retries_then_fails_without_reporting_success(tmp_path) -> None:
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
    assert result.attempts == 2
    assert result.error_code == "UPDATE_FAILED"
    assert sleeps == [3600]
    assert notices == ["UPDATE_FAILED"]
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
    assert result.attempts == 2
    assert result.error_code == "LIVE_DOMINANT_MISMATCH"
    assert sleeps == [3600]
    assert notices == ["LIVE_DOMINANT_MISMATCH"]
    assert live_store.published == [
        {"trading_day": "2026-08-10"},
        {"trading_day": "2026-08-10"},
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
