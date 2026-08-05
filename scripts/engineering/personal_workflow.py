#!/usr/bin/env python3
"""Shared fail-closed models for the personal engineering workflow.

The module is deliberately side-effect free. It classifies repository and
controlled operations, validates non-secret execution scopes, keeps explicit
intent only in process memory, and builds the stable engineering JSON result
schema. It does not read credentials, execute commands, or persist authority.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

SCHEMA_VERSION = 1
MAX_SCOPE_COMPONENT_LENGTH = 256
MAX_RESOURCE_BOUNDARY_ITEMS = 16
MAX_CHECK_DETAIL_LENGTH = 512
MAX_ERROR_DETAIL_LENGTH = 384


class OperationClass(StrEnum):
    """Top-level policy classification."""

    ORDINARY_REPOSITORY_CHANGE = "ordinary_repository_change"
    ORDINARY_REPOSITORY_DELETION = "ordinary_repository_deletion"
    CONTROLLED_EXTERNAL_ACTION = "controlled_external_action"
    BUSINESS_CORRECTNESS_CONSTRAINT = "business_correctness_constraint"


class OperationAction(StrEnum):
    MODIFY = "modify"
    DELETE = "delete"
    ENFORCE = "enforce"


class ResourceBoundary(StrEnum):
    REPOSITORY_TRACKED = "repository_tracked"
    BUSINESS_CORRECTNESS = "business_correctness"
    PRODUCTION_DATABASE = "production_database"
    FORMAL_MARKET_DATA = "formal_market_data"
    RUNTIME_STATE = "runtime_state"
    LIVE_CONFIGURATION = "live_configuration"
    NOTIFICATION_CHANNEL = "notification_channel"
    REMOTE_RELEASE_REF = "remote_release_ref"
    GIT_HISTORY = "git_history"
    GITHUB_RULES = "github_rules"


class OperationCategory(StrEnum):
    RELEASE_BRANCH = "release_branch"
    PUSH_TAG = "push_tag"
    FORCE_UPDATE = "force_update"
    PRODUCTION_DATA_WRITE = "production_data_write"
    PRODUCTION_DELETE = "production_delete"
    RUNTIME_SWITCH = "runtime_switch"
    LIVE_ENABLE = "live_enable"
    REAL_NOTIFICATION = "real_notification"
    GITHUB_RULE_CHANGE = "github_rule_change"


class IntentMode(StrEnum):
    MUTATION = "mutation"
    DRY_RUN = "dry_run"


class ResultMode(StrEnum):
    READ_ONLY = "read_only"
    DRY_RUN = "dry_run"
    MUTATION = "mutation"


class ResultStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARN = "warn"
    UNAVAILABLE = "unavailable"


class ToolOperation(StrEnum):
    POLICY = "policy"
    PREFLIGHT = "preflight"
    VALIDATE = "validate"
    CONSISTENCY = "consistency"
    SECRET_SCAN = "secret_scan"
    PUBLISH_BRANCH = "publish_branch"
    PUBLISH_TAG = "publish_tag"


class ErrorType(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_OPERATION = "invalid_operation"
    INVALID_SCOPE = "invalid_scope"
    INTENT_REQUIRED = "intent_required"
    INTENT_SESSION_MISMATCH = "intent_session_mismatch"
    INTENT_CONSUMED = "intent_consumed"
    DRY_RUN_REUSE = "dry_run_reuse"
    INTENT_MODE_MISMATCH = "intent_mode_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    BUSINESS_CONSTRAINT = "business_constraint"
    OPERATION_FAILED = "operation_failed"
    OPERATION_BLOCKED = "operation_blocked"
    TOOL_UNAVAILABLE = "tool_unavailable"


class BusinessConstraint(StrEnum):
    AUTHENTICATION_VALID = "authentication_valid"
    INPUT_VALIDATION = "input_validation"
    DATA_QUALITY = "data_quality"
    DATA_GAP_CLEAR = "data_gap_clear"
    NO_FUTURE_DATA = "no_future_data"
    SECRETS_PROTECTED = "secrets_protected"
    OPERATIONAL_DEFAULTS = "operational_defaults"
    NO_ORDER = "no_order"
    HISTORICAL_LIVE_SEPARATION = "historical_live_separation"
    CATEGORY_SEPARATION = "category_separation"


class ConstraintStatus(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    MISSING = "missing"
    MALFORMED = "malformed"


EnumT = TypeVar("EnumT", bound=StrEnum)


def _closed_enum(enum_type: type[EnumT], value: object, *, field_name: str) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise PolicyError(
            ErrorType.INVALID_INPUT,
            f"{field_name} must be a member of the closed {enum_type.__name__} enum",
        )
    try:
        return enum_type(value)
    except ValueError as exc:
        raise PolicyError(
            ErrorType.INVALID_INPUT,
            f"unknown {field_name}",
        ) from exc


def _normalize_component(
    value: object,
    *,
    field_name: str,
    max_length: int = MAX_SCOPE_COMPONENT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise PolicyError(ErrorType.INVALID_SCOPE, f"{field_name} must be text")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > max_length:
        raise PolicyError(
            ErrorType.INVALID_SCOPE,
            f"{field_name} must contain 1 to {max_length} characters",
        )
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise PolicyError(
            ErrorType.INVALID_SCOPE,
            f"{field_name} contains unsupported control characters",
        )
    return " ".join(normalized.split())


_EXTERNAL_CATEGORY_BY_RESOURCE: Mapping[ResourceBoundary, frozenset[OperationCategory]] = {
    ResourceBoundary.PRODUCTION_DATABASE: frozenset(
        {OperationCategory.PRODUCTION_DATA_WRITE, OperationCategory.PRODUCTION_DELETE}
    ),
    ResourceBoundary.FORMAL_MARKET_DATA: frozenset(
        {OperationCategory.PRODUCTION_DATA_WRITE, OperationCategory.PRODUCTION_DELETE}
    ),
    ResourceBoundary.RUNTIME_STATE: frozenset({OperationCategory.RUNTIME_SWITCH}),
    ResourceBoundary.LIVE_CONFIGURATION: frozenset({OperationCategory.LIVE_ENABLE}),
    ResourceBoundary.NOTIFICATION_CHANNEL: frozenset(
        {OperationCategory.REAL_NOTIFICATION}
    ),
    ResourceBoundary.REMOTE_RELEASE_REF: frozenset(
        {
            OperationCategory.RELEASE_BRANCH,
            OperationCategory.PUSH_TAG,
            OperationCategory.FORCE_UPDATE,
        }
    ),
    ResourceBoundary.GIT_HISTORY: frozenset({OperationCategory.FORCE_UPDATE}),
    ResourceBoundary.GITHUB_RULES: frozenset({OperationCategory.GITHUB_RULE_CHANGE}),
}


@dataclass(frozen=True, slots=True)
class OperationClassification:
    operation_class: OperationClass
    category: OperationCategory | None = None


def classify_operation(
    action: OperationAction | str,
    resource: ResourceBoundary | str,
    *,
    category: OperationCategory | str | None = None,
) -> OperationClassification:
    """Classify an operation without consulting collaboration metadata.

    External resources require an explicit, resource-compatible category.
    Repository-local changes and deletions reject an external category.
    """

    normalized_action = _closed_enum(OperationAction, action, field_name="action")
    normalized_resource = _closed_enum(ResourceBoundary, resource, field_name="resource")
    normalized_category = (
        None
        if category is None
        else _closed_enum(OperationCategory, category, field_name="category")
    )

    if normalized_resource is ResourceBoundary.REPOSITORY_TRACKED:
        if normalized_category is not None or normalized_action is OperationAction.ENFORCE:
            raise PolicyError(
                ErrorType.INVALID_OPERATION,
                "repository operations cannot carry external authority",
            )
        operation_class = (
            OperationClass.ORDINARY_REPOSITORY_DELETION
            if normalized_action is OperationAction.DELETE
            else OperationClass.ORDINARY_REPOSITORY_CHANGE
        )
        return OperationClassification(operation_class)

    if normalized_resource is ResourceBoundary.BUSINESS_CORRECTNESS:
        if normalized_action is not OperationAction.ENFORCE or normalized_category is not None:
            raise PolicyError(
                ErrorType.INVALID_OPERATION,
                "business correctness constraints can only be enforced",
            )
        return OperationClassification(OperationClass.BUSINESS_CORRECTNESS_CONSTRAINT)

    allowed_categories = _EXTERNAL_CATEGORY_BY_RESOURCE.get(normalized_resource)
    if normalized_category is None or allowed_categories is None:
        raise PolicyError(
            ErrorType.INVALID_OPERATION,
            "controlled external actions require an explicit category",
        )
    if normalized_category not in allowed_categories:
        raise PolicyError(
            ErrorType.INVALID_OPERATION,
            "operation category does not match the resource boundary",
        )
    if (
        normalized_category is OperationCategory.PRODUCTION_DELETE
        and normalized_action is not OperationAction.DELETE
    ) or (
        normalized_action is OperationAction.DELETE
        and normalized_category is not OperationCategory.PRODUCTION_DELETE
    ):
        raise PolicyError(
            ErrorType.INVALID_OPERATION,
            "delete action and category are inconsistent",
        )
    if normalized_action is OperationAction.ENFORCE:
        raise PolicyError(
            ErrorType.INVALID_OPERATION,
            "controlled external actions cannot use the enforce action",
        )
    return OperationClassification(
        OperationClass.CONTROLLED_EXTERNAL_ACTION,
        normalized_category,
    )


_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|cookie|license|authorization)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:password|passwd|token|api[_-]?key|secret|key|license)=)[^&#\s]+"
)
_URL_USERINFO_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
    re.DOTALL,
)
_TOKEN_FAMILY_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b")
_WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
_POSIX_USER_PATH_RE = re.compile(r"(?<!\w)/(?:home|Users)/[^/\s]+")
_PRIVATE_ADDRESS_RE = re.compile(
    r"\b(?:127\.0\.0\.1|10\.(?:\d{1,3}\.){2}\d{1,3}|"
    r"192\.168\.(?:\d{1,3}\.)\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3})\b"
)


def redact_text(value: object, *, max_length: int = MAX_CHECK_DETAIL_LENGTH) -> str:
    """Return one bounded line with common secret/internal details removed."""

    if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 32:
        raise PolicyError(ErrorType.INVALID_INPUT, "max_length must be an integer of at least 32")
    text = value if isinstance(value, str) else type(value).__name__
    text = _PRIVATE_KEY_RE.sub("<redacted-private-key>", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _SENSITIVE_QUERY_RE.sub(lambda match: f"{match.group(1)}<redacted>", text)
    text = _URL_USERINFO_RE.sub(lambda match: f"{match.group(1)}<redacted>@", text)
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _TOKEN_FAMILY_RE.sub("<redacted-token>", text)
    text = _WINDOWS_USER_PATH_RE.sub("<redacted-user-path>", text)
    text = _POSIX_USER_PATH_RE.sub("<redacted-user-path>", text)
    text = _PRIVATE_ADDRESS_RE.sub("<redacted-internal-address>", text)
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


class PolicyError(ValueError):
    """Bounded error safe to expose at a command or API boundary."""

    def __init__(self, error_type: ErrorType | str, detail: object) -> None:
        self.error_type = _closed_enum_without_policy_error(ErrorType, error_type)
        self.detail = redact_text(detail, max_length=MAX_ERROR_DETAIL_LENGTH)
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, str]:
        return {"type": self.error_type.value, "detail": self.detail}


def _closed_enum_without_policy_error(
    enum_type: type[EnumT], value: object
) -> EnumT:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            pass
    raise ValueError(f"unknown {enum_type.__name__}")


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    category: OperationCategory
    environment: str
    target: str
    resource_boundary: tuple[str, ...]

    def __post_init__(self) -> None:
        category = _closed_enum(OperationCategory, self.category, field_name="category")
        environment = _normalize_component(
            self.environment,
            field_name="environment",
            max_length=64,
        )
        target = _normalize_component(self.target, field_name="target")
        if not isinstance(self.resource_boundary, (tuple, list)):
            raise PolicyError(
                ErrorType.INVALID_SCOPE,
                "resource_boundary must be an ordered collection",
            )
        if not self.resource_boundary or len(self.resource_boundary) > MAX_RESOURCE_BOUNDARY_ITEMS:
            raise PolicyError(
                ErrorType.INVALID_SCOPE,
                f"resource_boundary must contain 1 to {MAX_RESOURCE_BOUNDARY_ITEMS} items",
            )
        resources = tuple(
            sorted(
                {
                    _normalize_component(item, field_name="resource_boundary item")
                    for item in self.resource_boundary
                }
            )
        )
        if len(resources) != len(self.resource_boundary):
            raise PolicyError(
                ErrorType.INVALID_SCOPE,
                "resource_boundary items must be unique after normalization",
            )
        public_values = (environment, target, *resources)
        if any(redact_text(value) != value for value in public_values):
            raise PolicyError(
                ErrorType.INVALID_SCOPE,
                "execution scope must not contain credentials or internal details",
            )
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "resource_boundary", resources)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "environment": self.environment,
            "target": self.target,
            "resource_boundary": list(self.resource_boundary),
        }


@dataclass(frozen=True, slots=True)
class ConstraintCheck:
    constraint: BusinessConstraint
    status: ConstraintStatus

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint",
            _closed_enum(BusinessConstraint, self.constraint, field_name="constraint"),
        )
        object.__setattr__(
            self,
            "status",
            _closed_enum(ConstraintStatus, self.status, field_name="constraint status"),
        )


def enforce_business_constraints(checks: Iterable[ConstraintCheck]) -> None:
    seen: set[BusinessConstraint] = set()
    for check in checks:
        if not isinstance(check, ConstraintCheck):
            raise PolicyError(
                ErrorType.BUSINESS_CONSTRAINT,
                "business constraint checks must use ConstraintCheck",
            )
        if check.constraint in seen:
            raise PolicyError(
                ErrorType.BUSINESS_CONSTRAINT,
                "business constraint checks must be unique",
            )
        seen.add(check.constraint)
        if check.status is not ConstraintStatus.SATISFIED:
            raise PolicyError(
                ErrorType.BUSINESS_CONSTRAINT,
                f"{check.constraint.value} is {check.status.value}",
            )


@dataclass(slots=True)
class ExplicitIntent:
    """One in-memory intent issued by exactly one :class:`IntentState`."""

    scope: ExecutionScope
    mode: IntentMode
    _session_token: object = field(repr=False, compare=False)
    _consumed: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def consumed(self) -> bool:
        return self._consumed


@dataclass(frozen=True, slots=True)
class AuthorizedAttempt:
    scope: ExecutionScope
    mode: IntentMode


class IntentState:
    """In-process issuer/consumer; replacing the instance starts a new session."""

    __slots__ = ("_session_token",)

    def __init__(self) -> None:
        self._session_token = object()

    def issue(
        self,
        scope: ExecutionScope,
        *,
        mode: IntentMode | str = IntentMode.MUTATION,
    ) -> ExplicitIntent:
        if not isinstance(scope, ExecutionScope):
            raise PolicyError(ErrorType.INVALID_SCOPE, "intent requires a validated scope")
        normalized_mode = _closed_enum(IntentMode, mode, field_name="intent mode")
        return ExplicitIntent(scope, normalized_mode, self._session_token)

    def consume_for_attempt(
        self,
        intent: ExplicitIntent | None,
        scope: ExecutionScope,
        *,
        mode: IntentMode | str,
        constraints: Iterable[ConstraintCheck],
    ) -> AuthorizedAttempt:
        if not isinstance(scope, ExecutionScope):
            raise PolicyError(ErrorType.INVALID_SCOPE, "attempt requires a validated scope")
        normalized_mode = _closed_enum(IntentMode, mode, field_name="attempt mode")
        enforce_business_constraints(constraints)
        if intent is None or not isinstance(intent, ExplicitIntent):
            raise PolicyError(ErrorType.INTENT_REQUIRED, "explicit execution intent is required")
        if intent._session_token is not self._session_token:
            raise PolicyError(
                ErrorType.INTENT_SESSION_MISMATCH,
                "intent belongs to a different in-memory session",
            )
        if intent._consumed:
            error_type = (
                ErrorType.DRY_RUN_REUSE
                if intent.mode is IntentMode.DRY_RUN
                else ErrorType.INTENT_CONSUMED
            )
            raise PolicyError(error_type, "intent has already been consumed")

        # Consume before matching so a changed-scope or mode probe cannot be retried.
        intent._consumed = True
        if intent.mode is not normalized_mode:
            raise PolicyError(
                ErrorType.INTENT_MODE_MISMATCH,
                "dry-run and mutation intent cannot be converted or reused",
            )
        if intent.scope != scope:
            raise PolicyError(
                ErrorType.SCOPE_MISMATCH,
                "attempt scope does not match explicit execution intent",
            )
        return AuthorizedAttempt(scope, normalized_mode)


@dataclass(frozen=True, slots=True)
class BoundedError:
    error_type: ErrorType
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "error_type",
            _closed_enum(ErrorType, self.error_type, field_name="error type"),
        )
        object.__setattr__(
            self,
            "detail",
            redact_text(self.detail, max_length=MAX_ERROR_DETAIL_LENGTH),
        )

    @classmethod
    def from_exception(cls, error: PolicyError) -> BoundedError:
        if not isinstance(error, PolicyError):
            raise PolicyError(
                ErrorType.INVALID_INPUT,
                "only bounded PolicyError instances may cross the result boundary",
            )
        return cls(error.error_type, error.detail)

    def to_dict(self) -> dict[str, str]:
        return {"type": self.error_type.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _normalize_component(self.name, field_name="check name", max_length=96),
        )
        object.__setattr__(
            self,
            "status",
            _closed_enum(CheckStatus, self.status, field_name="check status"),
        )
        object.__setattr__(
            self,
            "detail",
            redact_text(self.detail, max_length=MAX_CHECK_DETAIL_LENGTH),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


_TOOL_PATH_RE = re.compile(r"scripts/engineering/[A-Za-z0-9_.-]+\.(?:ps1|py)\Z")


@dataclass(frozen=True, slots=True)
class StableResult:
    tool: str
    operation: ToolOperation
    mode: ResultMode
    status: ResultStatus
    checks: tuple[CheckResult, ...] = ()
    scope: ExecutionScope | None = None
    error: BoundedError | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tool, str) or _TOOL_PATH_RE.fullmatch(self.tool) is None:
            raise PolicyError(
                ErrorType.INVALID_INPUT,
                "tool must be a repository-relative engineering script path",
            )
        operation = _closed_enum(ToolOperation, self.operation, field_name="operation")
        mode = _closed_enum(ResultMode, self.mode, field_name="result mode")
        status = _closed_enum(ResultStatus, self.status, field_name="result status")
        if not isinstance(self.checks, (tuple, list)) or any(
            not isinstance(check, CheckResult) for check in self.checks
        ):
            raise PolicyError(
                ErrorType.INVALID_INPUT,
                "checks must contain only CheckResult values",
            )
        checks = tuple(self.checks)
        if self.scope is not None and not isinstance(self.scope, ExecutionScope):
            raise PolicyError(ErrorType.INVALID_SCOPE, "result scope must be validated")
        if self.error is not None and not isinstance(self.error, BoundedError):
            raise PolicyError(ErrorType.INVALID_INPUT, "result error must be bounded")
        if status is ResultStatus.OK and any(
            check.status in {CheckStatus.FAILED, CheckStatus.UNAVAILABLE}
            for check in checks
        ):
            raise PolicyError(
                ErrorType.INVALID_INPUT,
                "ok result cannot contain failed or unavailable checks",
            )
        if status is ResultStatus.BLOCKED and self.error is None:
            raise PolicyError(ErrorType.INVALID_INPUT, "blocked result requires a bounded error")
        if status is ResultStatus.UNAVAILABLE and not (
            self.error is not None
            or any(check.status is CheckStatus.UNAVAILABLE for check in checks)
        ):
            raise PolicyError(
                ErrorType.INVALID_INPUT,
                "unavailable result requires an unavailable check or bounded error",
            )
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "checks", checks)

    def to_dict(self) -> dict[str, Any]:
        summary = {
            "passed": sum(check.status is CheckStatus.PASSED for check in self.checks),
            "failed": sum(check.status is CheckStatus.FAILED for check in self.checks),
            "warn": sum(check.status is CheckStatus.WARN for check in self.checks),
            "unavailable": sum(
                check.status is CheckStatus.UNAVAILABLE for check in self.checks
            ),
        }
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tool": self.tool,
            "operation": self.operation.value,
            "mode": self.mode.value,
            "status": self.status.value,
            "summary": summary,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.scope is not None:
            payload["scope"] = self.scope.to_public_dict()
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
