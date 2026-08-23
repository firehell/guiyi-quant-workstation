"""Single-run orchestration for the local research backtest sidecar."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import stat
import threading
from typing import Any, BinaryIO, cast

from app.backtest.artifact_store import ActiveLock, ArtifactStore, RunPaths
from app.backtest.contracts import BacktestRunRequest, RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RunFailureCode
from app.backtest.registry import (
    ParameterDescriptor,
    RegisteredStrategy,
    StrategyRegistry,
    ValidatedBacktestRequest,
)
from app.backtest.runner import (
    MonitorResult,
    RunningProcess,
    RunnerProbe,
    SubprocessRunner,
)


_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
_NORMAL_TERMINAL_STATES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.TIMED_OUT}
)
_REQUIRED_RESULT_ARTIFACTS = ("report_zip", "result_pickle", "equity_png")


class BacktestService:
    """Coordinate one owned child without adopting any pre-existing process."""

    def __init__(
        self,
        *,
        registry: StrategyRegistry,
        store: ArtifactStore,
        runner: SubprocessRunner,
        repository_commit: str,
    ) -> None:
        if _COMMIT_SHA.fullmatch(repository_commit) is None:
            raise ValueError("BACKTEST_REPOSITORY_COMMIT_INVALID")
        self.registry = registry
        self.store = store
        self.runner = runner
        self.repository_commit = repository_commit
        self._operation_lock = threading.RLock()
        self._ownership_lock = threading.Lock()
        self._owned_pids: set[int] = set()

    def health(self) -> dict[str, Any]:
        """Return readiness while treating every live lock as degraded/busy."""

        with self._operation_lock:
            try:
                active_lock = self._reconcile_stale_lock()
            except (BacktestError, OSError, RuntimeError, ValueError):
                active_lock = None
                reconciliation_valid = False
            else:
                reconciliation_valid = True
            probe = self.runner.probe()
            bundle_available = self._directory_available(
                self.runner.settings.bundle_path,
                access_mode=os.R_OK | os.X_OK,
            )
            runs_root_available = self._directory_available(
                self.store.runs_root,
                access_mode=os.R_OK | os.W_OK | os.X_OK,
            )
            busy = active_lock is not None
            ready = (
                reconciliation_valid
                and not busy
                and probe.available
                and bundle_available
                and runs_root_available
            )
            return {
                "status": "ready" if ready else "degraded",
                "research_only": True,
                "formal_evidence": False,
                "promotion_eligible": False,
                "busy": busy,
                "runner": self._probe_payload(probe),
                "bundle_available": bundle_available,
                "runs_root_available": runs_root_available,
            }

    def list_strategies(self) -> list[dict[str, Any]]:
        """List only enabled registered strategies, never their filesystem paths."""

        with self._operation_lock:
            self._reconcile_stale_lock()
            return [
                self._strategy_payload(item) for item in self.registry.list_enabled()
            ]

    def start_run(self, request: BacktestRunRequest) -> dict[str, Any]:
        """Synchronously create/spawn/lock, then monitor the owned child in background."""

        with self._operation_lock:
            active_lock = self._reconcile_stale_lock()
            if active_lock is not None:
                raise BacktestError(BacktestHttpErrorCode.BACKTEST_ALREADY_RUNNING)
            self._require_start_readiness()
            validated = self.registry.validate_request(request)
            probe = self.runner.probe()
            if not probe.available:
                raise BacktestError(BacktestHttpErrorCode.RUNNER_UNAVAILABLE)

            run_id = self._new_run_id()
            started_at = self._now()
            paths = self.store.run_paths(run_id)
            record = self._initial_record(
                request=request,
                validated=validated,
                probe=probe,
                run_id=run_id,
                started_at=started_at,
            )
            self.store.create_run(
                run_id,
                run_record=record,
                strategy_file=validated.strategy_file,
                strategy_params=validated.parameters,
            )
            try:
                effective_config = self.runner.effective_config(validated, paths)
                self.store.update_run(
                    run_id,
                    {
                        "effective_config": effective_config,
                        "effective_parameters": dict(validated.parameters),
                    },
                )
                process = self.runner.start(validated, paths)
            except Exception as exc:
                failure_code = (
                    RunFailureCode.RUNNER_UNAVAILABLE
                    if isinstance(exc, BacktestError)
                    and str(exc) == BacktestHttpErrorCode.RUNNER_UNAVAILABLE
                    else RunFailureCode.STRATEGY_EXECUTION_FAILED
                )
                self._write_start_failure(run_id, failure_code)
                raise

            try:
                self.store.acquire_lock(
                    run_id,
                    pid=process.pid,
                    started_at=started_at,
                )
            except Exception:
                self._stop_new_process(process)
                self._write_start_failure(
                    run_id,
                    RunFailureCode.STRATEGY_EXECUTION_FAILED,
                )
                raise
            self._mark_owned(process.pid)

            monitor = threading.Thread(
                target=self._monitor_owned_run,
                args=(run_id, paths, process),
                name=f"backtest-monitor-{run_id}",
                daemon=True,
            )
            try:
                monitor.start()
            except Exception:
                self._stop_new_process(process)
                try:
                    self._write_start_failure(
                        run_id,
                        RunFailureCode.STRATEGY_EXECUTION_FAILED,
                    )
                except Exception:
                    pass
                else:
                    self.store.release_lock(run_id)
                finally:
                    self._unmark_owned(process.pid)
                raise
            return self.store.read_run(run_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent authoritative run records after stale-lock reconciliation."""

        with self._operation_lock:
            self._reconcile_stale_lock()
            return self.store.list_runs(limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return one authoritative record with optional result and bounded logs."""

        with self._operation_lock:
            self._reconcile_stale_lock()
            record = self.store.read_run(run_id)
            result: dict[str, Any] | None = None
            if record.get("status") == RunStatus.SUCCEEDED:
                result = self.store.read_result(run_id)
            return {
                **record,
                "result": result,
                "stdout_tail": self.store.read_log_tail(run_id, "stdout"),
                "stderr_tail": self.store.read_log_tail(run_id, "stderr"),
            }

    def open_artifact(
        self,
        run_id: str,
        kind: str,
    ) -> AbstractContextManager[BinaryIO]:
        """Open one allowlisted artifact after stale-lock reconciliation."""

        with self._operation_lock:
            self._reconcile_stale_lock()
            if kind == "report_zip":
                return self.store.temporary_report_zip(run_id)
            return cast(
                AbstractContextManager[BinaryIO],
                self.store.resolve_artifact(run_id, kind),
            )

    def _require_start_readiness(self) -> None:
        if not self._directory_available(
            self.runner.settings.bundle_path,
            access_mode=os.R_OK | os.X_OK,
        ):
            raise BacktestError(BacktestHttpErrorCode.BUNDLE_UNAVAILABLE)
        if not self._directory_available(
            self.store.runs_root,
            access_mode=os.R_OK | os.W_OK | os.X_OK,
        ):
            raise BacktestError(BacktestHttpErrorCode.BACKTEST_LOCAL_UNAVAILABLE)

    def _monitor_owned_run(
        self,
        run_id: str,
        paths: RunPaths,
        process: RunningProcess,
    ) -> None:
        monitor_failed = False
        try:
            try:
                result = process.monitor()
            except Exception:
                monitor_failed = True
                result = MonitorResult(
                    exit_code=None,
                    outcome=RunStatus.FAILED,
                    failure_code=RunFailureCode.STRATEGY_EXECUTION_FAILED,
                )
            result = self._validated_monitor_result(result)
            if result.outcome is RunStatus.SUCCEEDED and not self._outputs_complete(
                run_id, paths
            ):
                result = MonitorResult(
                    exit_code=result.exit_code,
                    outcome=RunStatus.FAILED,
                    failure_code=RunFailureCode.RESULT_INCOMPLETE,
                )
            self.store.update_run(
                run_id,
                {
                    "status": result.outcome,
                    "finished_at": self._now(),
                    "exit_code": result.exit_code,
                    "failure_code": result.failure_code,
                },
            )
        except Exception:
            # Preserve the live lock when terminal state could not be published.
            # A later public operation will reconcile it only after the PID is gone.
            self._unmark_owned(process.pid)
            return
        if monitor_failed:
            # The monitor no longer proves the owned PID is gone. Keep the lock
            # so a live child cannot overlap a later run; stale reconciliation
            # releases it after the PID disappears.
            self._unmark_owned(process.pid)
            return
        try:
            self.store.release_lock(run_id)
        except (BacktestError, OSError, RuntimeError, ValueError):
            pass
        finally:
            self._unmark_owned(process.pid)

    def _reconcile_stale_lock(self) -> ActiveLock | None:
        return self.store.reconcile_stale_lock(pid_exists=self._pid_is_active)

    def _pid_is_active(self, pid: int) -> bool:
        with self._ownership_lock:
            if pid in self._owned_pids:
                return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _mark_owned(self, pid: int) -> None:
        with self._ownership_lock:
            self._owned_pids.add(pid)

    def _unmark_owned(self, pid: int) -> None:
        with self._ownership_lock:
            self._owned_pids.discard(pid)

    @staticmethod
    def _validated_monitor_result(result: MonitorResult) -> MonitorResult:
        if result.outcome not in _NORMAL_TERMINAL_STATES:
            return MonitorResult(
                exit_code=None,
                outcome=RunStatus.FAILED,
                failure_code=RunFailureCode.STRATEGY_EXECUTION_FAILED,
            )
        if result.outcome is RunStatus.SUCCEEDED:
            if result.exit_code == 0 and result.failure_code is None:
                return result
        elif result.outcome is RunStatus.TIMED_OUT:
            if result.failure_code is RunFailureCode.RUN_TIMED_OUT:
                return result
        elif result.failure_code in {
            RunFailureCode.STRATEGY_EXECUTION_FAILED,
            RunFailureCode.RESULT_INCOMPLETE,
        }:
            return result
        return MonitorResult(
            exit_code=result.exit_code,
            outcome=RunStatus.FAILED,
            failure_code=RunFailureCode.STRATEGY_EXECUTION_FAILED,
        )

    def _outputs_complete(self, run_id: str, paths: RunPaths) -> bool:
        try:
            result = self.store.read_result(run_id)
            artifacts = result.get("artifacts")
            if not isinstance(artifacts, Mapping) or not all(
                artifacts.get(kind) is True for kind in _REQUIRED_RESULT_ARTIFACTS
            ):
                return False
            for kind in ("result_pickle", "equity_png"):
                with self.store.resolve_artifact(run_id, kind) as artifact:
                    if not artifact.read(1):
                        return False
            with self.store.temporary_report_zip(run_id) as report_zip:
                if not report_zip.read(1):
                    return False
            return self._regular_file(paths.result_json)
        except (BacktestError, OSError, RuntimeError, TypeError, ValueError):
            return False

    def _write_start_failure(
        self,
        run_id: str,
        failure_code: RunFailureCode,
    ) -> None:
        self.store.update_run(
            run_id,
            {
                "status": RunStatus.FAILED,
                "finished_at": self._now(),
                "exit_code": None,
                "failure_code": failure_code,
            },
        )

    @staticmethod
    def _stop_new_process(process: RunningProcess) -> None:
        """Stop only the handle returned by this start attempt."""

        terminate = getattr(process, "_terminate_owned_process_group", None)
        if not callable(terminate):
            raise RuntimeError("BACKTEST_STARTED_PROCESS_CLEANUP_UNAVAILABLE")
        terminate()

    def _initial_record(
        self,
        *,
        request: BacktestRunRequest,
        validated: ValidatedBacktestRequest,
        probe: RunnerProbe,
        run_id: str,
        started_at: str,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "research_only": True,
            "formal_evidence": False,
            "promotion_eligible": False,
            "strategy_id": validated.strategy.id,
            "strategy_name": validated.strategy.name,
            "strategy_entry_file": validated.strategy.entry_file,
            "repository_commit": self.repository_commit,
            "bundle_path": str(self.runner.settings.bundle_path),
            "versions": {
                "rqalpha": probe.rqalpha_version,
                "rqsdk": probe.rqsdk_version,
                "python": probe.python_version,
            },
            "requested_config": request.model_dump(mode="json"),
            "effective_config": {},
            "effective_parameters": {},
            "status": RunStatus.RUNNING,
            "started_at": started_at,
            "finished_at": None,
            "exit_code": None,
            "failure_code": None,
        }

    @staticmethod
    def _probe_payload(probe: RunnerProbe) -> dict[str, Any]:
        return {
            "available": probe.available,
            "rqalpha_version": probe.rqalpha_version,
            "rqsdk_version": probe.rqsdk_version,
            "python_version": probe.python_version,
        }

    @classmethod
    def _strategy_payload(cls, strategy: RegisteredStrategy) -> dict[str, Any]:
        return {
            "id": strategy.id,
            "name": strategy.name,
            "description": strategy.description,
            "supported_frequencies": list(strategy.supported_frequencies),
            "defaults": dict(strategy.defaults),
            "parameters": [
                cls._parameter_payload(item) for item in strategy.parameters
            ],
            "research_only": True,
            "formal_evidence": False,
            "promotion_eligible": False,
        }

    @staticmethod
    def _parameter_payload(parameter: ParameterDescriptor) -> dict[str, Any]:
        return {
            "name": parameter.name,
            "type": parameter.type,
            "default": parameter.default,
            "minimum": parameter.minimum,
            "maximum": parameter.maximum,
            "options": list(parameter.options),
        }

    @staticmethod
    def _directory_available(path: Path, *, access_mode: int) -> bool:
        try:
            return stat.S_ISDIR(path.lstat().st_mode) and os.access(path, access_mode)
        except OSError:
            return False

    @staticmethod
    def _regular_file(path: Path) -> bool:
        try:
            return stat.S_ISREG(path.lstat().st_mode)
        except OSError:
            return False

    @staticmethod
    def _new_run_id() -> str:
        prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}-{secrets.token_hex(8)}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["BacktestService"]
