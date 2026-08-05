"""Read-only Audit V2 composition with stable finding codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.services.data_operations.contracts import (
    AuditRequest,
    AuditScope,
    CommandResult,
    CommandStatus,
    PublicError,
    empty_effects,
)


COMPONENT_SCOPES = (
    AuditScope.CATALOG,
    AuditScope.COVERAGE,
    AuditScope.SCHEMA,
    AuditScope.PHYSICAL,
    AuditScope.GAP,
)


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    scope: AuditScope
    facts: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "scope": self.scope.value,
            "facts": dict(self.facts),
        }


class _Checker(Protocol):
    def __call__(self, request: AuditRequest) -> Sequence[AuditFinding]: ...


class AuditV2ApplicationService:
    """Compose read-only catalog/coverage/schema/physical/gap checks."""

    def __init__(
        self,
        *,
        checkers: Mapping[AuditScope, _Checker],
        provider_factory: Callable[[], object] | None = None,
        mutating_repository: object | None = None,
    ) -> None:
        if provider_factory is not None:
            raise RuntimeError("AUDIT_PROVIDER_FORBIDDEN")
        if mutating_repository is not None:
            raise RuntimeError("AUDIT_MUTATING_REPOSITORY_FORBIDDEN")
        self._checkers = dict(checkers)
        self._repair_calls = 0

    def run(self, request: AuditRequest) -> CommandResult:
        scopes = COMPONENT_SCOPES if request.scope is AuditScope.ALL else (request.scope,)
        findings: list[AuditFinding] = []
        component_results: dict[str, list[dict[str, Any]]] = {}
        for scope in scopes:
            checker = self._checkers.get(scope)
            if checker is None:
                return CommandResult(
                    command="data.audit",
                    status=CommandStatus.ERROR,
                    readonly=True,
                    effects=empty_effects(),
                    error=PublicError(
                        code="AUDIT_SCOPE_UNAVAILABLE",
                        type="KeyError",
                    ),
                )
            scoped = tuple(checker(request))
            component_results[scope.value] = [item.as_payload() for item in scoped]
            findings.extend(scoped)

        status = CommandStatus.PASSED if not findings else CommandStatus.ERROR
        return CommandResult(
            command="data.audit",
            status=status,
            readonly=True,
            effects=empty_effects(),
            extras={
                "scope": request.scope.value,
                "components": list(component_results),
                "findings": [item.as_payload() for item in findings],
                "component_results": component_results,
                "repair_calls": self._repair_calls,
            },
        )

    def repair(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("AUDIT_REPAIR_FORBIDDEN")
