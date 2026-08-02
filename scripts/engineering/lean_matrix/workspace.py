"""Plan-scoped ignored workspace for recoverable Lean Matrix runtime evidence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .contracts import ExecutionPlanV1, TransitionProposalV1, TransitionReceiptV1
from .digests import canonical_json, semantic_digest
from .errors import LeanMatrixError
from .receipts import EvidenceBundle, EvidenceRecord, artifact_name, read_bound_artifact


def plan_digest(plan: ExecutionPlanV1) -> str:
    return semantic_digest(plan.to_dict())


def workspace_path(repo_root: Path, plan: ExecutionPlanV1) -> Path:
    digest = plan_digest(plan).removeprefix("sha256:")
    root = (repo_root.resolve() / ".ai" / "lean-matrix").resolve()
    workspace = (root / digest).resolve()
    if workspace.parent != root:
        raise LeanMatrixError("invalid_workspace_path", "plan workspace escaped the ignored runtime root")
    return workspace


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_plan(path: Path, expected: ExecutionPlanV1) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanMatrixError("workspace_plan_invalid", "plan workspace contains an unreadable plan") from exc
    loaded = ExecutionPlanV1.from_mapping(raw)
    if plan_digest(loaded) != plan_digest(expected):
        raise LeanMatrixError("workspace_plan_mismatch", "plan workspace belongs to another execution plan")


def load_evidence(repo_root: Path, plan: ExecutionPlanV1) -> EvidenceBundle:
    """Load only this plan's evidence; a missing workspace is an empty read-only result."""
    workspace = workspace_path(repo_root, plan)
    if not workspace.exists():
        return EvidenceBundle(())
    if not workspace.is_dir():
        raise LeanMatrixError("workspace_path_invalid", "plan workspace is not a directory")
    _read_plan(workspace / "plan.json", plan)
    proposal_dir = workspace / "proposals"
    receipt_dir = workspace / "receipts"
    proposal_paths = sorted(proposal_dir.glob("*.json")) if proposal_dir.is_dir() else []
    receipt_paths = sorted(receipt_dir.glob("*.json")) if receipt_dir.is_dir() else []
    proposals: dict[str, TransitionProposalV1] = {}
    receipts: dict[str, TransitionReceiptV1] = {}
    for path in proposal_paths:
        proposal = TransitionProposalV1.from_mapping(read_bound_artifact(path))
        if path.name.split(".", 1)[0] != proposal.transition_id or proposal.transition_id in proposals:
            raise LeanMatrixError("workspace_artifact_mismatch", "proposal identity does not match its filename")
        proposals[proposal.transition_id] = proposal
    for path in receipt_paths:
        receipt = TransitionReceiptV1.from_mapping(read_bound_artifact(path))
        if path.name.split(".", 1)[0] != receipt.transition_id or receipt.transition_id in receipts:
            raise LeanMatrixError("workspace_artifact_mismatch", "receipt identity does not match its filename")
        if receipt.plan_digest != plan_digest(plan):
            raise LeanMatrixError("receipt_plan_mismatch", "receipt belongs to another execution plan")
        receipts[receipt.transition_id] = receipt
    if proposals.keys() != receipts.keys():
        raise LeanMatrixError("workspace_evidence_incomplete", "each proposal must have exactly one receipt")
    records: list[EvidenceRecord] = []
    for transition_id in sorted(proposals):
        proposal = proposals[transition_id]
        receipt = receipts[transition_id]
        if receipt.before_state_digest != proposal.from_state_digest:
            raise LeanMatrixError("receipt_state_mismatch", "receipt before-state does not match its proposal")
        records.append(EvidenceRecord(proposal, receipt))
    return EvidenceBundle(tuple(records))


def record_transition(
    repo_root: Path,
    plan: ExecutionPlanV1,
    proposal: TransitionProposalV1,
    receipt: TransitionReceiptV1,
    *,
    error_type: str | None,
) -> None:
    """Atomically append one proposal/receipt pair without storing raw command output."""
    expected_plan_digest = plan_digest(plan)
    if receipt.plan_digest != expected_plan_digest:
        raise LeanMatrixError("receipt_plan_mismatch", "receipt does not match the current execution plan")
    if receipt.transition_id != proposal.transition_id:
        raise LeanMatrixError("receipt_transition_mismatch", "receipt transition does not match its proposal")
    if receipt.before_state_digest != proposal.from_state_digest:
        raise LeanMatrixError("receipt_state_mismatch", "receipt before-state does not match its proposal")
    workspace = workspace_path(repo_root, plan)
    plan_path = workspace / "plan.json"
    if workspace.exists():
        _read_plan(plan_path, plan)
        existing = load_evidence(repo_root, plan)
        if proposal.action in existing.attempted_actions:
            raise LeanMatrixError("transition_already_attempted", "transition action already has a receipt")
    _atomic_json(plan_path, plan.to_dict())
    proposal_path = workspace / "proposals" / artifact_name(proposal.transition_id, proposal.to_dict())
    receipt_path = workspace / "receipts" / artifact_name(receipt.transition_id, receipt.to_dict())
    log_payload: dict[str, object] = {
        "transition_id": proposal.transition_id,
        "action": proposal.action,
        "result": receipt.result,
        "exit_codes": list(receipt.exit_codes),
        "error_type": error_type,
    }
    log_path = workspace / "logs" / artifact_name(proposal.transition_id, log_payload)
    _atomic_json(proposal_path, proposal.to_dict())
    _atomic_json(receipt_path, receipt.to_dict())
    _atomic_json(log_path, log_payload)
