from __future__ import annotations

from datetime import date
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime_entry import main, run_after_market


QUANT_API_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_TRADING_DAY = date(2026, 8, 21)
_PASSED_PAYLOAD = {
    "schema_version": 2,
    "command": "data.after-market",
    "status": "passed",
    "trading_day": "2026-08-21",
    "attempts": 1,
    "error_code": None,
}


class _TrackedSession:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def __enter__(self) -> str:
        self._events.append(f"enter:{self._name}")
        return self._name

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self._events.append(f"exit:{self._name}")


class _TrackedSessionFactory:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._calls = 0

    def __call__(self) -> _TrackedSession:
        self._calls += 1
        return _TrackedSession(f"session-{self._calls}", self._events)


class _MarketResult:
    def __init__(self, status: str, payload: dict[str, object]) -> None:
        self.status = status
        self.trading_day = _SOURCE_TRADING_DAY
        self._payload = payload

    def as_payload(self) -> dict[str, object]:
        return self._payload


def _after_market_factory(
    result: _MarketResult,
    events: list[str],
):
    class Updater:
        def run(self, *, post_update=None) -> _MarketResult:
            events.append("market_run")
            if result.status == "passed" and post_update is not None:
                try:
                    post_update(result.trading_day)
                except Exception:
                    return _MarketResult(
                        "failed",
                        {
                            **result.as_payload(),
                            "status": "failed",
                            "error_code": "SUBING_DAILY_WATCH_FAILED",
                        },
                    )
            return result

    return lambda _manager, **_kwargs: Updater()


def test_actual_runtime_launch_module_imports_no_offline_research() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.runtime_entry; "
                "print(sum(name == 'app.research' or "
                "name.startswith('app.research.') for name in sys.modules))"
            ),
        ],
        cwd=QUANT_API_ROOT,
        env={**os.environ, "PYTHONPATH": str(QUANT_API_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


@pytest.mark.parametrize("market_status", ("failed", "skipped"))
def test_daily_watch_is_not_constructed_for_non_passed_after_market(
    market_status: str,
) -> None:
    events: list[str] = []
    payload = {**_PASSED_PAYLOAD, "status": market_status}

    result = run_after_market(
        session_factory=_TrackedSessionFactory(events),
        manager_factory=lambda session: events.append(f"manager:{session}") or object(),
        after_market_factory=_after_market_factory(
            _MarketResult(market_status, payload),
            events,
        ),
        failure_notification=True,
        daily_watch_generator_factory=lambda _session: pytest.fail(
            "daily watch must not be constructed"
        ),
    )

    assert result == payload
    assert events == [
        "enter:session-1",
        "manager:session-1",
        "market_run",
        "exit:session-1",
    ]


def test_passed_after_market_runs_daily_watch_once_in_a_fresh_session() -> None:
    events: list[str] = []

    class Generator:
        def run(self, source_trading_day: date) -> None:
            events.append(f"daily_watch:{source_trading_day.isoformat()}")

    result = run_after_market(
        session_factory=_TrackedSessionFactory(events),
        manager_factory=lambda session: events.append(f"manager:{session}") or object(),
        after_market_factory=_after_market_factory(
            _MarketResult("passed", _PASSED_PAYLOAD),
            events,
        ),
        failure_notification=True,
        daily_watch_generator_factory=lambda session: (
            events.append(f"daily_watch_factory:{session}") or Generator()
        ),
    )

    assert result == _PASSED_PAYLOAD
    assert events == [
        "enter:session-1",
        "manager:session-1",
        "market_run",
        "enter:session-2",
        "daily_watch_factory:session-2",
        "daily_watch:2026-08-21",
        "exit:session-2",
        "exit:session-1",
    ]


def test_daily_watch_exception_marks_runtime_after_market_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []

    class Generator:
        def run(self, _source_trading_day: date) -> None:
            raise RuntimeError("private /Volumes/secret/research path")

    stdout = io.StringIO()
    stderr = io.StringIO()
    caplog.set_level(logging.WARNING)
    exit_code = main(
        ["after-market"],
        session_factory=_TrackedSessionFactory(events),
        manager_factory=lambda _session: object(),
        after_market_factory=_after_market_factory(
            _MarketResult("passed", _PASSED_PAYLOAD),
            events,
        ),
        daily_watch_generator_factory=lambda _session: Generator(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert json.loads(stdout.getvalue()) == {
        **_PASSED_PAYLOAD,
        "status": "failed",
        "error_code": "SUBING_DAILY_WATCH_FAILED",
    }
    assert stderr.getvalue() == ""
    assert caplog.records == []
    assert all(record.exc_info is None for record in caplog.records)
    assert "private" not in caplog.text
    assert "/Volumes/" not in caplog.text


def test_runtime_main_passes_daily_watch_factory_to_after_market_runner() -> None:
    events: list[str] = []

    class Generator:
        def run(self, source_trading_day: date) -> None:
            events.append(f"daily_watch:{source_trading_day.isoformat()}")

    stdout = io.StringIO()
    exit_code = main(
        ["after-market"],
        session_factory=_TrackedSessionFactory(events),
        manager_factory=lambda _session: object(),
        after_market_factory=_after_market_factory(
            _MarketResult("passed", _PASSED_PAYLOAD),
            events,
        ),
        daily_watch_generator_factory=lambda _session: Generator(),
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert exit_code == 0
    assert events.count("daily_watch:2026-08-21") == 1
    assert json.loads(stdout.getvalue()) == _PASSED_PAYLOAD
