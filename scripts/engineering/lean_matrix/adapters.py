"""Narrow argv adapter for the existing controlled task-worktree entrypoint."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExecutionPlanV1
from .digests import semantic_digest
from .errors import LeanMatrixError


ENTRYPOINT = "scripts/engineering/task-worktree.sh"
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    command_digest: str
    exit_code: int
    error_type: str | None


def _identity(plan: ExecutionPlanV1) -> tuple[str, str]:
    kind, separator, identity = plan.task.branch.partition("/")
    prefix = f"{plan.task.task_id}-"
    if not separator or not identity.startswith(prefix) or len(identity) == len(prefix):
        raise LeanMatrixError("task_identity_mismatch", "plan branch does not match task ID and slug")
    return kind, identity.removeprefix(prefix)


def _commit_message(plan: ExecutionPlanV1) -> str:
    kind, _ = _identity(plan)
    commit_kind = {
        "feature": "feat",
        "fix": "fix",
        "docs": "docs",
        "research": "docs",
        "refactor": "refactor",
    }[kind]
    return f"{commit_kind}(workstation): complete {plan.task.task_id}"


def command_for_action(
    plan: ExecutionPlanV1,
    action: str,
    *,
    apply: bool = False,
) -> tuple[str, ...]:
    """Return one fixed argv command; execution and cwd selection remain separate."""
    kind, slug = _identity(plan)
    common = ("--lane", "2", "--issue", str(plan.task.issue_number))
    if action == "task-create":
        command = (
            "bash", ENTRYPOINT, "create", "--kind", kind, "--task-id", plan.task.task_id,
            "--slug", slug, *common, "--json",
        )
    elif action == "local-integrate-to-draft-pr":
        command = (
            "bash", ENTRYPOINT, "integrate", *common,
            "--test-profile", plan.validation.test_profile,
            "--commit-message", _commit_message(plan), "--json",
        )
    elif action == "local-cleanup-after-merge-observed":
        command = (
            "bash", ENTRYPOINT, "cleanup", "--task-path", plan.task.worktree,
            *common, "--json",
        )
    else:
        raise LeanMatrixError("unsupported_transition", f"unsupported local transition: {action}")
    return (*command, "--apply") if apply else command


def execute_action(
    plan: ExecutionPlanV1,
    action: str,
    repo_root: Path,
    *,
    runner: Runner = subprocess.run,
) -> ExecutionResult:
    """Execute exactly one existing entrypoint without persisting raw process output."""
    if (
        action == "local-cleanup-after-merge-observed"
        and repo_root.resolve() == Path(plan.task.worktree).resolve()
    ):
        raise LeanMatrixError(
            "cleanup_invocation_from_target",
            "cleanup must run from a surviving repository checkout, not the target worktree",
        )
    command = command_for_action(plan, action, apply=True)
    cwd = Path(plan.task.worktree) if action == "local-integrate-to-draft-pr" else repo_root.resolve()
    command_digest = semantic_digest(list(command))
    try:
        result = runner(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError:
        return ExecutionResult(command_digest, -1, "transition_process_unavailable")
    error_type = None if result.returncode == 0 else "transition_command_failed"
    return ExecutionResult(command_digest, result.returncode, error_type)
