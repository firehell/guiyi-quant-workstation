"""Metadata sync orchestration by delegation to rqdata_ingest services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    DataOperationsError,
    EffectSummary,
    MetadataSyncRequest,
    MetadataSyncScope,
    PublicError,
    empty_effects,
)


ALL_SCOPE_ORDER = (
    MetadataSyncScope.INSTRUMENTS,
    MetadataSyncScope.CONTRACTS,
    MetadataSyncScope.CALENDAR,
    MetadataSyncScope.SESSIONS,
    MetadataSyncScope.MAIN_CONTRACT_MAP,
)


class _IngestResult(Protocol):
    rows: int
    files: int


class _ScopedService(Protocol):
    effect_profile: Mapping[str, bool]
    def plan(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def apply(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MetadataSyncPlan:
    scopes: tuple[MetadataSyncScope, ...]
    planned: tuple[Mapping[str, Any], ...]
    apply: bool
    filters: Mapping[str, Any]


class MetadataSyncApplicationService:
    """Coordinate metadata scopes without copying provider/upsert algorithms."""

    def __init__(
        self,
        *,
        services: Mapping[MetadataSyncScope, _ScopedService],
        begin_transaction: Callable[[], None] | None = None,
        commit: Callable[[], None] | None = None,
        rollback: Callable[[], None] | None = None,
    ) -> None:
        self._services = dict(services)
        self._begin = begin_transaction or (lambda: None)
        self._commit = commit or (lambda: None)
        self._rollback = rollback or (lambda: None)

    def plan(self, request: MetadataSyncRequest) -> MetadataSyncPlan:
        scopes = self._expand_scopes(request.scope)
        filters = _filters(request)
        planned = []
        for scope in scopes:
            service = self._require_service(scope)
            planned.append(
                {
                    "scope": scope.value,
                    "result": dict(service.plan(**filters)),
                }
            )
        return MetadataSyncPlan(
            scopes=scopes,
            planned=tuple(planned),
            apply=request.apply,
            filters=filters,
        )

    def execute(self, plan: MetadataSyncPlan) -> CommandResult:
        if not plan.apply:
            return CommandResult(
                command="data.sync",
                status=CommandStatus.PLANNED,
                readonly=True,
                effects=empty_effects(),
                extras={
                    "scopes": [scope.value for scope in plan.scopes],
                    "plan": [dict(item) for item in plan.planned],
                },
            )

        applied: list[dict[str, Any]] = []
        calls_rqdata = False
        writes_provider_raw = False
        writes_postgresql = False
        for scope in plan.scopes:
            service = self._require_service(scope)
            profile = _effect_profile(service)
            self._begin()
            try:
                result = dict(service.apply(**plan.filters))
                self._commit()
            except Exception as exc:  # noqa: BLE001 - scoped durable boundary
                self._rollback()
                observed = _exception_effects(exc, profile)
                calls_rqdata = calls_rqdata or observed["calls_rqdata"]
                writes_provider_raw = writes_provider_raw or observed[
                    "writes_provider_raw"
                ]
                return CommandResult(
                    command="data.sync",
                    status=CommandStatus.PARTIAL if applied else CommandStatus.ERROR,
                    readonly=False,
                    effects=EffectSummary(
                        calls_rqdata=calls_rqdata,
                        writes_provider_raw=writes_provider_raw,
                        writes_postgresql=writes_postgresql,
                    ),
                    error=PublicError(
                        code=getattr(exc, "code", "METADATA_SYNC_FAILED"),
                        type=type(exc).__name__,
                    ),
                    extras={
                        "scopes": [item.value for item in plan.scopes],
                        "completed_scopes": [item["scope"] for item in applied],
                        "failed_scope": scope.value,
                    },
                )
            calls_rqdata = calls_rqdata or profile["calls_rqdata"]
            writes_provider_raw = writes_provider_raw or bool(result.get("files", 0))
            writes_postgresql = writes_postgresql or (
                profile["writes_postgresql"] and bool(result.get("rows", 0))
            )
            applied.append({"scope": scope.value, "result": result})
        return CommandResult(
            command="data.sync",
            status=CommandStatus.PASSED,
            readonly=False,
            effects=EffectSummary(
                calls_rqdata=calls_rqdata,
                writes_provider_raw=writes_provider_raw,
                writes_postgresql=writes_postgresql,
            ),
            extras={
                "scopes": [scope.value for scope in plan.scopes],
                "applied": applied,
            },
        )

    def run(self, request: MetadataSyncRequest) -> CommandResult:
        return self.execute(self.plan(request))

    def _expand_scopes(
        self,
        scope: MetadataSyncScope,
    ) -> tuple[MetadataSyncScope, ...]:
        if scope is MetadataSyncScope.ALL:
            return ALL_SCOPE_ORDER
        return (scope,)

    def _require_service(self, scope: MetadataSyncScope) -> _ScopedService:
        service = self._services.get(scope)
        if service is None:
            raise KeyError(f"missing metadata service for {scope.value}")
        return service


def default_rqdata_ingest_service_map(
    *,
    catalog_ingestor_factory: Callable[[], Any],
    contract_ingestor_factory: Callable[[], Any],
    main_mapping_ingestor_factory: Callable[[], Any],
    start: date | None,
    end: date | None,
    products: Sequence[str] | None = None,
) -> dict[MetadataSyncScope, _ScopedService]:
    """Build thin adapters around existing ingestors (no algorithm copy)."""

    class _Adapter:
        def __init__(
            self, factory: Callable[[], Any], mode: str, *, writes_provider_raw: bool
        ) -> None:
            self._factory = factory
            self._mode = mode
            self.effect_profile = {
                "calls_rqdata": True,
                "writes_provider_raw": writes_provider_raw,
                "writes_postgresql": True,
            }

        def plan(self, **kwargs: Any) -> Mapping[str, Any]:
            return {
                "mode": self._mode,
                "dry_run": True,
                "start": _optional_isoformat(kwargs.get("start", start)),
                "end": _optional_isoformat(kwargs.get("end", end)),
                "products": list(kwargs.get("symbols") or products or []),
            }

        def apply(self, **kwargs: Any) -> Mapping[str, Any]:
            ingestor = self._factory()
            window_start = kwargs.get("start", start)
            window_end = kwargs.get("end", end)
            if window_start is None or window_end is None:
                raise DataOperationsError(code="METADATA_SYNC_WINDOW_REQUIRED")
            if isinstance(window_start, datetime):
                window_start = window_start.date()
            if isinstance(window_end, datetime):
                window_end = window_end.date()
            selected = list(kwargs.get("symbols") or products or [])
            if self._mode == "instruments":
                result = ingestor.run(
                    window_start, window_end, products=selected or None
                )
            elif self._mode == "contracts":
                result = ingestor.run(selected, window_start, window_end)
            elif self._mode == "calendar":
                result = ingestor.run_calendar(
                    window_start, window_end, products=selected or None
                )
            elif self._mode == "sessions":
                result = ingestor.run_sessions(
                    window_start, window_end, products=selected or None
                )
            else:
                if not selected:
                    raise DataOperationsError(code="METADATA_SYNC_PRODUCTS_REQUIRED")
                result = ingestor.run(selected, window_start, window_end, [1])
            return {
                "mode": self._mode,
                "rows": getattr(result, "rows", 0),
                "files": getattr(result, "files", 0),
            }

    catalog = _Adapter(catalog_ingestor_factory, "instruments", writes_provider_raw=True)
    contracts = _Adapter(contract_ingestor_factory, "contracts", writes_provider_raw=True)
    return {
        MetadataSyncScope.INSTRUMENTS: catalog,
        MetadataSyncScope.CONTRACTS: contracts,
        MetadataSyncScope.CALENDAR: _Adapter(catalog_ingestor_factory, "calendar", writes_provider_raw=False),
        MetadataSyncScope.SESSIONS: _Adapter(catalog_ingestor_factory, "sessions", writes_provider_raw=False),
        MetadataSyncScope.MAIN_CONTRACT_MAP: _Adapter(main_mapping_ingestor_factory, "main-contract-map", writes_provider_raw=True),
    }


def _filters(request: MetadataSyncRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"symbols": tuple(request.symbols)}
    if request.start is not None:
        payload["start"] = request.start
    if request.end is not None:
        payload["end"] = request.end
    return payload


def _optional_isoformat(value: object) -> str | None:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _effect_profile(service: object) -> dict[str, bool]:
    raw = getattr(service, "effect_profile", {})
    return {
        "calls_rqdata": bool(raw.get("calls_rqdata", True)),
        "writes_provider_raw": bool(raw.get("writes_provider_raw", False)),
        "writes_postgresql": bool(raw.get("writes_postgresql", True)),
    }


def _exception_effects(exc: Exception, profile: Mapping[str, bool]) -> dict[str, bool]:
    facts = getattr(exc, "facts", {})
    return {
        "calls_rqdata": bool(facts.get("calls_rqdata", profile["calls_rqdata"])),
        "writes_provider_raw": bool(
            facts.get("writes_provider_raw", profile["writes_provider_raw"])
        ),
    }
