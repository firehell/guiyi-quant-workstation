"""
GUIYI Dispatch Phase Engine V1 — 10-stage phased execution with checkpoint/resume.

Core capabilities:
- define_phase_sequence:    resolve permitted phases by risk level
- create_checkpoint:        write dispatch_checkpoint.json
- verify_resume_integrity:  validate branch/commit/plan_hash before --resume
- validate_phase_gate:      per-phase pre-flight check (approval/lock/sandbox)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Constants ────────────────────────────────────────────────────────────────

PHASE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "prepare": {
        "index": 0,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "none",
        "command": None,
        "description": "Validate schema/deps/env/branch/worktree",
    },
    "plan": {
        "index": 1,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "read-only",
        "command": ["scripts/ai/codex_plan.sh", "--task"],
        "description": "Generate execution plan",
    },
    "audit": {
        "index": 2,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "read-only",
        "command": None,
        "description": "Security audit and threat model",
    },
    "dev": {
        "index": 3,
        "operation": "DEV",
        "requires_approval": True,
        "requires_resource_lock": True,
        "requires_writer_lock": True,
        "sandbox": "workspace-write",
        "command": ["scripts/ai/codex_dev.sh", "--task"],
        "description": "Write code",
    },
    "dry-run": {
        "index": 4,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": True,
        "requires_writer_lock": False,
        "sandbox": "read-only",
        "command": None,
        "description": "Simulate execution (read-only sandbox)",
    },
    "apply": {
        "index": 5,
        "operation": None,  # Resolved at runtime: DATA_WRITE or RUNTIME
        "requires_approval": True,
        "requires_resource_lock": True,
        "requires_writer_lock": False,
        "sandbox": "workspace-write",
        "command": None,
        "description": "Execute write/run operations (post-verify enforced)",
    },
    "test": {
        "index": 6,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "none",
        "command": ["scripts/ai/run_tests.sh", "--task"],
        "description": "Run test suite",
    },
    "review": {
        "index": 7,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "read-only",
        "command": ["scripts/ai/codex_review.sh", "--task"],
        "description": "Code review",
    },
    "result": {
        "index": 8,
        "operation": "AUDIT",
        "requires_approval": False,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "none",
        "command": ["scripts/ai/collect_result.sh", "--task"],
        "description": "Collect delivery artifacts",
    },
    "close": {
        "index": 9,
        "operation": "MERGE",
        "requires_approval": True,
        "requires_resource_lock": False,
        "requires_writer_lock": False,
        "sandbox": "none",
        "command": None,
        "description": "Mark CLOSED (final state)",
    },
}

# Phase sequences by risk level
RISK_PHASE_SEQUENCES: Dict[str, List[str]] = {
    "R0": ["prepare", "plan", "audit", "result", "close"],
    "R1": ["prepare", "plan", "audit", "dev", "test", "review", "result", "close"],
    "R2": ["prepare", "plan", "audit", "dev", "dry-run", "apply", "test", "review", "result", "close"],
    "R3": ["prepare", "plan", "audit", "dev", "dry-run", "apply", "test", "review", "result", "close"],
}

# R0 forbidden phases
R0_FORBIDDEN_PHASES = frozenset({"dev", "fix", "dry-run", "apply", "test"})

# Phases that can be individually invoked
VALID_PHASES = frozenset(PHASE_DEFINITIONS)


@dataclass
class PhaseResult:
    status: str  # PASSED | FAILED | SKIPPED | PENDING
    started_at: str = ""
    ended_at: str = ""
    exit_code: int = 0
    error: str = ""
    log_file: str = ""


@dataclass
class Checkpoint:
    schema_version: int = 1
    task_id: str = ""
    epic_id: str = ""
    risk_level: str = "R1"
    branch: str = ""
    commit_at_start: str = ""
    plan_hash: str = ""
    task_hash: str = ""
    worktree: str = ""
    phases: Dict[str, PhaseResult] = field(default_factory=dict)
    overall_status: str = "IN_PROGRESS"
    generated_at: str = ""


class PhaseError(Exception):
    """Structured phase execution error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"[{code}] {detail}")
        self.code = code
        self.detail = detail


# ── Helpers ──────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_branch(repo_root: Path) -> str:
    r = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    return r.stdout.strip()


def _git_head(repo_root: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    return r.stdout.strip()


# ── Phase Sequence ───────────────────────────────────────────────────────────

def define_phase_sequence(risk_level: str) -> List[str]:
    """Return the permitted phase sequence for a given risk level."""
    level = risk_level.strip().upper()
    return RISK_PHASE_SEQUENCES.get(level, RISK_PHASE_SEQUENCES["R1"])


def is_phase_forbidden(risk_level: str, phase: str) -> bool:
    """Check if a phase is explicitly forbidden for a risk level."""
    if risk_level == "R0" and phase in R0_FORBIDDEN_PHASES:
        return True
    return False


# ── Checkpoint ───────────────────────────────────────────────────────────────

def create_checkpoint(
    *,
    task_id: str,
    epic_id: str,
    risk_level: str,
    repo_root: str,
    worktree: str,
    plan_file: str,
    task_file: str,
    out_dir: Optional[str] = None,
) -> Checkpoint:
    root = Path(repo_root).resolve()
    plan_path = (root / plan_file).resolve() if plan_file else None
    task_path = (root / task_file).resolve() if task_file else None

    cp = Checkpoint(
        schema_version=1,
        task_id=task_id,
        epic_id=epic_id,
        risk_level=risk_level,
        branch=_git_branch(root),
        commit_at_start=_git_head(root),
        plan_hash=_sha256(plan_path) if plan_path and plan_path.is_file() else "",
        task_hash=_sha256(task_path) if task_path and task_path.is_file() else "",
        worktree=worktree,
        overall_status="IN_PROGRESS",
        generated_at=_utc_now(),
    )

    # Initialize all phases as PENDING
    for phase_name in define_phase_sequence(risk_level):
        cp.phases[phase_name] = PhaseResult(status="PENDING")

    if out_dir:
        checkpoint_path = Path(out_dir) / "dispatch_checkpoint.json"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = checkpoint_path.with_suffix(f".{os.getpid()}.tmp")
        try:
            cp_dict = _checkpoint_to_dict(cp)
            tmp.write_text(_json_dumps(cp_dict), encoding="utf-8")
            tmp.rename(checkpoint_path)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise

    return cp


def read_checkpoint(checkpoint_file: str) -> Checkpoint:
    """Read a checkpoint from disk. Raises PhaseError if missing or invalid."""
    cp_path = Path(checkpoint_file)
    if not cp_path.is_file():
        raise PhaseError("CHECKPOINT_MISSING", f"No checkpoint at {cp_path}")

    try:
        data = json.loads(cp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PhaseError("CHECKPOINT_CORRUPT", f"Invalid JSON in {cp_path}: {e}")

    cp = Checkpoint(
        schema_version=data.get("schema_version", 1),
        task_id=data.get("task_id", ""),
        epic_id=data.get("epic_id", ""),
        risk_level=data.get("risk_level", "R1"),
        branch=data.get("branch", ""),
        commit_at_start=data.get("commit_at_start", ""),
        plan_hash=data.get("plan_hash", ""),
        task_hash=data.get("task_hash", ""),
        worktree=data.get("worktree", ""),
        overall_status=data.get("overall_status", ""),
        generated_at=data.get("generated_at", ""),
    )

    for name, pr in data.get("phases", {}).items():
        cp.phases[name] = PhaseResult(
            status=pr.get("status", "PENDING"),
            started_at=pr.get("started_at", ""),
            ended_at=pr.get("ended_at", ""),
            exit_code=pr.get("exit_code", 0),
            error=pr.get("error", ""),
            log_file=pr.get("log_file", ""),
        )

    return cp


def update_checkpoint(
    checkpoint: Checkpoint,
    out_dir: str,
    phase_name: str = "",
    phase_result: Optional[PhaseResult] = None,
    overall_status: Optional[str] = None,
) -> None:
    """Update checkpoint in-memory and on-disk atomically."""
    if phase_name and phase_result:
        checkpoint.phases[phase_name] = phase_result
    if overall_status:
        checkpoint.overall_status = overall_status
    checkpoint.generated_at = _utc_now()

    cp_path = Path(out_dir) / "dispatch_checkpoint.json"
    tmp = cp_path.with_suffix(f".{os.getpid()}.tmp")
    try:
        cp_dict = _checkpoint_to_dict(checkpoint)
        tmp.write_text(_json_dumps(cp_dict), encoding="utf-8")
        tmp.rename(cp_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def find_resume_phase(checkpoint: Checkpoint, risk_level: str) -> Optional[str]:
    """Find the first phase to resume. Returns None if all done."""
    sequence = define_phase_sequence(risk_level)
    for phase_name in sequence:
        pr = checkpoint.phases.get(phase_name)
        if not pr or pr.status in ("PENDING", "FAILED"):
            return phase_name
    return None


def verify_resume_integrity(
    checkpoint: Checkpoint,
    repo_root: str,
    plan_file: str,
    task_file: str,
) -> Dict[str, Any]:
    """
    Verify that --resume can proceed safely.
    Returns {"ok": True} or {"ok": False, "failures": [...]}
    """
    root = Path(repo_root).resolve()
    plan_path = (root / plan_file).resolve() if plan_file else None
    task_path = (root / task_file).resolve() if task_file else None
    failures: List[Dict[str, str]] = []

    # Branch check
    current_branch = _git_branch(root)
    if checkpoint.branch and current_branch != checkpoint.branch:
        failures.append({
            "check": "branch",
            "expected": checkpoint.branch,
            "actual": current_branch,
        })

    # Commit check
    current_commit = _git_head(root)
    if checkpoint.commit_at_start and current_commit != checkpoint.commit_at_start:
        failures.append({
            "check": "commit",
            "expected": checkpoint.commit_at_start[:12],
            "actual": current_commit[:12],
        })

    # Plan hash check
    if plan_path and plan_path.is_file():
        current_plan = _sha256(plan_path)
        if checkpoint.plan_hash and current_plan != checkpoint.plan_hash:
            failures.append({
                "check": "plan_hash",
                "expected": checkpoint.plan_hash[:12],
                "actual": current_plan[:12],
            })

    # Task hash check
    if task_path and task_path.is_file():
        current_task = _sha256(task_path)
        if checkpoint.task_hash and current_task != checkpoint.task_hash:
            failures.append({
                "check": "task_hash",
                "expected": checkpoint.task_hash[:12],
                "actual": current_task[:12],
            })

    # Worktree check
    if checkpoint.worktree:
        current_worktree = str(root)
        if current_worktree.strip("/") != checkpoint.worktree.strip("/"):
            failures.append({
                "check": "worktree",
                "expected": checkpoint.worktree,
                "actual": current_worktree,
            })

    if failures:
        return {"ok": False, "failures": failures}
    return {"ok": True}


# ── Phase Gate Validation ────────────────────────────────────────────────────

def validate_phase_gate(
    phase: str,
    risk_level: str,
    checkpoint: Checkpoint,
    *,
    approval_available: bool = False,
    approval_operation: str = "",
    repo_root: str = "",
    task_id: str = "",
) -> Dict[str, Any]:
    """
    Pre-flight gate check for a single phase.

    Returns {"ok": True} or {"ok": False, "code": str, "detail": str}
    """
    # R0 gate: forbid dev/dry-run/apply/test
    if is_phase_forbidden(risk_level, phase):
        return {
            "ok": False,
            "code": "RISK_GATE",
            "detail": f"R0 tasks cannot execute phase '{phase}'",
        }

    # Approval gate
    phase_def = PHASE_DEFINITIONS.get(phase, {})
    if phase_def.get("requires_approval"):
        if not approval_available:
            return {
                "ok": False,
                "code": "APPROVAL_MISSING",
                "detail": f"Phase '{phase}' requires approval",
            }
        if approval_operation:
            required_op = phase_def.get("operation")
            if required_op:
                if required_op != approval_operation:
                    return {
                        "ok": False,
                        "code": "SCOPE_MISMATCH",
                        "detail": f"Phase '{phase}' requires operation '{required_op}', got '{approval_operation}'",
                    }
            elif phase == "apply" and approval_operation not in ("DATA_WRITE", "RUNTIME"):
                # apply phase requires DATA_WRITE or RUNTIME, not just any approval
                return {
                    "ok": False,
                    "code": "SCOPE_MISMATCH",
                    "detail": f"Phase 'apply' requires DATA_WRITE or RUNTIME operation, got '{approval_operation}'",
                }

    # Dependency gate: ensure previous phases passed
    sequence = define_phase_sequence(risk_level)
    phase_idx = sequence.index(phase) if phase in sequence else -1
    for prev_phase in sequence[:phase_idx]:
        prev = checkpoint.phases.get(prev_phase)
        if not prev or prev.status == "FAILED":
            return {
                "ok": False,
                "code": "DEPENDENCY_FAILED",
                "detail": f"Previous phase '{prev_phase}' has status={prev.status if prev else 'UNKNOWN'}",
            }

    return {"ok": True}


# ── Serialization ────────────────────────────────────────────────────────────

def _checkpoint_to_dict(cp: Checkpoint) -> Dict[str, Any]:
    phases_dict: Dict[str, Dict[str, Any]] = {}
    for name, pr in cp.phases.items():
        phases_dict[name] = {
            "status": pr.status,
            "started_at": pr.started_at,
            "ended_at": pr.ended_at,
            "exit_code": pr.exit_code,
            "error": pr.error,
            "log_file": pr.log_file,
        }

    return {
        "schema_version": cp.schema_version,
        "task_id": cp.task_id,
        "epic_id": cp.epic_id,
        "risk_level": cp.risk_level,
        "branch": cp.branch,
        "commit_at_start": cp.commit_at_start,
        "plan_hash": cp.plan_hash,
        "task_hash": cp.task_hash,
        "worktree": cp.worktree,
        "phases": phases_dict,
        "overall_status": cp.overall_status,
        "generated_at": cp.generated_at,
    }


def _json_dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ── CLI Entry ────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Phase engine utility — resolve sequence or validate checkpoint")
    subp = parser.add_subparsers(dest="cmd", required=True)

    p_seq = subp.add_parser("sequence", help="Print phase sequence for risk level")
    p_seq.add_argument("--risk-level", required=True)
    p_seq.add_argument("--json", action="store_true")

    p_resume = subp.add_parser("resume-phase", help="Find next phase to resume")
    p_resume.add_argument("--checkpoint", required=True)
    p_resume.add_argument("--risk-level", required=True)
    p_resume.add_argument("--json", action="store_true")

    p_verify = subp.add_parser("verify-resume", help="Verify checkpoint integrity for --resume")
    p_verify.add_argument("--checkpoint", required=True)
    p_verify.add_argument("--repo-root", required=True)
    p_verify.add_argument("--plan-file", required=True)
    p_verify.add_argument("--task-file", required=True)
    p_verify.add_argument("--json", action="store_true")

    p_gate = subp.add_parser("gate", help="Validate phase gate")
    p_gate.add_argument("--phase", required=True)
    p_gate.add_argument("--risk-level", required=True)
    p_gate.add_argument("--checkpoint", required=True)
    p_gate.add_argument("--approval-available", action="store_true")
    p_gate.add_argument("--approval-operation", default="")
    p_gate.add_argument("--repo-root", default=".")
    p_gate.add_argument("--task-id", default="")
    p_gate.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "sequence":
        seq = define_phase_sequence(args.risk_level)
        if args.json:
            print(json.dumps({"risk_level": args.risk_level, "phases": seq}, ensure_ascii=False, indent=2))
        else:
            print(" ".join(seq))
        return 0

    if args.cmd == "resume-phase":
        cp = read_checkpoint(args.checkpoint)
        next_phase = find_resume_phase(cp, args.risk_level)
        if args.json:
            print(json.dumps({
                "next_phase": next_phase,
                "overall_status": cp.overall_status,
            }, ensure_ascii=False, indent=2))
        else:
            print(next_phase or "ALL_DONE")
        return 0

    if args.cmd == "verify-resume":
        cp = read_checkpoint(args.checkpoint)
        result = verify_resume_integrity(
            cp,
            repo_root=args.repo_root,
            plan_file=args.plan_file,
            task_file=args.task_file,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if args.cmd == "gate":
        cp = read_checkpoint(args.checkpoint)
        result = validate_phase_gate(
            phase=args.phase,
            risk_level=args.risk_level,
            checkpoint=cp,
            approval_available=args.approval_available,
            approval_operation=args.approval_operation,
            repo_root=args.repo_root,
            task_id=args.task_id,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
