from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

import pytest

from app.backtest.artifact_store import RunPaths
from app.backtest.config import BacktestSettings
from app.backtest.contracts import RunStatus
from app.backtest.errors import RunFailureCode
from app.backtest.registry import RegisteredStrategy, ValidatedBacktestRequest
from app.backtest import runner as runner_module
from app.backtest.runner import SubprocessRunner, build_rqalpha_config


_FAKE_ENTRY = Path(__file__).parent / "fixtures" / "fake_runner.py"
_SAFE_ENV_NAMES = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "GUIYI_BACKTEST_STRATEGY_PARAMS_FILE",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
}


@pytest.fixture
def settings(tmp_path: Path) -> BacktestSettings:
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


@pytest.fixture
def run_paths(settings: BacktestSettings) -> RunPaths:
    root = settings.runs_root / "run-001"
    root.mkdir()
    (root / "report").mkdir()
    for name in ("strategy.py", "stdout.log", "stderr.log"):
        (root / name).write_text("", encoding="utf-8")
    return RunPaths(
        root=root,
        run_json=root / "run.json",
        result_json=root / "result.json",
        strategy_file=root / "strategy.py",
        strategy_params_json=root / "strategy_params.json",
        result_pickle=root / "result.pkl",
        equity_png=root / "equity.png",
        report_dir=root / "report",
        stdout_log=root / "stdout.log",
        stderr_log=root / "stderr.log",
    )


@pytest.fixture
def validated_request(tmp_path: Path) -> ValidatedBacktestRequest:
    strategy_file = tmp_path / "registered.py"
    strategy_file.write_text("def init(context): pass\n", encoding="utf-8")
    strategy = RegisteredStrategy(
        id="example",
        name="Example",
        description="fixture",
        enabled=True,
        entry_file="registered.py",
        strategy_file=strategy_file,
        supported_frequencies=("1d", "1m"),
        defaults={},
        parameters=(),
    )
    return ValidatedBacktestRequest(
        strategy=strategy,
        strategy_file=strategy_file,
        parameters={"quantity": 1},
        config={
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "frequency": "1d",
            "future_cash": "1000000",
            "matching_type": "current_bar",
            "margin_multiplier": "1",
            "futures_commission_multiplier": "1",
            "slippage_model": "PriceRatioSlippage",
            "slippage": "0",
        },
    )


def _prepare_run(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    *,
    mode: str,
) -> None:
    config = build_rqalpha_config(settings, validated_request, run_paths)
    validated_request.parameters["fake_mode"] = mode
    run_paths.run_json.write_text(
        json.dumps({"effective_config": config}), encoding="utf-8"
    )
    run_paths.strategy_params_json.write_text(
        json.dumps(validated_request.parameters), encoding="utf-8"
    )


def _fake_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "_RUNNER_ENTRY_PATH", _FAKE_ENTRY)


def test_build_rqalpha_config_forces_complete_safe_configuration(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
) -> None:
    config = build_rqalpha_config(settings, validated_request, run_paths)

    assert config == {
        "base": {
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "frequency": "1d",
            "accounts": {"FUTURE": "1000000"},
            "margin_multiplier": "1",
            "data_bundle_path": str(settings.bundle_path),
            "auto_update_bundle": False,
            "rqdatac_uri": "disabled",
        },
        "mod": {
            "sys_simulation": {
                "enabled": True,
                "matching_type": "current_bar",
                "slippage_model": "PriceRatioSlippage",
                "slippage": "0",
                "signal": False,
            },
            "sys_transaction_cost": {
                "enabled": True,
                "futures_commission_multiplier": "1",
            },
            "sys_analyser": {
                "enabled": True,
                "record": True,
                "output_file": str(run_paths.result_pickle),
                "report_save_path": str(run_paths.report_dir),
                "plot": True,
                "plot_save_file": str(run_paths.equity_png),
            },
            "sys_progress": {"enabled": True, "show": False},
            "ams": {"enabled": False},
            "incremental": {"enabled": False},
        },
    }


def test_probe_returns_external_runner_versions(
    settings: BacktestSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)

    probe = SubprocessRunner(settings).probe()

    assert probe.available is True
    assert probe.rqalpha_version == "fake-rqalpha-1"
    assert probe.rqsdk_version == "fake-rqsdk-1"
    assert probe.python_version == "fake-python-1"


def test_start_uses_fixed_argv_cwd_shell_false_and_environment_allowlist(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    _prepare_run(settings, run_paths, validated_request, mode="success")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db-secret")
    monkeypatch.setenv("REDIS_URL", "redis://redis-secret")
    monkeypatch.setenv("PUSHPLUS_TOKEN", "pushplus-secret")
    monkeypatch.setenv("RQDATA_USERNAME", "rqdata-user")
    real_popen = subprocess.Popen
    observed: dict[str, Any] = {}

    def observe_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", observe_popen)

    handle = SubprocessRunner(settings).start(validated_request, run_paths)
    result = handle.monitor()

    assert result.outcome is RunStatus.SUCCEEDED
    assert observed["args"] == (
        [
            str(settings.python_executable),
            str(_FAKE_ENTRY),
            "--run-root",
            str(run_paths.root),
        ],
    )
    kwargs = observed["kwargs"]
    assert kwargs["cwd"] == str(Path(runner_module.__file__).resolve().parents[2])
    assert kwargs["shell"] is False
    assert set(kwargs["env"]) <= _SAFE_ENV_NAMES
    assert kwargs["env"]["GUIYI_BACKTEST_STRATEGY_PARAMS_FILE"] == str(
        run_paths.strategy_params_json
    )
    assert not {
        "DATABASE_URL",
        "REDIS_URL",
        "PUSHPLUS_TOKEN",
        "RQDATA_USERNAME",
    } & set(kwargs["env"])


@pytest.mark.parametrize(
    ("mode", "outcome", "exit_code", "failure_code"),
    [
        ("success", RunStatus.SUCCEEDED, 0, None),
        (
            "failure",
            RunStatus.FAILED,
            7,
            RunFailureCode.STRATEGY_EXECUTION_FAILED,
        ),
        ("incomplete", RunStatus.FAILED, 0, RunFailureCode.RESULT_INCOMPLETE),
        ("malformed", RunStatus.FAILED, 0, RunFailureCode.RESULT_INCOMPLETE),
    ],
)
def test_monitor_classifies_terminal_outcome(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    outcome: RunStatus,
    exit_code: int,
    failure_code: RunFailureCode | None,
) -> None:
    _fake_runner(monkeypatch)
    _prepare_run(settings, run_paths, validated_request, mode=mode)

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    assert result.outcome is outcome
    assert result.exit_code == exit_code
    assert result.failure_code is failure_code


def test_monitor_terminates_then_kills_a_timed_out_runner(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    monkeypatch.setattr(runner_module, "_TERMINATE_GRACE_SECONDS", 0.05)
    settings = BacktestSettings(
        python_executable=settings.python_executable,
        bundle_path=settings.bundle_path,
        runs_root=settings.runs_root,
        timeout_seconds=1,
        cors_origins=settings.cors_origins,
    )
    _prepare_run(settings, run_paths, validated_request, mode="ignore_terminate")
    started = time.monotonic()

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    assert time.monotonic() - started < 3
    assert result.outcome is RunStatus.TIMED_OUT
    assert result.failure_code is RunFailureCode.RUN_TIMED_OUT
    assert result.exit_code is not None


def test_timeout_terminates_then_kills_the_owned_process_group_and_drains_pipes(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    monkeypatch.setattr(runner_module, "_TERMINATE_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(runner_module, "_PIPE_DRAIN_SECONDS", 0.2, raising=False)
    settings = BacktestSettings(
        python_executable=settings.python_executable,
        bundle_path=settings.bundle_path,
        runs_root=settings.runs_root,
        timeout_seconds=1,
        cors_origins=settings.cors_origins,
    )
    _prepare_run(settings, run_paths, validated_request, mode="descendant_timeout")
    signals: list[tuple[int, int]] = []
    real_killpg = os.killpg

    def observe_killpg(process_group: int, sent_signal: int) -> None:
        signals.append((process_group, sent_signal))
        real_killpg(process_group, sent_signal)

    monkeypatch.setattr(runner_module.os, "killpg", observe_killpg)
    started = time.monotonic()

    handle = SubprocessRunner(settings).start(validated_request, run_paths)
    result = handle.monitor()

    assert time.monotonic() - started < 3
    assert result.outcome is RunStatus.TIMED_OUT
    assert signals == [(handle.pid, signal.SIGTERM), (handle.pid, signal.SIGKILL)]
    with pytest.raises(ProcessLookupError):
        os.killpg(handle.pid, 0)


def test_timeout_uses_group_identity_captured_before_a_late_leader_lookup(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    monkeypatch.setattr(runner_module, "_TERMINATE_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(runner_module, "_PIPE_DRAIN_SECONDS", 0.2, raising=False)
    settings = BacktestSettings(
        python_executable=settings.python_executable,
        bundle_path=settings.bundle_path,
        runs_root=settings.runs_root,
        timeout_seconds=1,
        cors_origins=settings.cors_origins,
    )
    _prepare_run(settings, run_paths, validated_request, mode="descendant_timeout")
    start_returned = False
    real_getpgid = os.getpgid

    def leader_identity(process_id: int) -> int:
        if start_returned:
            raise ProcessLookupError
        return real_getpgid(process_id)

    monkeypatch.setattr(runner_module.os, "getpgid", leader_identity)
    started = time.monotonic()

    handle = SubprocessRunner(settings).start(validated_request, run_paths)
    start_returned = True
    result = handle.monitor()

    assert time.monotonic() - started < 3
    assert result.outcome is RunStatus.TIMED_OUT
    assert all(not thread.is_alive() for thread in handle._drain_threads)
    with pytest.raises(ProcessLookupError):
        os.killpg(handle.pid, 0)


def test_streamed_logs_are_redacted_and_exclude_parent_secrets(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://db-user:db-secret@host/db")
    monkeypatch.setenv("REDIS_URL", "redis://parent-redis-secret")
    monkeypatch.setenv("PUSHPLUS_TOKEN", "parent-pushplus-secret")
    monkeypatch.setenv("RQDATA_USERNAME", "parent-rqdata-user")
    _prepare_run(settings, run_paths, validated_request, mode="redaction")

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    assert result.outcome is RunStatus.SUCCEEDED
    combined = run_paths.stdout_log.read_text("utf-8") + run_paths.stderr_log.read_text(
        "utf-8"
    )
    assert "stdout-secret" not in combined
    assert "stdout-password" not in combined
    assert "redis-password" not in combined
    assert "child-json-secret" not in combined
    assert "db-secret" not in combined
    assert "parent-redis-secret" not in combined
    assert "parent-pushplus-secret" not in combined
    assert "parent-rqdata-user" not in combined
    assert "[REDACTED]" in combined
    assert '"SENSITIVE_ENV_PRESENT": false' in combined


def test_chunked_redaction_handles_escaped_quotes_boundaries_and_long_lines(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    monkeypatch.setattr(runner_module, "_LOG_CHUNK_BYTES", 7, raising=False)
    _prepare_run(settings, run_paths, validated_request, mode="redaction_chunks")

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    assert result.outcome is RunStatus.SUCCEEDED
    stdout = run_paths.stdout_log.read_text("utf-8")
    stderr = run_paths.stderr_log.read_text("utf-8")
    assert "def-sensitive-suffix" not in stdout
    assert "x" * 128 not in stderr
    assert "prefix" in stdout and "tail" in stdout
    assert "[REDACTED]" in stdout
    assert "[REDACTED]" in stderr
    assert len(stderr) < 256


def test_exact_maximum_length_secret_is_redacted_before_emit_boundary(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    secret = "q" * 4096
    monkeypatch.setenv("API_TOKEN", secret)
    monkeypatch.setattr(runner_module, "_LOG_CHUNK_BYTES", 4097, raising=False)
    _prepare_run(
        settings, run_paths, validated_request, mode="redaction_exact_boundary"
    )

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    stdout = run_paths.stdout_log.read_text("utf-8")
    assert result.outcome is RunStatus.SUCCEEDED
    assert secret not in stdout
    assert stdout == "[REDACTED]!"


def test_start_rejects_run_record_without_exact_effective_config(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
) -> None:
    run_paths.run_json.write_text(
        json.dumps({"effective_config": {"base": {}}}), encoding="utf-8"
    )
    run_paths.strategy_params_json.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="^BACKTEST_RUN_CONFIG_INVALID$"):
        SubprocessRunner(settings).start(validated_request, run_paths)


def test_start_rejects_replaced_fixed_run_path(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
) -> None:
    unsafe = RunPaths(
        root=run_paths.root,
        run_json=run_paths.run_json,
        result_json=run_paths.result_json,
        strategy_file=run_paths.strategy_file,
        strategy_params_json=run_paths.root / "attacker-params.json",
        result_pickle=run_paths.result_pickle,
        equity_png=run_paths.equity_png,
        report_dir=run_paths.report_dir,
        stdout_log=run_paths.stdout_log,
        stderr_log=run_paths.stderr_log,
    )

    with pytest.raises(ValueError, match="^BACKTEST_RUN_PATHS_INVALID$"):
        SubprocessRunner(settings).start(validated_request, unsafe)


def test_start_rejects_symlinked_config_or_params_file(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    tmp_path: Path,
) -> None:
    config = build_rqalpha_config(settings, validated_request, run_paths)
    run_paths.run_json.write_text(
        json.dumps({"effective_config": config}), encoding="utf-8"
    )
    outside = tmp_path / "outside-params.json"
    outside.write_text(json.dumps(validated_request.parameters), encoding="utf-8")
    run_paths.strategy_params_json.symlink_to(outside)

    with pytest.raises(ValueError, match="^BACKTEST_RUN_CONFIG_INVALID$"):
        SubprocessRunner(settings).start(validated_request, run_paths)


def test_safe_environment_does_not_inherit_arbitrary_names(
    settings: BacktestSettings,
    run_paths: RunPaths,
    validated_request: ValidatedBacktestRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_runner(monkeypatch)
    _prepare_run(settings, run_paths, validated_request, mode="success")
    monkeypatch.setenv("GUIYI_UNRELATED_VALUE", "must-not-cross")
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    captured: dict[str, str] = {}
    real_popen = subprocess.Popen

    def observe_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        captured.update(kwargs["env"])
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", observe_popen)

    result = SubprocessRunner(settings).start(validated_request, run_paths).monitor()

    assert result.outcome is RunStatus.SUCCEEDED
    assert "GUIYI_UNRELATED_VALUE" not in captured
    assert "PYTHONWARNINGS" not in captured
    assert captured["PYTHONUNBUFFERED"] == "1"
    assert os.path.isabs(captured["PYTHONPATH"])
