"""Build exact-head review packages and derived final decisions without side effects."""

from __future__ import annotations

from pathlib import Path

from .briefs import intake_digest
from .contracts import (
    DocumentIntakeV1,
    FinalDecisionV1,
    HandoffReportV1,
    ReviewPackageV1,
    RoleBriefV1,
    validate_handoff_test_receipts,
)
from .digests import semantic_digest
from .errors import LeanMatrixError
from .review_git import (
    observe_current_head,
    observe_exact_diff,
    validate_stored_package_git,
    validate_worktree_clean,
)
from .workspace import intake_workspace


def build_review_package(
    repo_root: Path,
    intake: DocumentIntakeV1,
    *,
    implementer_brief: RoleBriefV1,
    implementer_handoff: HandoffReportV1,
    reviewer_brief: RoleBriefV1,
    specialist_evidence: tuple[tuple[RoleBriefV1, HandoffReportV1], ...] = (),
) -> ReviewPackageV1:
    """Build one package from trusted contracts and the current local exact HEAD."""
    if not isinstance(intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "intake must be trusted")
    head = observe_current_head(repo_root)
    if implementer_handoff.exact_head_sha != head:
        raise LeanMatrixError(
            "stale_package_head", "implementer handoff does not bind current local HEAD",
        )
    validate_worktree_clean(repo_root, intake_workspace(repo_root, intake))
    test_receipts = validate_handoff_test_receipts(
        repo_root, intake, implementer_handoff, exact_head_sha=head,
    )
    observation = observe_exact_diff(repo_root, intake.develop_sha, head)
    payload: dict[str, object] = {
        "schema_version": 1,
        "execution_plan_digest": intake.execution_plan_digest,
        "intake_digest": intake_digest(intake),
        "task_brief_digest": semantic_digest(implementer_brief.to_dict()),
        "exact_base_sha": intake.develop_sha,
        "exact_head_sha": head,
        "round": implementer_brief.round,
        "implementer_context_id": implementer_brief.context_id,
        "reviewer_context_id": reviewer_brief.context_id,
        "changed_paths": list(observation.changed_paths),
        "diff_digest": observation.diff_digest,
        "test_receipts": [receipt.to_dict() for receipt in test_receipts],
        "implementer_handoff_digest": semantic_digest(implementer_handoff.to_dict()),
        "specialist_evidence_digests": [
            semantic_digest(report.to_dict()) for _, report in specialist_evidence
        ],
    }
    return ReviewPackageV1.from_mapping(
        payload,
        repo_root=repo_root,
        document_intake=intake,
        implementer_brief=implementer_brief,
        implementer_handoff=implementer_handoff,
        reviewer_brief=reviewer_brief,
        specialist_evidence=specialist_evidence,
    )


def build_final_decision(
    review_package: ReviewPackageV1,
    *,
    repo_root: Path,
    document_intake: DocumentIntakeV1,
    spec_verdict: str,
    quality_verdict: str,
    findings: list[dict[str, object]],
    round_number: int,
    decision: str,
) -> FinalDecisionV1:
    """Build a decision whose allowed value is derived by the strict contract."""
    if not isinstance(review_package, ReviewPackageV1):
        raise LeanMatrixError(
            "invalid_review_package", "decision builder requires a trusted review package",
        )
    if not isinstance(document_intake, DocumentIntakeV1):
        raise LeanMatrixError(
            "invalid_document_intake", "decision builder requires the trusted document intake",
        )
    if (
        review_package.execution_plan_digest != document_intake.execution_plan_digest
        or review_package.intake_digest != intake_digest(document_intake)
        or review_package.exact_base_sha != document_intake.develop_sha
    ):
        raise LeanMatrixError(
            "decision_intake_mismatch",
            "decision package must bind the supplied trusted document intake",
        )
    if review_package.exact_head_sha != observe_current_head(repo_root):
        raise LeanMatrixError(
            "stale_decision_head", "decision package must bind the current local exact HEAD",
        )
    validate_stored_package_git(repo_root, review_package)
    validate_worktree_clean(repo_root, intake_workspace(repo_root, document_intake))
    payload: dict[str, object] = {
        "schema_version": 1,
        "review_package_digest": semantic_digest(review_package.to_dict()),
        "exact_head_sha": review_package.exact_head_sha,
        "implementer_context_id": review_package.implementer_context_id,
        "reviewer_context_id": review_package.reviewer_context_id,
        "round": round_number,
        "spec_verdict": spec_verdict,
        "quality_verdict": quality_verdict,
        "findings": findings,
        "decision": decision,
    }
    return FinalDecisionV1.from_mapping(payload, review_package=review_package)
