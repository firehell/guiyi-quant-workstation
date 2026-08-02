"""Narrow argv adapter for the existing controlled task-worktree entrypoint."""

from __future__ import annotations

import subprocess
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .contracts import ExecutionPlanV1
from .digests import semantic_digest
from .errors import LeanMatrixError


ENTRYPOINT = "scripts/engineering/task-worktree.sh"
Runner = Callable[..., subprocess.CompletedProcess[str]]
LANE_ONE_PREFIXES = ("experiments/", "tests/", "docs/research/")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    command_digest: str
    exit_code: int
    error_type: str | None


@dataclass(frozen=True, slots=True)
class ExecutionInvocation:
    argv: tuple[str, ...]
    cwd: Path

    @property
    def digest(self) -> str:
        return semantic_digest({"argv": list(self.argv), "cwd": str(self.cwd)})


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


def plan_lane(plan: ExecutionPlanV1) -> int:
    """Validate frozen dispatch/Gate consistency and infer the least privileged Lane."""
    dispatch = (plan.dispatch.model, plan.dispatch.reasoning_effort)
    if dispatch == ("Sol", "high"):
        if not plan.external_gates:
            raise LeanMatrixError(
                "lane_three_plan_invalid",
                "a Sol/high Lane 3 plan cannot omit its required external Gate",
            )
        return 3
    if dispatch != ("Terra", "medium"):
        raise LeanMatrixError("invalid_plan_dispatch", "execution plan has no supported frozen Lane dispatch")
    if plan.external_gates:
        raise LeanMatrixError(
            "invalid_plan_dispatch",
            "a Terra local execution plan cannot contain external Gates",
        )

    def lane_one_path(path: str) -> bool:
        literal = path.removesuffix("**")
        return any(literal.startswith(prefix) for prefix in LANE_ONE_PREFIXES)

    return 1 if all(lane_one_path(path) for path in plan.scope.allowed_paths) else 2


def execution_lane(plan: ExecutionPlanV1) -> int:
    lane = plan_lane(plan)
    if lane == 3:
        raise LeanMatrixError("lane_three_apply_forbidden", "Lane 3 cannot use local apply")
    return lane


def command_for_action(
    plan: ExecutionPlanV1,
    action: str,
    *,
    apply: bool = False,
) -> tuple[str, ...]:
    """Return one fixed argv command; execution and cwd selection remain separate."""
    kind, slug = _identity(plan)
    common = ("--lane", str(execution_lane(plan)), "--issue", str(plan.task.issue_number))
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


def invocation_for_action(
    plan: ExecutionPlanV1,
    action: str,
    repo_root: Path,
) -> ExecutionInvocation:
    """Bind execution to the surviving clean controller checkout and exact target cwd."""
    controller = repo_root.resolve()
    task = Path(plan.task.worktree).resolve()
    if controller == task:
        raise LeanMatrixError(
            "untrusted_controller_checkout",
            "local apply must run from the surviving develop controller checkout",
        )
    entrypoint = controller / ENTRYPOINT
    try:
        metadata = entrypoint.lstat()
    except OSError as exc:
        raise LeanMatrixError("controller_entrypoint_unavailable", "trusted task workflow is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise LeanMatrixError(
            "controller_entrypoint_untrusted",
            "trusted task workflow must be a regular non-symlink file",
        )
    logical = list(command_for_action(plan, action, apply=True))
    logical[1] = str(entrypoint)
    cwd = task if action == "local-integrate-to-draft-pr" else controller
    return ExecutionInvocation(tuple(logical), cwd)


def execution_digest(plan: ExecutionPlanV1, action: str, repo_root: Path) -> str:
    return invocation_for_action(plan, action, repo_root).digest


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
    invocation = invocation_for_action(plan, action, repo_root)
    try:
        result = runner(
            list(invocation.argv),
            cwd=invocation.cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except OSError:
        return ExecutionResult(invocation.digest, -1, "transition_process_unavailable")
    error_type = None if result.returncode == 0 else "transition_command_failed"
    return ExecutionResult(invocation.digest, result.returncode, error_type)
