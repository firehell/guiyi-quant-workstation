"""Fixed, secret-safe subprocess seam for one local RQAlpha run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
from typing import Any, BinaryIO, NoReturn

from app.backtest.artifact_store import RunPaths
from app.backtest.config import BacktestSettings
from app.backtest.contracts import RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RunFailureCode
from app.backtest.registry import ValidatedBacktestRequest


_RUNNER_ENTRY_PATH = Path(__file__).with_name("runner_entry.py")
_QUANT_API_ROOT = Path(__file__).resolve().parents[2]
_TERMINATE_GRACE_SECONDS = 2.0
_INHERITED_ENV_ALLOWLIST = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
)
_SENSITIVE_ENV_MARKERS = (
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "RQDATA",
    "RQDATAC",
    "PUSHPLUS",
    "LICENSE",
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)((?:\"|')?\b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|license|database_url|redis_url|rqdata(?:c)?[_-]?\w*)\b"
    r"(?:\"|')?\s*[=:]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;}]+)"
)
_URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")


@dataclass(frozen=True, slots=True)
class RunnerProbe:
    available: bool
    rqalpha_version: str
    rqsdk_version: str
    python_version: str


@dataclass(frozen=True, slots=True)
class MonitorResult:
    exit_code: int | None
    outcome: RunStatus
    failure_code: RunFailureCode | None


def _invalid_paths() -> NoReturn:
    raise ValueError("BACKTEST_RUN_PATHS_INVALID")


def _expected_paths(root: Path) -> dict[str, Path]:
    return {
        "run_json": root / "run.json",
        "result_json": root / "result.json",
        "strategy_file": root / "strategy.py",
        "strategy_params_json": root / "strategy_params.json",
        "result_pickle": root / "result.pkl",
        "equity_png": root / "equity.png",
        "report_dir": root / "report",
        "stdout_log": root / "stdout.log",
        "stderr_log": root / "stderr.log",
    }


def _validate_paths(settings: BacktestSettings, paths: RunPaths) -> None:
    root = paths.root
    if not root.is_absolute() or root.parent != settings.runs_root:
        _invalid_paths()
    try:
        if root.resolve(strict=True) != root or not stat.S_ISDIR(root.lstat().st_mode):
            _invalid_paths()
    except OSError:
        _invalid_paths()
    expected = _expected_paths(root)
    if any(getattr(paths, name) != path for name, path in expected.items()):
        _invalid_paths()


def build_rqalpha_config(
    settings: BacktestSettings,
    request: ValidatedBacktestRequest,
    paths: RunPaths,
) -> dict[str, Any]:
    """Build the complete non-overridable RQAlpha configuration."""

    _validate_paths(settings, paths)
    config = request.config
    expected_keys = {
        "start_date",
        "end_date",
        "frequency",
        "future_cash",
        "matching_type",
        "margin_multiplier",
        "futures_commission_multiplier",
        "slippage_model",
        "slippage",
    }
    if set(config) != expected_keys:
        raise ValueError("BACKTEST_REQUEST_CONFIG_INVALID")
    return {
        "base": {
            "start_date": config["start_date"],
            "end_date": config["end_date"],
            "frequency": config["frequency"],
            "accounts": {"future": config["future_cash"]},
            "data_bundle_path": str(settings.bundle_path),
            "auto_update_bundle": False,
            "rqdatac_uri": "disabled",
        },
        "mod": {
            "sys_simulation": {
                "enabled": True,
                "matching_type": config["matching_type"],
                "margin_multiplier": config["margin_multiplier"],
                "commission_multiplier": config["futures_commission_multiplier"],
                "slippage_model": config["slippage_model"],
                "slippage": config["slippage"],
                "signal": False,
            },
            "sys_analyser": {
                "enabled": True,
                "record": True,
                "output_file": str(paths.result_pickle),
                "report_save_path": str(paths.report_dir),
                "plot": True,
                "plot_save_file": str(paths.equity_png),
            },
            "sys_progress": {"enabled": True, "show": False},
            "ams": {"enabled": False},
        },
        "incremental": {"enabled": False},
    }


def _safe_environment(params_path: Path) -> dict[str, str]:
    environment = {
        name: value
        for name in _INHERITED_ENV_ALLOWLIST
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "GUIYI_BACKTEST_STRATEGY_PARAMS_FILE": str(params_path),
            "PYTHONPATH": str(_QUANT_API_ROOT),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment


def _parent_secrets() -> tuple[str, ...]:
    values: set[str] = set()
    for name, value in os.environ.items():
        upper = name.upper()
        if (
            value
            and len(value) >= 4
            and any(marker in upper for marker in _SENSITIVE_ENV_MARKERS)
        ):
            values.add(value)
    return tuple(sorted(values, key=len, reverse=True))


class _LogRedactor:
    def __init__(self) -> None:
        self._exact_secrets = _parent_secrets()

    def redact(self, text: str) -> str:
        sanitized = text
        for secret in self._exact_secrets:
            sanitized = sanitized.replace(secret, "[REDACTED]")
        sanitized = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", sanitized)
        sanitized = _BEARER.sub(r"\1[REDACTED]", sanitized)
        return _SENSITIVE_ASSIGNMENT.sub(r"\1[REDACTED]", sanitized)


def _open_log(path: Path) -> BinaryIO:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("BACKTEST_RUN_PATHS_INVALID")
        return os.fdopen(descriptor, "ab", buffering=0)
    except Exception:
        os.close(descriptor)
        raise


def _read_json_regular(path: Path) -> object:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ValueError("BACKTEST_RUN_CONFIG_INVALID") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("BACKTEST_RUN_CONFIG_INVALID")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("BACKTEST_RUN_CONFIG_INVALID")
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("BACKTEST_RUN_CONFIG_INVALID") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _drain_stream(source: BinaryIO, target: BinaryIO, redactor: _LogRedactor) -> None:
    try:
        while raw_line := source.readline():
            sanitized = redactor.redact(raw_line.decode("utf-8", errors="replace"))
            target.write(sanitized.encode("utf-8"))
    finally:
        source.close()
        target.close()


def _valid_result(path: Path) -> bool:
    try:
        payload = _read_json_regular(path)
    except ValueError:
        return False
    if not isinstance(payload, Mapping) or set(payload) != {
        "summary",
        "equity",
        "trade_count",
        "artifacts",
    }:
        return False
    summary = payload["summary"]
    equity = payload["equity"]
    artifacts = payload["artifacts"]
    if not (
        isinstance(summary, Mapping)
        and set(summary)
        == {
            "total_returns",
            "annualized_returns",
            "max_drawdown",
            "sharpe",
            "sortino",
            "volatility",
            "total_value",
            "cash",
        }
        and all(isinstance(value, str) for value in summary.values())
        and isinstance(equity, list)
        and isinstance(payload["trade_count"], str)
        and isinstance(artifacts, Mapping)
        and set(artifacts)
        == {
            "report_zip",
            "result_pickle",
            "equity_png",
            "stdout_log",
            "stderr_log",
            "run_json",
        }
        and all(isinstance(value, bool) for value in artifacts.values())
    ):
        return False
    try:
        for value in summary.values():
            if not value or not Decimal(value).is_finite():
                return False
        trade_count = payload["trade_count"]
        if not trade_count.isdecimal() or int(trade_count) < 0:
            return False
        for row in equity:
            if not isinstance(row, Mapping) or set(row) != {
                "date",
                "unit_net_value",
            }:
                return False
            if (
                not isinstance(row["date"], str)
                or date.fromisoformat(row["date"]).isoformat() != row["date"]
            ):
                return False
            value = row["unit_net_value"]
            if (
                not isinstance(value, str)
                or not value
                or not Decimal(value).is_finite()
            ):
                return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    return True


class RunningProcess:
    """Started child process with one synchronous terminal monitor."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        paths: RunPaths,
        timeout_seconds: int,
        drain_threads: tuple[threading.Thread, threading.Thread],
    ) -> None:
        self._process = process
        self._paths = paths
        self._timeout_seconds = timeout_seconds
        self._drain_threads = drain_threads
        self._monitor_lock = threading.Lock()
        self._monitor_result: MonitorResult | None = None

    @property
    def pid(self) -> int:
        return self._process.pid

    def monitor(self) -> MonitorResult:
        with self._monitor_lock:
            if self._monitor_result is not None:
                return self._monitor_result
            timed_out = False
            try:
                exit_code = self._process.wait(timeout=self._timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._process.terminate()
                try:
                    exit_code = self._process.wait(timeout=_TERMINATE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    exit_code = self._process.wait()
            for thread in self._drain_threads:
                thread.join()
            if timed_out:
                result = MonitorResult(
                    exit_code=exit_code,
                    outcome=RunStatus.TIMED_OUT,
                    failure_code=RunFailureCode.RUN_TIMED_OUT,
                )
            elif exit_code != 0:
                result = MonitorResult(
                    exit_code=exit_code,
                    outcome=RunStatus.FAILED,
                    failure_code=RunFailureCode.STRATEGY_EXECUTION_FAILED,
                )
            elif not _valid_result(self._paths.result_json):
                result = MonitorResult(
                    exit_code=exit_code,
                    outcome=RunStatus.FAILED,
                    failure_code=RunFailureCode.RESULT_INCOMPLETE,
                )
            else:
                result = MonitorResult(
                    exit_code=exit_code,
                    outcome=RunStatus.SUCCEEDED,
                    failure_code=None,
                )
            self._monitor_result = result
            return result


class SubprocessRunner:
    """Launch the one fixed runner entry with no inherited project secrets."""

    def __init__(self, settings: BacktestSettings) -> None:
        self.settings = settings

    def probe(self) -> RunnerProbe:
        command = [
            str(self.settings.python_executable),
            str(_RUNNER_ENTRY_PATH),
            "--probe",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(_QUANT_API_ROOT),
                env=_safe_environment(Path("/dev/null")),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=min(self.settings.timeout_seconds, 15),
                shell=False,
                check=False,
            )
            payload = json.loads(completed.stdout.decode("utf-8"))
            if (
                completed.returncode != 0
                or not isinstance(payload, Mapping)
                or any(
                    not isinstance(payload.get(key), str) or not payload[key]
                    for key in ("rqalpha_version", "rqsdk_version", "python_version")
                )
            ):
                raise ValueError
            return RunnerProbe(
                available=True,
                rqalpha_version=payload["rqalpha_version"],
                rqsdk_version=payload["rqsdk_version"],
                python_version=payload["python_version"],
            )
        except (
            OSError,
            subprocess.TimeoutExpired,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return RunnerProbe(
                available=False,
                rqalpha_version="unknown",
                rqsdk_version="unknown",
                python_version="unknown",
            )

    def effective_config(
        self,
        request: ValidatedBacktestRequest,
        paths: RunPaths,
    ) -> dict[str, Any]:
        return build_rqalpha_config(self.settings, request, paths)

    def start(
        self,
        request: ValidatedBacktestRequest,
        paths: RunPaths,
    ) -> RunningProcess:
        expected_config = build_rqalpha_config(self.settings, request, paths)
        try:
            record = _read_json_regular(paths.run_json)
            params = _read_json_regular(paths.strategy_params_json)
        except ValueError as exc:
            raise ValueError("BACKTEST_RUN_CONFIG_INVALID") from exc
        if (
            not isinstance(record, Mapping)
            or record.get("effective_config") != expected_config
        ):
            raise ValueError("BACKTEST_RUN_CONFIG_INVALID")
        if not isinstance(params, Mapping) or dict(params) != request.parameters:
            raise ValueError("BACKTEST_RUN_CONFIG_INVALID")

        command = [
            str(self.settings.python_executable),
            str(_RUNNER_ENTRY_PATH),
            "--run-root",
            str(paths.root),
        ]
        stdout_target = _open_log(paths.stdout_log)
        try:
            stderr_target = _open_log(paths.stderr_log)
        except Exception:
            stdout_target.close()
            raise
        try:
            process = subprocess.Popen(
                command,
                cwd=str(_QUANT_API_ROOT),
                env=_safe_environment(paths.strategy_params_json),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            stdout_target.close()
            stderr_target.close()
            raise BacktestError(BacktestHttpErrorCode.RUNNER_UNAVAILABLE) from exc
        if process.stdout is None or process.stderr is None:
            process.kill()
            stdout_target.close()
            stderr_target.close()
            raise BacktestError(BacktestHttpErrorCode.RUNNER_UNAVAILABLE)
        redactor = _LogRedactor()
        threads = (
            threading.Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_target, redactor),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_target, redactor),
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()
        return RunningProcess(process, paths, self.settings.timeout_seconds, threads)


__all__ = [
    "MonitorResult",
    "RunnerProbe",
    "RunningProcess",
    "SubprocessRunner",
    "build_rqalpha_config",
]
