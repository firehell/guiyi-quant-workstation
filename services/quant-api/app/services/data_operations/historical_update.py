"""High-level historical update workflow over existing data_operations services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from app.data_core.contracts import BarFrequency
from app.services.data_operations.aggregate import AggregateApplicationService
from app.services.data_operations.contracts import (
    AggregateRequest,
    CommandResult,
    CommandStatus,
    DataTarget,
    DownloadRequest,
    EffectSummary,
    HistoricalUpdateRequest,
    MetadataSyncRequest,
    MetadataSyncScope,
    PublicError,
    TargetResult,
    empty_effects,
    overall_batch_status,
)
from app.services.data_operations.download import DownloadApplicationService
from app.services.data_operations.metadata_sync import MetadataSyncApplicationService
from app.services.data_operations.target_planner import (
    HistoricalUpdatePlan,
    HistoricalUpdateTargetPlanner,
)
from app.services.data_operations.target_verifier import TargetWindowVerifier


class HistoricalUpdateAbort(RuntimeError):
    """Global composition / publisher / DB / schema failure — stop immediately."""

    def __init__(self, code: str, *, type_name: str = "HistoricalUpdateAbort") -> None:
        self.code = code
        self.type_name = type_name
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ApplyDeps:
    download: DownloadApplicationService
    aggregate: AggregateApplicationService
    metadata: MetadataSyncApplicationService | None
    verifier: TargetWindowVerifier | None
    readiness: Callable[[], Mapping[str, object]] | None


class HistoricalUpdateWorkflow:
    """Orchestrate metadata → Direct → Aggregate → verify without owning algorithms."""

    def __init__(
        self,
        *,
        planner: HistoricalUpdateTargetPlanner,
        apply_deps_factory: Callable[[], ApplyDeps] | None = None,
    ) -> None:
        self._planner = planner
        self._apply_deps_factory = apply_deps_factory

    def plan(self, request: HistoricalUpdateRequest) -> HistoricalUpdatePlan:
        return self._planner.plan(request)

    def execute(self, plan: HistoricalUpdatePlan) -> CommandResult:
        if not plan.apply:
            results = [
                TargetResult(target=target, status=CommandStatus.PLANNED)
                for target in (*plan.direct_targets, *plan.aggregate_targets)
            ]
            return CommandResult(
                command="data.update",
                status=overall_batch_status(results) if results else CommandStatus.PLANNED,
                readonly=True,
                effects=empty_effects(),
                targets=tuple(results),
                extras=_extras(
                    plan,
                    changed_count=len(plan.direct_targets) + len(plan.aggregate_targets),
                    blocked_count=0,
                    publication_count=0,
                ),
            )

        if self._apply_deps_factory is None:
            raise HistoricalUpdateAbort("HISTORICAL_UPDATE_APPLY_DEPS_MISSING")

        try:
            deps = self._apply_deps_factory()
        except HistoricalUpdateAbort:
            raise
        except Exception as exc:  # noqa: BLE001 - composition failures abort
            raise HistoricalUpdateAbort(
                getattr(exc, "code", "HISTORICAL_UPDATE_COMPOSITION_FAILED"),
                type_name=type(exc).__name__,
            ) from exc

        if deps.readiness is not None:
            try:
                deps.readiness()
            except HistoricalUpdateAbort:
                raise
            except Exception as exc:  # noqa: BLE001
                raise HistoricalUpdateAbort(
                    getattr(exc, "code", "HISTORICAL_UPDATE_NOT_READY"),
                    type_name=type(exc).__name__,
                ) from exc

        if not plan.direct_targets and not plan.aggregate_targets:
            return CommandResult(
                command="data.update",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=empty_effects(),
                targets=(),
                extras=_extras(
                    plan,
                    changed_count=0,
                    blocked_count=0,
                    publication_count=0,
                ),
            )

        if deps.metadata is not None and plan.windows:
            meta = deps.metadata.run(
                MetadataSyncRequest(
                    scope=MetadataSyncScope.MAIN_CONTRACT_MAP,
                    apply=True,
                    symbols=plan.products,
                    start=_as_datetime(plan.windows[0].since_day),
                    end=_as_datetime(plan.windows[0].through_day),
                )
            )
            if meta.status is CommandStatus.ERROR:
                raise HistoricalUpdateAbort(
                    meta.error.code if meta.error else "METADATA_SYNC_FAILED"
                )

        direct_result = deps.download.run(
            DownloadRequest(targets=plan.direct_targets, apply=True)
        )
        direct_by_key = {
            _target_key(item.target): item for item in direct_result.targets
        }
        results: list[TargetResult] = list(direct_result.targets)
        publication_count = sum(
            1
            for item in direct_result.targets
            if item.status is CommandStatus.PASSED
            and bool(item.detail.get("published_windows"))
        )

        aggregate_targets: list[DataTarget] = []
        blocked = 0
        for target in plan.aggregate_targets:
            parent = _parent_1m_key(target)
            parent_result = direct_by_key.get(parent)
            if parent_result is None or parent_result.status is not CommandStatus.PASSED:
                blocked += 1
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.BLOCKED,
                        detail={"reason": "direct_1m_failed_or_missing"},
                        error=PublicError(
                            code="AGGREGATE_BLOCKED_BY_DIRECT_1M",
                            type="BlockedError",
                        ),
                    )
                )
                continue
            aggregate_targets.append(target)

        if aggregate_targets:
            try:
                aggregate_result = deps.aggregate.run(
                    AggregateRequest(targets=tuple(aggregate_targets), apply=True)
                )
            except HistoricalUpdateAbort:
                raise
            except Exception as exc:  # noqa: BLE001 - publisher/schema abort
                raise HistoricalUpdateAbort(
                    getattr(exc, "code", "AGGREGATE_PUBLISH_FAILED"),
                    type_name=type(exc).__name__,
                ) from exc
            results.extend(aggregate_result.targets)
            publication_count += sum(
                1
                for item in aggregate_result.targets
                if item.status is CommandStatus.PASSED
            )

        verify_targets = [
            item.target
            for item in results
            if item.status is CommandStatus.PASSED
        ]
        if deps.verifier is not None and verify_targets:
            verified = deps.verifier.verify(verify_targets)
            # Replace passed entries with verifier outcomes for the same targets.
            by_key = {_target_key(item.target): item for item in verified}
            merged: list[TargetResult] = []
            for item in results:
                replacement = by_key.get(_target_key(item.target))
                merged.append(replacement if replacement is not None else item)
            results = merged

        write_effects = publication_count > 0
        return CommandResult(
            command="data.update",
            status=overall_batch_status(results),
            readonly=False,
            effects=EffectSummary(
                calls_rqdata=bool(plan.direct_targets) and write_effects,
                writes_staging=write_effects,
                writes_canonical=write_effects,
                writes_postgresql=write_effects,
            )
            if write_effects
            else empty_effects(),
            targets=tuple(results),
            extras=_extras(
                plan,
                changed_count=sum(
                    1
                    for item in results
                    if item.status
                    in {CommandStatus.PASSED, CommandStatus.PARTIAL, CommandStatus.ERROR}
                ),
                blocked_count=blocked,
                publication_count=publication_count,
            ),
        )

    def run(self, request: HistoricalUpdateRequest) -> CommandResult:
        plan = self.plan(request)
        try:
            return self.execute(plan)
        except HistoricalUpdateAbort as exc:
            return CommandResult(
                command="data.update",
                status=CommandStatus.ERROR,
                readonly=not request.apply,
                effects=empty_effects(),
                error=PublicError(code=exc.code, type=exc.type_name),
                extras=_extras(
                    plan,
                    changed_count=0,
                    blocked_count=0,
                    publication_count=0,
                ),
            )


def _extras(
    plan: HistoricalUpdatePlan,
    *,
    changed_count: int,
    blocked_count: int,
    publication_count: int,
) -> dict[str, object]:
    return {
        "plan_summary": {
            "product_count": len(plan.products),
            "window_count": len(plan.windows),
            "direct_target_count": len(plan.direct_targets),
            "aggregate_target_count": len(plan.aggregate_targets),
            "windows": [
                {
                    "symbol": window.symbol,
                    "since": window.since_day.isoformat(),
                    "through": window.through_day.isoformat(),
                }
                for window in plan.windows
            ],
        },
        "changed_count": changed_count,
        "blocked_count": blocked_count,
        "publication_count": publication_count,
    }


def _target_key(target: DataTarget) -> tuple[object, ...]:
    return (
        target.dataset_kind.value,
        target.symbol,
        target.contract_or_series,
        target.frequency.value,
        target.start.isoformat(),
        target.end.isoformat(),
    )


def _parent_1m_key(target: DataTarget) -> tuple[object, ...]:
    return (
        target.dataset_kind.value,
        target.symbol,
        target.contract_or_series,
        BarFrequency.M1.value,
        target.start.isoformat(),
        target.end.isoformat(),
    )


def _as_datetime(value: object) -> object:
    from datetime import date, datetime, time

    from app.services.trading_session_clock import SHANGHAI

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=SHANGHAI)
    return value
