"""Plan-scoped ignored workspace for recoverable Lean Matrix runtime evidence."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from .adapters import command_for_action, execution_digest
from .contracts import ExecutionPlanV1, TransitionProposalV1, TransitionReceiptV1
from .digests import canonical_json, semantic_digest
from .errors import LeanMatrixError
from .receipts import EvidenceBundle, EvidenceRecord, artifact_name, read_bound_artifact
from .transitions import transition_id


def plan_digest(plan: ExecutionPlanV1) -> str:
    return semantic_digest(plan.to_dict())


def _reject_symlink(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise LeanMatrixError(
            "workspace_symlink_forbidden",
            "Lean Matrix evidence paths must not contain symbolic links",
        )


def workspace_path(repo_root: Path, plan: ExecutionPlanV1) -> Path:
    digest = plan_digest(plan).removeprefix("sha256:")
    repo = repo_root.resolve()
    ai_root = repo / ".ai"
    runtime_root = ai_root / "lean-matrix"
    workspace = runtime_root / digest
    for candidate in (ai_root, runtime_root, workspace):
        _reject_symlink(candidate)
    if workspace.parent != runtime_root:
        raise LeanMatrixError("invalid_workspace_path", "plan workspace escaped the ignored runtime root")
    return workspace


def _ensure_directory(path: Path, repo_root: Path) -> None:
    repo = repo_root.resolve()
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise LeanMatrixError("invalid_workspace_path", "runtime directory escaped repository") from exc
    current = repo
    for part in relative.parts:
        current = current / part
        _reject_symlink(current)
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _reject_symlink(current)
        if not current.is_dir():
            raise LeanMatrixError("workspace_path_invalid", "runtime evidence parent is not a directory")


def _atomic_json(path: Path, payload: dict[str, object], repo_root: Path) -> None:
    _ensure_directory(path.parent, repo_root)
    _reject_symlink(path)
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


def _exclusive_json(path: Path, payload: dict[str, object], repo_root: Path) -> None:
    _ensure_directory(path.parent, repo_root)
    _reject_symlink(path)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise LeanMatrixError(
            "transition_already_attempted",
            "transition already has an atomic attempt claim",
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_plan(path: Path, expected: ExecutionPlanV1) -> None:
    _reject_symlink(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanMatrixError("workspace_plan_invalid", "plan workspace contains an unreadable plan") from exc
    loaded = ExecutionPlanV1.from_mapping(raw)
    if plan_digest(loaded) != plan_digest(expected):
        raise LeanMatrixError("workspace_plan_mismatch", "plan workspace belongs to another execution plan")


def _artifact_paths(directory: Path) -> list[Path]:
    _reject_symlink(directory)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise LeanMatrixError("workspace_path_invalid", "runtime artifact path is not a directory")
    paths = sorted(directory.glob("*.json"))
    for path in paths:
        _reject_symlink(path)
    return paths


def _validate_proposal(plan: ExecutionPlanV1, proposal: TransitionProposalV1) -> None:
    expected_id = transition_id(plan, proposal.action, proposal.from_state_digest)
    if proposal.transition_id != expected_id:
        raise LeanMatrixError("proposal_transition_mismatch", "proposal ID is not derived from this plan and state")
    expected_commands = (command_for_action(plan, proposal.action),)
    if (
        proposal.commands != expected_commands
        or not proposal.requires_apply
        or proposal.side_effect_scope != "task-worktree"
        or proposal.human_gate is not None
    ):
        raise LeanMatrixError("proposal_command_mismatch", "proposal is not the canonical local command")


def _validate_receipt(
    repo_root: Path,
    plan: ExecutionPlanV1,
    proposal: TransitionProposalV1,
    receipt: TransitionReceiptV1,
) -> None:
    if receipt.plan_digest != plan_digest(plan):
        raise LeanMatrixError("receipt_plan_mismatch", "receipt belongs to another execution plan")
    if receipt.transition_id != proposal.transition_id:
        raise LeanMatrixError("receipt_transition_mismatch", "receipt transition does not match its proposal")
    if receipt.before_state_digest != proposal.from_state_digest:
        raise LeanMatrixError("receipt_state_mismatch", "receipt before-state does not match its proposal")
    expected_command_digest = execution_digest(plan, proposal.action, repo_root)
    if receipt.command_digests != (expected_command_digest,) or len(receipt.exit_codes) != 1:
        raise LeanMatrixError("receipt_command_mismatch", "receipt command is not derived from the frozen plan")
    successful_shape = (
        receipt.exit_codes == (0,)
        and receipt.after_state_digest != receipt.before_state_digest
    )
    if (receipt.result == "PASS") != successful_shape:
        raise LeanMatrixError("receipt_result_mismatch", "receipt result is inconsistent with exit and state facts")


def load_evidence(repo_root: Path, plan: ExecutionPlanV1) -> EvidenceBundle:
    """Load only this plan's fully rebound evidence; a missing workspace is read-only empty."""
    workspace = workspace_path(repo_root, plan)
    if not workspace.exists():
        return EvidenceBundle(())
    _reject_symlink(workspace)
    if not workspace.is_dir():
        raise LeanMatrixError("workspace_path_invalid", "plan workspace is not a directory")
    _read_plan(workspace / "plan.json", plan)
    proposal_paths = _artifact_paths(workspace / "proposals")
    receipt_paths = _artifact_paths(workspace / "receipts")
    attempt_paths = _artifact_paths(workspace / "attempts")
    proposals: dict[str, TransitionProposalV1] = {}
    receipts: dict[str, TransitionReceiptV1] = {}
    attempts: dict[str, dict[str, object]] = {}
    for path in attempt_paths:
        raw = read_bound_artifact(path)
        identifier = raw.get("transition_id")
        if (
            not isinstance(identifier, str)
            or path.name.split(".", 1)[0] != identifier
            or identifier in attempts
        ):
            raise LeanMatrixError("workspace_artifact_mismatch", "attempt identity does not match filename")
        attempts[identifier] = raw
    for path in proposal_paths:
        proposal = TransitionProposalV1.from_mapping(read_bound_artifact(path))
        if path.name.split(".", 1)[0] != proposal.transition_id or proposal.transition_id in proposals:
            raise LeanMatrixError("workspace_artifact_mismatch", "proposal identity does not match its filename")
        _validate_proposal(plan, proposal)
        proposals[proposal.transition_id] = proposal
    for path in receipt_paths:
        receipt = TransitionReceiptV1.from_mapping(read_bound_artifact(path))
        if path.name.split(".", 1)[0] != receipt.transition_id or receipt.transition_id in receipts:
            raise LeanMatrixError("workspace_artifact_mismatch", "receipt identity does not match its filename")
        receipts[receipt.transition_id] = receipt
    if attempts.keys() != proposals.keys() or proposals.keys() != receipts.keys():
        raise LeanMatrixError("workspace_evidence_incomplete", "each atomic attempt must have one proposal and receipt")
    records: list[EvidenceRecord] = []
    for identifier in sorted(proposals):
        proposal = proposals[identifier]
        receipt = receipts[identifier]
        expected_attempt: dict[str, object] = {
            "transition_id": proposal.transition_id,
            "plan_digest": plan_digest(plan),
            "action": proposal.action,
            "from_state_digest": proposal.from_state_digest,
            "command_digest": execution_digest(plan, proposal.action, repo_root),
        }
        if attempts[identifier] != expected_attempt:
            raise LeanMatrixError("attempt_contract_mismatch", "attempt claim is not derived from its plan")
        _validate_receipt(repo_root, plan, proposal, receipt)
        records.append(EvidenceRecord(proposal, receipt))
    return EvidenceBundle(tuple(records))


def claim_transition(repo_root: Path, plan: ExecutionPlanV1, proposal: TransitionProposalV1) -> None:
    """Claim one transition before any external action; crashes intentionally leave a blocker."""
    _validate_proposal(plan, proposal)
    workspace = workspace_path(repo_root, plan)
    plan_path = workspace / "plan.json"
    if workspace.exists():
        _reject_symlink(workspace)
        if plan_path.exists():
            _read_plan(plan_path, plan)
    attempt_payload: dict[str, object] = {
        "transition_id": proposal.transition_id,
        "plan_digest": plan_digest(plan),
        "action": proposal.action,
        "from_state_digest": proposal.from_state_digest,
        "command_digest": execution_digest(plan, proposal.action, repo_root),
    }
    attempt_path = workspace / "attempts" / artifact_name(proposal.transition_id, attempt_payload)
    _exclusive_json(attempt_path, attempt_payload, repo_root)
    _atomic_json(plan_path, plan.to_dict(), repo_root)
    proposal_path = workspace / "proposals" / artifact_name(proposal.transition_id, proposal.to_dict())
    _atomic_json(proposal_path, proposal.to_dict(), repo_root)


def record_transition(
    repo_root: Path,
    plan: ExecutionPlanV1,
    proposal: TransitionProposalV1,
    receipt: TransitionReceiptV1,
    *,
    error_type: str | None,
) -> None:
    """Finalize one pre-claimed transition without storing raw command output."""
    _validate_proposal(plan, proposal)
    _validate_receipt(repo_root, plan, proposal, receipt)
    workspace = workspace_path(repo_root, plan)
    attempt_dir = workspace / "attempts"
    claimed = [
        path for path in _artifact_paths(attempt_dir)
        if path.name.split(".", 1)[0] == proposal.transition_id
    ]
    if not claimed:
        claim_transition(repo_root, plan, proposal)
    elif len(claimed) != 1:
        raise LeanMatrixError("workspace_artifact_mismatch", "transition has multiple attempt claims")
    receipt_path = workspace / "receipts" / artifact_name(receipt.transition_id, receipt.to_dict())
    log_payload: dict[str, object] = {
        "transition_id": proposal.transition_id,
        "action": proposal.action,
        "result": receipt.result,
        "exit_codes": list(receipt.exit_codes),
        "error_type": error_type,
    }
    log_path = workspace / "logs" / artifact_name(proposal.transition_id, log_payload)
    _atomic_json(receipt_path, receipt.to_dict(), repo_root)
    _atomic_json(log_path, log_payload, repo_root)
