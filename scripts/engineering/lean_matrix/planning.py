"""Pure construction of a version-one Execution Plan."""

from __future__ import annotations

from .charter import WORKTREE_ROOT
from .contracts import ExecutionPlanV1, TaskCharterV1
from .digests import charter_digest
from .routing import BASE_ROLES, DOMAIN_SPECIALISTS, LANE_DISPATCH


REQUIRED_CHECKS = (
    "independent-review",
    "exact-head-ci",
    "diff-check",
    "secret-scan",
)
TRANSITIONS = (
    "task-create",
    "implementation-complete",
    "draft-pr",
    "review-complete",
    "develop-merge",
    "cleanup",
)


def build_execution_plan(
    charter: TaskCharterV1, *, base_ref: str, base_sha: str,
) -> ExecutionPlanV1:
    """Build a deterministic plan from validated inputs without observing external state."""
    model, reasoning_effort, _mode, _sessions = LANE_DISPATCH[charter.lane]
    specialists = tuple(DOMAIN_SPECIALISTS[domain] for domain in charter.domains)
    independence = ["implementer and independent-quality-reviewer use separate contexts"]
    if {"quant-research", "backtest-audit"}.issubset(charter.domains):
        independence.append("quant-research-specialist and backtest-audit-specialist use separate contexts")
    identity = f"{charter.task_id}-{charter.slug}"
    return ExecutionPlanV1.from_mapping({
        "schema_version": 1,
        "status": "ok",
        "charter_digest": charter_digest(charter),
        "task": {
            "issue_number": charter.issue_number,
            "task_id": charter.task_id,
            "branch": f"{charter.kind}/{identity}",
            "worktree": f"{WORKTREE_ROOT}/{identity}",
        },
        "base": {"ref": base_ref, "expected_sha": base_sha},
        "dispatch": {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "roles": list(BASE_ROLES),
            "specialists": list(specialists),
            "independence_requirements": independence,
        },
        "scope": {
            "allowed_paths": list(charter.allowed_paths),
            "forbidden_paths": list(charter.forbidden_paths),
        },
        "validation": {
            "test_profile": "all-safe",
            "required_checks": list(REQUIRED_CHECKS),
        },
        "transitions": list(TRANSITIONS),
        "external_gates": list(charter.external_gates),
    })
