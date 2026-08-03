"""Plan-scoped ignored workspace for recoverable Lean Matrix runtime evidence."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from .adapters import command_for_action, execution_digest
from .contracts import (
    DocumentIntakeV1,
    ExecutionPlanV1,
    RoleBriefV1,
    TransitionProposalV1,
    TransitionReceiptV1,
)
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


def intake_workspace(repo_root: Path, intake: DocumentIntakeV1) -> Path:
    """Derive the exact ignored workspace for one trusted document intake."""
    from .briefs import intake_digest

    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "intake must be a trusted DocumentIntakeV1")
    repo = repo_root.resolve()
    workspace = (
        repo
        / ".ai"
        / "lean-matrix"
        / intake.execution_plan_digest.removeprefix("sha256:")
        / intake_digest(intake).removeprefix("sha256:")
    )
    current = repo
    for part in workspace.relative_to(repo).parts:
        current = current / part
        _reject_symlink(current)
    if workspace.parents[1].name != "lean-matrix" or workspace.parents[2].name != ".ai":
        raise LeanMatrixError("invalid_workspace_path", "intake workspace escaped the ignored runtime root")
    return workspace


def _reject_path_symlinks(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        _reject_symlink(current)


def _resolved_output(path: Path) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if ".." in absolute.parts:
        raise LeanMatrixError("invalid_workspace_path", "workspace output must not contain path traversal")
    _reject_path_symlinks(absolute)
    return absolute.resolve()


def _write_fsynced_text(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_pair_staging(staging: Path) -> None:
    if not staging.exists():
        return
    for child in staging.iterdir():
        child.unlink(missing_ok=True)
    staging.rmdir()


def _publish_brief_pair(
    artifact_dir: Path,
    *,
    json_path: Path,
    json_content: str,
    markdown_path: Path,
    markdown_content: str,
    repo_root: Path,
) -> None:
    _ensure_directory(artifact_dir, repo_root)
    staging = Path(tempfile.mkdtemp(prefix=".brief-pair-", dir=artifact_dir))
    staged_json = staging / json_path.name
    staged_markdown = staging / markdown_path.name
    backups = {
        json_path: staging / "previous-role-brief.json",
        markdown_path: staging / "previous-role-brief.md",
    }
    published: list[Path] = []
    try:
        _write_fsynced_text(staged_json, json_content)
        _write_fsynced_text(staged_markdown, markdown_content)
        for target, backup in backups.items():
            if target.exists():
                os.link(target, backup)
        _fsync_directory(staging)
        os.replace(staged_json, json_path)
        published.append(json_path)
        os.replace(staged_markdown, markdown_path)
        published.append(markdown_path)
        _fsync_directory(artifact_dir)
    except OSError as exc:
        rollback_error: OSError | None = None
        for target in reversed(published):
            try:
                backup = backups[target]
                if backup.exists():
                    os.replace(backup, target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as rollback_exc:
                rollback_error = rollback_exc
        try:
            _fsync_directory(artifact_dir)
        except OSError as rollback_exc:
            rollback_error = rollback_exc
        if rollback_error is not None:
            raise LeanMatrixError(
                "brief_rollback_failed",
                "brief pair publication failed and the previous pair could not be restored",
            ) from rollback_error
        raise LeanMatrixError(
            "brief_write_failed",
            "brief pair publication failed without exposing a partial new pair",
        ) from exc
    finally:
        try:
            _remove_pair_staging(staging)
        except OSError:
            pass


def write_role_brief_files(
    repo_root: Path,
    intake: DocumentIntakeV1,
    brief: RoleBriefV1,
    output: Path,
    *,
    round_zero_brief: RoleBriefV1 | None = None,
) -> dict[str, object]:
    """Atomically write only one deterministic JSON/Markdown brief pair."""
    from .briefs import intake_digest, render_role_brief_markdown

    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "intake must be a trusted DocumentIntakeV1")
    validated_brief = RoleBriefV1.from_mapping(
        brief.to_dict(),
        document_intake=intake,
        round_zero_brief=round_zero_brief,
    )
    workspace = intake_workspace(repo_root, intake)
    if _resolved_output(output) != workspace:
        raise LeanMatrixError("brief_output_mismatch", "--output must equal the derived intake workspace")
    if (
        validated_brief.intake_digest != intake_digest(intake)
        or validated_brief.execution_plan_digest != intake.execution_plan_digest
        or validated_brief.trusted_allowed_paths != intake.execution_plan.scope.allowed_paths
        or validated_brief.trusted_forbidden_paths != intake.execution_plan.scope.forbidden_paths
        or validated_brief.acceptance_criteria != intake.execution_plan.validation.required_checks
    ):
        raise LeanMatrixError("brief_intake_mismatch", "brief belongs to another document intake")
    repo = repo_root.resolve()
    _require_ignored_noncanonical_workspace(repo, workspace)
    if validated_brief.role == "implementer" and validated_brief.round == 0:
        _preflight_round_zero_implementer_anchor(repo, intake, validated_brief)
    if validated_brief.role == "specialist":
        assert validated_brief.specialist_domain is not None
        artifact_dir = (
            workspace
            / "briefs"
            / "specialists"
            / validated_brief.specialist_domain
            / validated_brief.context_id
            / f"round-{validated_brief.round}"
        )
    else:
        artifact_dir = (
            workspace
            / "briefs"
            / validated_brief.role
            / validated_brief.context_id
            / f"round-{validated_brief.round}"
        )
    report = repo / validated_brief.report_path
    try:
        report.relative_to(workspace)
    except ValueError as exc:
        raise LeanMatrixError(
            "brief_report_path_mismatch", "brief report path escaped its intake workspace",
        ) from exc
    _reject_path_symlinks(report)
    json_path = artifact_dir / "role-brief.json"
    markdown_path = artifact_dir / "role-brief.md"
    for path in (json_path, markdown_path):
        _reject_path_symlinks(path)
        if path.exists() and not path.is_file():
            raise LeanMatrixError("brief_write_failed", "brief artifact target is not a regular file")
    _publish_brief_pair(
        artifact_dir,
        json_path=json_path,
        json_content=canonical_json(validated_brief.to_dict()) + "\n",
        markdown_path=markdown_path,
        markdown_content=render_role_brief_markdown(validated_brief),
        repo_root=repo,
    )
    if validated_brief.role == "implementer" and validated_brief.round == 0:
        _freeze_round_zero_implementer_anchor(repo, intake, validated_brief)
    return {
        "schema_version": 1,
        "status": "ok",
        "json_path": json_path.relative_to(repo).as_posix(),
        "markdown_path": markdown_path.relative_to(repo).as_posix(),
        "brief_digest": semantic_digest(validated_brief.to_dict()),
    }


def _round_zero_implementer_anchor(repo_root: Path, intake: DocumentIntakeV1) -> Path:
    return intake_workspace(repo_root, intake) / "identity" / "implementer-round-zero.json"


def load_round_zero_implementer_brief(
    repo_root: Path,
    intake: DocumentIntakeV1,
) -> RoleBriefV1:
    """Load the one fixed identity anchor; never glob or trust a caller-selected report path."""
    anchor = _round_zero_implementer_anchor(repo_root, intake)
    _reject_path_symlinks(anchor)
    try:
        payload = json.loads(anchor.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeanMatrixError(
            "round_zero_brief_required", "the frozen round-zero implementer brief is unavailable",
        ) from exc
    brief = RoleBriefV1.from_mapping(payload, document_intake=intake)
    if brief.role != "implementer" or brief.round != 0:
        raise LeanMatrixError(
            "invalid_round_zero_brief", "identity anchor is not a round-zero implementer brief",
        )
    return brief


def _preflight_round_zero_implementer_anchor(
    repo_root: Path,
    intake: DocumentIntakeV1,
    brief: RoleBriefV1,
) -> None:
    anchor = _round_zero_implementer_anchor(repo_root, intake)
    if not anchor.exists():
        return
    frozen = load_round_zero_implementer_brief(repo_root, intake)
    if semantic_digest(frozen.to_dict()) != semantic_digest(brief.to_dict()):
        raise LeanMatrixError(
            "implementer_identity_frozen", "round-zero implementer identity is already frozen",
        )


def _freeze_round_zero_implementer_anchor(
    repo_root: Path,
    intake: DocumentIntakeV1,
    brief: RoleBriefV1,
) -> None:
    anchor = _round_zero_implementer_anchor(repo_root, intake)
    _ensure_directory(anchor.parent, repo_root)
    try:
        _write_fsynced_text(anchor, canonical_json(brief.to_dict()) + "\n")
        _fsync_directory(anchor.parent)
    except FileExistsError:
        _preflight_round_zero_implementer_anchor(repo_root, intake, brief)
    except OSError as exc:
        raise LeanMatrixError(
            "brief_write_failed", "round-zero implementer identity could not be frozen",
        ) from exc


def _require_ignored_noncanonical_workspace(repo_root: Path, workspace: Path) -> None:
    """Reject tracked workspace content and repositories that do not ignore it."""
    from .review_git import _run_git

    relative = workspace.relative_to(repo_root).as_posix()
    try:
        ignored = _run_git(
            repo_root,
            ("check-ignore", "--", f"{relative}/.lean-matrix-probe"),
        )
    except LeanMatrixError as exc:
        raise LeanMatrixError(
            "workspace_not_ignored", "the exact document-intake workspace must be ignored by Git",
        ) from exc
    if not ignored.strip():
        raise LeanMatrixError(
            "workspace_not_ignored", "the exact document-intake workspace must be ignored by Git",
        )
    tracked = _run_git(repo_root, ("ls-files", "--", relative))
    if tracked.strip():
        raise LeanMatrixError(
            "canonical_workspace_conflict", "tracked canonical files exist inside the evidence workspace",
        )


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
