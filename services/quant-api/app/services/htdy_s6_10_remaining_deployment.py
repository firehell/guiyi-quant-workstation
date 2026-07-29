"""Ordered, fail-closed state machine for schema-v7 deployment."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


class RemainingDeploymentError(RuntimeError):
    """Deployment context or state-machine violation."""


@dataclass(frozen=True)
class DeploymentStep:
    name: str


_DEPLOYMENT_STEPS = (
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
    "activate_s610",
    "start_s610_services",
    "verify_post_activation",
)


def validate_source_context(
    *,
    actual_source_root: Path,
    orchestrator_source_root: Path,
) -> None:
    if actual_source_root.resolve(strict=False) != (
        orchestrator_source_root.resolve(strict=False)
    ):
        raise RemainingDeploymentError("source_root_mismatch")


def deployment_step_names() -> tuple[str, ...]:
    return _DEPLOYMENT_STEPS


def execute_deployment_steps(
    *,
    steps: Iterable[DeploymentStep],
    rollback_steps: Iterable[DeploymentStep],
    runner: Callable[[DeploymentStep], None],
    failure_recorder: Callable[[BaseException], None],
) -> bool:
    try:
        for step in steps:
            runner(step)
    except BaseException as error:
        setattr(error, "deployment_step", step.name)
        rollback_failures: list[dict[str, str]] = []
        for rollback_step in rollback_steps:
            try:
                runner(rollback_step)
            except BaseException as rollback_error:
                failure = {
                    "step": rollback_step.name,
                    "error_type": type(rollback_error).__name__,
                }
                diagnostic_path = str(
                    getattr(
                        rollback_error,
                        "restore_diagnostic_path",
                        "",
                    )
                    or ""
                )
                if diagnostic_path:
                    failure["restore_diagnostic_path"] = diagnostic_path
                rollback_failures.append(failure)
                continue
        setattr(error, "rollback_failures", rollback_failures)
        failure_recorder(error)
        return False
    return True
