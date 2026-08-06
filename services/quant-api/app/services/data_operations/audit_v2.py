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


def build_catalog_audit_checkers(
    *,
    catalog: object,
    strict_probe: Callable[[object], bool] | None = None,
) -> dict[AuditScope, _Checker]:
    """Build the read-only V2 audit checks over Catalog and Canonical reader."""

    def selected(request: AuditRequest) -> tuple[object, ...]:
        rows: list[object] = []
        for symbol in request.symbols:
            rows.extend(catalog.list_datasets(symbol=symbol.strip().lower()))
        return tuple(rows)

    def targets(request: AuditRequest) -> tuple[object, ...]:
        from app.data_core.contracts import BarFrequency, DatasetKind
        result: list[object] = []
        for row in selected(request):
            if request.dataset_kind is not None and getattr(row, "dataset_kind") != request.dataset_kind.value:
                continue
            if request.frequency is not None and getattr(row, "frequency") != request.frequency.value:
                continue
            result.append(
                (DatasetKind(getattr(row, "dataset_kind")), BarFrequency(getattr(row, "frequency")), row)
            )
        return tuple(result)

    def missing_symbols(request: AuditRequest, scope: AuditScope) -> list[AuditFinding]:
        present = {getattr(row, "symbol") for row in selected(request)}
        return [
            AuditFinding("AUDIT_CATALOG_DATASET_MISSING", scope, {"symbol": symbol})
            for symbol in request.symbols
            if symbol.strip().lower() not in present
        ]

    def catalog_check(request: AuditRequest) -> Sequence[AuditFinding]:
        if not request.symbols:
            return (AuditFinding("AUDIT_SYMBOLS_REQUIRED", AuditScope.CATALOG),)
        return tuple(missing_symbols(request, AuditScope.CATALOG))

    def partition_check(request: AuditRequest, scope: AuditScope) -> Sequence[AuditFinding]:
        if not request.symbols:
            return (AuditFinding("AUDIT_SYMBOLS_REQUIRED", scope),)
        findings = missing_symbols(request, scope)
        for kind, frequency, row in targets(request):
            key = _dataset_key_from_row(row, kind, frequency)
            partitions = tuple(catalog.list_effective_partitions(key))
            if not partitions:
                findings.append(AuditFinding("AUDIT_COVERAGE_MISSING", scope, {"symbol": key.symbol, "frequency": key.frequency.value}))
                continue
            if scope is AuditScope.GAP:
                for gap in catalog.list_gaps(key):
                    if _gap_in_requested_window(gap, request):
                        findings.append(AuditFinding("AUDIT_DATA_GAP_PRESENT", scope, {"symbol": key.symbol, "frequency": key.frequency.value}))
            elif scope in {AuditScope.SCHEMA, AuditScope.PHYSICAL}:
                for partition in partitions:
                    target = _target_from_partition(key, partition)
                    if strict_probe is None or not strict_probe(target):
                        findings.append(AuditFinding("AUDIT_CANONICAL_STRICT_PROBE_FAILED", scope, {"symbol": key.symbol, "frequency": key.frequency.value}))
                        break
        return tuple(findings)

    return {
        AuditScope.CATALOG: catalog_check,
        AuditScope.COVERAGE: lambda request: partition_check(request, AuditScope.COVERAGE),
        AuditScope.SCHEMA: lambda request: partition_check(request, AuditScope.SCHEMA),
        AuditScope.PHYSICAL: lambda request: partition_check(request, AuditScope.PHYSICAL),
        AuditScope.GAP: lambda request: partition_check(request, AuditScope.GAP),
    }


def _dataset_key_from_row(row: object, kind: object, frequency: object) -> object:
    from app.data_core.contracts import DatasetKey

    return DatasetKey(
        provider=getattr(row, "provider"), dataset_kind=kind, symbol=getattr(row, "symbol"),
        contract_or_series=getattr(row, "contract_or_series"), frequency=frequency,
        adjustment=getattr(row, "adjustment"), schema_version=getattr(row, "schema_version"),
    )


def _target_from_partition(key: object, partition: object) -> object:
    from app.services.data_operations.contracts import DataTarget

    return DataTarget(
        provider=key.provider, dataset_kind=key.dataset_kind, symbol=key.symbol,
        contract_or_series=key.contract_or_series, frequency=key.frequency,
        adjustment=key.adjustment, schema_version=key.schema_version,
        start=getattr(partition, "coverage_start"), end=getattr(partition, "coverage_end"),
    )


def _gap_in_requested_window(gap: object, request: AuditRequest) -> bool:
    start, end = getattr(gap, "gap_start"), getattr(gap, "gap_end")
    return (request.start is None or end > request.start) and (request.end is None or start < request.end)
