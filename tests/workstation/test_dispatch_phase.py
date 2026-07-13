from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

# Inject scripts/ai/lib into path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ai" / "lib"))

from dispatch_phase import (
    Checkpoint,
    PhaseResult,
    PhaseError,
    VALID_PHASES,
    RISK_PHASE_SEQUENCES,
    define_phase_sequence,
    is_phase_forbidden,
    create_checkpoint,
    read_checkpoint,
    update_checkpoint,
    find_resume_phase,
    verify_resume_integrity,
    validate_phase_gate,
    _checkpoint_to_dict,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_checkpoint(
    task_id: str = "WS-V2-005",
    risk_level: str = "R1",
    branch: str = "feature/test",
    commit: str = "abc123def",
    plan_hash: str = "plan123abc",
    task_hash: str = "task456def",
    worktree: str = "/tmp/test-worktree",
) -> Checkpoint:
    cp = Checkpoint(
        schema_version=1,
        task_id=task_id,
        epic_id="WORKSTATION-GOVERNANCE-V2",
        risk_level=risk_level,
        branch=branch,
        commit_at_start=commit,
        plan_hash=plan_hash,
        task_hash=task_hash,
        worktree=worktree,
        overall_status="IN_PROGRESS",
    )
    for phase_name in define_phase_sequence(risk_level):
        cp.phases[phase_name] = PhaseResult(status="PENDING")
    return cp


@pytest.fixture
def tmp_repo() -> Path:
    """Create a temporary git repo for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        subprocess.run(["git", "init", "-b", "feature/test"], cwd=repo, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-m", "init"],
            cwd=repo, capture_output=True, text=True,
        )
        # Create fake plan and task files
        out_dir = repo / ".ai" / "results" / "WS-V2-005"
        out_dir.mkdir(parents=True, exist_ok=True)
        plan_file = out_dir / "plan_result.md"
        plan_file.write_text("# Plan\n\nTest plan content.", encoding="utf-8")
        task_file = repo / "docs" / "tasks" / "WS-V2-005.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text("# WS-V2-005\n\nTest task.", encoding="utf-8")
        yield repo


# ── Phase Sequence Tests ─────────────────────────────────────────────────────

class TestPhaseSequence:
    def test_r0_forbids_write_phases(self):
        assert is_phase_forbidden("R0", "dev")
        assert is_phase_forbidden("R0", "dry-run")
        assert is_phase_forbidden("R0", "apply")
        assert is_phase_forbidden("R0", "test")
        assert not is_phase_forbidden("R0", "prepare")
        assert not is_phase_forbidden("R0", "plan")
        assert not is_phase_forbidden("R0", "audit")
        assert not is_phase_forbidden("R0", "result")
        assert not is_phase_forbidden("R0", "close")

    def test_r1_allows_dev_not_apply(self):
        seq = define_phase_sequence("R1")
        assert "dev" in seq
        assert "apply" not in seq
        assert "dry-run" not in seq

    def test_r2_includes_dryrun_and_apply(self):
        seq = define_phase_sequence("R2")
        assert "dry-run" in seq
        assert "apply" in seq

    def test_r3_includes_dryrun_and_apply(self):
        seq = define_phase_sequence("R3")
        assert "dry-run" in seq
        assert "apply" in seq

    def test_all_phases_known(self):
        for phase in ["prepare", "plan", "audit", "dev", "dry-run", "apply", "test", "review", "result", "close"]:
            assert phase in VALID_PHASES, f"Unknown phase: {phase}"


# ── Checkpoint Tests ─────────────────────────────────────────────────────────

class TestCheckpointReadWrite:
    def test_create_initial_checkpoint(self, tmp_repo: Path):
        out_dir = tmp_repo / ".ai" / "results" / "WS-V2-005"
        cp = create_checkpoint(
            task_id="WS-V2-005",
            epic_id="WORKSTATION-GOVERNANCE-V2",
            risk_level="R1",
            repo_root=str(tmp_repo),
            worktree=str(tmp_repo),
            plan_file=".ai/results/WS-V2-005/plan_result.md",
            task_file="docs/tasks/WS-V2-005.md",
            out_dir=str(out_dir),
        )
        assert cp.task_id == "WS-V2-005"
        assert cp.risk_level == "R1"
        assert cp.overall_status == "IN_PROGRESS"
        assert len(cp.phases) == len(define_phase_sequence("R1"))
        assert all(pr.status == "PENDING" for pr in cp.phases.values())

    def test_checkpoint_persisted(self, tmp_repo: Path):
        out_dir = tmp_repo / ".ai" / "results" / "WS-V2-005"
        create_checkpoint(
            task_id="WS-V2-005",
            epic_id="WORKSTATION-GOVERNANCE-V2",
            risk_level="R1",
            repo_root=str(tmp_repo),
            worktree=str(tmp_repo),
            plan_file=".ai/results/WS-V2-005/plan_result.md",
            task_file="docs/tasks/WS-V2-005.md",
            out_dir=str(out_dir),
        )
        cp_file = out_dir / "dispatch_checkpoint.json"
        assert cp_file.is_file()
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        assert data["task_id"] == "WS-V2-005"
        assert data["schema_version"] == 1

    def test_read_checkpoint(self, tmp_repo: Path):
        out_dir = tmp_repo / ".ai" / "results" / "WS-V2-005"
        create_checkpoint(
            task_id="WS-V2-005",
            epic_id="WORKSTATION-GOVERNANCE-V2",
            risk_level="R1",
            repo_root=str(tmp_repo),
            worktree=str(tmp_repo),
            plan_file=".ai/results/WS-V2-005/plan_result.md",
            task_file="docs/tasks/WS-V2-005.md",
            out_dir=str(out_dir),
        )
        cp = read_checkpoint(str(out_dir / "dispatch_checkpoint.json"))
        assert cp.task_id == "WS-V2-005"
        assert cp.phases["prepare"].status == "PENDING"

    def test_update_checkpoint_phase(self, tmp_repo: Path):
        out_dir = tmp_repo / ".ai" / "results" / "WS-V2-005"
        create_checkpoint(
            task_id="WS-V2-005",
            epic_id="WORKSTATION-GOVERNANCE-V2",
            risk_level="R1",
            repo_root=str(tmp_repo),
            worktree=str(tmp_repo),
            plan_file=".ai/results/WS-V2-005/plan_result.md",
            task_file="docs/tasks/WS-V2-005.md",
            out_dir=str(out_dir),
        )
        cp = read_checkpoint(str(out_dir / "dispatch_checkpoint.json"))
        pr = PhaseResult(status="PASSED", started_at="2026-07-13T17:00:00Z", ended_at="2026-07-13T17:01:00Z")
        update_checkpoint(cp, str(out_dir), phase_name="prepare", phase_result=pr)

        cp2 = read_checkpoint(str(out_dir / "dispatch_checkpoint.json"))
        assert cp2.phases["prepare"].status == "PASSED"


class TestCheckpointIntegrity:
    def test_missing_checkpoint_raises(self, tmp_repo: Path):
        with pytest.raises(PhaseError, match="CHECKPOINT_MISSING"):
            read_checkpoint(str(tmp_repo / "nonexistent.json"))

    def test_corrupt_checkpoint_raises(self, tmp_repo: Path):
        bad = tmp_repo / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(PhaseError, match="CHECKPOINT_CORRUPT"):
            read_checkpoint(str(bad))


# ── Resume Tests ─────────────────────────────────────────────────────────────

class TestFindResumePhase:
    def test_resume_from_failed(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED")
        cp.phases["plan"] = PhaseResult(status="FAILED", exit_code=1, error="plan failed")
        nxt = find_resume_phase(cp, "R1")
        assert nxt == "plan"

    def test_resume_from_first_pending(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED")
        # plan is still PENDING
        nxt = find_resume_phase(cp, "R1")
        assert nxt == "plan"

    def test_all_done_returns_none(self):
        cp = _make_checkpoint()
        for p in define_phase_sequence("R1"):
            cp.phases[p] = PhaseResult(status="PASSED")
        nxt = find_resume_phase(cp, "R1")
        assert nxt is None

    def test_resume_same_phase_after_failed(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED")
        cp.phases["plan"] = PhaseResult(status="FAILED")
        nxt = find_resume_phase(cp, "R1")
        assert nxt == "plan"  # Not skipping to dev


# ── Phase Gate Tests ─────────────────────────────────────────────────────────

class TestPhaseGateValidation:
    def test_r0_blocks_dev(self):
        cp = _make_checkpoint(risk_level="R0")
        result = validate_phase_gate("dev", "R0", cp)
        assert result["ok"] is False
        assert result["code"] == "RISK_GATE"

    def test_r0_allows_prepare(self):
        cp = _make_checkpoint(risk_level="R0")
        result = validate_phase_gate("prepare", "R0", cp)
        assert result["ok"] is True

    def test_requires_previous_phase_passed(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="FAILED")
        result = validate_phase_gate("plan", "R1", cp)
        assert result["ok"] is False
        assert result["code"] == "DEPENDENCY_FAILED"

    def test_allows_when_previous_passed(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED")
        result = validate_phase_gate("plan", "R1", cp)
        assert result["ok"] is True

    def test_approval_gate_dev(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED")
        cp.phases["plan"] = PhaseResult(status="PASSED")
        cp.phases["audit"] = PhaseResult(status="PASSED")
        # Without approval
        result = validate_phase_gate("dev", "R1", cp, approval_available=False)
        assert result["ok"] is False
        assert result["code"] == "APPROVAL_MISSING"
        # With approval
        result = validate_phase_gate("dev", "R1", cp, approval_available=True, approval_operation="DEV")
        assert result["ok"] is True


# ── Gateway Demo Tests (4 Risk Routes) ──────────────────────────────────────

class TestDemoR0ReadOnly:
    """D1: R0 task — prepare→plan→audit→result, dev/apply REJECTED."""

    def test_r0_phases_only_read(self):
        seq = define_phase_sequence("R0")
        assert "dev" not in seq
        assert "apply" not in seq
        assert "dry-run" not in seq
        assert "test" not in seq
        assert seq == ["prepare", "plan", "audit", "result", "close"]

    def test_r0_prepare_passes(self):
        cp = _make_checkpoint(risk_level="R0")
        result = validate_phase_gate("prepare", "R0", cp)
        assert result["ok"] is True

    def test_r0_dev_rejected(self):
        cp = _make_checkpoint(risk_level="R0")
        result = validate_phase_gate("dev", "R0", cp)
        assert result["ok"] is False
        assert "R0" in result["detail"]

    def test_r0_apply_rejected(self):
        cp = _make_checkpoint(risk_level="R0")
        result = validate_phase_gate("apply", "R0", cp)
        assert result["ok"] is False
        assert "R0" in result["detail"]


class TestDemoR1Dev:
    """D2: R1 task — prepare→plan→audit→dev→test→review→result, all PASS."""

    def test_r1_full_sequence_forward(self):
        cp = _make_checkpoint(risk_level="R1")
        seq = define_phase_sequence("R1")
        assert "dev" in seq
        assert "apply" not in seq
        assert "dry-run" not in seq

    def test_r1_all_phases_gate_pass(self):
        cp = _make_checkpoint(risk_level="R1")
        # Phase → correct approval_operation mapping
        phase_ops = {
            "prepare": "", "plan": "", "audit": "", "dev": "DEV",
            "test": "", "review": "", "result": "", "close": "MERGE",
        }
        for i, phase in enumerate(define_phase_sequence("R1")):
            for prev in define_phase_sequence("R1")[:i]:
                cp.phases[prev] = PhaseResult(status="PASSED")
            op = phase_ops.get(phase, "")
            result = validate_phase_gate(phase, "R1", cp, approval_available=bool(op), approval_operation=op)
            assert result["ok"] is True, f"{phase} gate failed: {result}"


class TestDemoR2DryRunBlocked:
    """D3: R2 task — dry-run passes, apply blocked without DATA_WRITE approval."""

    def test_r2_dryrun_in_sequence(self):
        seq = define_phase_sequence("R2")
        assert "dry-run" in seq
        assert "apply" in seq

    def test_r2_apply_blocked_without_approval(self):
        cp = _make_checkpoint(risk_level="R2")
        # Pass prepare/plan/audit/dev/dry-run
        for phase in ["prepare", "plan", "audit", "dev", "dry-run"]:
            cp.phases[phase] = PhaseResult(status="PASSED")
        # Try apply without approval
        result = validate_phase_gate("apply", "R2", cp, approval_available=False)
        assert result["ok"] is False
        assert result["code"] == "APPROVAL_MISSING"

    def test_r2_apply_allowed_with_approval(self):
        cp = _make_checkpoint(risk_level="R2")
        for phase in ["prepare", "plan", "audit", "dev", "dry-run"]:
            cp.phases[phase] = PhaseResult(status="PASSED")
        result = validate_phase_gate("apply", "R2", cp, approval_available=True, approval_operation="DATA_WRITE")
        assert result["ok"] is True

    def test_r2_dryrun_passes_without_special_approval(self):
        cp = _make_checkpoint(risk_level="R2")
        for phase in ["prepare", "plan", "audit", "dev"]:
            cp.phases[phase] = PhaseResult(status="PASSED")
        result = validate_phase_gate("dry-run", "R2", cp)
        assert result["ok"] is True


class TestDemoR3RuntimeBlocked:
    """D4: R3 task — DEV approval exists, but apply blocked without RUNTIME approval."""

    def test_r3_separate_runtime_approval(self):
        cp = _make_checkpoint(risk_level="R3")
        for phase in ["prepare", "plan", "audit", "dev", "dry-run"]:
            cp.phases[phase] = PhaseResult(status="PASSED")

        # DEV approval available but NOT RUNTIME
        result = validate_phase_gate("apply", "R3", cp, approval_available=True, approval_operation="DEV")
        assert result["ok"] is False
        assert result["code"] == "SCOPE_MISMATCH"

    def test_r3_apply_allowed_with_runtime(self):
        cp = _make_checkpoint(risk_level="R3")
        for phase in ["prepare", "plan", "audit", "dev", "dry-run"]:
            cp.phases[phase] = PhaseResult(status="PASSED")
        result = validate_phase_gate("apply", "R3", cp, approval_available=True, approval_operation="RUNTIME")
        assert result["ok"] is True


# ── Serialization Tests ──────────────────────────────────────────────────────

class TestCheckpointSerialization:
    def test_to_dict_round_trip(self):
        cp = _make_checkpoint()
        cp.phases["prepare"] = PhaseResult(status="PASSED", started_at="t1", ended_at="t2")
        d = _checkpoint_to_dict(cp)
        assert d["task_id"] == "WS-V2-005"
        assert d["phases"]["prepare"]["status"] == "PASSED"

    def test_to_dict_includes_all_phases(self):
        cp = _make_checkpoint(risk_level="R2")
        d = _checkpoint_to_dict(cp)
        assert len(d["phases"]) == len(define_phase_sequence("R2"))
