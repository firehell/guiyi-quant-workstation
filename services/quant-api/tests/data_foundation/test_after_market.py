from __future__ import annotations

import json
from datetime import date, datetime

from app.market_data.after_market import AfterMarketUpdater
from app.market_data.maintenance import MaintenanceResult


class _Coverage:
    def __init__(self, trading_day: date) -> None:
        self.trading_day = trading_day
        self.calls: list[tuple[str, ...]] = []

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        self.calls.append(products)
        return self.trading_day


class _Manager:
    def __init__(self, trading_day: date, results: list[MaintenanceResult]) -> None:
        self.coverage = _Coverage(trading_day)
        self._results = results
        self.calls = []

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


def _updater(tmp_path, *, trading_day: date, readiness: list[bool], results: list[MaintenanceResult]):
    manager = _Manager(trading_day, results)
    rqdata = _RQData(readiness)
    sleeps: list[float] = []
    notices: list[str] = []
    updater = AfterMarketUpdater(
        manager=manager,
        rqdata=rqdata,
        status_path=tmp_path / "after-market-status.json",
        sleep=sleeps.append,
        notifier=notices.append,
        now=lambda: datetime(2026, 8, 10, 17, 0),
    )
    return updater, manager, rqdata, sleeps, notices


def _status(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_skips_non_trading_day_without_ready_update_or_retry(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices = _updater(
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


def test_updates_once_when_first_attempt_is_ready(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices = _updater(
        tmp_path,
        trading_day=date(2026, 8, 10),
        readiness=[True],
        results=[_result("passed")],
    )

    result = updater.run()

    assert result.status == "passed"
    assert result.attempts == 1
    assert result.error_code is None
    assert manager.calls[0].products == ("j", "jm", "ap", "ag")
    assert manager.calls[0].since is None
    assert manager.calls[0].through == date(2026, 8, 10)
    assert manager.calls[0].apply is True
    assert rqdata.calls == [date(2026, 8, 10)]
    assert sleeps == []
    assert notices == []


def test_retries_once_after_data_is_not_ready(tmp_path) -> None:
    updater, manager, rqdata, sleeps, notices = _updater(
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
    updater, manager, rqdata, sleeps, notices = _updater(
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
    updater, manager, rqdata, sleeps, notices = _updater(
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
