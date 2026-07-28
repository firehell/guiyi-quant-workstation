from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


def _load_orchestrator_module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "jm_htdy_s6_10_remaining_deploy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "jm_htdy_s6_10_remaining_deploy_test_module",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_orchestrator_launchd_probe_requires_running_state_and_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_orchestrator_module()
    monkeypatch.setattr(
        module,
        "_launchd_snapshot",
        lambda _label: subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 12345\n",
            stderr="",
        ),
    )

    assert module._launchd_running("com.guiyi.test") is True

    monkeypatch.setattr(
        module,
        "_launchd_snapshot",
        lambda _label: subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="state = running\npid = 0\n",
            stderr="",
        ),
    )
    assert module._launchd_running("com.guiyi.test") is False


def test_after_market_install_retries_transient_launchctl_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_orchestrator_module()
    attempts: list[list[str]] = []

    def run(command, **_kwargs):
        attempts.append(command)
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(5, command)

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module._install_after_market_with_retry(
        tmp_path,
        environment={},
    )

    assert len(attempts) == 2
    assert attempts[-1][-1] == "--confirm-load"


def test_orchestrator_rejects_execution_from_a_different_source_checkout(
    tmp_path: Path,
) -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        RemainingDeploymentError,
        validate_source_context,
    )

    with pytest.raises(RemainingDeploymentError, match="source_root_mismatch"):
        validate_source_context(
            actual_source_root=tmp_path / "wrong",
            orchestrator_source_root=tmp_path / "bound",
        )


def test_orchestrator_has_one_ordered_activation_sequence() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        deployment_step_names,
    )

    assert deployment_step_names() == (
        "stop_s610_services",
        "pause_after_market",
        "switch_runtime",
        "restart_core_runtime",
        "write_deployment_receipt",
        "rebind_s607",
        "restore_after_market",
        "verify_activation_ready",
        "configure_s610",
        "create_activation_receipt",
        "start_s610_services",
        "verify_post_activation",
    )


def test_orchestrator_failure_runs_complete_fail_closed_sequence() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        DeploymentStep,
        execute_deployment_steps,
    )

    observed: list[str] = []
    failure: list[str] = []

    def run(step: DeploymentStep) -> None:
        observed.append(step.name)
        if step.name == "switch_runtime":
            raise RuntimeError("boom")

    execute_deployment_steps(
        steps=(
            DeploymentStep("stop_s610_services"),
            DeploymentStep("pause_after_market"),
            DeploymentStep("switch_runtime"),
        ),
        rollback_steps=(
            DeploymentStep("rollback_stop_s610"),
            DeploymentStep("rollback_disable_s610"),
            DeploymentStep("rollback_runtime"),
            DeploymentStep("rollback_restore_after_market"),
        ),
        runner=run,
        failure_recorder=lambda error: failure.append(type(error).__name__),
    )

    assert observed == [
        "stop_s610_services",
        "pause_after_market",
        "switch_runtime",
        "rollback_stop_s610",
        "rollback_disable_s610",
        "rollback_runtime",
        "rollback_restore_after_market",
    ]
    assert failure == ["RuntimeError"]


def test_orchestrator_reports_rollback_failures_instead_of_suppressing() -> None:
    from app.services.htdy_s6_10_remaining_deployment import (
        DeploymentStep,
        execute_deployment_steps,
    )

    captured: list[BaseException] = []

    def run(step: DeploymentStep) -> None:
        if step.name in {"switch_runtime", "rollback_runtime"}:
            raise RuntimeError(step.name)

    assert execute_deployment_steps(
        steps=(DeploymentStep("switch_runtime"),),
        rollback_steps=(
            DeploymentStep("rollback_disable_s610"),
            DeploymentStep("rollback_runtime"),
        ),
        runner=run,
        failure_recorder=captured.append,
    ) is False

    assert captured[0].deployment_step == "switch_runtime"
    assert captured[0].rollback_failures == [
        {
            "step": "rollback_runtime",
            "error_type": "RuntimeError",
        }
    ]
