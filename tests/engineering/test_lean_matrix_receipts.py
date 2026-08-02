"""Tests for plan-scoped, tamper-evident Lean Matrix runtime evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"


def _contracts(task_id: str = "AI-TEAM-005"):
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import ExecutionPlanV1, TransitionProposalV1, TransitionReceiptV1
        from lean_matrix.digests import semantic_digest
    finally:
        sys.path.pop(0)
    suffix = "local-orchestrator" if task_id == "AI-TEAM-005" else "other-plan"
    plan = ExecutionPlanV1.from_mapping({
        "schema_version": 1,
        "status": "ok",
        "charter_digest": "sha256:" + ("1" if task_id == "AI-TEAM-005" else "9") * 64,
        "task": {
            "issue_number": 109 if task_id == "AI-TEAM-005" else 110,
            "task_id": task_id,
            "branch": f"feature/{task_id}-{suffix}",
            "worktree": f"/Volumes/扩展盘/GuiyiWorktrees/tasks/{task_id}-{suffix}",
        },
        "base": {"ref": "origin/develop", "expected_sha": "a" * 40},
        "dispatch": {
            "model": "Terra",
            "reasoning_effort": "medium",
            "roles": ["ai-project-lead"],
            "specialists": [],
            "independence_requirements": ["independent review"],
        },
        "scope": {"allowed_paths": ["tests/example.py"], "forbidden_paths": ["Runtime"]},
        "validation": {"test_profile": "engineering", "required_checks": ["diff-check"]},
        "transitions": ["task-create"],
        "external_gates": [],
    })
    plan_digest = semantic_digest(plan.to_dict())
    from lean_matrix.adapters import command_for_action
    from lean_matrix.transitions import transition_id
    state_digest = "sha256:" + "3" * 64
    proposal = TransitionProposalV1.from_mapping({
        "transition_id": transition_id(plan, "task-create", state_digest),
        "from_state_digest": state_digest,
        "action": "task-create",
        "commands": [list(command_for_action(plan, "task-create"))],
        "side_effect_scope": "task-worktree",
        "requires_apply": True,
        "human_gate": None,
    })
    receipt = TransitionReceiptV1.from_mapping({
        "transition_id": proposal.transition_id,
        "plan_digest": plan_digest,
        "before_state_digest": proposal.from_state_digest,
        "after_state_digest": "sha256:" + "4" * 64,
        "command_digests": [semantic_digest(list(command_for_action(plan, "task-create", apply=True)))],
        "exit_codes": [0],
        "result": "PASS",
        "recorded_at": "2026-08-02T12:00:00Z",
    })
    return plan, proposal, receipt


def _workspace_api():
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.workspace import load_evidence, record_transition
    finally:
        sys.path.pop(0)
    return load_evidence, record_transition


def _valid_evidence():
    plan, _, _ = _contracts()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.adapters import command_for_action
        from lean_matrix.contracts import TransitionProposalV1, TransitionReceiptV1
        from lean_matrix.digests import semantic_digest
        from lean_matrix.transitions import transition_id
        from lean_matrix.workspace import plan_digest
    finally:
        sys.path.pop(0)
    state_digest = "sha256:" + "3" * 64
    identifier = transition_id(plan, "task-create", state_digest)
    proposal = TransitionProposalV1.from_mapping({
        "transition_id": identifier,
        "from_state_digest": state_digest,
        "action": "task-create",
        "commands": [list(command_for_action(plan, "task-create"))],
        "side_effect_scope": "task-worktree",
        "requires_apply": True,
        "human_gate": None,
    })
    receipt = TransitionReceiptV1.from_mapping({
        "transition_id": identifier,
        "plan_digest": plan_digest(plan),
        "before_state_digest": state_digest,
        "after_state_digest": "sha256:" + "4" * 64,
        "command_digests": [semantic_digest(list(command_for_action(plan, "task-create", apply=True)))],
        "exit_codes": [0],
        "result": "PASS",
        "recorded_at": "2026-08-02T12:00:00Z",
    })
    return plan, proposal, receipt


def test_loading_missing_workspace_is_read_only(tmp_path: Path) -> None:
    """observe/next must not create `.ai` merely by checking for prior receipts."""
    plan, _, _ = _contracts()
    load_evidence, _ = _workspace_api()

    evidence = load_evidence(tmp_path, plan)

    assert evidence.attempted_actions == frozenset()
    assert evidence.records == ()
    assert not (tmp_path / ".ai").exists()


def test_recorded_transition_is_plan_scoped_and_round_trips(tmp_path: Path) -> None:
    """Losing proposal-to-receipt linkage would allow a receipt to authorize another action."""
    plan, proposal, receipt = _contracts()
    load_evidence, record_transition = _workspace_api()

    record_transition(tmp_path, plan, proposal, receipt, error_type=None)
    evidence = load_evidence(tmp_path, plan)

    assert evidence.attempted_actions == frozenset({"task-create"})
    assert len(evidence.records) == 1
    assert evidence.records[0].proposal == proposal
    assert evidence.records[0].receipt == receipt
    workspace = tmp_path / ".ai" / "lean-matrix" / receipt.plan_digest.removeprefix("sha256:")
    assert json.loads((workspace / "plan.json").read_text(encoding="utf-8")) == plan.to_dict()
    log = json.loads(next((workspace / "logs").iterdir()).read_text(encoding="utf-8"))
    assert log == {
        "action": "task-create",
        "error_type": None,
        "exit_codes": [0],
        "result": "PASS",
        "transition_id": proposal.transition_id,
    }


def test_modified_receipt_content_fails_filename_digest_check(tmp_path: Path) -> None:
    """An in-place receipt edit must block recovery instead of silently changing history."""
    plan, proposal, receipt = _contracts()
    load_evidence, record_transition = _workspace_api()
    record_transition(tmp_path, plan, proposal, receipt, error_type=None)
    workspace = tmp_path / ".ai" / "lean-matrix" / receipt.plan_digest.removeprefix("sha256:")
    receipt_path = next((workspace / "receipts").iterdir())
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["result"] = "FAIL"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        load_evidence(tmp_path, plan)
    assert raised.value.error_type == "workspace_artifact_tampered"


def test_two_plan_workspaces_remain_isolated(tmp_path: Path) -> None:
    """Scanning a sibling plan directory would let one task suppress another task transition."""
    first = _contracts()
    second = _contracts("AI-TEAM-006")
    load_evidence, record_transition = _workspace_api()
    record_transition(tmp_path, *first, error_type=None)

    assert load_evidence(tmp_path, second[0]).attempted_actions == frozenset()
    assert load_evidence(tmp_path, first[0]).attempted_actions == frozenset({"task-create"})


def test_receipt_bound_to_another_plan_is_rejected_before_write(tmp_path: Path) -> None:
    """A valid receipt from a sibling plan must not be copied into this plan's workspace."""
    plan, proposal, _ = _contracts()
    _, _, foreign_receipt = _contracts("AI-TEAM-006")
    _, record_transition = _workspace_api()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        record_transition(tmp_path, plan, proposal, foreign_receipt, error_type=None)
    assert raised.value.error_type == "receipt_plan_mismatch"
    assert not (tmp_path / ".ai").exists()


def test_workspace_root_symlink_is_rejected_without_external_write(tmp_path: Path) -> None:
    """Ignored evidence must not escape the repository through a pre-existing symlink."""
    plan, _, _ = _contracts()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".ai").symlink_to(outside, target_is_directory=True)
    load_evidence, _ = _workspace_api()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        load_evidence(tmp_path, plan)
    assert raised.value.error_type == "workspace_symlink_forbidden"
    assert list(outside.iterdir()) == []


def test_receipt_is_rederived_from_plan_and_command_contract(tmp_path: Path) -> None:
    """Rehashed but fabricated proposal commands cannot become recovery evidence."""
    plan, proposal, receipt = _valid_evidence()
    load_evidence, record_transition = _workspace_api()
    record_transition(tmp_path, plan, proposal, receipt, error_type=None)
    workspace = tmp_path / ".ai" / "lean-matrix" / receipt.plan_digest.removeprefix("sha256:")
    proposal_path = next((workspace / "proposals").iterdir())
    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    payload["commands"] = [["bash", "attacker.sh"]]
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.receipts import artifact_name
    finally:
        sys.path.pop(0)
    forged = proposal_path.with_name(artifact_name(proposal.transition_id, payload))
    proposal_path.unlink()
    forged.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(Exception) as raised:
        load_evidence(tmp_path, plan)
    assert raised.value.error_type == "proposal_command_mismatch"


def test_claim_is_atomic_and_blocks_a_concurrent_second_apply(tmp_path: Path) -> None:
    """The attempt marker must exist before the external command can start."""
    plan, proposal, _ = _valid_evidence()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.workspace import claim_transition
    finally:
        sys.path.pop(0)

    claim_transition(tmp_path, plan, proposal)
    with pytest.raises(LeanMatrixError) as raised:
        claim_transition(tmp_path, plan, proposal)
    assert raised.value.error_type == "transition_already_attempted"
