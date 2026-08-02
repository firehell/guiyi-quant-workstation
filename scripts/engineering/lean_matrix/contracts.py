"""Frozen, strict version-one contracts for Lean Matrix execution planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
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
