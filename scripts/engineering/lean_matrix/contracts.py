"""Frozen, strict version-one contracts for Lean Matrix execution planning."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Mapping

from .charter import WORKTREE_ROOT, validate_charter
from .errors import LeanMatrixError


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RECORDED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BRANCH_RE = re.compile(r"^(feature|fix|docs|research|refactor)/[A-Za-z0-9][A-Za-z0-9._-]{0,160}$")
WORKTREE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}$")
CORE_STATES = frozenset({"NOT_RUN", "PASS", "FAIL"})
GATE_STATES = CORE_STATES | {"NOT_APPLICABLE"}
BRIEF_ROLES = frozenset({"implementer", "reviewer", "specialist"})
HANDOFF_KINDS = frozenset({"implementer", "specialist"})
HANDOFF_STATUSES = frozenset({"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"})
REVIEW_PHASES = frozenset({"task", "final"})
FINDING_SEVERITIES = frozenset({"Critical", "Important", "Minor"})
SPEC_VERDICTS = frozenset({"PASS", "FAIL"})
QUALITY_VERDICTS = frozenset({"APPROVED", "CHANGES_REQUIRED"})


def _require_keys(raw: Mapping[str, object], expected: frozenset[str], name: str) -> None:
    if set(raw) != expected:
        raise LeanMatrixError("invalid_contract_keys", f"{name} keys must exactly match schema version 1")


def _require_mapping(raw: object, name: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise LeanMatrixError("invalid_contract", f"{name} must be a JSON object")
    return raw


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeanMatrixError("invalid_string", f"{field} must be a non-blank string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise LeanMatrixError(
            "invalid_string_control_characters",
            f"{field} must not contain control characters",
        )
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _identifier(value: object, field: str) -> str:
    identifier = _string(value, field)
    if not IDENTIFIER_RE.fullmatch(identifier) or ".." in identifier:
        raise LeanMatrixError("invalid_identifier", f"{field} must be a simple identifier")
    return identifier


def _branch(value: object, field: str) -> str:
    branch = _string(value, field)
    if not BRANCH_RE.fullmatch(branch) or ".." in branch or branch.endswith(".lock") or "@{" in branch:
        raise LeanMatrixError("invalid_branch", f"{field} must be a managed task branch")
    return branch


def _strings(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LeanMatrixError("invalid_string_list", f"{field} must be a JSON list of strings")
    return tuple(_string(item, f"{field} item") for item in value)


def _relative_path(value: object, field: str) -> str:
    path = _string(value, field)
    pure = PurePosixPath(path)
    if (
        path.startswith("/")
        or "\\" in path
        or re.match(r"^[A-Za-z]:", path)
        or ".." in pure.parts
        or path in {".", ""}
    ):
        raise LeanMatrixError(
            "invalid_repository_path",
            f"{field} must be a repository-relative slash-separated path without traversal",
        )
    return path


def _relative_paths(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LeanMatrixError("invalid_path_list", f"{field} must be a JSON list of repository-relative paths")
    return tuple(_relative_path(item, f"{field} item") for item in value)


def _repository_file_digest(repo_root: Path, relative_path: str, field: str) -> str:
    """Hash one regular, non-symlink repository file at its declared relative path."""
    if not isinstance(repo_root, Path):
        raise LeanMatrixError("invalid_repository_root", "repo_root must be a pathlib.Path")
    try:
        resolved_root = repo_root.resolve(strict=True)
        candidate = resolved_root.joinpath(*PurePosixPath(relative_path).parts)
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise LeanMatrixError(
            "document_unavailable", f"{field} is unavailable below repo_root",
        ) from exc
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise LeanMatrixError(
            "repository_path_escape", f"{field} resolves outside repo_root",
        ) from exc
    if resolved_candidate != candidate:
        raise LeanMatrixError(
            "document_symlink_forbidden", f"{field} must not contain a symlink component",
        )
    if not resolved_candidate.is_file():
        raise LeanMatrixError("document_unavailable", f"{field} must identify a regular file")
    try:
        content = resolved_candidate.read_bytes()
    except OSError as exc:
        raise LeanMatrixError("document_unavailable", f"{field} could not be read") from exc
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _sha(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    sha = _string(value, field)
    if not SHA_RE.fullmatch(sha):
        raise LeanMatrixError("invalid_sha", f"{field} must be 40 lowercase hexadecimal characters")
    return sha


def _digest(value: object, field: str) -> str:
    digest = _string(value, field)
    if not DIGEST_RE.fullmatch(digest):
        raise LeanMatrixError("invalid_digest", f"{field} must use sha256:<64 lowercase hexadecimal>")
    return digest


def _bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise LeanMatrixError("invalid_boolean", f"{field} must be a JSON boolean")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise LeanMatrixError("invalid_positive_integer", f"{field} must be a positive integer or null")
    return value


def _positive_int(value: object, field: str) -> int:
    result = _optional_positive_int(value, field)
    if result is None:
        raise LeanMatrixError("invalid_positive_integer", f"{field} must be a positive integer")
    return result


def _round(value: object, field: str = "round") -> int:
    if type(value) is not int or not 0 <= value <= 3:
        raise LeanMatrixError("invalid_round", f"{field} must be an integer from 0 through 3")
    return value


def _schema_version(value: object, name: str) -> int:
    if type(value) is not int or value != 1:
        raise LeanMatrixError("invalid_schema_version", f"{name} schema_version must equal 1")
    return 1


def _identifiers(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LeanMatrixError("invalid_identifier_list", f"{field} must be a JSON list of identifiers")
    return tuple(_identifier(item, f"{field} item") for item in value)


def _digests(value: object, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LeanMatrixError("invalid_digest_list", f"{field} must be a JSON list of digests")
    return tuple(_digest(item, f"{field} item") for item in value)


def _status(value: object, field: str, allowed: frozenset[str]) -> str:
    state = _string(value, field)
    if state not in allowed:
        raise LeanMatrixError("invalid_status", f"{field} has invalid status: {state}")
    return state


def _worktree(value: object, field: str) -> str:
    path = _string(value, field)
    prefix = f"{WORKTREE_ROOT}/"
    suffix = path.removeprefix(prefix)
    if (
        not path.startswith(prefix)
        or not suffix
        or "/" in suffix
        or "//" in path
        or ".." in PurePosixPath(path).parts
        or not WORKTREE_COMPONENT_RE.fullmatch(suffix)
    ):
        raise LeanMatrixError("invalid_worktree", f"{field} must be inside {WORKTREE_ROOT}")
    return path


@dataclass(frozen=True, slots=True)
class TaskCharterV1:
    schema_version: int
    issue_number: int
    task_id: str
    kind: str
    slug: str
    title: str
    value: str
    goal: str
    current_facts: tuple[str, ...]
    lane: int
    domains: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    acceptance: tuple[str, ...]
    external_gates: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: object) -> TaskCharterV1:
        validated = validate_charter(raw)
        return cls(
            schema_version=validated["schema_version"],
            issue_number=validated["issue_number"],
            task_id=validated["task_id"],
            kind=validated["kind"],
            slug=validated["slug"],
            title=validated["title"],
            value=validated["value"],
            goal=validated["goal"],
            current_facts=tuple(validated["current_facts"]),
            lane=validated["lane"],
            domains=tuple(validated["domains"]),
            allowed_paths=tuple(validated["allowed_paths"]),
            forbidden_paths=tuple(validated["forbidden_paths"]),
            acceptance=tuple(validated["acceptance"]),
            external_gates=tuple(validated["external_gates"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "issue_number": self.issue_number,
            "task_id": self.task_id,
            "kind": self.kind,
            "slug": self.slug,
            "title": self.title,
            "value": self.value,
            "goal": self.goal,
            "current_facts": list(self.current_facts),
            "lane": self.lane,
            "domains": list(self.domains),
            "allowed_paths": list(self.allowed_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "acceptance": list(self.acceptance),
            "external_gates": list(self.external_gates),
        }


@dataclass(frozen=True, slots=True)
class TaskIdentityV1:
    issue_number: int
    task_id: str
    branch: str
    worktree: str

    KEYS: ClassVar[frozenset[str]] = frozenset({"issue_number", "task_id", "branch", "worktree"})

    @classmethod
    def from_mapping(cls, raw: object) -> TaskIdentityV1:
        data = _require_mapping(raw, "task")
        _require_keys(data, cls.KEYS, "task")
        issue_number = _optional_positive_int(data["issue_number"], "task.issue_number")
        if issue_number is None:
            raise LeanMatrixError("invalid_positive_integer", "task.issue_number must be a positive integer")
        return cls(
            issue_number=issue_number,
            task_id=_identifier(data["task_id"], "task.task_id"),
            branch=_branch(data["branch"], "task.branch"),
            worktree=_worktree(data["worktree"], "task.worktree"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"issue_number": self.issue_number, "task_id": self.task_id, "branch": self.branch, "worktree": self.worktree}


@dataclass(frozen=True, slots=True)
class BaseRevisionV1:
    ref: str
    expected_sha: str

    KEYS: ClassVar[frozenset[str]] = frozenset({"ref", "expected_sha"})

    @classmethod
    def from_mapping(cls, raw: object) -> BaseRevisionV1:
        data = _require_mapping(raw, "base")
        _require_keys(data, cls.KEYS, "base")
        sha = _sha(data["expected_sha"], "base.expected_sha")
        assert sha is not None
        return cls(ref=_string(data["ref"], "base.ref"), expected_sha=sha)

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "expected_sha": self.expected_sha}


@dataclass(frozen=True, slots=True)
class DispatchPlanV1:
    model: str
    reasoning_effort: str
    roles: tuple[str, ...]
    specialists: tuple[str, ...]
    independence_requirements: tuple[str, ...]

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "model", "reasoning_effort", "roles", "specialists", "independence_requirements",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> DispatchPlanV1:
        data = _require_mapping(raw, "dispatch")
        _require_keys(data, cls.KEYS, "dispatch")
        return cls(
            model=_string(data["model"], "dispatch.model"),
            reasoning_effort=_string(data["reasoning_effort"], "dispatch.reasoning_effort"),
            roles=_strings(data["roles"], "dispatch.roles", allow_empty=False),
            specialists=_strings(data["specialists"], "dispatch.specialists"),
            independence_requirements=_strings(
                data["independence_requirements"], "dispatch.independence_requirements", allow_empty=False,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "roles": list(self.roles),
            "specialists": list(self.specialists),
            "independence_requirements": list(self.independence_requirements),
        }


@dataclass(frozen=True, slots=True)
class ScopeV1:
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]

    KEYS: ClassVar[frozenset[str]] = frozenset({"allowed_paths", "forbidden_paths"})

    @classmethod
    def from_mapping(cls, raw: object) -> ScopeV1:
        data = _require_mapping(raw, "scope")
        _require_keys(data, cls.KEYS, "scope")
        return cls(
            allowed_paths=_relative_paths(data["allowed_paths"], "scope.allowed_paths", allow_empty=False),
            forbidden_paths=_strings(data["forbidden_paths"], "scope.forbidden_paths"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"allowed_paths": list(self.allowed_paths), "forbidden_paths": list(self.forbidden_paths)}


@dataclass(frozen=True, slots=True)
class ValidationPlanV1:
    test_profile: str
    required_checks: tuple[str, ...]

    KEYS: ClassVar[frozenset[str]] = frozenset({"test_profile", "required_checks"})

    @classmethod
    def from_mapping(cls, raw: object) -> ValidationPlanV1:
        data = _require_mapping(raw, "validation")
        _require_keys(data, cls.KEYS, "validation")
        return cls(
            test_profile=_string(data["test_profile"], "validation.test_profile"),
            required_checks=_strings(data["required_checks"], "validation.required_checks", allow_empty=False),
        )

    def to_dict(self) -> dict[str, object]:
        return {"test_profile": self.test_profile, "required_checks": list(self.required_checks)}


@dataclass(frozen=True, slots=True)
class ExecutionPlanV1:
    schema_version: int
    status: str
    charter_digest: str
    task: TaskIdentityV1
    base: BaseRevisionV1
    dispatch: DispatchPlanV1
    scope: ScopeV1
    validation: ValidationPlanV1
    transitions: tuple[str, ...]
    external_gates: tuple[str, ...]

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "status", "charter_digest", "task", "base", "dispatch", "scope",
        "validation", "transitions", "external_gates",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> ExecutionPlanV1:
        data = _require_mapping(raw, "execution plan")
        _require_keys(data, cls.KEYS, "execution plan")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise LeanMatrixError("invalid_schema_version", "execution plan schema_version must equal 1")
        if data["status"] != "ok":
            raise LeanMatrixError("invalid_status", "execution plan status must equal ok")
        return cls(
            schema_version=1,
            status="ok",
            charter_digest=_digest(data["charter_digest"], "charter_digest"),
            task=TaskIdentityV1.from_mapping(data["task"]),
            base=BaseRevisionV1.from_mapping(data["base"]),
            dispatch=DispatchPlanV1.from_mapping(data["dispatch"]),
            scope=ScopeV1.from_mapping(data["scope"]),
            validation=ValidationPlanV1.from_mapping(data["validation"]),
            transitions=_strings(data["transitions"], "transitions", allow_empty=False),
            external_gates=_strings(data["external_gates"], "external_gates"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "charter_digest": self.charter_digest,
            "task": self.task.to_dict(),
            "base": self.base.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "scope": self.scope.to_dict(),
            "validation": self.validation.to_dict(),
            "transitions": list(self.transitions),
            "external_gates": list(self.external_gates),
        }


@dataclass(frozen=True, slots=True, init=False)
class DocumentIntakeV1:
    """Bind untrusted design documents to one trusted execution plan.

    Document bodies never enter this contract. Lane, scope, external Gates, task
    identity, and the develop base are read only from ``execution_plan``.
    """

    schema_version: int
    design_path: str
    design_digest: str
    implementation_plan_path: str
    implementation_plan_digest: str
    execution_plan_digest: str
    execution_plan: ExecutionPlanV1
    delivery_mode: str
    task_id: str
    develop_ref: str
    develop_sha: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version",
        "design_path",
        "design_digest",
        "implementation_plan_path",
        "implementation_plan_digest",
        "execution_plan_digest",
        "execution_plan",
        "delivery_mode",
        "task_id",
        "develop_ref",
        "develop_sha",
    })

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        repo_root: Path,
        approved_execution_plan: ExecutionPlanV1,
    ) -> DocumentIntakeV1:
        data = _require_mapping(raw, "document intake")
        _require_keys(data, cls.KEYS, "document intake")
        execution_plan = ExecutionPlanV1.from_mapping(data["execution_plan"])
        supplied_execution_digest = _digest(
            data["execution_plan_digest"], "execution_plan_digest",
        )
        from .digests import semantic_digest

        if supplied_execution_digest != semantic_digest(execution_plan.to_dict()):
            raise LeanMatrixError(
                "execution_plan_digest_mismatch",
                "execution_plan_digest must match the embedded execution plan",
            )
        if not isinstance(approved_execution_plan, ExecutionPlanV1):
            raise LeanMatrixError(
                "invalid_approved_execution_plan",
                "approved_execution_plan must be a trusted ExecutionPlanV1",
            )
        approved_plan = ExecutionPlanV1.from_mapping(approved_execution_plan.to_dict())
        if (
            supplied_execution_digest != semantic_digest(approved_plan.to_dict())
            or execution_plan.to_dict() != approved_plan.to_dict()
        ):
            raise LeanMatrixError(
                "unapproved_execution_plan",
                "embedded execution plan does not match the trusted approved plan",
            )
        design_path = _relative_path(data["design_path"], "design_path")
        implementation_plan_path = _relative_path(
            data["implementation_plan_path"], "implementation_plan_path",
        )
        design_digest = _digest(data["design_digest"], "design_digest")
        implementation_plan_digest = _digest(
            data["implementation_plan_digest"], "implementation_plan_digest",
        )
        if design_digest != _repository_file_digest(repo_root, design_path, "design_path"):
            raise LeanMatrixError(
                "stale_design_document",
                "design document digest does not match its current repository content",
            )
        if implementation_plan_digest != _repository_file_digest(
            repo_root,
            implementation_plan_path,
            "implementation_plan_path",
        ):
            raise LeanMatrixError(
                "stale_implementation_plan",
                "implementation plan digest does not match its current repository content",
            )
        task_id = _identifier(data["task_id"], "task_id")
        if task_id != execution_plan.task.task_id:
            raise LeanMatrixError(
                "intake_task_mismatch", "document intake task_id must match the execution plan",
            )
        develop_ref = _string(data["develop_ref"], "develop_ref")
        develop_sha = _sha(data["develop_sha"], "develop_sha")
        assert develop_sha is not None
        if (
            develop_ref != "origin/develop"
            or execution_plan.base.ref != develop_ref
            or execution_plan.base.expected_sha != develop_sha
        ):
            raise LeanMatrixError(
                "intake_develop_mismatch",
                "document intake and execution plan must bind the same origin/develop commit",
            )
        from .git_readonly import resolve_base_sha

        if develop_sha != resolve_base_sha(repo_root):
            raise LeanMatrixError(
                "stale_develop_head", "document intake does not match current origin/develop",
            )
        delivery_mode = _string(data["delivery_mode"], "delivery_mode")
        provisional = object.__new__(cls)
        trusted_values = {
            "schema_version": _schema_version(data["schema_version"], "document intake"),
            "design_path": design_path,
            "design_digest": design_digest,
            "implementation_plan_path": implementation_plan_path,
            "implementation_plan_digest": implementation_plan_digest,
            "execution_plan_digest": supplied_execution_digest,
            "execution_plan": execution_plan,
            "delivery_mode": delivery_mode,
            "task_id": task_id,
            "develop_ref": develop_ref,
            "develop_sha": develop_sha,
        }
        for field, value in trusted_values.items():
            object.__setattr__(provisional, field, value)
        expected_mode = "fast_path" if provisional.lane == 1 else "team_path"
        if delivery_mode != expected_mode:
            raise LeanMatrixError(
                "delivery_mode_mismatch",
                f"delivery_mode must equal {expected_mode} for the trusted execution-plan Lane",
            )
        return provisional

    @property
    def lane(self) -> int:
        """Infer the frozen Lane through the existing V05 plan policy."""
        from .adapters import plan_lane

        return plan_lane(self.execution_plan)

    @property
    def trusted_allowed_paths(self) -> tuple[str, ...]:
        return self.execution_plan.scope.allowed_paths

    @property
    def trusted_external_gates(self) -> tuple[str, ...]:
        return self.execution_plan.external_gates

    @property
    def charter_freeze(self) -> str:
        return "owner_gate_required" if self.lane == 3 else "automatic"

    def owner_gate_required(self, *, proposed_allowed_paths: object | None = None) -> bool:
        """Return whether trusted Lane policy or a scope expansion requires Owner Gate."""
        if self.lane == 3:
            return True
        if proposed_allowed_paths is None:
            return False
        proposed = _relative_paths(
            proposed_allowed_paths,
            "proposed_allowed_paths",
        )
        from .scope import scope_is_subset, validate_scope_patterns

        validate_scope_patterns(proposed, ())
        return not scope_is_subset(proposed, self.trusted_allowed_paths)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "design_path": self.design_path,
            "design_digest": self.design_digest,
            "implementation_plan_path": self.implementation_plan_path,
            "implementation_plan_digest": self.implementation_plan_digest,
            "execution_plan_digest": self.execution_plan_digest,
            "execution_plan": self.execution_plan.to_dict(),
            "delivery_mode": self.delivery_mode,
            "task_id": self.task_id,
            "develop_ref": self.develop_ref,
            "develop_sha": self.develop_sha,
        }


@dataclass(frozen=True, slots=True)
class _ReviewFindingV1:
    schema_version: int
    severity: str
    summary: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "severity", "summary",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> _ReviewFindingV1:
        data = _require_mapping(raw, "review finding")
        _require_keys(data, cls.KEYS, "review finding")
        return cls(
            schema_version=1,
            severity=_status(data["severity"], "finding.severity", FINDING_SEVERITIES),
            summary=_string(data["summary"], "finding.summary"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "summary": self.summary,
        }


def _findings(value: object, field: str) -> tuple[_ReviewFindingV1, ...]:
    if not isinstance(value, list):
        raise LeanMatrixError("invalid_findings", f"{field} must be a JSON list of review findings")
    return tuple(_ReviewFindingV1.from_mapping(item) for item in value)


@dataclass(frozen=True, slots=True, init=False)
class RoleBriefV1:
    schema_version: int
    intake_digest: str
    execution_plan_digest: str
    role: str
    specialist_domain: str | None
    context_id: str
    implementer_context_id: str
    reviewer_context_id: str
    original_implementer_context_id: str
    specialist_contexts: tuple[tuple[str, str], ...]
    round: int
    selected_context: tuple[str, ...]
    trusted_allowed_paths: tuple[str, ...]
    trusted_forbidden_paths: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    report_path: str
    predecessor_decision_digest: str | None

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "intake_digest", "execution_plan_digest", "role", "specialist_domain",
        "context_id", "implementer_context_id", "reviewer_context_id",
        "original_implementer_context_id", "specialist_contexts", "round", "selected_context",
        "trusted_allowed_paths", "trusted_forbidden_paths", "acceptance_criteria", "report_path",
        "predecessor_decision_digest",
    })

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        document_intake: DocumentIntakeV1,
        round_zero_brief: RoleBriefV1 | None = None,
    ) -> RoleBriefV1:
        data = _require_mapping(raw, "role brief")
        _require_keys(data, cls.KEYS, "role brief")
        if not isinstance(document_intake, DocumentIntakeV1):
            raise LeanMatrixError(
                "invalid_document_intake", "document_intake must be a trusted DocumentIntakeV1",
            )
        from .digests import canonical_json, semantic_digest

        role = _status(data["role"], "role", BRIEF_ROLES)
        specialist_domain = (
            None
            if data["specialist_domain"] is None
            else _identifier(data["specialist_domain"], "specialist_domain")
        )
        if (role == "specialist") != (specialist_domain is not None):
            raise LeanMatrixError(
                "invalid_specialist_identity",
                "specialist briefs require specialist_domain and every other role forbids it",
            )
        context_id = _identifier(data["context_id"], "context_id")
        implementer_context_id = _identifier(
            data["implementer_context_id"], "implementer_context_id",
        )
        reviewer_context_id = _identifier(data["reviewer_context_id"], "reviewer_context_id")
        original_implementer_context_id = _identifier(
            data["original_implementer_context_id"], "original_implementer_context_id",
        )
        if implementer_context_id == reviewer_context_id:
            raise LeanMatrixError(
                "role_identity_collision", "implementer and reviewer contexts must differ",
            )
        raw_specialist_contexts = data["specialist_contexts"]
        if not isinstance(raw_specialist_contexts, list):
            raise LeanMatrixError(
                "invalid_specialist_contexts", "specialist_contexts must be a JSON list",
            )
        specialist_contexts: list[tuple[str, str]] = []
        for item in raw_specialist_contexts:
            assignment = _require_mapping(item, "specialist context")
            _require_keys(
                assignment, frozenset({"domain", "context_id"}), "specialist context",
            )
            specialist_contexts.append((
                _identifier(assignment["domain"], "specialist_context.domain"),
                _identifier(assignment["context_id"], "specialist_context.context_id"),
            ))
        specialist_context_tuple = tuple(specialist_contexts)
        specialist_context_ids = tuple(context for _, context in specialist_context_tuple)
        all_contexts = (implementer_context_id, reviewer_context_id, *specialist_context_ids)
        if len(set(all_contexts)) != len(all_contexts):
            raise LeanMatrixError(
                "specialist_identity_collision",
                "specialist contexts must be distinct from every other delivery context",
            )
        expected_context = {
            "implementer": implementer_context_id,
            "reviewer": reviewer_context_id,
        }.get(role)
        if expected_context is not None and context_id != expected_context:
            raise LeanMatrixError("brief_context_mismatch", "role brief context does not match its role")
        if role == "specialist" and context_id not in specialist_context_ids:
            raise LeanMatrixError(
                "brief_context_mismatch", "specialist brief context is absent from the specialist roster",
            )
        round_number = _round(data["round"])
        predecessor = (
            None
            if data["predecessor_decision_digest"] is None
            else _digest(data["predecessor_decision_digest"], "predecessor_decision_digest")
        )
        if (round_number == 0) != (predecessor is None):
            raise LeanMatrixError(
                "invalid_predecessor",
                "round zero forbids a predecessor decision and repair rounds require one",
            )
        if round_number == 0:
            if round_zero_brief is not None:
                raise LeanMatrixError(
                    "unexpected_round_zero_anchor", "round-zero briefs cannot depend on another brief",
                )
            trusted_original_context = implementer_context_id
        else:
            if not isinstance(round_zero_brief, RoleBriefV1):
                raise LeanMatrixError(
                    "round_zero_brief_required",
                    "repair rounds require the independently frozen round-zero implementer brief",
                )
            if (
                round_zero_brief.role != "implementer"
                or round_zero_brief.round != 0
                or round_zero_brief.intake_digest
                != semantic_digest(document_intake.to_dict())
                or round_zero_brief.execution_plan_digest
                != document_intake.execution_plan_digest
            ):
                raise LeanMatrixError(
                    "invalid_round_zero_brief",
                    "repair anchor must be the round-zero implementer brief for this intake",
                )
            trusted_original_context = round_zero_brief.implementer_context_id
        if (
            implementer_context_id != trusted_original_context
            or original_implementer_context_id != trusted_original_context
        ):
            raise LeanMatrixError(
                "implementer_context_changed", "repair rounds must retain the frozen original implementer",
            )
        if role == "specialist" and round_number != 0:
            raise LeanMatrixError("invalid_specialist_round", "specialist briefs are advisory round-zero evidence")
        intake_digest = _digest(data["intake_digest"], "intake_digest")
        execution_plan_digest = _digest(data["execution_plan_digest"], "execution_plan_digest")
        report_path = _relative_path(data["report_path"], "report_path")
        root = (
            f".ai/lean-matrix/{execution_plan_digest.removeprefix('sha256:')}/"
            f"{intake_digest.removeprefix('sha256:')}"
        )
        if role == "implementer":
            expected_report_path = (
                f"{root}/handoffs/implementer/{context_id}/round-{round_number}/handoff-report.json"
            )
        elif role == "reviewer":
            expected_report_path = (
                f"{root}/reviews/{context_id}/round-{round_number}/final-decision.json"
            )
        else:
            assert specialist_domain is not None
            expected_report_path = (
                f"{root}/handoffs/specialists/{specialist_domain}/{context_id}/"
                "round-0/handoff-report.json"
            )
        if report_path != expected_report_path:
            raise LeanMatrixError(
                "brief_report_path_mismatch", "role brief report path is not its exact derived path",
            )
        selected_context = _strings(data["selected_context"], "selected_context", allow_empty=False)
        trusted_allowed_paths = _relative_paths(
            data["trusted_allowed_paths"], "trusted_allowed_paths", allow_empty=False,
        )
        trusted_forbidden_paths = _relative_paths(
            data["trusted_forbidden_paths"], "trusted_forbidden_paths",
        )
        acceptance_criteria = _strings(
            data["acceptance_criteria"], "acceptance_criteria", allow_empty=False,
        )
        expected_context = [
            canonical_json({"field": "task_id", "value": document_intake.task_id}),
            canonical_json({"field": "delivery_mode", "value": document_intake.delivery_mode}),
            canonical_json({"field": "role", "value": role}),
        ]
        if specialist_domain is not None:
            expected_context.append(
                canonical_json({"field": "specialist_domain", "value": specialist_domain}),
            )
        declared_specialists = tuple(dict.fromkeys(document_intake.execution_plan.dispatch.specialists))
        if len(declared_specialists) > 2:
            raise LeanMatrixError(
                "split_required", "a third independent specialist domain requires a separate delivery split",
            )
        if (
            intake_digest != semantic_digest(document_intake.to_dict())
            or execution_plan_digest != document_intake.execution_plan_digest
            or trusted_allowed_paths != document_intake.execution_plan.scope.allowed_paths
            or trusted_forbidden_paths != document_intake.execution_plan.scope.forbidden_paths
            or acceptance_criteria != document_intake.execution_plan.validation.required_checks
            or selected_context != tuple(expected_context)
            or tuple(domain for domain, _ in specialist_context_tuple) != declared_specialists
            or (specialist_domain is not None and specialist_domain not in declared_specialists)
        ):
            raise LeanMatrixError(
                "brief_intake_mismatch", "role brief context or scope does not match its trusted intake",
            )
        if role == "specialist":
            specialist_context_by_domain = dict(specialist_context_tuple)
            if specialist_context_by_domain[specialist_domain] != context_id:
                raise LeanMatrixError(
                    "specialist_context_mismatch",
                    "specialist domain must remain bound to its exact assigned context",
                )
        provisional = object.__new__(cls)
        validated_values = {
            "schema_version": _schema_version(data["schema_version"], "role brief"),
            "intake_digest": intake_digest,
            "execution_plan_digest": execution_plan_digest,
            "role": role,
            "specialist_domain": specialist_domain,
            "context_id": context_id,
            "implementer_context_id": implementer_context_id,
            "reviewer_context_id": reviewer_context_id,
            "original_implementer_context_id": original_implementer_context_id,
            "specialist_contexts": specialist_context_tuple,
            "round": round_number,
            "selected_context": selected_context,
            "trusted_allowed_paths": trusted_allowed_paths,
            "trusted_forbidden_paths": trusted_forbidden_paths,
            "acceptance_criteria": acceptance_criteria,
            "report_path": report_path,
            "predecessor_decision_digest": predecessor,
        }
        for field, value in validated_values.items():
            object.__setattr__(provisional, field, value)
        return provisional

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intake_digest": self.intake_digest,
            "execution_plan_digest": self.execution_plan_digest,
            "role": self.role,
            "specialist_domain": self.specialist_domain,
            "context_id": self.context_id,
            "implementer_context_id": self.implementer_context_id,
            "reviewer_context_id": self.reviewer_context_id,
            "original_implementer_context_id": self.original_implementer_context_id,
            "specialist_contexts": [
                {"domain": domain, "context_id": context}
                for domain, context in self.specialist_contexts
            ],
            "round": self.round,
            "selected_context": list(self.selected_context),
            "trusted_allowed_paths": list(self.trusted_allowed_paths),
            "trusted_forbidden_paths": list(self.trusted_forbidden_paths),
            "acceptance_criteria": list(self.acceptance_criteria),
            "report_path": self.report_path,
            "predecessor_decision_digest": self.predecessor_decision_digest,
        }

    @property
    def specialist_context_ids(self) -> tuple[str, ...]:
        return tuple(context for _, context in self.specialist_contexts)


@dataclass(frozen=True, slots=True, init=False)
class HandoffReportV1:
    schema_version: int
    report_kind: str
    specialist_domain: str | None
    intake_digest: str
    brief_digest: str
    context_id: str
    round: int
    report_path: str
    exact_head_sha: str
    changed_paths: tuple[str, ...]
    test_evidence: tuple[str, ...]
    advisory_evidence_digests: tuple[str, ...]
    status: str
    concerns: tuple[str, ...]
    predecessor_decision_digest: str | None

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "report_kind", "specialist_domain", "intake_digest", "brief_digest",
        "context_id", "round", "report_path", "exact_head_sha", "changed_paths", "test_evidence",
        "advisory_evidence_digests", "status", "concerns", "predecessor_decision_digest",
    })

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        role_brief: RoleBriefV1,
        expected_head_sha: object | None = None,
    ) -> HandoffReportV1:
        data = _require_mapping(raw, "handoff report")
        _require_keys(data, cls.KEYS, "handoff report")
        if not isinstance(role_brief, RoleBriefV1):
            raise LeanMatrixError("invalid_role_brief", "role_brief must be a trusted RoleBriefV1")
        brief = role_brief
        if brief.role not in HANDOFF_KINDS:
            raise LeanMatrixError("invalid_handoff_role", "reviewers produce decisions, not handoff reports")
        report_kind = _status(data["report_kind"], "report_kind", HANDOFF_KINDS)
        specialist_domain = (
            None
            if data["specialist_domain"] is None
            else _identifier(data["specialist_domain"], "specialist_domain")
        )
        if (report_kind == "specialist") != (specialist_domain is not None):
            raise LeanMatrixError(
                "invalid_specialist_identity",
                "specialist reports require specialist_domain and implementer reports forbid it",
            )
        round_number = _round(data["round"])
        exact_head = _sha(data["exact_head_sha"], "exact_head_sha")
        assert exact_head is not None
        if expected_head_sha is not None and exact_head != _sha(expected_head_sha, "expected_head_sha"):
            raise LeanMatrixError("stale_report_head", "work report exact head does not match the expected head")
        predecessor = (
            None
            if data["predecessor_decision_digest"] is None
            else _digest(data["predecessor_decision_digest"], "predecessor_decision_digest")
        )
        if (round_number == 0) != (predecessor is None):
            raise LeanMatrixError(
                "invalid_predecessor", "round zero forbids a predecessor digest and later rounds require one",
            )
        advisory_digests = _digests(data["advisory_evidence_digests"], "advisory_evidence_digests")
        if report_kind == "specialist" and (round_number != 0 or advisory_digests):
            raise LeanMatrixError(
                "invalid_specialist_report",
                "specialist reports are round-zero advisory evidence and cannot depend on advisory evidence",
            )
        from .digests import semantic_digest

        intake_digest = _digest(data["intake_digest"], "intake_digest")
        brief_digest = _digest(data["brief_digest"], "brief_digest")
        context_id = _identifier(data["context_id"], "context_id")
        report_path = _relative_path(data["report_path"], "report_path")
        if (
            report_kind != brief.role
            or specialist_domain != brief.specialist_domain
            or intake_digest != brief.intake_digest
            or brief_digest != semantic_digest(brief.to_dict())
            or context_id != brief.context_id
            or round_number != brief.round
            or report_path != brief.report_path
            or predecessor != brief.predecessor_decision_digest
        ):
            raise LeanMatrixError(
                "handoff_brief_mismatch",
                "handoff identity and provenance must exactly match its role brief",
            )
        provisional = object.__new__(cls)
        validated_values = {
            "schema_version": _schema_version(data["schema_version"], "handoff report"),
            "report_kind": report_kind,
            "specialist_domain": specialist_domain,
            "intake_digest": intake_digest,
            "brief_digest": brief_digest,
            "context_id": context_id,
            "round": round_number,
            "report_path": report_path,
            "exact_head_sha": exact_head,
            "changed_paths": _relative_paths(data["changed_paths"], "changed_paths"),
            "test_evidence": _strings(data["test_evidence"], "test_evidence"),
            "advisory_evidence_digests": advisory_digests,
            "status": _status(data["status"], "status", HANDOFF_STATUSES),
            "concerns": _strings(data["concerns"], "concerns"),
            "predecessor_decision_digest": predecessor,
        }
        for field, value in validated_values.items():
            object.__setattr__(provisional, field, value)
        return provisional

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_kind": self.report_kind,
            "specialist_domain": self.specialist_domain,
            "intake_digest": self.intake_digest,
            "brief_digest": self.brief_digest,
            "context_id": self.context_id,
            "round": self.round,
            "report_path": self.report_path,
            "exact_head_sha": self.exact_head_sha,
            "changed_paths": list(self.changed_paths),
            "test_evidence": list(self.test_evidence),
            "advisory_evidence_digests": list(self.advisory_evidence_digests),
            "status": self.status,
            "concerns": list(self.concerns),
            "predecessor_decision_digest": self.predecessor_decision_digest,
        }


@dataclass(frozen=True, slots=True)
class _ArtifactReceiptV1:
    path: str
    digest: str

    KEYS: ClassVar[frozenset[str]] = frozenset({"path", "digest"})

    @classmethod
    def from_mapping(cls, raw: object, field: str) -> _ArtifactReceiptV1:
        data = _require_mapping(raw, field)
        _require_keys(data, cls.KEYS, field)
        return cls(
            path=_relative_path(data["path"], f"{field}.path"),
            digest=_digest(data["digest"], f"{field}.digest"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "digest": self.digest}


def _artifact_receipts(value: object, field: str) -> tuple[_ArtifactReceiptV1, ...]:
    if not isinstance(value, list) or not value:
        raise LeanMatrixError(
            "invalid_artifact_receipts", f"{field} must be a non-empty JSON list",
        )
    return tuple(
        _ArtifactReceiptV1.from_mapping(item, f"{field} item") for item in value
    )


MAX_TEST_RECEIPT_BYTES = 8 * 1024 * 1024
TEST_RECEIPT_KEYS = frozenset({
    "schema_version", "required_check", "exact_head_sha", "status", "exit_code",
})


def validate_handoff_test_receipts(
    repo_root: Path,
    document_intake: DocumentIntakeV1,
    handoff: HandoffReportV1,
    *,
    exact_head_sha: str,
) -> tuple[_ArtifactReceiptV1, ...]:
    """Validate strict successful receipt JSON before reading any untrusted path."""
    if not isinstance(repo_root, Path):
        raise LeanMatrixError("invalid_repository_root", "repo_root must be a pathlib.Path")
    if not isinstance(document_intake, DocumentIntakeV1):
        raise LeanMatrixError("invalid_document_intake", "test receipts require a trusted intake")
    if not isinstance(handoff, HandoffReportV1):
        raise LeanMatrixError("invalid_handoff", "test receipts require a trusted handoff")
    exact_head = _sha(exact_head_sha, "exact_head_sha")
    assert exact_head is not None
    from .workspace import intake_workspace

    repo = repo_root.resolve()
    workspace = intake_workspace(repo, document_intake)
    required_checks = document_intake.execution_plan.validation.required_checks
    if not required_checks or len(required_checks) != len(set(required_checks)):
        raise LeanMatrixError(
            "invalid_required_checks", "trusted required checks must be non-empty and unique",
        )
    if len(handoff.test_evidence) != len(required_checks):
        raise LeanMatrixError(
            "required_check_coverage_missing",
            "every handoff must provide exactly one receipt for each trusted required check",
        )
    receipts: list[_ArtifactReceiptV1] = []
    observed_checks: list[str] = []
    for raw_path in handoff.test_evidence:
        relative = _relative_path(raw_path, "test receipt path")
        candidate = repo.joinpath(*PurePosixPath(relative).parts)
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise LeanMatrixError(
                "test_receipt_outside_workspace",
                "test receipts must stay below the exact intake workspace",
            ) from exc
        current = repo
        for component in PurePosixPath(relative).parts[:-1]:
            current /= component
            try:
                metadata = current.lstat()
            except FileNotFoundError as exc:
                raise LeanMatrixError(
                    "test_receipt_missing", "test receipt parent path is missing",
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise LeanMatrixError(
                    "test_receipt_symlink", "test receipt paths must not contain symlinks",
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise LeanMatrixError(
                    "test_receipt_not_regular", "test receipt parent must be a directory",
                )
        try:
            metadata = candidate.lstat()
        except FileNotFoundError as exc:
            raise LeanMatrixError("test_receipt_missing", "test receipt is missing") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise LeanMatrixError("test_receipt_symlink", "test receipt must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise LeanMatrixError("test_receipt_not_regular", "test receipt must be a regular file")
        if metadata.st_size > MAX_TEST_RECEIPT_BYTES:
            raise LeanMatrixError(
                "test_receipt_too_large", "test receipt exceeds the 8 MiB limit",
            )
        try:
            content = candidate.read_bytes()
            raw_receipt = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LeanMatrixError(
                "test_receipt_invalid", "test receipt must contain valid UTF-8 JSON",
            ) from exc
        receipt = _require_mapping(raw_receipt, "test receipt")
        _require_keys(receipt, TEST_RECEIPT_KEYS, "test receipt")
        _schema_version(receipt["schema_version"], "test receipt")
        required_check = _string(receipt["required_check"], "required_check")
        receipt_head = _sha(receipt["exact_head_sha"], "receipt.exact_head_sha")
        if receipt_head != exact_head:
            raise LeanMatrixError(
                "test_receipt_head_mismatch", "test receipt must bind the exact reviewed HEAD",
            )
        if receipt["status"] != "PASS" or type(receipt["exit_code"]) is not int or receipt["exit_code"] != 0:
            raise LeanMatrixError(
                "test_receipt_failed", "test receipt must record PASS with exit_code zero",
            )
        observed_checks.append(required_check)
        receipts.append(_ArtifactReceiptV1(
            path=relative,
            digest="sha256:" + hashlib.sha256(content).hexdigest(),
        ))
    if set(observed_checks) != set(required_checks) or len(observed_checks) != len(set(observed_checks)):
        raise LeanMatrixError(
            "required_check_coverage_missing",
            "test receipts must cover every trusted required check exactly once",
        )
    return tuple(receipts)


@dataclass(frozen=True, slots=True, init=False)
class ReviewPackageV1:
    schema_version: int
    execution_plan_digest: str
    intake_digest: str
    task_brief_digest: str
    exact_base_sha: str
    exact_head_sha: str
    round: int
    implementer_context_id: str
    reviewer_context_id: str
    changed_paths: tuple[str, ...]
    diff_digest: str
    test_receipts: tuple[_ArtifactReceiptV1, ...]
    implementer_handoff_digest: str
    specialist_evidence_digests: tuple[str, ...]

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "execution_plan_digest", "intake_digest", "task_brief_digest",
        "exact_base_sha", "exact_head_sha", "round", "implementer_context_id",
        "reviewer_context_id", "changed_paths", "diff_digest", "test_receipts",
        "implementer_handoff_digest", "specialist_evidence_digests",
    })

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        repo_root: Path,
        document_intake: DocumentIntakeV1,
        implementer_brief: RoleBriefV1,
        implementer_handoff: HandoffReportV1,
        reviewer_brief: RoleBriefV1,
        specialist_evidence: tuple[tuple[RoleBriefV1, HandoffReportV1], ...] = (),
        require_current_head: bool = True,
    ) -> ReviewPackageV1:
        data = _require_mapping(raw, "review package")
        _require_keys(data, cls.KEYS, "review package")
        if not isinstance(document_intake, DocumentIntakeV1):
            raise LeanMatrixError(
                "invalid_document_intake", "review package requires one trusted document intake",
            )
        if not isinstance(implementer_brief, RoleBriefV1) or implementer_brief.role != "implementer":
            raise LeanMatrixError(
                "invalid_implementer_brief", "review package requires a trusted implementer brief",
            )
        if not isinstance(reviewer_brief, RoleBriefV1) or reviewer_brief.role != "reviewer":
            raise LeanMatrixError(
                "invalid_reviewer_brief", "review package requires a trusted reviewer brief",
            )
        if not isinstance(implementer_handoff, HandoffReportV1):
            raise LeanMatrixError(
                "invalid_implementer_handoff", "review package requires a trusted handoff",
            )
        from .briefs import intake_digest
        from .digests import semantic_digest
        from .review_git import (
            is_ancestor,
            observe_current_head,
            observe_exact_diff,
            validate_worktree_clean,
        )
        from .scope import scope_allows
        from .workspace import intake_workspace

        exact_base = _sha(data["exact_base_sha"], "exact_base_sha")
        exact_head = _sha(data["exact_head_sha"], "exact_head_sha")
        assert exact_base is not None and exact_head is not None
        if exact_base != document_intake.develop_sha:
            raise LeanMatrixError(
                "stale_package_base", "review package base must equal the trusted intake base",
            )
        if not is_ancestor(repo_root, exact_base, exact_head):
            raise LeanMatrixError(
                "package_base_not_ancestor",
                "trusted intake base must be an ancestor of the exact reviewed HEAD",
            )
        if require_current_head and exact_head != observe_current_head(repo_root):
            raise LeanMatrixError(
                "stale_package_head", "review package must bind the current local exact HEAD",
            )
        workspace = intake_workspace(repo_root, document_intake)
        if require_current_head:
            validate_worktree_clean(repo_root, workspace)
        observation = observe_exact_diff(repo_root, exact_base, exact_head)
        changed_paths = _relative_paths(data["changed_paths"], "changed_paths", allow_empty=False)
        if changed_paths != tuple(sorted(changed_paths)):
            raise LeanMatrixError(
                "changed_paths_unsorted", "review package changed paths must be sorted",
            )
        if changed_paths != observation.changed_paths:
            raise LeanMatrixError(
                "stored_package_git_mismatch", "review package paths differ from exact Git evidence",
            )
        if _digest(data["diff_digest"], "diff_digest") != observation.diff_digest:
            raise LeanMatrixError(
                "stored_package_git_mismatch", "review package diff digest differs from exact Git evidence",
            )
        for path in changed_paths:
            if scope_allows(path, document_intake.execution_plan.scope.forbidden_paths):
                raise LeanMatrixError(
                    "changed_path_forbidden", "exact Git diff includes a forbidden path",
                )
            if not scope_allows(path, document_intake.trusted_allowed_paths):
                raise LeanMatrixError(
                    "changed_path_out_of_scope", "exact Git diff escaped trusted intake scope",
                )
        supplied_intake_digest = _digest(data["intake_digest"], "intake_digest")
        task_brief_digest = _digest(data["task_brief_digest"], "task_brief_digest")
        implementer_digest = _digest(
            data["implementer_handoff_digest"], "implementer_handoff_digest",
        )
        specialist_digests = _digests(
            data["specialist_evidence_digests"], "specialist_evidence_digests",
        )
        implementer_context = _identifier(
            data["implementer_context_id"], "implementer_context_id",
        )
        reviewer_context = _identifier(data["reviewer_context_id"], "reviewer_context_id")
        round_number = _round(data["round"])
        if implementer_context == reviewer_context:
            raise LeanMatrixError("context_reuse", "implementer and reviewer contexts must differ")
        if implementer_handoff.changed_paths != changed_paths:
            raise LeanMatrixError(
                "handoff_paths_mismatch",
                "implementer handoff paths must equal the sorted exact Git changed paths",
            )
        if (
            _digest(data["execution_plan_digest"], "execution_plan_digest")
            != document_intake.execution_plan_digest
            or supplied_intake_digest != intake_digest(document_intake)
            or task_brief_digest != semantic_digest(implementer_brief.to_dict())
            or implementer_brief.intake_digest != supplied_intake_digest
            or reviewer_brief.intake_digest != supplied_intake_digest
            or implementer_brief.round != round_number
            or reviewer_brief.round != round_number
            or implementer_context != implementer_brief.context_id
            or reviewer_context != reviewer_brief.context_id
            or implementer_handoff.intake_digest != supplied_intake_digest
            or implementer_handoff.brief_digest != task_brief_digest
            or implementer_handoff.context_id != implementer_context
            or implementer_handoff.round != round_number
            or implementer_handoff.exact_head_sha != exact_head
            or implementer_digest != semantic_digest(implementer_handoff.to_dict())
        ):
            raise LeanMatrixError(
                "review_evidence_mismatch",
                "review package identity and evidence must match its trusted intake, briefs, and handoff",
            )
        if implementer_handoff.status not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise LeanMatrixError(
                "handoff_incomplete", "only completed implementer handoffs are reviewable",
            )
        receipts = _artifact_receipts(data["test_receipts"], "test_receipts")
        if tuple(receipt.path for receipt in receipts) != implementer_handoff.test_evidence:
            raise LeanMatrixError(
                "test_receipt_mismatch", "test receipts must exactly match the handoff evidence list",
            )
        trusted_receipts = validate_handoff_test_receipts(
            repo_root, document_intake, implementer_handoff, exact_head_sha=exact_head,
        )
        if receipts != trusted_receipts:
            raise LeanMatrixError(
                "test_receipt_digest_mismatch",
                "stored test receipt bindings do not match validated local receipt bytes",
            )
        expected_specialist_digests: list[str] = []
        expected_domains = tuple(domain for domain, _ in implementer_brief.specialist_contexts)
        actual_domains: list[str] = []
        implementation_contexts = {implementer_context}
        for brief, report in specialist_evidence:
            if (
                not isinstance(brief, RoleBriefV1)
                or not isinstance(report, HandoffReportV1)
                or brief.role != "specialist"
                or report.report_kind != "specialist"
                or brief.specialist_domain != report.specialist_domain
                or brief.context_id != report.context_id
                or brief.intake_digest != supplied_intake_digest
                or report.intake_digest != supplied_intake_digest
                or report.brief_digest != semantic_digest(brief.to_dict())
                or report.exact_head_sha != exact_head
                or report.changed_paths
                or report.status not in {"DONE", "DONE_WITH_CONCERNS"}
            ):
                raise LeanMatrixError(
                    "specialist_evidence_mismatch", "specialist evidence is incomplete or cross-wired",
                )
            assert brief.specialist_domain is not None
            validate_handoff_test_receipts(
                repo_root, document_intake, report, exact_head_sha=exact_head,
            )
            actual_domains.append(brief.specialist_domain)
            implementation_contexts.add(brief.context_id)
            expected_specialist_digests.append(semantic_digest(report.to_dict()))
        if (
            tuple(actual_domains) != expected_domains
            or specialist_digests != tuple(expected_specialist_digests)
            or implementer_handoff.advisory_evidence_digests != specialist_digests
        ):
            raise LeanMatrixError(
                "specialist_evidence_mismatch", "package must bind every specialist in trusted order",
            )
        if reviewer_context in implementation_contexts:
            raise LeanMatrixError(
                "context_reuse", "reviewer context cannot reuse implementation-side context",
            )
        provisional = object.__new__(cls)
        values = {
            "schema_version": _schema_version(data["schema_version"], "review package"),
            "execution_plan_digest": document_intake.execution_plan_digest,
            "intake_digest": supplied_intake_digest,
            "task_brief_digest": task_brief_digest,
            "exact_base_sha": exact_base,
            "exact_head_sha": exact_head,
            "round": round_number,
            "implementer_context_id": implementer_context,
            "reviewer_context_id": reviewer_context,
            "changed_paths": changed_paths,
            "diff_digest": observation.diff_digest,
            "test_receipts": receipts,
            "implementer_handoff_digest": implementer_digest,
            "specialist_evidence_digests": specialist_digests,
        }
        for field, value in values.items():
            object.__setattr__(provisional, field, value)
        return provisional

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_plan_digest": self.execution_plan_digest,
            "intake_digest": self.intake_digest,
            "task_brief_digest": self.task_brief_digest,
            "exact_base_sha": self.exact_base_sha,
            "exact_head_sha": self.exact_head_sha,
            "round": self.round,
            "implementer_context_id": self.implementer_context_id,
            "reviewer_context_id": self.reviewer_context_id,
            "changed_paths": list(self.changed_paths),
            "diff_digest": self.diff_digest,
            "test_receipts": [receipt.to_dict() for receipt in self.test_receipts],
            "implementer_handoff_digest": self.implementer_handoff_digest,
            "specialist_evidence_digests": list(self.specialist_evidence_digests),
        }


FINAL_DECISIONS = frozenset({"允许集成 develop", "要求修正后再集成", "阻塞"})


@dataclass(frozen=True, slots=True, init=False)
class FinalDecisionV1:
    schema_version: int
    review_package_digest: str
    exact_head_sha: str
    implementer_context_id: str
    reviewer_context_id: str
    round: int
    spec_verdict: str
    quality_verdict: str
    findings: tuple[_ReviewFindingV1, ...]
    decision: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "review_package_digest", "exact_head_sha",
        "implementer_context_id", "reviewer_context_id", "round", "spec_verdict",
        "quality_verdict", "findings", "decision",
    })

    @classmethod
    def from_mapping(
        cls,
        raw: object,
        *,
        review_package: ReviewPackageV1,
    ) -> FinalDecisionV1:
        data = _require_mapping(raw, "final decision")
        _require_keys(data, cls.KEYS, "final decision")
        if not isinstance(review_package, ReviewPackageV1):
            raise LeanMatrixError(
                "invalid_review_package", "final decision requires a trusted review package",
            )
        from .digests import semantic_digest

        package_digest = _digest(data["review_package_digest"], "review_package_digest")
        exact_head = _sha(data["exact_head_sha"], "exact_head_sha")
        assert exact_head is not None
        implementer_context = _identifier(
            data["implementer_context_id"], "implementer_context_id",
        )
        reviewer_context = _identifier(data["reviewer_context_id"], "reviewer_context_id")
        round_number = _round(data["round"])
        if (
            package_digest != semantic_digest(review_package.to_dict())
            or exact_head != review_package.exact_head_sha
            or implementer_context != review_package.implementer_context_id
            or reviewer_context != review_package.reviewer_context_id
            or round_number != review_package.round
        ):
            raise LeanMatrixError(
                "review_package_mismatch", "final decision must exactly bind its review package",
            )
        spec_verdict = _status(data["spec_verdict"], "spec_verdict", SPEC_VERDICTS)
        quality_verdict = _status(
            data["quality_verdict"], "quality_verdict", QUALITY_VERDICTS,
        )
        findings = _findings(data["findings"], "findings")
        has_load_bearing = any(
            finding.severity in {"Critical", "Important"} for finding in findings
        )
        approved = (
            spec_verdict == "PASS"
            and quality_verdict == "APPROVED"
            and not has_load_bearing
        )
        if round_number == 3 and not approved:
            expected_decision = "阻塞"
        elif approved:
            expected_decision = "允许集成 develop"
        else:
            expected_decision = "要求修正后再集成"
        decision = _status(data["decision"], "decision", FINAL_DECISIONS)
        if decision != expected_decision:
            raise LeanMatrixError(
                "decision_mismatch", "decision must be derived from both verdicts, findings, and round",
            )
        provisional = object.__new__(cls)
        values = {
            "schema_version": _schema_version(data["schema_version"], "final decision"),
            "review_package_digest": package_digest,
            "exact_head_sha": exact_head,
            "implementer_context_id": implementer_context,
            "reviewer_context_id": reviewer_context,
            "round": round_number,
            "spec_verdict": spec_verdict,
            "quality_verdict": quality_verdict,
            "findings": findings,
            "decision": decision,
        }
        for field, value in values.items():
            object.__setattr__(provisional, field, value)
        return provisional

    @property
    def has_load_bearing_findings(self) -> bool:
        return any(finding.severity in {"Critical", "Important"} for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "review_package_digest": self.review_package_digest,
            "exact_head_sha": self.exact_head_sha,
            "implementer_context_id": self.implementer_context_id,
            "reviewer_context_id": self.reviewer_context_id,
            "round": self.round,
            "spec_verdict": self.spec_verdict,
            "quality_verdict": self.quality_verdict,
            "findings": [finding.to_dict() for finding in self.findings],
            "decision": self.decision,
        }


@dataclass(frozen=True, slots=True)
class ObservedStateV1:
    state_digest: str
    branch: str | None
    worktree: str | None
    base_sha: str
    dirty: bool
    changed_paths: tuple[str, ...]
    pr_number: int | None
    pr_head_sha: str | None
    ci_state: str
    review_state: str
    merge_state: str
    cleanup_safe: bool

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "state_digest", "branch", "worktree", "base_sha", "dirty", "changed_paths", "pr_number",
        "pr_head_sha", "ci_state", "review_state", "merge_state", "cleanup_safe",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> ObservedStateV1:
        data = _require_mapping(raw, "observed state")
        _require_keys(data, cls.KEYS, "observed state")
        base_sha = _sha(data["base_sha"], "base_sha")
        pr_head_sha = _sha(data["pr_head_sha"], "pr_head_sha", allow_none=True)
        assert base_sha is not None
        return cls(
            state_digest=_digest(data["state_digest"], "state_digest"),
            branch=None if data["branch"] is None else _branch(data["branch"], "branch"),
            worktree=None if data["worktree"] is None else _worktree(data["worktree"], "worktree"),
            base_sha=base_sha,
            dirty=_bool(data["dirty"], "dirty"),
            changed_paths=_relative_paths(data["changed_paths"], "changed_paths"),
            pr_number=_optional_positive_int(data["pr_number"], "pr_number"),
            pr_head_sha=pr_head_sha,
            ci_state=_status(data["ci_state"], "ci_state", CORE_STATES),
            review_state=_status(data["review_state"], "review_state", CORE_STATES),
            merge_state=_status(data["merge_state"], "merge_state", CORE_STATES),
            cleanup_safe=_bool(data["cleanup_safe"], "cleanup_safe"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "state_digest": self.state_digest,
            "branch": self.branch,
            "worktree": self.worktree,
            "base_sha": self.base_sha,
            "dirty": self.dirty,
            "changed_paths": list(self.changed_paths),
            "pr_number": self.pr_number,
            "pr_head_sha": self.pr_head_sha,
            "ci_state": self.ci_state,
            "review_state": self.review_state,
            "merge_state": self.merge_state,
            "cleanup_safe": self.cleanup_safe,
        }


@dataclass(frozen=True, slots=True)
class TransitionProposalV1:
    transition_id: str
    from_state_digest: str
    action: str
    commands: tuple[tuple[str, ...], ...]
    side_effect_scope: str
    requires_apply: bool
    human_gate: str | None

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "transition_id", "from_state_digest", "action", "commands", "side_effect_scope",
        "requires_apply", "human_gate",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> TransitionProposalV1:
        data = _require_mapping(raw, "transition proposal")
        _require_keys(data, cls.KEYS, "transition proposal")
        commands_raw = data["commands"]
        if not isinstance(commands_raw, list):
            raise LeanMatrixError("invalid_commands", "commands must be a JSON list of argv lists")
        commands = tuple(_strings(command, "command", allow_empty=False) for command in commands_raw)
        return cls(
            transition_id=_identifier(data["transition_id"], "transition_id"),
            from_state_digest=_digest(data["from_state_digest"], "from_state_digest"),
            action=_identifier(data["action"], "action"),
            commands=commands,
            side_effect_scope=_identifier(data["side_effect_scope"], "side_effect_scope"),
            requires_apply=_bool(data["requires_apply"], "requires_apply"),
            human_gate=_optional_string(data["human_gate"], "human_gate"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "from_state_digest": self.from_state_digest,
            "action": self.action,
            "commands": [list(command) for command in self.commands],
            "side_effect_scope": self.side_effect_scope,
            "requires_apply": self.requires_apply,
            "human_gate": self.human_gate,
        }


@dataclass(frozen=True, slots=True)
class TransitionReceiptV1:
    transition_id: str
    plan_digest: str
    before_state_digest: str
    after_state_digest: str
    command_digests: tuple[str, ...]
    exit_codes: tuple[int, ...]
    result: str
    recorded_at: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "transition_id", "plan_digest", "before_state_digest", "after_state_digest",
        "command_digests", "exit_codes", "result", "recorded_at",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> TransitionReceiptV1:
        data = _require_mapping(raw, "transition receipt")
        _require_keys(data, cls.KEYS, "transition receipt")
        command_digests_raw = data["command_digests"]
        exit_codes_raw = data["exit_codes"]
        if not isinstance(command_digests_raw, list) or not isinstance(exit_codes_raw, list):
            raise LeanMatrixError("invalid_receipt_commands", "command_digests and exit_codes must be JSON lists")
        command_digests = tuple(_digest(item, "command_digests item") for item in command_digests_raw)
        if any(type(code) is not int for code in exit_codes_raw):
            raise LeanMatrixError("invalid_exit_code", "exit_codes items must be integers")
        exit_codes = tuple(exit_codes_raw)
        if len(command_digests) != len(exit_codes):
            raise LeanMatrixError("receipt_length_mismatch", "command_digests and exit_codes must have equal length")
        recorded_at = _string(data["recorded_at"], "recorded_at")
        if not RECORDED_AT_RE.fullmatch(recorded_at):
            raise LeanMatrixError("invalid_recorded_at", "recorded_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
        return cls(
            transition_id=_identifier(data["transition_id"], "transition_id"),
            plan_digest=_digest(data["plan_digest"], "plan_digest"),
            before_state_digest=_digest(data["before_state_digest"], "before_state_digest"),
            after_state_digest=_digest(data["after_state_digest"], "after_state_digest"),
            command_digests=command_digests,
            exit_codes=exit_codes,
            result=_status(data["result"], "result", CORE_STATES),
            recorded_at=recorded_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "transition_id": self.transition_id,
            "plan_digest": self.plan_digest,
            "before_state_digest": self.before_state_digest,
            "after_state_digest": self.after_state_digest,
            "command_digests": list(self.command_digests),
            "exit_codes": list(self.exit_codes),
            "result": self.result,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class StageReportV1:
    schema_version: int
    task_id: str
    charter_digest: str
    plan_digest: str
    exact_head_sha: str
    code_state: str
    tests_state: str
    ci_state: str
    review_state: str
    real_gate_state: str
    release_state: str
    runtime_state: str
    completed: tuple[str, ...]
    verification_evidence: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    user_actions: tuple[str, ...]
    automatic_next_step: str

    KEYS: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "task_id", "charter_digest", "plan_digest", "exact_head_sha",
        "code_state", "tests_state", "ci_state", "review_state", "real_gate_state",
        "release_state", "runtime_state", "completed", "verification_evidence",
        "remaining_risks", "user_actions", "automatic_next_step",
    })

    @classmethod
    def from_mapping(cls, raw: object) -> StageReportV1:
        data = _require_mapping(raw, "stage report")
        _require_keys(data, cls.KEYS, "stage report")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise LeanMatrixError("invalid_schema_version", "stage report schema_version must equal 1")
        exact_head_sha = _sha(data["exact_head_sha"], "exact_head_sha")
        assert exact_head_sha is not None
        return cls(
            schema_version=1,
            task_id=_identifier(data["task_id"], "task_id"),
            charter_digest=_digest(data["charter_digest"], "charter_digest"),
            plan_digest=_digest(data["plan_digest"], "plan_digest"),
            exact_head_sha=exact_head_sha,
            code_state=_status(data["code_state"], "code_state", CORE_STATES),
            tests_state=_status(data["tests_state"], "tests_state", CORE_STATES),
            ci_state=_status(data["ci_state"], "ci_state", CORE_STATES),
            review_state=_status(data["review_state"], "review_state", CORE_STATES),
            real_gate_state=_status(data["real_gate_state"], "real_gate_state", GATE_STATES),
            release_state=_status(data["release_state"], "release_state", GATE_STATES),
            runtime_state=_status(data["runtime_state"], "runtime_state", GATE_STATES),
            completed=_strings(data["completed"], "completed"),
            verification_evidence=_strings(data["verification_evidence"], "verification_evidence"),
            remaining_risks=_strings(data["remaining_risks"], "remaining_risks"),
            user_actions=_strings(data["user_actions"], "user_actions"),
            automatic_next_step=_string(data["automatic_next_step"], "automatic_next_step"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "charter_digest": self.charter_digest,
            "plan_digest": self.plan_digest,
            "exact_head_sha": self.exact_head_sha,
            "code_state": self.code_state,
            "tests_state": self.tests_state,
            "ci_state": self.ci_state,
            "review_state": self.review_state,
            "real_gate_state": self.real_gate_state,
            "release_state": self.release_state,
            "runtime_state": self.runtime_state,
            "completed": list(self.completed),
            "verification_evidence": list(self.verification_evidence),
            "remaining_risks": list(self.remaining_risks),
            "user_actions": list(self.user_actions),
            "automatic_next_step": self.automatic_next_step,
        }
