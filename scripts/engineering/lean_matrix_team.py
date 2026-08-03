#!/usr/bin/env python3
"""Run validated Lean Matrix contract commands from JSON input."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import ClassVar

# The CLI's contract is stdout/stderr only. Prevent Python's import machinery
# from creating an ignored __pycache__ beside repository modules.
sys.dont_write_bytecode = True

from lean_matrix.charter import SCHEMA_VERSION, render_charter  # noqa: E402
from lean_matrix.adapters import execute_action  # noqa: E402
from lean_matrix.briefs import build_role_brief  # noqa: E402
from lean_matrix.contracts import (  # noqa: E402
    DocumentIntakeV1,
    ExecutionPlanV1,
    HandoffReportV1,
    ReviewPackageV1,
    RoleBriefV1,
    TaskCharterV1,
    TransitionReceiptV1,
    required_checks_for_owner,
)
from lean_matrix.errors import LeanMatrixError  # noqa: E402
from lean_matrix.digests import semantic_digest  # noqa: E402
from lean_matrix.git_readonly import BASE_REF, resolve_base_sha  # noqa: E402
from lean_matrix.review_git import validate_worktree_clean  # noqa: E402
from lean_matrix.observing import observe_execution_plan  # noqa: E402
from lean_matrix.planning import build_execution_plan  # noqa: E402
from lean_matrix.rendering import render_execution_plan_markdown  # noqa: E402
from lean_matrix.transitions import propose_next_transition  # noqa: E402
from lean_matrix.scope import scope_allows, validate_scope_patterns  # noqa: E402
from lean_matrix.workspace import (  # noqa: E402
    claim_transition,
    load_round_zero_implementer_brief,
    load_evidence,
    intake_workspace,
    plan_digest,
    record_transition,
    write_role_brief_files,
)
import task_workflow  # noqa: E402
from task_workflow import WorkflowError, classify_paths  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]

GITHUB_REPOSITORY_ID = 1276918660
GITHUB_REPOSITORY_FULL_NAME = "firehell/guiyi-quant-workstation"
GITHUB_FACT_TTL = timedelta(minutes=5)
DEVELOP_GATE_DECISIONS = frozenset({
    "ALLOW_DEVELOP_MERGE",
    "WAIT_CI",
    "WAIT_REVIEW",
    "BLOCKED_PR_IDENTITY",
    "BLOCKED_HEAD_DRIFT",
    "BLOCKED_BASE_DRIFT",
    "BLOCKED_SCOPE_DRIFT",
    "BLOCKED_CI",
    "BLOCKED_REVIEW",
    "BLOCKED_THREADS",
    "BLOCKED_MERGEABILITY",
    "MANUAL_GATE_REQUIRED",
    "BLOCKED",
})
GITHUB_CHECK_STATES = frozenset({
    "PENDING", "SUCCESS", "FAILURE", "CANCELLED", "SKIPPED", "TIMED_OUT", "STALE", "MISSING",
})
GITHUB_REVIEW_STATES = frozenset({"MISSING", "PENDING", "APPROVED", "CHANGES_REQUESTED"})
GITHUB_PR_STATES = frozenset({"OPEN", "CLOSED", "MERGED"})
GITHUB_MERGEABILITY_STATES = frozenset({"MERGEABLE", "CONFLICTING", "UNKNOWN"})
DEVELOP_GATE_STAGES = frozenset({"pre_merge", "merge_readback", "cleanup"})
_ALL_DEVELOP_GATE_STAGES = DEVELOP_GATE_STAGES
_PRE_MERGE_STAGE = frozenset({"pre_merge"})
_MERGE_READBACK_STAGE = frozenset({"merge_readback"})
_CLEANUP_STAGE = frozenset({"cleanup"})
DEVELOP_GATE_REASON_RULES: dict[str, tuple[str, frozenset[str]]] = {
    "DEVELOP_MERGE_ALLOWED": ("ALLOW_DEVELOP_MERGE", _PRE_MERGE_STAGE),
    "READY_TRANSITION_REQUIRED": ("ALLOW_DEVELOP_MERGE", _PRE_MERGE_STAGE),
    "ALREADY_MERGED": ("ALLOW_DEVELOP_MERGE", _PRE_MERGE_STAGE),
    "MERGE_READBACK_CONFIRMED": ("ALLOW_DEVELOP_MERGE", _MERGE_READBACK_STAGE),
    "CLEANUP_ALLOWED": ("ALLOW_DEVELOP_MERGE", _CLEANUP_STAGE),
    "CI_PENDING": ("WAIT_CI", _PRE_MERGE_STAGE),
    "REVIEW_PENDING": ("WAIT_REVIEW", _PRE_MERGE_STAGE),
    "REPOSITORY_ID_MISMATCH": ("BLOCKED_PR_IDENTITY", _ALL_DEVELOP_GATE_STAGES),
    "REPOSITORY_NAME_MISMATCH": ("BLOCKED_PR_IDENTITY", _ALL_DEVELOP_GATE_STAGES),
    "PR_BASE_REF_MISMATCH": ("BLOCKED_PR_IDENTITY", _ALL_DEVELOP_GATE_STAGES),
    "PR_HEAD_REF_MISMATCH": ("BLOCKED_PR_IDENTITY", _ALL_DEVELOP_GATE_STAGES),
    "PR_CLOSED_UNMERGED": ("BLOCKED_PR_IDENTITY", _ALL_DEVELOP_GATE_STAGES),
    "TASK_HEAD_DRIFT": ("BLOCKED_HEAD_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "CI_HEAD_DRIFT": ("BLOCKED_HEAD_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "REVIEW_HEAD_DRIFT": ("BLOCKED_HEAD_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "PR_BASE_SHA_DRIFT": ("BLOCKED_BASE_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "REVIEW_BASE_DRIFT": ("BLOCKED_BASE_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "CURRENT_DEVELOP_DRIFT": ("BLOCKED_BASE_DRIFT", frozenset({"pre_merge", "merge_readback"})),
    "CHANGED_PATH_FORBIDDEN": ("BLOCKED_SCOPE_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "CHANGED_PATH_OUTSIDE_SCOPE": ("BLOCKED_SCOPE_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "WORKFLOW_CLASSIFICATION_BLOCKED": ("BLOCKED_SCOPE_DRIFT", _ALL_DEVELOP_GATE_STAGES),
    "CI_CHECK_MISSING": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_FAILURE": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_CANCELLED": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_SKIPPED": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_TIMED_OUT": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_STALE": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "CI_MISSING": ("BLOCKED_CI", _PRE_MERGE_STAGE),
    "INDEPENDENT_REVIEW_REQUIRED": ("BLOCKED_REVIEW", _PRE_MERGE_STAGE),
    "REVIEW_CHANGES_REQUESTED": ("BLOCKED_REVIEW", _PRE_MERGE_STAGE),
    "CRITICAL_FINDINGS": ("BLOCKED_REVIEW", _PRE_MERGE_STAGE),
    "IMPORTANT_FINDINGS": ("BLOCKED_REVIEW", _PRE_MERGE_STAGE),
    "BLOCKING_THREADS_OPEN": ("BLOCKED_THREADS", _PRE_MERGE_STAGE),
    "MERGEABILITY_CONFLICTING": ("BLOCKED_MERGEABILITY", _PRE_MERGE_STAGE),
    "MERGEABILITY_UNKNOWN": ("BLOCKED_MERGEABILITY", _PRE_MERGE_STAGE),
    "EXTERNAL_GATE_REQUIRED": ("MANUAL_GATE_REQUIRED", _ALL_DEVELOP_GATE_STAGES),
    "SENSITIVE_OPERATION_REQUESTED": ("MANUAL_GATE_REQUIRED", _ALL_DEVELOP_GATE_STAGES),
    "WORKFLOW_MANUAL_GATE_REQUIRED": ("MANUAL_GATE_REQUIRED", _ALL_DEVELOP_GATE_STAGES),
    "FACTS_DIGEST_MISMATCH": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "FACTS_MALFORMED": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "FACTS_EXPIRED": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "FACTS_FROM_FUTURE": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "PLAN_DIGEST_MISMATCH": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "CHARTER_DIGEST_MISMATCH": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "PLAN_CHARTER_BINDING_MISMATCH": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "UNKNOWN_EXTERNAL_GATE": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "UNKNOWN_REQUESTED_OPERATION": ("BLOCKED", _ALL_DEVELOP_GATE_STAGES),
    "MERGE_RESULT_UNCONFIRMED": ("BLOCKED", _MERGE_READBACK_STAGE),
    "MERGE_NOT_CONFIRMED": ("BLOCKED", _CLEANUP_STAGE),
    "WORKTREE_NOT_CLEAN": ("BLOCKED", _CLEANUP_STAGE),
    "LOCAL_DEVELOP_MISSING_TASK_HEAD": ("BLOCKED", _CLEANUP_STAGE),
    "REMOTE_DEVELOP_MISSING_TASK_HEAD": ("BLOCKED", _CLEANUP_STAGE),
}
_GATE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GATE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GATE_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MALFORMED_FACTS_DIGEST = semantic_digest({
    "schema_version": 1,
    "kind": "malformed-github-gate-facts",
})
_SAFE_STAGE_OPERATIONS = {
    "pre_merge": frozenset({"develop_merge"}),
    "merge_readback": frozenset({"merge_readback"}),
    "cleanup": frozenset({"cleanup"}),
}
_SENSITIVE_OPERATIONS = frozenset({
    "main", "tag", "release", "runtime", "live", "notification", "data_write", "db_write",
    "delete", "github_rules",
})
DEVELOP_GATE_CHANGE_CATEGORIES = task_workflow.DEVELOP_CHANGE_CATEGORIES


def _gate_mapping(raw: object, name: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise LeanMatrixError("invalid_contract", f"{name} must be a JSON object")
    return raw


def _gate_keys(data: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    if set(data) != expected:
        raise LeanMatrixError("invalid_contract_keys", f"{name} keys must exactly match schema version 1")


def _gate_schema_version(value: object, name: str) -> int:
    if type(value) is not int or value != 1:
        raise LeanMatrixError("invalid_schema_version", f"{name} schema_version must equal 1")
    return 1


def _gate_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeanMatrixError("invalid_string", f"{field} must be a non-blank string")
    if value != value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise LeanMatrixError("invalid_string", f"{field} must be trimmed and contain no control characters")
    return value


def _gate_optional_string(value: object, field: str) -> str | None:
    return None if value is None else _gate_string(value, field)


def _gate_sha(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    sha = _gate_string(value, field)
    if not _GATE_SHA_RE.fullmatch(sha):
        raise LeanMatrixError("invalid_sha", f"{field} must be 40 lowercase hexadecimal characters")
    return sha


def _gate_digest(value: object, field: str) -> str:
    digest = _gate_string(value, field)
    if not _GATE_DIGEST_RE.fullmatch(digest):
        raise LeanMatrixError("invalid_digest", f"{field} must use sha256:<64 lowercase hexadecimal>")
    return digest


def _gate_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise LeanMatrixError("invalid_boolean", f"{field} must be a JSON boolean")
    return value


def _gate_positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise LeanMatrixError("invalid_positive_integer", f"{field} must be a positive integer")
    return value


def _gate_nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise LeanMatrixError("invalid_nonnegative_integer", f"{field} must be a non-negative integer")
    return value


def _gate_status(value: object, field: str, allowed: frozenset[str]) -> str:
    status = _gate_string(value, field)
    if status not in allowed:
        raise LeanMatrixError("invalid_status", f"{field} has invalid status: {status}")
    return status


def _gate_strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise LeanMatrixError("invalid_string_list", f"{field} must be a JSON list of strings")
    result = tuple(_gate_string(item, f"{field} item") for item in value)
    if len(result) != len(set(result)):
        raise LeanMatrixError("duplicate_values", f"{field} must not contain duplicates")
    return result


def _gate_paths(value: object, field: str) -> tuple[str, ...]:
    paths = _gate_strings(value, field)
    if not paths:
        raise LeanMatrixError("empty_changed_paths", f"{field} must not be empty")
    if tuple(sorted(paths)) != paths:
        raise LeanMatrixError("unsorted_changed_paths", f"{field} must be sorted")
    for path in paths:
        pure = PurePosixPath(path)
        if path.startswith("/") or "\\" in path or ".." in pure.parts or path in {"", "."}:
            raise LeanMatrixError("invalid_repository_path", f"{field} contains an invalid repository path")
    return paths


def _gate_rfc3339(value: object, field: str) -> tuple[str, datetime]:
    timestamp = _gate_string(value, field)
    if not _GATE_RFC3339_RE.fullmatch(timestamp):
        raise LeanMatrixError("invalid_timestamp", f"{field} must be RFC3339 UTC with whole seconds")
    try:
        naive = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        parsed = datetime(
            naive.year, naive.month, naive.day, naive.hour, naive.minute, naive.second, tzinfo=UTC,
        )
    except ValueError as exc:
        raise LeanMatrixError("invalid_timestamp", f"{field} is not a valid UTC timestamp") from exc
    return timestamp, parsed


def _gate_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class GitHubCheckV1:
    schema_version: int
    name: str
    status: str
    head_sha: str

    KEYS: ClassVar[frozenset[str]] = frozenset({"schema_version", "name", "status", "head_sha"})

    @classmethod
    def from_mapping(cls, raw: object) -> GitHubCheckV1:
        data = _gate_mapping(raw, "GitHub check")
        _gate_keys(data, cls.KEYS, "GitHub check")
        head_sha = _gate_sha(data["head_sha"], "check.head_sha")
        assert head_sha is not None
        return cls(
            schema_version=_gate_schema_version(data["schema_version"], "GitHub check"),
            name=_gate_string(data["name"], "check.name"),
            status=_gate_status(data["status"], "check.status", GITHUB_CHECK_STATES),
            head_sha=head_sha,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "status": self.status,
            "head_sha": self.head_sha,
        }


@dataclass(frozen=True, slots=True)
class GitHubReviewEvidenceV1:
    schema_version: int
    status: str
    reviewer_context_id: str | None
    implementer_context_id: str
    head_sha: str | None
    base_sha: str | None
    critical_findings: int
    important_findings: int
    minor_findings: int
    blocking_threads: int

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "status", "reviewer_context_id", "implementer_context_id", "head_sha",
        "base_sha", "critical_findings", "important_findings", "minor_findings", "blocking_threads",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> GitHubReviewEvidenceV1:
        data = _gate_mapping(raw, "GitHub review evidence")
        _gate_keys(data, cls.KEYS, "GitHub review evidence")
        status = _gate_status(data["status"], "review.status", GITHUB_REVIEW_STATES)
        reviewer = _gate_optional_string(data["reviewer_context_id"], "review.reviewer_context_id")
        head_sha = _gate_sha(data["head_sha"], "review.head_sha", allow_none=True)
        base_sha = _gate_sha(data["base_sha"], "review.base_sha", allow_none=True)
        if status in {"APPROVED", "CHANGES_REQUESTED"} and (
            reviewer is None or head_sha is None or base_sha is None
        ):
            raise LeanMatrixError(
                "incomplete_review_evidence",
                "completed review evidence requires reviewer context and exact head/base SHAs",
            )
        return cls(
            schema_version=_gate_schema_version(data["schema_version"], "GitHub review evidence"),
            status=status,
            reviewer_context_id=reviewer,
            implementer_context_id=_gate_string(
                data["implementer_context_id"], "review.implementer_context_id",
            ),
            head_sha=head_sha,
            base_sha=base_sha,
            critical_findings=_gate_nonnegative_int(
                data["critical_findings"], "review.critical_findings",
            ),
            important_findings=_gate_nonnegative_int(
                data["important_findings"], "review.important_findings",
            ),
            minor_findings=_gate_nonnegative_int(data["minor_findings"], "review.minor_findings"),
            blocking_threads=_gate_nonnegative_int(data["blocking_threads"], "review.blocking_threads"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reviewer_context_id": self.reviewer_context_id,
            "implementer_context_id": self.implementer_context_id,
            "head_sha": self.head_sha,
            "base_sha": self.base_sha,
            "critical_findings": self.critical_findings,
            "important_findings": self.important_findings,
            "minor_findings": self.minor_findings,
            "blocking_threads": self.blocking_threads,
        }


@dataclass(frozen=True, slots=True)
class GitHubGateFactsV1:
    schema_version: int
    stage: str
    plan_digest: str
    charter_digest: str
    charter: TaskCharterV1
    repository_id: int
    repository_full_name: str
    pr_number: int
    pr_state: str
    pr_merged: bool
    pr_draft: bool
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    current_task_head_sha: str
    current_develop_sha: str
    changed_paths: tuple[str, ...]
    checks: tuple[GitHubCheckV1, ...]
    review: GitHubReviewEvidenceV1
    pending_external_gates: tuple[str, ...]
    requested_operations: tuple[str, ...]
    change_categories: tuple[str, ...]
    mergeability: str
    observed_at: str
    expires_at: str
    facts_digest: str
    readback_merge_sha: str | None
    readback_develop_contains_task_head: bool
    cleanup_worktree_clean: bool
    cleanup_local_develop_contains_task_head: bool
    cleanup_remote_develop_contains_task_head: bool

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "stage", "plan_digest", "charter_digest", "charter", "repository_id",
        "repository_full_name", "pr_number", "pr_state", "pr_merged", "pr_draft", "base_ref",
        "base_sha", "head_ref", "head_sha", "current_task_head_sha", "current_develop_sha",
        "changed_paths", "checks", "review", "pending_external_gates", "requested_operations",
        "change_categories", "mergeability", "observed_at", "expires_at", "facts_digest",
        "readback_merge_sha",
        "readback_develop_contains_task_head", "cleanup_worktree_clean",
        "cleanup_local_develop_contains_task_head", "cleanup_remote_develop_contains_task_head",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> GitHubGateFactsV1:
        data = _gate_mapping(raw, "GitHub Gate facts")
        _gate_keys(data, cls.KEYS, "GitHub Gate facts")
        supplied_digest = _gate_digest(data["facts_digest"], "facts_digest")
        semantic_fields = dict(data)
        semantic_fields.pop("facts_digest")
        if supplied_digest != semantic_digest(semantic_fields):
            raise LeanMatrixError(
                "facts_digest_mismatch", "facts_digest must bind every normalized Connector fact",
            )
        stage = _gate_status(data["stage"], "stage", DEVELOP_GATE_STAGES)
        checks_raw = data["checks"]
        if not isinstance(checks_raw, list):
            raise LeanMatrixError("invalid_check_list", "checks must be a JSON list")
        checks = tuple(GitHubCheckV1.from_mapping(check) for check in checks_raw)
        names = [check.name for check in checks]
        if len(names) != len(set(names)):
            raise LeanMatrixError("duplicate_check", "check names must be unique")
        observed_at, observed = _gate_rfc3339(data["observed_at"], "observed_at")
        expires_at, expires = _gate_rfc3339(data["expires_at"], "expires_at")
        if expires - observed != GITHUB_FACT_TTL:
            raise LeanMatrixError("invalid_expiry", "expires_at must be exactly five minutes after observed_at")
        pr_state = _gate_status(data["pr_state"], "pr_state", GITHUB_PR_STATES)
        pr_merged = _gate_bool(data["pr_merged"], "pr_merged")
        if pr_merged != (pr_state == "MERGED"):
            raise LeanMatrixError("inconsistent_pr_state", "pr_merged must exactly match pr_state=MERGED")
        base_sha = _gate_sha(data["base_sha"], "base_sha")
        head_sha = _gate_sha(data["head_sha"], "head_sha")
        current_task_head = _gate_sha(data["current_task_head_sha"], "current_task_head_sha")
        current_develop = _gate_sha(data["current_develop_sha"], "current_develop_sha")
        assert base_sha is not None and head_sha is not None
        assert current_task_head is not None and current_develop is not None
        change_categories = _gate_strings(data["change_categories"], "change_categories")
        if not set(change_categories).issubset(DEVELOP_GATE_CHANGE_CATEGORIES):
            raise LeanMatrixError(
                "invalid_change_category",
                "change_categories must use the closed safe-category set",
            )
        return cls(
            schema_version=_gate_schema_version(data["schema_version"], "GitHub Gate facts"),
            stage=stage,
            plan_digest=_gate_digest(data["plan_digest"], "plan_digest"),
            charter_digest=_gate_digest(data["charter_digest"], "charter_digest"),
            charter=TaskCharterV1.from_mapping(data["charter"]),
            repository_id=_gate_positive_int(data["repository_id"], "repository_id"),
            repository_full_name=_gate_string(data["repository_full_name"], "repository_full_name"),
            pr_number=_gate_positive_int(data["pr_number"], "pr_number"),
            pr_state=pr_state,
            pr_merged=pr_merged,
            pr_draft=_gate_bool(data["pr_draft"], "pr_draft"),
            base_ref=_gate_string(data["base_ref"], "base_ref"),
            base_sha=base_sha,
            head_ref=_gate_string(data["head_ref"], "head_ref"),
            head_sha=head_sha,
            current_task_head_sha=current_task_head,
            current_develop_sha=current_develop,
            changed_paths=_gate_paths(data["changed_paths"], "changed_paths"),
            checks=checks,
            review=GitHubReviewEvidenceV1.from_mapping(data["review"]),
            pending_external_gates=_gate_strings(
                data["pending_external_gates"], "pending_external_gates",
            ),
            requested_operations=_gate_strings(data["requested_operations"], "requested_operations"),
            change_categories=change_categories,
            mergeability=_gate_status(
                data["mergeability"], "mergeability", GITHUB_MERGEABILITY_STATES,
            ),
            observed_at=observed_at,
            expires_at=expires_at,
            facts_digest=supplied_digest,
            readback_merge_sha=_gate_sha(
                data["readback_merge_sha"], "readback_merge_sha", allow_none=True,
            ),
            readback_develop_contains_task_head=_gate_bool(
                data["readback_develop_contains_task_head"], "readback_develop_contains_task_head",
            ),
            cleanup_worktree_clean=_gate_bool(
                data["cleanup_worktree_clean"], "cleanup_worktree_clean",
            ),
            cleanup_local_develop_contains_task_head=_gate_bool(
                data["cleanup_local_develop_contains_task_head"],
                "cleanup_local_develop_contains_task_head",
            ),
            cleanup_remote_develop_contains_task_head=_gate_bool(
                data["cleanup_remote_develop_contains_task_head"],
                "cleanup_remote_develop_contains_task_head",
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "plan_digest": self.plan_digest,
            "charter_digest": self.charter_digest,
            "charter": self.charter.to_dict(),
            "repository_id": self.repository_id,
            "repository_full_name": self.repository_full_name,
            "pr_number": self.pr_number,
            "pr_state": self.pr_state,
            "pr_merged": self.pr_merged,
            "pr_draft": self.pr_draft,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "current_task_head_sha": self.current_task_head_sha,
            "current_develop_sha": self.current_develop_sha,
            "changed_paths": list(self.changed_paths),
            "checks": [check.to_dict() for check in self.checks],
            "review": self.review.to_dict(),
            "pending_external_gates": list(self.pending_external_gates),
            "requested_operations": list(self.requested_operations),
            "change_categories": list(self.change_categories),
            "mergeability": self.mergeability,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "readback_merge_sha": self.readback_merge_sha,
            "readback_develop_contains_task_head": self.readback_develop_contains_task_head,
            "cleanup_worktree_clean": self.cleanup_worktree_clean,
            "cleanup_local_develop_contains_task_head": self.cleanup_local_develop_contains_task_head,
            "cleanup_remote_develop_contains_task_head": self.cleanup_remote_develop_contains_task_head,
            "facts_digest": self.facts_digest,
        }


@dataclass(frozen=True, slots=True)
class DevelopGateDecisionV1:
    schema_version: int
    stage: str
    decision: str
    reason_codes: tuple[str, ...]
    plan_digest: str
    facts_digest: str
    evaluated_at: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "stage", "decision", "reason_codes", "plan_digest", "facts_digest",
        "evaluated_at",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> DevelopGateDecisionV1:
        data = _gate_mapping(raw, "develop Gate decision")
        _gate_keys(data, cls.KEYS, "develop Gate decision")
        reasons = _gate_strings(data["reason_codes"], "reason_codes")
        if not reasons:
            raise LeanMatrixError("missing_reason_code", "reason_codes must not be empty")
        if len(reasons) != 1 or reasons[0] not in DEVELOP_GATE_REASON_RULES:
            raise LeanMatrixError("invalid_reason_code", "reason_codes must contain one closed V1 reason code")
        stage = _gate_status(data["stage"], "stage", DEVELOP_GATE_STAGES)
        decision = _gate_status(data["decision"], "decision", DEVELOP_GATE_DECISIONS)
        expected_decision, allowed_stages = DEVELOP_GATE_REASON_RULES[reasons[0]]
        if decision != expected_decision or stage not in allowed_stages:
            raise LeanMatrixError(
                "invalid_decision_reason_combination",
                "decision, stage, and reason code must form an allowed V1 combination",
            )
        return cls(
            schema_version=_gate_schema_version(data["schema_version"], "develop Gate decision"),
            stage=stage,
            decision=decision,
            reason_codes=reasons,
            plan_digest=_gate_digest(data["plan_digest"], "plan_digest"),
            facts_digest=_gate_digest(data["facts_digest"], "facts_digest"),
            evaluated_at=_gate_rfc3339(data["evaluated_at"], "evaluated_at")[0],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "plan_digest": self.plan_digest,
            "facts_digest": self.facts_digest,
            "evaluated_at": self.evaluated_at,
        }


def _develop_decision(
    *,
    stage: str,
    decision: str,
    reasons: Sequence[str],
    plan_digest_value: str,
    facts_digest: str,
    now: datetime,
) -> DevelopGateDecisionV1:
    return DevelopGateDecisionV1.from_mapping({
        "schema_version": 1,
        "stage": stage,
        "decision": decision,
        "reason_codes": list(reasons),
        "plan_digest": plan_digest_value,
        "facts_digest": facts_digest,
        "evaluated_at": _gate_timestamp(now),
    })


def _fallback_facts_identity(raw: object) -> tuple[str, str]:
    if isinstance(raw, Mapping):
        stage_raw = raw.get("stage")
        stage = stage_raw if isinstance(stage_raw, str) and stage_raw in DEVELOP_GATE_STAGES else "pre_merge"
        digest_raw = raw.get("facts_digest")
        if isinstance(digest_raw, str) and _GATE_DIGEST_RE.fullmatch(digest_raw):
            return stage, digest_raw
    return "pre_merge", _MALFORMED_FACTS_DIGEST


def _plan_matches_charter(plan: ExecutionPlanV1, charter: TaskCharterV1) -> bool:
    identity = f"{charter.task_id}-{charter.slug}"
    return (
        plan.task.issue_number == charter.issue_number
        and plan.task.task_id == charter.task_id
        and plan.task.branch == f"{charter.kind}/{identity}"
        and plan.scope.allowed_paths == charter.allowed_paths
        and plan.scope.forbidden_paths == charter.forbidden_paths
        and plan.external_gates == charter.external_gates
    )


def _manual_or_scope_decision(
    plan: ExecutionPlanV1,
    facts: GitHubGateFactsV1,
) -> tuple[str, str] | None:
    if facts.pending_external_gates:
        if not set(facts.pending_external_gates).issubset(plan.external_gates):
            return "BLOCKED", "UNKNOWN_EXTERNAL_GATE"
        return "MANUAL_GATE_REQUIRED", "EXTERNAL_GATE_REQUIRED"
    requested = set(facts.requested_operations)
    if requested & _SENSITIVE_OPERATIONS:
        return "MANUAL_GATE_REQUIRED", "SENSITIVE_OPERATION_REQUESTED"
    if not requested or not requested.issubset(_SAFE_STAGE_OPERATIONS[facts.stage]):
        return "BLOCKED", "UNKNOWN_REQUESTED_OPERATION"
    try:
        validate_scope_patterns(plan.scope.allowed_paths, plan.scope.forbidden_paths)
        if any(scope_allows(path, plan.scope.forbidden_paths) for path in facts.changed_paths):
            return "BLOCKED_SCOPE_DRIFT", "CHANGED_PATH_FORBIDDEN"
        if any(not scope_allows(path, plan.scope.allowed_paths) for path in facts.changed_paths):
            return "BLOCKED_SCOPE_DRIFT", "CHANGED_PATH_OUTSIDE_SCOPE"
        classifier = getattr(task_workflow, "classify_develop_merge", None)
        if classifier is None:
            classify_paths(facts.charter.lane, facts.changed_paths)
        else:
            classifier(
                facts.charter.lane,
                facts.changed_paths,
                facts.requested_operations,
                facts.pending_external_gates,
                change_categories=facts.change_categories,
            )
    except WorkflowError as exc:
        if exc.error_type == "manual_gate_required":
            return "MANUAL_GATE_REQUIRED", "WORKFLOW_MANUAL_GATE_REQUIRED"
        return "BLOCKED_SCOPE_DRIFT", "WORKFLOW_CLASSIFICATION_BLOCKED"
    return None


def evaluate_develop_gate(
    plan: ExecutionPlanV1 | object,
    facts: GitHubGateFactsV1 | object,
    *,
    now: datetime,
) -> DevelopGateDecisionV1:
    """Purely evaluate normalized GitHub facts; perform no observation or mutation."""
    plan_contract = plan if isinstance(plan, ExecutionPlanV1) else ExecutionPlanV1.from_mapping(plan)
    plan_digest_value = semantic_digest(plan_contract.to_dict())
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise LeanMatrixError("invalid_now", "now must be an aware UTC datetime")
    raw_facts = facts.to_dict() if isinstance(facts, GitHubGateFactsV1) else facts
    try:
        facts_contract = GitHubGateFactsV1.from_mapping(raw_facts)
    except LeanMatrixError as exc:
        stage, facts_digest = _fallback_facts_identity(raw_facts)
        reason = "FACTS_DIGEST_MISMATCH" if exc.error_type == "facts_digest_mismatch" else "FACTS_MALFORMED"
        return _develop_decision(
            stage=stage,
            decision="BLOCKED",
            reasons=(reason,),
            plan_digest_value=plan_digest_value,
            facts_digest=facts_digest,
            now=now,
        )
    decision_args = {
        "stage": facts_contract.stage,
        "plan_digest_value": plan_digest_value,
        "facts_digest": facts_contract.facts_digest,
        "now": now,
    }

    def decide(decision: str, reason: str) -> DevelopGateDecisionV1:
        return _develop_decision(decision=decision, reasons=(reason,), **decision_args)

    expires = _gate_rfc3339(facts_contract.expires_at, "expires_at")[1]
    observed = _gate_rfc3339(facts_contract.observed_at, "observed_at")[1]
    if now >= expires:
        return decide("BLOCKED", "FACTS_EXPIRED")
    if now < observed:
        return decide("BLOCKED", "FACTS_FROM_FUTURE")
    if facts_contract.plan_digest != plan_digest_value:
        return decide("BLOCKED", "PLAN_DIGEST_MISMATCH")
    actual_charter_digest = semantic_digest(facts_contract.charter.to_dict())
    if (
        facts_contract.charter_digest != actual_charter_digest
        or plan_contract.charter_digest != actual_charter_digest
    ):
        return decide("BLOCKED", "CHARTER_DIGEST_MISMATCH")
    if not _plan_matches_charter(plan_contract, facts_contract.charter):
        return decide("BLOCKED", "PLAN_CHARTER_BINDING_MISMATCH")

    if facts_contract.repository_id != GITHUB_REPOSITORY_ID:
        return decide("BLOCKED_PR_IDENTITY", "REPOSITORY_ID_MISMATCH")
    if facts_contract.repository_full_name != GITHUB_REPOSITORY_FULL_NAME:
        return decide("BLOCKED_PR_IDENTITY", "REPOSITORY_NAME_MISMATCH")
    if facts_contract.base_ref != "develop":
        return decide("BLOCKED_PR_IDENTITY", "PR_BASE_REF_MISMATCH")
    if facts_contract.head_ref != plan_contract.task.branch:
        return decide("BLOCKED_PR_IDENTITY", "PR_HEAD_REF_MISMATCH")
    if facts_contract.pr_state == "CLOSED":
        return decide("BLOCKED_PR_IDENTITY", "PR_CLOSED_UNMERGED")

    if facts_contract.current_task_head_sha != facts_contract.head_sha:
        return decide("BLOCKED_HEAD_DRIFT", "TASK_HEAD_DRIFT")
    if any(check.head_sha != facts_contract.head_sha for check in facts_contract.checks):
        return decide("BLOCKED_HEAD_DRIFT", "CI_HEAD_DRIFT")
    if facts_contract.review.head_sha not in {None, facts_contract.head_sha}:
        return decide("BLOCKED_HEAD_DRIFT", "REVIEW_HEAD_DRIFT")

    if facts_contract.base_sha != plan_contract.base.expected_sha:
        return decide("BLOCKED_BASE_DRIFT", "PR_BASE_SHA_DRIFT")
    if facts_contract.review.base_sha not in {None, plan_contract.base.expected_sha}:
        return decide("BLOCKED_BASE_DRIFT", "REVIEW_BASE_DRIFT")
    if (
        facts_contract.stage == "pre_merge"
        and not facts_contract.pr_merged
        and facts_contract.current_develop_sha != plan_contract.base.expected_sha
    ):
        return decide("BLOCKED_BASE_DRIFT", "CURRENT_DEVELOP_DRIFT")
    if (
        facts_contract.stage == "merge_readback"
        and not facts_contract.pr_merged
        and facts_contract.current_develop_sha != plan_contract.base.expected_sha
    ):
        return decide("BLOCKED_BASE_DRIFT", "CURRENT_DEVELOP_DRIFT")

    policy_decision = _manual_or_scope_decision(plan_contract, facts_contract)
    if policy_decision is not None:
        return decide(*policy_decision)

    merge_confirmed = (
        facts_contract.pr_state == "MERGED"
        and facts_contract.pr_merged
        and facts_contract.readback_merge_sha is not None
        and facts_contract.readback_develop_contains_task_head
    )
    if facts_contract.stage == "merge_readback":
        return (
            decide("ALLOW_DEVELOP_MERGE", "MERGE_READBACK_CONFIRMED")
            if merge_confirmed
            else decide("BLOCKED", "MERGE_RESULT_UNCONFIRMED")
        )
    if facts_contract.stage == "cleanup":
        if not merge_confirmed:
            return decide("BLOCKED", "MERGE_NOT_CONFIRMED")
        if not facts_contract.cleanup_worktree_clean:
            return decide("BLOCKED", "WORKTREE_NOT_CLEAN")
        if not facts_contract.cleanup_local_develop_contains_task_head:
            return decide("BLOCKED", "LOCAL_DEVELOP_MISSING_TASK_HEAD")
        if not facts_contract.cleanup_remote_develop_contains_task_head:
            return decide("BLOCKED", "REMOTE_DEVELOP_MISSING_TASK_HEAD")
        return decide("ALLOW_DEVELOP_MERGE", "CLEANUP_ALLOWED")
    if merge_confirmed:
        return decide("ALLOW_DEVELOP_MERGE", "ALREADY_MERGED")

    required = set(required_checks_for_owner(
        plan_contract.validation.required_checks,
        "ci",
    ))
    observed_checks = {check.name: check for check in facts_contract.checks}
    if not required.issubset(observed_checks):
        return decide("BLOCKED_CI", "CI_CHECK_MISSING")
    required_states = {observed_checks[name].status for name in required}
    blocking_states = (required_states - {"SUCCESS", "PENDING"})
    if blocking_states:
        state = sorted(blocking_states)[0]
        return decide("BLOCKED_CI", f"CI_{state}")
    if "PENDING" in required_states:
        return decide("WAIT_CI", "CI_PENDING")

    review = facts_contract.review
    if review.status in {"MISSING", "PENDING"}:
        return decide("WAIT_REVIEW", "REVIEW_PENDING")
    if review.reviewer_context_id == review.implementer_context_id:
        return decide("BLOCKED_REVIEW", "INDEPENDENT_REVIEW_REQUIRED")
    if review.status == "CHANGES_REQUESTED":
        return decide("BLOCKED_REVIEW", "REVIEW_CHANGES_REQUESTED")
    if review.critical_findings:
        return decide("BLOCKED_REVIEW", "CRITICAL_FINDINGS")
    if review.important_findings:
        return decide("BLOCKED_REVIEW", "IMPORTANT_FINDINGS")
    if review.blocking_threads:
        return decide("BLOCKED_THREADS", "BLOCKING_THREADS_OPEN")
    if facts_contract.mergeability != "MERGEABLE":
        return decide("BLOCKED_MERGEABILITY", f"MERGEABILITY_{facts_contract.mergeability}")
    if facts_contract.pr_draft:
        return decide("ALLOW_DEVELOP_MERGE", "READY_TRANSITION_REQUIRED")
    return decide("ALLOW_DEVELOP_MERGE", "DEVELOP_MERGE_ALLOWED")


class LeanMatrixArgumentParser(argparse.ArgumentParser):
    """Route invalid command syntax through the stable JSON error contract."""

    def error(self, message: str) -> None:
        raise LeanMatrixError("invalid_cli_arguments", message)


def _read_input(input_name: str) -> object:
    try:
        if input_name == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            content = binary_stdin.read().decode("utf-8") if binary_stdin else sys.stdin.read()
        else:
            content = Path(input_name).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise LeanMatrixError("invalid_input_encoding", "input must be UTF-8 encoded JSON") from exc
    except OSError as exc:
        raise LeanMatrixError("input_file_unavailable", str(exc)) from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise LeanMatrixError("invalid_json", exc.msg) from exc


def render(raw: object) -> dict[str, object]:
    """Backward-compatible import alias for the schema-v1 Charter renderer."""
    return render_charter(raw)


def _blocked(error: LeanMatrixError) -> int:
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "error_type": error.error_type,
        "detail": error.detail,
    }), file=sys.stderr)
    return 2


def _specialist_context_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise LeanMatrixError(
                "invalid_specialist_context", "--specialist-context must use DOMAIN=CONTEXT",
            )
        domain, context = value.split("=", 1)
        if not domain or not context or domain in mapping:
            raise LeanMatrixError(
                "invalid_specialist_context", "specialist domain/context must be non-blank and unique",
            )
        mapping[domain] = context
    return mapping


def _specialist_evidence_pairs(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise LeanMatrixError(
                "invalid_specialist_evidence",
                "--specialist-evidence must use BRIEF_PATH=HANDOFF_PATH",
            )
        brief_path, handoff_path = value.split("=", 1)
        if not brief_path or not handoff_path:
            raise LeanMatrixError(
                "invalid_specialist_evidence", "specialist evidence paths must be non-blank",
            )
        pairs.append((brief_path, handoff_path))
    return pairs


def _load_review_inputs(args):  # noqa: ANN001, ANN202
    approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
    intake = DocumentIntakeV1.from_mapping(
        _read_input(args.intake),
        repo_root=REPO_ROOT,
        approved_execution_plan=approved_plan,
    )
    raw_implementer = _read_input(args.implementer_brief)
    round_number = raw_implementer.get("round") if isinstance(raw_implementer, dict) else None
    round_zero = (
        load_round_zero_implementer_brief(REPO_ROOT, intake)
        if isinstance(round_number, int) and round_number > 0
        else None
    )
    implementer_brief = RoleBriefV1.from_mapping(
        raw_implementer,
        document_intake=intake,
        round_zero_brief=round_zero,
    )
    reviewer_brief = RoleBriefV1.from_mapping(
        _read_input(args.reviewer_brief),
        document_intake=intake,
        round_zero_brief=round_zero,
    )
    implementer_handoff = HandoffReportV1.from_mapping(
        _read_input(args.implementer_handoff), role_brief=implementer_brief,
    )
    specialist_evidence = []
    for brief_path, handoff_path in _specialist_evidence_pairs(args.specialist_evidence):
        specialist_brief = RoleBriefV1.from_mapping(
            _read_input(brief_path), document_intake=intake,
        )
        specialist_handoff = HandoffReportV1.from_mapping(
            _read_input(handoff_path), role_brief=specialist_brief,
        )
        specialist_evidence.append((specialist_brief, specialist_handoff))
    return (
        intake,
        implementer_brief,
        implementer_handoff,
        reviewer_brief,
        tuple(specialist_evidence),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = LeanMatrixArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=LeanMatrixArgumentParser)
    charter = subcommands.add_parser("charter")
    charter.add_argument("--input", required=True)
    charter.add_argument("--format", required=True, choices=("markdown", "json"))
    plan = subcommands.add_parser("plan")
    plan.add_argument("--charter", required=True)
    plan.add_argument("--format", required=True, choices=("markdown", "json"))
    develop_gate = subcommands.add_parser("develop-gate")
    develop_gate.add_argument("--plan", required=True)
    develop_gate.add_argument("--facts", required=True)
    develop_gate.add_argument("--format", required=True, choices=("json",))
    intake_command = subcommands.add_parser("intake")
    intake_command.add_argument("--input", required=True)
    intake_command.add_argument("--approved-plan", required=True)
    intake_command.add_argument("--format", required=True, choices=("json",))
    observe = subcommands.add_parser("observe")
    observe.add_argument("--plan", required=True)
    observe.add_argument("--format", required=True, choices=("json",))
    next_command = subcommands.add_parser("next")
    next_command.add_argument("--plan", required=True)
    next_command.add_argument("--format", required=True, choices=("json",))
    apply_command = subcommands.add_parser("apply")
    apply_command.add_argument("--plan", required=True)
    apply_command.add_argument("--expected-transition", required=True)
    apply_command.add_argument("--expected-state-digest", required=True)
    apply_command.add_argument("--format", required=True, choices=("json",))
    apply_command.add_argument("--apply", action="store_true")
    brief_command = subcommands.add_parser("brief")
    brief_command.add_argument("--intake", required=True)
    brief_command.add_argument("--approved-plan", required=True)
    brief_command.add_argument("--role", required=True)
    brief_command.add_argument("--specialist-domain")
    brief_command.add_argument("--specialist-context", action="append", default=[])
    brief_command.add_argument("--context-id", required=True)
    brief_command.add_argument("--implementer-context-id", required=True)
    brief_command.add_argument("--reviewer-context-id", required=True)
    brief_command.add_argument("--original-implementer-context-id")
    brief_command.add_argument("--round", type=int, default=0)
    brief_command.add_argument("--predecessor-decision-digest")
    brief_command.add_argument("--output", required=True)
    review_package_command = subcommands.add_parser("review-package")
    review_package_command.add_argument("--intake", required=True)
    review_package_command.add_argument("--approved-plan", required=True)
    review_package_command.add_argument("--implementer-brief", required=True)
    review_package_command.add_argument("--implementer-handoff", required=True)
    review_package_command.add_argument("--reviewer-brief", required=True)
    review_package_command.add_argument("--specialist-evidence", action="append", default=[])
    review_package_command.add_argument("--format", required=True, choices=("json",))
    decision_command = subcommands.add_parser("decision")
    decision_command.add_argument("--intake", required=True)
    decision_command.add_argument("--approved-plan", required=True)
    decision_command.add_argument("--implementer-brief", required=True)
    decision_command.add_argument("--implementer-handoff", required=True)
    decision_command.add_argument("--reviewer-brief", required=True)
    decision_command.add_argument("--specialist-evidence", action="append", default=[])
    decision_command.add_argument("--package", required=True)
    decision_command.add_argument("--input", required=True)
    decision_command.add_argument("--format", required=True, choices=("json",))
    try:
        args = parser.parse_args(argv)
        if args.command == "charter":
            result = render_charter(_read_input(args.input))
            output = result["charter_markdown"] if args.format == "markdown" else result
        elif args.command == "plan":
            charter_contract = TaskCharterV1.from_mapping(_read_input(args.charter))
            base_sha = resolve_base_sha(REPO_ROOT)
            plan_contract = build_execution_plan(
                charter_contract, base_ref=BASE_REF, base_sha=base_sha,
            )
            result = plan_contract.to_dict()
            output = render_execution_plan_markdown(plan_contract) if args.format == "markdown" else result
        elif args.command == "intake":
            approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
            output = DocumentIntakeV1.from_mapping(
                _read_input(args.input),
                repo_root=REPO_ROOT,
                approved_execution_plan=approved_plan,
            ).to_dict()
        elif args.command == "develop-gate":
            approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.plan))
            output = evaluate_develop_gate(
                approved_plan,
                _read_input(args.facts),
                now=datetime.now(UTC),
            ).to_dict()
        elif args.command == "brief":
            approved_plan = ExecutionPlanV1.from_mapping(_read_input(args.approved_plan))
            intake = DocumentIntakeV1.from_mapping(
                _read_input(args.intake),
                repo_root=REPO_ROOT,
                approved_execution_plan=approved_plan,
            )
            round_zero_brief = (
                load_round_zero_implementer_brief(REPO_ROOT, intake)
                if args.round > 0
                else None
            )
            original_implementer_context_id = (
                args.original_implementer_context_id
                if args.original_implementer_context_id is not None
                else (
                    round_zero_brief.implementer_context_id
                    if round_zero_brief is not None
                    else args.implementer_context_id
                )
            )
            brief = build_role_brief(
                intake,
                role=args.role,
                context_id=args.context_id,
                implementer_context_id=args.implementer_context_id,
                reviewer_context_id=args.reviewer_context_id,
                original_implementer_context_id=original_implementer_context_id,
                specialist_contexts=_specialist_context_mapping(args.specialist_context),
                round_number=args.round,
                specialist_domain=args.specialist_domain,
                predecessor_decision_digest=args.predecessor_decision_digest,
                round_zero_brief=round_zero_brief,
            )
            output = write_role_brief_files(
                REPO_ROOT,
                intake,
                brief,
                Path(args.output),
                round_zero_brief=round_zero_brief,
            )
        elif args.command == "review-package":
            from lean_matrix.review_packages import build_review_package

            (
                intake,
                implementer_brief,
                implementer_handoff,
                reviewer_brief,
                specialist_evidence,
            ) = _load_review_inputs(args)
            output = build_review_package(
                REPO_ROOT,
                intake,
                implementer_brief=implementer_brief,
                implementer_handoff=implementer_handoff,
                reviewer_brief=reviewer_brief,
                specialist_evidence=specialist_evidence,
            ).to_dict()
        elif args.command == "decision":
            (
                intake,
                implementer_brief,
                implementer_handoff,
                reviewer_brief,
                specialist_evidence,
            ) = _load_review_inputs(args)
            package = ReviewPackageV1.from_mapping(
                _read_input(args.package),
                repo_root=REPO_ROOT,
                document_intake=intake,
                implementer_brief=implementer_brief,
                implementer_handoff=implementer_handoff,
                reviewer_brief=reviewer_brief,
                specialist_evidence=specialist_evidence,
            )
            from lean_matrix.contracts import FinalDecisionV1

            validate_worktree_clean(REPO_ROOT, intake_workspace(REPO_ROOT, intake))
            output = FinalDecisionV1.from_mapping(
                _read_input(args.input), review_package=package,
            ).to_dict()
        else:
            plan_contract = ExecutionPlanV1.from_mapping(_read_input(args.plan))
            observed = observe_execution_plan(plan_contract, REPO_ROOT)
            if args.command == "observe":
                output = observed.state.to_dict()
            else:
                evidence = load_evidence(REPO_ROOT, plan_contract)
                proposal = propose_next_transition(
                    plan_contract,
                    observed,
                    attempted_actions=evidence.attempted_actions,
                    successful_actions=evidence.successful_actions,
                )
                if args.command == "next":
                    output = proposal.to_dict()
                else:
                    if args.expected_state_digest != observed.state.state_digest:
                        raise LeanMatrixError(
                            "expected_state_mismatch",
                            "current state digest does not match --expected-state-digest",
                        )
                    if args.expected_transition != proposal.transition_id:
                        raise LeanMatrixError(
                            "expected_transition_mismatch",
                            "current transition does not match --expected-transition",
                        )
                    if not args.apply:
                        output = proposal.to_dict()
                    else:
                        if plan_contract.external_gates:
                            raise LeanMatrixError(
                                "lane_three_apply_forbidden",
                                "plans with external Gates cannot use generic apply",
                            )
                        if not proposal.requires_apply:
                            raise LeanMatrixError(
                                "transition_not_applicable",
                                "the current proposal has no executable local transition",
                            )
                        claim_transition(REPO_ROOT, plan_contract, proposal)
                        execution = execute_action(plan_contract, proposal.action, REPO_ROOT)
                        after = observe_execution_plan(plan_contract, REPO_ROOT)
                        execution_error = execution.error_type
                        if execution_error is None and after.state.state_digest == observed.state.state_digest:
                            execution_error = "transition_state_unchanged"
                        receipt = TransitionReceiptV1.from_mapping({
                            "transition_id": proposal.transition_id,
                            "plan_digest": plan_digest(plan_contract),
                            "before_state_digest": observed.state.state_digest,
                            "after_state_digest": after.state.state_digest,
                            "command_digests": [execution.command_digest],
                            "exit_codes": [execution.exit_code],
                            "result": "PASS" if execution_error is None else "FAIL",
                            "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        })
                        record_transition(
                            REPO_ROOT,
                            plan_contract,
                            proposal,
                            receipt,
                            error_type=execution_error,
                        )
                        if execution_error:
                            raise LeanMatrixError(
                                execution_error,
                                "local transition failed or its external result is uncertain; inspect before retrying",
                            )
                        output = receipt.to_dict()
    except LeanMatrixError as exc:
        return _blocked(exc)
    if getattr(args, "format", None) == "markdown":
        print(output, end="")
    else:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
