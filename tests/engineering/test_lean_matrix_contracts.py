"""Behavior contracts for the modular Lean Matrix kernel."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"


def _charter() -> dict[str, object]:
    return {
        "schema_version": 1,
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "value": "Keep later orchestration deterministic.",
        "goal": "Render one execution plan.",
        "current_facts": ["The Charter contract is frozen."],
        "lane": 2,
        "domains": [],
        "allowed_paths": ["scripts/engineering/lean_matrix/"],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["Contracts serialize deterministically."],
        "external_gates": [],
    }


def test_modular_charter_renderer_preserves_the_public_payload() -> None:
    """Moving the renderer behind modules cannot change its consumer-visible JSON."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.charter import render_charter
    finally:
        sys.path.pop(0)

    rendered = render_charter(_charter())

    assert rendered["schema_version"] == 1
    assert rendered["status"] == "ok"
    assert rendered["task"] == {
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "branch": "feature/AI-TEAM-004-execution-contracts",
        "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-004-execution-contracts",
    }
    assert rendered["dispatch"] == {
        "model": "Terra",
        "reasoning_effort": "medium",
        "mode": "plan-then-execute",
        "session_count": 3,
        "roles": [
            "ai-project-lead",
            "technical-lead",
            "implementer",
            "independent-quality-reviewer",
        ],
        "specialists": [],
        "independence_requirements": [
            "implementer and independent-quality-reviewer use separate contexts",
        ],
    }
    assert rendered["charter_markdown"].startswith("# Task Charter\n")


def test_task_charter_contract_is_frozen_strict_and_semantically_normalized() -> None:
    """Unknown fields or mutable/duplicated semantic state cannot enter a frozen Charter."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import TaskCharterV1
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    raw = _charter() | {"domains": ["frontend", "frontend"]}
    charter = TaskCharterV1.from_mapping(raw)

    assert charter.domains == ("frontend",)
    assert charter.allowed_paths == ("scripts/engineering/lean_matrix/",)
    assert charter.to_dict() == {
        "schema_version": 1,
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "value": "Keep later orchestration deterministic.",
        "goal": "Render one execution plan.",
        "current_facts": ["The Charter contract is frozen."],
        "lane": 2,
        "domains": ["frontend"],
        "allowed_paths": ["scripts/engineering/lean_matrix/"],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["Contracts serialize deterministically."],
        "external_gates": [],
    }
    with pytest.raises(FrozenInstanceError):
        charter.lane = 1  # type: ignore[misc]
    with pytest.raises(LeanMatrixError, match="input keys must exactly match"):
        TaskCharterV1.from_mapping(raw | {"unexpected": True})


def test_canonical_json_digest_uses_only_normalized_semantic_fields() -> None:
    """Key order and duplicate domains cannot drift a digest, while a semantic goal change must."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import TaskCharterV1
        from lean_matrix.digests import canonical_json, charter_digest
    finally:
        sys.path.pop(0)

    charter = TaskCharterV1.from_mapping(_charter())
    duplicate_domain = TaskCharterV1.from_mapping(_charter() | {"domains": []})
    changed = TaskCharterV1.from_mapping(_charter() | {"goal": "A different semantic goal."})

    assert canonical_json({"b": 2, "a": "归一"}) == '{"a":"归一","b":2}'
    assert charter_digest(charter).startswith("sha256:")
    assert len(charter_digest(charter)) == 71
    assert charter_digest(charter) == charter_digest(duplicate_domain)
    assert charter_digest(charter) != charter_digest(changed)


def test_runtime_contracts_serialize_deterministically_and_reject_unknown_state() -> None:
    """Runtime observations and reports cannot acquire undeclared state or mutable collections."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import (
            ObservedStateV1,
            StageReportV1,
            TransitionProposalV1,
            TransitionReceiptV1,
        )
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    state_payload = {
        "state_digest": "sha256:" + "1" * 64,
        "branch": "feature/AI-TEAM-004-execution-contracts",
        "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-004-execution-contracts",
        "base_sha": "2" * 40,
        "dirty": False,
        "changed_paths": ["scripts/engineering/lean_matrix/contracts.py"],
        "pr_number": None,
        "pr_head_sha": None,
        "ci_state": "NOT_RUN",
        "review_state": "NOT_RUN",
        "merge_state": "NOT_RUN",
        "cleanup_safe": False,
    }
    observed = ObservedStateV1.from_mapping(state_payload)
    assert observed.changed_paths == ("scripts/engineering/lean_matrix/contracts.py",)
    assert observed.to_dict() == state_payload
    with pytest.raises(LeanMatrixError, match="keys must exactly match"):
        ObservedStateV1.from_mapping(state_payload | {"extra": "state"})

    proposal = TransitionProposalV1.from_mapping({
        "transition_id": "transition-001",
        "from_state_digest": "sha256:" + "1" * 64,
        "action": "task-create",
        "commands": [["git", "status", "--short"]],
        "side_effect_scope": "repository-task-worktree",
        "requires_apply": True,
        "human_gate": None,
    })
    assert proposal.commands == (("git", "status", "--short"),)

    receipt = TransitionReceiptV1.from_mapping({
        "transition_id": "transition-001",
        "plan_digest": "sha256:" + "3" * 64,
        "before_state_digest": "sha256:" + "1" * 64,
        "after_state_digest": "sha256:" + "4" * 64,
        "command_digests": ["sha256:" + "5" * 64],
        "exit_codes": [0],
        "result": "PASS",
        "recorded_at": "2026-08-02T12:00:00Z",
    })
    assert receipt.exit_codes == (0,)

    report = StageReportV1.from_mapping({
        "schema_version": 1,
        "task_id": "AI-TEAM-004",
        "charter_digest": "sha256:" + "6" * 64,
        "plan_digest": "sha256:" + "7" * 64,
        "exact_head_sha": "8" * 40,
        "code_state": "PASS",
        "tests_state": "PASS",
        "ci_state": "NOT_RUN",
        "review_state": "NOT_RUN",
        "real_gate_state": "NOT_APPLICABLE",
        "release_state": "NOT_APPLICABLE",
        "runtime_state": "NOT_APPLICABLE",
        "completed": ["Contract tests pass."],
        "verification_evidence": ["pytest exit=0"],
        "remaining_risks": ["CI pending."],
        "user_actions": [],
        "automatic_next_step": "Create a Draft PR.",
    })
    assert report.user_actions == ()
    assert report.to_dict()["runtime_state"] == "NOT_APPLICABLE"


def test_runtime_contracts_fail_closed_on_invalid_sha_status_path_and_control_text() -> None:
    """Malformed runtime evidence must stop at the contract boundary."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import BaseRevisionV1, ScopeV1, StageReportV1
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError, match="40 lowercase hexadecimal"):
        BaseRevisionV1.from_mapping({"ref": "origin/develop", "expected_sha": "ABC"})
    with pytest.raises(LeanMatrixError, match="repository-relative"):
        ScopeV1.from_mapping({"allowed_paths": ["/tmp/outside"], "forbidden_paths": []})
    with pytest.raises(LeanMatrixError, match="invalid status"):
        StageReportV1.from_mapping({
            "schema_version": 1,
            "task_id": "AI-TEAM-004",
            "charter_digest": "sha256:" + "6" * 64,
            "plan_digest": "sha256:" + "7" * 64,
            "exact_head_sha": "8" * 40,
            "code_state": "DONE",
            "tests_state": "PASS",
            "ci_state": "NOT_RUN",
            "review_state": "NOT_RUN",
            "real_gate_state": "NOT_APPLICABLE",
            "release_state": "NOT_APPLICABLE",
            "runtime_state": "NOT_APPLICABLE",
            "completed": ["Contract tests pass."],
            "verification_evidence": ["pytest exit=0"],
            "remaining_risks": ["CI pending."],
            "user_actions": [],
            "automatic_next_step": "Create a Draft PR.",
        })
