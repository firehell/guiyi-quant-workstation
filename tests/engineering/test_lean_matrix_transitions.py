"""Policy tests for choosing exactly one local Lean Matrix transition."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"


def _contracts():
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import ExecutionPlanV1, ObservedStateV1
        from lean_matrix.observing import ObservedExecution
    finally:
        sys.path.pop(0)
    return ExecutionPlanV1, ObservedStateV1, ObservedExecution


def _plan(*, external_gates: list[str] | None = None):
    ExecutionPlanV1, _, _ = _contracts()
    gates = external_gates or []
    return ExecutionPlanV1.from_mapping({
        "schema_version": 1,
        "status": "ok",
        "charter_digest": "sha256:" + "1" * 64,
        "task": {
            "issue_number": 109,
            "task_id": "AI-TEAM-005",
            "branch": "feature/AI-TEAM-005-local-orchestrator",
            "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-005-local-orchestrator",
        },
        "base": {"ref": "origin/develop", "expected_sha": "a" * 40},
        "dispatch": {
            "model": "Sol" if gates else "Terra",
            "reasoning_effort": "high" if gates else "medium",
            "roles": ["ai-project-lead"],
            "specialists": [],
            "independence_requirements": ["independent review"],
        },
        "scope": {
            "allowed_paths": [
                "tests/example.py",
                "docs/research/note.md",
            ],
            "forbidden_paths": ["Runtime"],
        },
        "validation": {"test_profile": "engineering", "required_checks": ["diff-check"]},
        "transitions": ["task-create", "draft-pr", "cleanup"],
        "external_gates": gates,
    })


def _observed(
    phase: str,
    *,
    base_sha: str = "a" * 40,
    changed_paths: tuple[str, ...] = (),
    dirty: bool = False,
    cleanup_safe: bool = False,
):
    _, ObservedStateV1, ObservedExecution = _contracts()
    task_exists = phase not in {"planned", "closed"}
    state = ObservedStateV1.from_mapping({
        "state_digest": "sha256:" + ("2" if base_sha == "a" * 40 else "3") * 64,
        "branch": "feature/AI-TEAM-005-local-orchestrator" if task_exists else None,
        "worktree": (
            "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-005-local-orchestrator"
            if task_exists else None
        ),
        "base_sha": base_sha,
        "dirty": dirty,
        "changed_paths": list(changed_paths),
        "pr_number": None,
        "pr_head_sha": None,
        "ci_state": "NOT_RUN",
        "review_state": "NOT_RUN",
        "merge_state": "PASS" if cleanup_safe or phase == "closed" else "NOT_RUN",
        "cleanup_safe": cleanup_safe,
    })
    return ObservedExecution(
        state=state,
        phase=phase,
        base_matches_plan=base_sha == "a" * 40,
        task_head="b" * 40 if task_exists else None,
        local_develop_sha="a" * 40,
        remote_develop_sha=base_sha,
        local_branch_exists=task_exists,
        remote_branch_exists=False,
        worktree_registered=task_exists,
    )


def _propose(
    plan,
    observed,
    attempted: frozenset[str] = frozenset(),
    successful: frozenset[str] = frozenset(),
):
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.transitions import propose_next_transition
    finally:
        sys.path.pop(0)
    return propose_next_transition(
        plan,
        observed,
        attempted_actions=attempted,
        successful_actions=successful,
    )


def test_planned_state_proposes_one_deterministic_task_create() -> None:
    """A moving or random transition ID would defeat expected-transition replay protection."""
    plan = _plan()
    observed = _observed("planned")

    first = _propose(plan, observed)
    second = _propose(plan, observed)

    assert first == second
    assert first.action == "task-create"
    assert first.transition_id.startswith("tr-")
    assert first.from_state_digest == observed.state.state_digest
    assert first.requires_apply is True
    assert len(first.commands) == 1
    assert first.commands[0][:3] == ("bash", "scripts/engineering/task-worktree.sh", "create")
    assert "--apply" not in first.commands[0]


def test_base_drift_blocks_before_task_create_or_integrate() -> None:
    """Using a newer moving base than the plan approved would invalidate exact-SHA scope review."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        _propose(_plan(), _observed("planned", base_sha="c" * 40))
    assert raised.value.error_type == "base_sha_drift"


def test_implementation_with_allowed_changes_proposes_atomic_draft_pr_transition() -> None:
    """Splitting the existing integrate entrypoint would create a second workflow implementation."""
    proposal = _propose(
        _plan(),
        _observed(
            "implementation-ready",
            changed_paths=("tests/example.py",),
            dirty=True,
        ),
    )

    assert proposal.action == "local-integrate-to-draft-pr"
    assert proposal.commands[0][:3] == ("bash", "scripts/engineering/task-worktree.sh", "integrate")
    assert "--test-profile" in proposal.commands[0]
    assert "engineering" in proposal.commands[0]


def test_implementation_without_changes_waits_without_side_effects() -> None:
    """An empty worktree must not invoke a commit/push flow that cannot succeed."""
    proposal = _propose(_plan(), _observed("implementation-ready"))

    assert proposal.action == "await-implementation"
    assert proposal.commands == ()
    assert proposal.requires_apply is False


def test_clean_committed_changes_without_receipt_block_integrate_retry() -> None:
    """A lost post-push receipt must not cause commit/push/Draft-PR to run a second time."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        _propose(
            _plan(),
            _observed(
                "implementation-ready",
                changed_paths=("tests/example.py",),
                dirty=False,
            ),
        )
    assert raised.value.error_type == "integration_state_uncertain"


def test_successful_integrate_receipt_turns_clean_committed_state_into_draft_pr_ready() -> None:
    """A verified successful receipt must recover the wait-for-merge state after process restart."""
    proposal = _propose(
        _plan(),
        _observed(
            "implementation-ready",
            changed_paths=("tests/example.py",),
            dirty=False,
        ),
        frozenset({"local-integrate-to-draft-pr"}),
        frozenset({"local-integrate-to-draft-pr"}),
    )

    assert proposal.action == "await-develop-merge"
    assert proposal.requires_apply is False
    assert proposal.commands == ()
    assert proposal.human_gate == "AI-TEAM-007"


def test_changed_path_outside_plan_allowlist_fails_closed() -> None:
    """Lane 2 classification alone must not widen the frozen task scope."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        _propose(
            _plan(),
            _observed("implementation-ready", changed_paths=("services/quant-api/app/main.py",), dirty=True),
        )
    assert raised.value.error_type == "changed_path_out_of_scope"


def test_recursive_allowlist_entry_accepts_only_its_descendants() -> None:
    """Treating `/**` literally would make the documented module allowlist unusable."""
    ExecutionPlanV1, _, _ = _contracts()
    payload = _plan().to_dict()
    payload["scope"] = {
        "allowed_paths": ["docs/research/**"],
        "forbidden_paths": ["Runtime"],
    }
    plan = ExecutionPlanV1.from_mapping(payload)

    proposal = _propose(
        plan,
        _observed(
            "implementation-ready",
            changed_paths=("docs/research/nested/note.md",),
            dirty=True,
        ),
    )

    assert proposal.action == "local-integrate-to-draft-pr"


def test_explicit_forbidden_path_overrides_recursive_allowlist() -> None:
    """A broad allowlist must never cancel a more specific frozen prohibition."""
    ExecutionPlanV1, _, _ = _contracts()
    payload = _plan().to_dict()
    payload["scope"] = {
        "allowed_paths": ["scripts/**"],
        "forbidden_paths": ["scripts/private.py"],
    }
    plan = ExecutionPlanV1.from_mapping(payload)

    with pytest.raises(Exception) as raised:
        _propose(
            plan,
            _observed(
                "implementation-ready",
                changed_paths=("scripts/private.py",),
                dirty=True,
            ),
        )
    assert raised.value.error_type == "changed_path_forbidden"


def test_control_plane_change_cannot_use_generic_integration() -> None:
    """A task cannot replace the workflow guard that generic apply is about to execute."""
    ExecutionPlanV1, _, _ = _contracts()
    payload = _plan().to_dict()
    payload["scope"] = {
        "allowed_paths": ["scripts/engineering/task-worktree.sh"],
        "forbidden_paths": [],
    }
    plan = ExecutionPlanV1.from_mapping(payload)

    with pytest.raises(Exception) as raised:
        _propose(
            plan,
            _observed(
                "implementation-ready",
                changed_paths=("scripts/engineering/task-worktree.sh",),
                dirty=True,
            ),
        )
    assert raised.value.error_type == "controller_path_requires_manual_integration"


def test_lane_three_plan_only_returns_human_gate_and_never_an_apply_action() -> None:
    """A generic apply path must never turn an external Gate into ordinary automation."""
    proposal = _propose(
        _plan(external_gates=["Owner approves real operation."]),
        _observed("planned"),
    )

    assert proposal.action == "await-human-gate"
    assert proposal.requires_apply is False
    assert proposal.commands == ()
    assert proposal.human_gate == "Owner approves real operation."


def test_attempted_transition_cannot_be_replayed() -> None:
    """A failed or interrupted external action must be inspected, not blindly repeated."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        _propose(_plan(), _observed("planned"), frozenset({"task-create"}))
    assert raised.value.error_type == "transition_already_attempted"


def test_cleanup_requires_observed_merge_and_proposes_only_cleanup() -> None:
    """A clean worktree alone is insufficient evidence that its task HEAD reached develop."""
    proposal = _propose(
        _plan(),
        _observed("merged-develop-observed", cleanup_safe=True),
    )

    assert proposal.action == "local-cleanup-after-merge-observed"
    assert proposal.commands[0][:3] == ("bash", "scripts/engineering/task-worktree.sh", "cleanup")
    assert proposal.requires_apply is True
