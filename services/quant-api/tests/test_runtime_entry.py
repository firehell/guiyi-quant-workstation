from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime_entry import run_after_market


QUANT_API_ROOT = Path(__file__).resolve().parents[1]
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
        self._payload = payload

    def as_payload(self) -> dict[str, object]:
        return self._payload


def _after_market_factory(
    result: _MarketResult,
    events: list[str],
):
    class Updater:
        def run(self) -> _MarketResult:
            events.append("market_run")
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


def test_runtime_after_market_rejects_removed_daily_watch_hook() -> None:
    events: list[str] = []

    with pytest.raises(TypeError):
        run_after_market(
            session_factory=_TrackedSessionFactory(events),
            manager_factory=lambda session: (
                events.append(f"manager:{session}") or object()
            ),
            after_market_factory=_after_market_factory(
                _MarketResult("passed", _PASSED_PAYLOAD),
                events,
            ),
            failure_notification=True,
            daily_watch_generator_factory=lambda _session: object(),
        )
