"""Derive exactly one safe local transition from an observed execution plan."""

from __future__ import annotations

from collections.abc import Collection

from .adapters import command_for_action
from .contracts import ExecutionPlanV1, TransitionProposalV1
from .digests import semantic_digest
from .errors import LeanMatrixError
from .observing import ObservedExecution


def _transition_id(plan: ExecutionPlanV1, action: str, state_digest: str) -> str:
    digest = semantic_digest({
        "plan": semantic_digest(plan.to_dict()),
        "action": action,
        "from_state_digest": state_digest,
    })
    return f"tr-{digest.removeprefix('sha256:')}"


def _proposal(
    plan: ExecutionPlanV1,
    observed: ObservedExecution,
    action: str,
    *,
    apply_action: bool,
    human_gate: str | None = None,
) -> TransitionProposalV1:
    commands = [list(command_for_action(plan, action))] if apply_action else []
    return TransitionProposalV1.from_mapping({
        "transition_id": _transition_id(plan, action, observed.state.state_digest),
        "from_state_digest": observed.state.state_digest,
        "action": action,
        "commands": commands,
        "side_effect_scope": "task-worktree" if apply_action else "none",
        "requires_apply": apply_action,
        "human_gate": human_gate,
    })


def _validate_scope(plan: ExecutionPlanV1, changed_paths: tuple[str, ...]) -> None:
    exact = frozenset(entry for entry in plan.scope.allowed_paths if not entry.endswith("/**"))
    recursive = tuple(entry.removesuffix("**") for entry in plan.scope.allowed_paths if entry.endswith("/**"))
    unsupported = [entry for entry in plan.scope.allowed_paths if "*" in entry and not entry.endswith("/**")]
    if unsupported:
        raise LeanMatrixError("unsupported_allowlist_pattern", f"unsupported allowlist pattern: {unsupported[0]}")
    for path in changed_paths:
        if path not in exact and not any(path.startswith(prefix) for prefix in recursive):
            raise LeanMatrixError(
                "changed_path_out_of_scope",
                f"changed path is outside the frozen plan allowlist: {path}",
            )


def propose_next_transition(
    plan: ExecutionPlanV1,
    observed: ObservedExecution,
    *,
    attempted_actions: Collection[str] = (),
    successful_actions: Collection[str] = (),
) -> TransitionProposalV1:
    """Return one deterministic proposal or fail closed on inconsistent local facts."""
    if plan.external_gates:
        return _proposal(
            plan,
            observed,
            "await-human-gate",
            apply_action=False,
            human_gate=plan.external_gates[0],
        )

    if observed.phase == "closed":
        return _proposal(plan, observed, "closed", apply_action=False)

    if observed.phase in {"orphaned-task-state", "detached-task-state"}:
        raise LeanMatrixError(
            "task_state_ambiguous",
            "task branch exists without a matching managed worktree or verified develop ancestry",
        )

    if observed.phase == "merged-develop-observed":
        action = "local-cleanup-after-merge-observed"
        if not observed.state.cleanup_safe:
            raise LeanMatrixError("cleanup_not_safe", "cleanup requires clean dual-develop ancestry")
    elif observed.phase == "planned":
        if not observed.base_matches_plan:
            raise LeanMatrixError("base_sha_drift", "origin/develop no longer matches the planned exact SHA")
        action = "task-create"
    elif observed.phase == "implementation-ready":
        if "local-integrate-to-draft-pr" in successful_actions:
            return _proposal(
                plan,
                observed,
                "await-develop-merge",
                apply_action=False,
                human_gate="AI-TEAM-007",
            )
        if not observed.base_matches_plan:
            raise LeanMatrixError("base_sha_drift", "origin/develop no longer matches the planned exact SHA")
        _validate_scope(plan, observed.state.changed_paths)
        if not observed.state.changed_paths:
            return _proposal(plan, observed, "await-implementation", apply_action=False)
        if not observed.state.dirty:
            raise LeanMatrixError(
                "integration_state_uncertain",
                "clean committed task changes without a receipt require external inspection before retry",
            )
        action = "local-integrate-to-draft-pr"
    else:
        raise LeanMatrixError("unsupported_observed_phase", f"unsupported observed phase: {observed.phase}")

    if action in attempted_actions:
        raise LeanMatrixError(
            "transition_already_attempted",
            f"transition action already has a receipt and cannot be replayed: {action}",
        )
    return _proposal(plan, observed, action, apply_action=True)
