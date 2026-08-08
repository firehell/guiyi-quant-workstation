"""High-level historical update workflow over existing data_operations services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

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
                    metadata_refresh_required=True,
                    metadata_watermark=_watermark_from_plan(plan),
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

        stage_effects: list[EffectSummary] = []
        # Metadata bootstrap MUST precede final planning and MUST NOT depend on
        # a non-empty initial publish set / plan.windows.
        if deps.metadata is not None:
            bootstrap_start, bootstrap_through = _bootstrap_bounds(plan.request)
            for scope in (
                MetadataSyncScope.SESSIONS,
                MetadataSyncScope.CALENDAR,
            ):
                meta = deps.metadata.run(
                    MetadataSyncRequest(
                        scope=scope,
                        apply=True,
                        symbols=plan.products,
                        start=_as_datetime(bootstrap_start),
                        end=_as_datetime(bootstrap_through),
                    )
                )
                if meta.status is not CommandStatus.PASSED:
                    raise HistoricalUpdateAbort(
                        meta.error.code if meta.error else "METADATA_SYNC_FAILED"
                    )
                stage_effects.append(meta.effects)

            # Map refresh uses the apply watermark; final plan() re-reads the clock.
            refreshed_through = (
                plan.request.through
                if plan.request.through is not None
                else bootstrap_through
            )
            map_start = plan.request.since or bootstrap_start
            meta = deps.metadata.run(
                MetadataSyncRequest(
                    scope=MetadataSyncScope.MAIN_CONTRACT_MAP,
                    apply=True,
                    symbols=plan.products,
                    start=_as_datetime(map_start),
                    end=_as_datetime(refreshed_through),
                )
            )
            if meta.status is not CommandStatus.PASSED:
                raise HistoricalUpdateAbort(
                    meta.error.code if meta.error else "METADATA_SYNC_FAILED"
                )
            stage_effects.append(meta.effects)

            plan = self._planner.plan(plan.request)

        if not plan.direct_targets and not plan.aggregate_targets:
            return CommandResult(
                command="data.update",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=_merged_effects(stage_effects) if stage_effects else empty_effects(),
                targets=(),
                extras=_extras(
                    plan,
                    changed_count=0,
                    blocked_count=0,
                    publication_count=0,
                    metadata_refresh_required=False,
                    metadata_watermark=_watermark_from_plan(plan),
                ),
            )

        if plan.direct_targets:
            direct_result = deps.download.run(
                DownloadRequest(targets=plan.direct_targets, apply=True)
            )
            stage_effects.append(direct_result.effects)
        else:
            direct_result = CommandResult(
                command="data.download",
                status=CommandStatus.PASSED,
                readonly=False,
                effects=empty_effects(),
                targets=(),
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
            parent = _parent_1m_target(target)
            parent_key = _target_key(parent)
            parent_result = direct_by_key.get(parent_key)
            if parent_result is not None:
                if parent_result.status is not CommandStatus.PASSED:
                    blocked += 1
                    results.append(
                        TargetResult(
                            target=target,
                            status=CommandStatus.BLOCKED,
                            detail={"reason": "direct_1m_failed"},
                            error=PublicError(
                                code="BLOCKED_BY_SOURCE_1M",
                                type="BlockedError",
                            ),
                        )
                    )
                    continue
            elif not _source_1m_trusted(deps.verifier, parent):
                blocked += 1
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.BLOCKED,
                        detail={"reason": "source_1m_not_trusted"},
                        error=PublicError(
                            code="BLOCKED_BY_SOURCE_1M",
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
            stage_effects.append(aggregate_result.effects)
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

        return CommandResult(
            command="data.update",
            status=overall_batch_status(results),
            readonly=False,
            effects=_merged_effects(stage_effects),
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
    metadata_refresh_required: bool | None = None,
    metadata_watermark: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
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
    if metadata_refresh_required is not None:
        payload["metadata_refresh_required"] = metadata_refresh_required
    if metadata_watermark is not None:
        payload["metadata_watermark"] = metadata_watermark
    return payload


def _watermark_from_plan(plan: HistoricalUpdatePlan) -> str | None:
    if not plan.windows:
        if plan.request.through is not None:
            return plan.request.through.isoformat()
        return None
    return max(window.through_day for window in plan.windows).isoformat()


def _bootstrap_bounds(request: HistoricalUpdateRequest) -> tuple[object, object]:
    """Inclusive trading-day bounds for Calendar/Session bootstrap before final plan."""
    from datetime import date, datetime, timedelta

    from app.services.trading_session_clock import SHANGHAI

    through = request.through
    if through is None:
        through = datetime.now(tz=SHANGHAI).date()
    since = request.since
    if since is None:
        since = through - timedelta(days=45)
    if since > through:
        since = through
    return since, through


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
    return _target_key(_parent_1m_target(target))


def _parent_1m_target(target: DataTarget) -> DataTarget:
    return DataTarget(
        provider=target.provider,
        dataset_kind=target.dataset_kind,
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=BarFrequency.M1,
        adjustment=target.adjustment,
        schema_version=target.schema_version,
        start=target.start,
        end=target.end,
    )


def _source_1m_trusted(
    verifier: TargetWindowVerifier | None, parent: DataTarget
) -> bool:
    """Allow aggregate when canonical 1m already covers the window (no download)."""
    if verifier is None:
        return False
    verified = verifier.verify((parent,))
    return bool(verified) and verified[0].status is CommandStatus.PASSED


def _as_datetime(value: object) -> object:
    from datetime import date, datetime, time

    from app.services.trading_session_clock import SHANGHAI

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=SHANGHAI)
    return value


def _merged_effects(values: list[EffectSummary]) -> EffectSummary:
    if not values:
        return empty_effects()
    return EffectSummary(
        calls_rqdata=any(item.calls_rqdata for item in values),
        writes_provider_raw=any(item.writes_provider_raw for item in values),
        writes_staging=any(item.writes_staging for item in values),
        writes_canonical=any(item.writes_canonical for item in values),
        writes_postgresql=any(item.writes_postgresql for item in values),
        writes_historical_active=any(
            item.writes_historical_active for item in values
        ),
        sends_notification=any(item.sends_notification for item in values),
    )
