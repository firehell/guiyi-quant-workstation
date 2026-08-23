from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

import pytest

from app.backtest.artifact_store import ArtifactStore, RunPaths
from app.backtest.config import BacktestSettings
from app.backtest.contracts import BacktestRunRequest, RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RunFailureCode
from app.backtest.registry import StrategyRegistry, ValidatedBacktestRequest
from app.backtest.runner import MonitorResult, RunnerProbe, build_rqalpha_config
from app.backtest.service import BacktestService


REPOSITORY_COMMIT = "cc8b4dd1fc2e684ef1d067a4d6798287cc87c5b4"


def _registry(tmp_path: Path) -> StrategyRegistry:
    strategies = tmp_path / "strategies"
    strategies.mkdir()
    (strategies / "example.py").write_text("def init(context): pass\n", "utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategies": [
                    {
                        "id": "example",
                        "name": "Example",
                        "description": "Fixture strategy",
                        "enabled": True,
                        "entry_file": "example.py",
                        "supported_frequencies": ["1d", "1m"],
                        "defaults": {
                            "future_cash": "1000000",
                            "matching_type": "current_bar",
                            "margin_multiplier": "1",
                            "futures_commission_multiplier": "1",
                            "slippage_model": "PriceRatioSlippage",
                            "slippage": "0",
                        },
                        "parameters": [
                            {
                                "name": "quantity",
                                "type": "integer",
                                "default": 1,
                                "min": 1,
                                "max": 10,
                            }
                        ],
                    }
                ],
            }
        ),
        "utf-8",
    )
    return StrategyRegistry.load(registry, strategies)


def _settings(tmp_path: Path) -> BacktestSettings:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    return BacktestSettings(
        python_executable=Path(sys.executable).resolve(),
        bundle_path=bundle.resolve(),
        runs_root=runs.resolve(),
        timeout_seconds=2,
        cors_origins=("http://127.0.0.1:5173",),
    )


def _request() -> BacktestRunRequest:
    return BacktestRunRequest.model_validate(
        {
            "strategy_id": "example",
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "frequency": "1d",
            "future_cash": "1000000.00",
            "matching_type": "current_bar",
            "margin_multiplier": "1.0",
            "futures_commission_multiplier": "1.00",
            "slippage_model": "PriceRatioSlippage",
            "slippage": "0.0000",
            "parameters": {"quantity": 2},
        }
    )


def _result_payload() -> dict[str, Any]:
    return {
        "summary": {
            "total_returns": "0.125",
            "annualized_returns": "0.25",
            "max_drawdown": "0.05",
            "sharpe": "1.5",
            "sortino": "2",
            "volatility": "0.2",
            "total_value": "1125000",
            "cash": "100000",
        },
        "equity": [
            {"date": "2026-01-05", "unit_net_value": "1"},
            {"date": "2026-01-06", "unit_net_value": "1.125"},
        ],
        "trade_count": "1",
        "artifacts": {
            "report_zip": True,
            "result_pickle": True,
            "equity_png": True,
            "stdout_log": True,
            "stderr_log": True,
            "run_json": True,
        },
    }


@dataclass
class _FakeProcess:
    paths: RunPaths
    result: MonitorResult
    complete_artifacts: bool = True
    monitor_error: Exception | None = None
    wait_before_monitor: threading.Event | None = None
    pid: int = field(default_factory=os.getpid)
    terminated: bool = False

    def monitor(self) -> MonitorResult:
        if self.wait_before_monitor is not None:
            assert self.wait_before_monitor.wait(timeout=2)
        if self.monitor_error is not None:
            raise self.monitor_error
        if self.result.outcome is RunStatus.SUCCEEDED:
            self.paths.result_json.write_text(json.dumps(_result_payload()), "utf-8")
            if self.complete_artifacts:
                self.paths.result_pickle.write_bytes(b"fake-pickle")
                self.paths.equity_png.write_bytes(b"fake-png")
                (self.paths.report_dir / "summary.csv").write_text(
                    "metric,value\n", "utf-8"
                )
        elif self.result.outcome is RunStatus.FAILED:
            self.paths.stderr_log.write_text("fake strategy failure\n", "utf-8")
        return self.result

    def _terminate_owned_process_group(self) -> int:
        self.terminated = True
        return -9


class _FakeRunner:
    def __init__(
        self,
        settings: BacktestSettings,
        result: MonitorResult | None = None,
        *,
        complete_artifacts: bool = True,
        wait_before_monitor: threading.Event | None = None,
        monitor_error: Exception | None = None,
        process_pid: int | None = None,
    ) -> None:
        self.settings = settings
        self.result = result or MonitorResult(0, RunStatus.SUCCEEDED, None)
        self.complete_artifacts = complete_artifacts
        self.wait_before_monitor = wait_before_monitor
        self.monitor_error = monitor_error
        self.process_pid = process_pid
        self.started: list[_FakeProcess] = []
        self.start_error: Exception | None = None
        self.probe_result = RunnerProbe(
            available=True,
            rqalpha_version="fake-rqalpha-1",
            rqsdk_version="fake-rqsdk-1",
            python_version="fake-python-1",
        )

    def probe(self) -> RunnerProbe:
        return self.probe_result

    def effective_config(
        self, request: ValidatedBacktestRequest, paths: RunPaths
    ) -> dict[str, Any]:
        return build_rqalpha_config(self.settings, request, paths)

    def start(
        self, _request: ValidatedBacktestRequest, paths: RunPaths
    ) -> _FakeProcess:
        if self.start_error is not None:
            raise self.start_error
        process = _FakeProcess(
            paths=paths,
            result=self.result,
            complete_artifacts=self.complete_artifacts,
            wait_before_monitor=self.wait_before_monitor,
            monitor_error=self.monitor_error,
            pid=self.process_pid if self.process_pid is not None else os.getpid(),
        )
        self.started.append(process)
        return process


def _service(
    tmp_path: Path,
    *,
    runner: _FakeRunner | None = None,
) -> tuple[BacktestService, ArtifactStore, _FakeRunner]:
    settings = _settings(tmp_path)
    selected_runner = runner or _FakeRunner(settings)
    store = ArtifactStore(settings)
    service = BacktestService(
        registry=_registry(tmp_path),
        store=store,
        runner=selected_runner,
        repository_commit=REPOSITORY_COMMIT,
    )
    return service, store, selected_runner


def _wait_terminal(service: BacktestService, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        record = service.get_run(run_id)
        if record["status"] != RunStatus.RUNNING:
            return record
        time.sleep(0.01)
    raise AssertionError("run did not become terminal")


def test_health_and_strategies_are_research_only_and_safe(tmp_path: Path) -> None:
    service, _store, _runner = _service(tmp_path)

    assert service.health() == {
        "status": "ready",
        "research_only": True,
        "formal_evidence": False,
        "promotion_eligible": False,
        "busy": False,
        "runner": {
            "available": True,
            "rqalpha_version": "fake-rqalpha-1",
            "rqsdk_version": "fake-rqsdk-1",
            "python_version": "fake-python-1",
        },
        "bundle_available": True,
        "runs_root_available": True,
    }
    assert service.list_strategies() == [
        {
            "id": "example",
            "name": "Example",
            "description": "Fixture strategy",
            "supported_frequencies": ["1d", "1m"],
            "defaults": {
                "future_cash": "1000000",
                "matching_type": "current_bar",
                "margin_multiplier": "1",
                "futures_commission_multiplier": "1",
                "slippage_model": "PriceRatioSlippage",
                "slippage": "0",
            },
            "parameters": [
                {
                    "name": "quantity",
                    "type": "integer",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 10,
                    "options": [],
                }
            ],
            "research_only": True,
            "formal_evidence": False,
            "promotion_eligible": False,
        }
    ]


def test_unwritable_runs_root_is_degraded_and_start_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, _runner = _service(tmp_path)
    real_access = os.access

    def deny_runs_root_write(path: str | Path, mode: int) -> bool:
        if Path(path) == store.runs_root and mode & os.W_OK:
            return False
        return real_access(path, mode)

    monkeypatch.setattr("app.backtest.service.os.access", deny_runs_root_write)

    health = service.health()

    assert health["status"] == "degraded"
    assert health["runs_root_available"] is False
    with pytest.raises(BacktestError, match="^BACKTEST_LOCAL_UNAVAILABLE$"):
        service.start_run(_request())


def test_start_persists_authoritative_lineage_configs_and_terminal_times(
    tmp_path: Path,
) -> None:
    service, store, _runner = _service(tmp_path)

    started = service.start_run(_request())
    terminal = _wait_terminal(service, started["run_id"])
    persisted = store.read_run(started["run_id"])

    assert terminal == persisted | {
        "result": _result_payload(),
        "stdout_tail": "",
        "stderr_tail": "",
    }
    assert persisted["research_only"] is True
    assert persisted["formal_evidence"] is False
    assert persisted["promotion_eligible"] is False
    assert persisted["repository_commit"] == REPOSITORY_COMMIT
    assert persisted["strategy_id"] == "example"
    assert persisted["strategy_name"] == "Example"
    assert len(persisted["strategy_sha256"]) == 64
    assert persisted["bundle_path"].endswith("/bundle")
    assert persisted["versions"] == {
        "rqalpha": "fake-rqalpha-1",
        "rqsdk": "fake-rqsdk-1",
        "python": "fake-python-1",
    }
    assert persisted["requested_config"]["future_cash"] == "1000000.00"
    assert persisted["effective_parameters"] == {"quantity": 2}
    assert persisted["effective_config"]["base"]["auto_update_bundle"] is False
    assert persisted["status"] == "succeeded"
    assert persisted["started_at"] < persisted["finished_at"]
    assert persisted["exit_code"] == 0
    assert persisted["failure_code"] is None
    assert store.read_lock() is None


def test_alive_pid_remains_busy_and_degraded_without_takeover_or_kill(
    tmp_path: Path,
) -> None:
    service, store, runner = _service(tmp_path)
    strategy = service.registry.resolve_enabled("example")
    started_at = "2026-08-23T01:02:03+00:00"
    store.create_run(
        "live-run",
        run_record={"status": RunStatus.RUNNING, "started_at": started_at},
        strategy_file=strategy.strategy_file,
        strategy_params={"quantity": 1},
    )
    store.acquire_lock("live-run", pid=os.getpid(), started_at=started_at)

    assert service.health()["status"] == "degraded"
    assert service.health()["busy"] is True
    with pytest.raises(BacktestError, match="^BACKTEST_ALREADY_RUNNING$"):
        service.start_run(_request())

    assert store.read_lock() is not None
    assert runner.started == []


def test_missing_pid_is_reconciled_to_interrupted_before_public_read(
    tmp_path: Path,
) -> None:
    service, store, _runner = _service(tmp_path)
    strategy = service.registry.resolve_enabled("example")
    started_at = "2026-08-23T01:02:03+00:00"
    store.create_run(
        "lost-run",
        run_record={"status": RunStatus.RUNNING, "started_at": started_at},
        strategy_file=strategy.strategy_file,
        strategy_params={"quantity": 1},
    )
    store.acquire_lock("lost-run", pid=2_147_483_647, started_at=started_at)

    records = service.list_runs()

    assert records[0]["status"] == "interrupted"
    assert records[0]["failure_code"] == "RUN_INTERRUPTED"
    assert records[0]["finished_at"]
    assert store.read_lock() is None


@pytest.mark.parametrize(
    ("result", "expected_status", "expected_failure"),
    [
        (MonitorResult(0, RunStatus.SUCCEEDED, None), "succeeded", None),
        (
            MonitorResult(
                7, RunStatus.FAILED, RunFailureCode.STRATEGY_EXECUTION_FAILED
            ),
            "failed",
            "STRATEGY_EXECUTION_FAILED",
        ),
        (
            MonitorResult(-9, RunStatus.TIMED_OUT, RunFailureCode.RUN_TIMED_OUT),
            "timed_out",
            "RUN_TIMED_OUT",
        ),
    ],
)
def test_monitor_persists_normal_terminal_states_and_releases_lock(
    tmp_path: Path,
    result: MonitorResult,
    expected_status: str,
    expected_failure: str | None,
) -> None:
    settings = _settings(tmp_path)
    runner = _FakeRunner(settings, result)
    service = BacktestService(
        registry=_registry(tmp_path),
        store=ArtifactStore(settings),
        runner=runner,
        repository_commit=REPOSITORY_COMMIT,
    )

    started = service.start_run(_request())
    terminal = _wait_terminal(service, started["run_id"])

    assert terminal["status"] == expected_status
    assert terminal["exit_code"] == result.exit_code
    assert terminal["failure_code"] == expected_failure
    assert service.store.read_lock() is None
    if expected_status == "failed":
        assert terminal["stderr_tail"] == "fake strategy failure"


def test_succeeded_monitor_result_becomes_failed_when_analyser_artifacts_missing(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    runner = _FakeRunner(settings, complete_artifacts=False)
    service = BacktestService(
        registry=_registry(tmp_path),
        store=ArtifactStore(settings),
        runner=runner,
        repository_commit=REPOSITORY_COMMIT,
    )

    started = service.start_run(_request())
    terminal = _wait_terminal(service, started["run_id"])

    assert terminal["status"] == "failed"
    assert terminal["failure_code"] == "RESULT_INCOMPLETE"
    assert terminal["exit_code"] == 0
    assert service.store.read_lock() is None


def test_terminal_record_is_written_before_owned_lock_is_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, _runner = _service(tmp_path)
    events: list[tuple[str, str]] = []
    real_update = store.update_run
    real_release = store.release_lock

    def observe_update(run_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if "status" in changes and changes["status"] != RunStatus.RUNNING:
            events.append(("update", str(changes["status"])))
        return real_update(run_id, changes)

    def observe_release(run_id: str) -> bool:
        events.append(("release", run_id))
        assert store.read_run(run_id)["status"] == "succeeded"
        return real_release(run_id)

    monkeypatch.setattr(store, "update_run", observe_update)
    monkeypatch.setattr(store, "release_lock", observe_release)

    started = service.start_run(_request())
    _wait_terminal(service, started["run_id"])

    assert events == [
        ("update", "succeeded"),
        ("release", started["run_id"]),
    ]


def test_public_reconcile_does_not_interrupt_owned_pid_after_child_exit_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    missing_pid = 2_147_483_647
    runner = _FakeRunner(settings, process_pid=missing_pid)
    store = ArtifactStore(settings)
    service = BacktestService(
        registry=_registry(tmp_path),
        store=store,
        runner=runner,
        repository_commit=REPOSITORY_COMMIT,
    )
    terminal_write_entered = threading.Event()
    allow_terminal_write = threading.Event()
    real_update = store.update_run

    def pause_terminal_update(run_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if "status" in changes and changes["status"] == RunStatus.SUCCEEDED:
            terminal_write_entered.set()
            assert allow_terminal_write.wait(timeout=2)
        return real_update(run_id, changes)

    monkeypatch.setattr(store, "update_run", pause_terminal_update)

    started = service.start_run(_request())
    assert terminal_write_entered.wait(timeout=2)
    observed_while_monitor_owns_pid = service.get_run(started["run_id"])
    allow_terminal_write.set()
    terminal = _wait_terminal(service, started["run_id"])

    assert observed_while_monitor_owns_pid["status"] == "running"
    assert terminal["status"] == "succeeded"
    assert store.read_lock() is None


def test_spawn_failure_marks_failed_and_leaves_logs_without_lock(
    tmp_path: Path,
) -> None:
    service, store, runner = _service(tmp_path)
    runner.start_error = BacktestError(BacktestHttpErrorCode.RUNNER_UNAVAILABLE)

    with pytest.raises(BacktestError, match="^RUNNER_UNAVAILABLE$"):
        service.start_run(_request())

    record = store.list_runs()[0]
    assert record["status"] == "failed"
    assert record["failure_code"] == "RUNNER_UNAVAILABLE"
    assert (store.run_paths(record["run_id"]).root / "stdout.log").is_file()
    assert (store.run_paths(record["run_id"]).root / "stderr.log").is_file()
    assert store.read_lock() is None


def test_lock_failure_after_spawn_terminates_only_new_child_and_marks_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, runner = _service(tmp_path)

    def conflict(*_args: object, **_kwargs: object) -> None:
        raise BacktestError(BacktestHttpErrorCode.BACKTEST_ALREADY_RUNNING)

    monkeypatch.setattr(store, "acquire_lock", conflict)

    with pytest.raises(BacktestError, match="^BACKTEST_ALREADY_RUNNING$"):
        service.start_run(_request())

    assert len(runner.started) == 1
    assert runner.started[0].terminated is True
    assert store.list_runs()[0]["status"] == "failed"
    assert store.read_lock() is None


def test_monitor_thread_exception_records_failure_but_keeps_live_pid_lock(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    runner = _FakeRunner(settings, monitor_error=RuntimeError("private detail"))
    service = BacktestService(
        registry=_registry(tmp_path),
        store=ArtifactStore(settings),
        runner=runner,
        repository_commit=REPOSITORY_COMMIT,
    )

    started = service.start_run(_request())
    terminal = _wait_terminal(service, started["run_id"])

    assert terminal["status"] == "failed"
    assert terminal["failure_code"] == "STRATEGY_EXECUTION_FAILED"
    assert terminal["exit_code"] is None
    assert "private detail" not in json.dumps(terminal)
    assert service.store.read_lock() is not None


def test_terminal_write_failure_keeps_lock_for_later_stale_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = threading.Event()
    settings = _settings(tmp_path)
    runner = _FakeRunner(settings, wait_before_monitor=gate)
    store = ArtifactStore(settings)
    service = BacktestService(
        registry=_registry(tmp_path),
        store=store,
        runner=runner,
        repository_commit=REPOSITORY_COMMIT,
    )
    real_update = store.update_run

    def fail_terminal_update(run_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        if "status" in changes and changes["status"] != RunStatus.RUNNING:
            raise OSError("injected terminal write failure")
        return real_update(run_id, changes)

    monkeypatch.setattr(store, "update_run", fail_terminal_update)

    started = service.start_run(_request())
    gate.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and store.read_lock() is None:
        time.sleep(0.01)
    time.sleep(0.05)

    assert store.read_run(started["run_id"])["status"] == "running"
    assert store.read_lock() is not None


def test_every_public_operation_reconciles_before_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, store, _runner = _service(tmp_path)
    calls: list[str] = []
    real_reconcile = store.reconcile_stale_lock

    def observe_reconcile(**kwargs: Any) -> Any:
        calls.append("reconcile")
        return real_reconcile(**kwargs)

    monkeypatch.setattr(store, "reconcile_stale_lock", observe_reconcile)
    started = service.start_run(_request())
    terminal = _wait_terminal(service, started["run_id"])
    service.health()
    service.list_strategies()
    service.list_runs()
    service.get_run(started["run_id"])
    with service.open_artifact(started["run_id"], "equity_png") as artifact:
        assert artifact.read() == b"fake-png"

    assert len(calls) >= 7
    assert terminal["status"] == "succeeded"
