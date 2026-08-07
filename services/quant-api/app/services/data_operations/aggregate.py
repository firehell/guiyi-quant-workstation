"""Canonical-only aggregation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol, Sequence

from app.data_core.aggregation import AggregationSession, aggregate_bars
from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import (
    DERIVED_FREQUENCIES,
    BarFrequency,
    BarQuery,
    BarsResult,
    DataGapError,
    DatasetKey,
)
from app.services.data_operations.contracts import (
    AggregateRequest,
    CommandResult,
    CommandStatus,
    DataTarget,
    EffectSummary,
    PublicError,
    TargetResult,
    empty_effects,
    overall_batch_status,
    require_derived_frequency,
)
from app.services.data_operations.guards import (
    assert_no_gap_intersection,
    refuse_cross_kind_fallback,
    to_dataset_key,
)


class _MarketData(Protocol):
    def get_bars(self, request: BarQuery) -> BarsResult: ...


class _Catalog(Protocol):
    def list_gaps(self, key: DatasetKey) -> Sequence[object]: ...


class _Publisher(Protocol):
    def __call__(
        self,
        bars: Sequence[CanonicalBar],
        *,
        dataset: DatasetKey,
        source: BarsResult,
        aggregation_sessions: Sequence[AggregationSession],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AggregatePlan:
    targets: tuple[DataTarget, ...]
    apply: bool


class AggregateApplicationService:
    """Aggregate derived frequencies from trusted canonical 1m only."""

    def __init__(
        self,
        *,
        market_data: _MarketData,
        session_provider: Callable[
            [DatasetKey, datetime, datetime], Sequence[AggregationSession]
        ],
        catalog: _Catalog | None = None,
        publisher: _Publisher | None = None,
        rqdata_client_factory: Callable[[], object] | None = None,
    ) -> None:
        if rqdata_client_factory is not None:
            raise RuntimeError("AGGREGATE_RQDATA_CLIENT_FORBIDDEN")
        self._market_data = market_data
        self._session_provider = session_provider
        self._catalog = catalog
        self._publisher = publisher
        self._rqdata_calls = 0

    @property
    def rqdata_call_count(self) -> int:
        return self._rqdata_calls

    def plan(self, request: AggregateRequest) -> AggregatePlan:
        for target in request.targets:
            require_derived_frequency(target.frequency)
        return AggregatePlan(targets=tuple(request.targets), apply=request.apply)

    def execute(self, plan: AggregatePlan) -> CommandResult:
        if not plan.apply:
            results = [
                TargetResult(
                    target=target,
                    status=CommandStatus.PLANNED,
                    detail={"source_frequency": BarFrequency.M1.value},
                )
                for target in plan.targets
            ]
            return CommandResult(
                command="data.aggregate",
                status=overall_batch_status(results),
                readonly=True,
                effects=empty_effects(),
                targets=tuple(results),
            )

        results: list[TargetResult] = []
        published = 0
        for target in plan.targets:
            require_derived_frequency(target.frequency)
            dataset = to_dataset_key(target)
            refuse_cross_kind_fallback(
                requested=target.dataset_kind,
                resolved=dataset.dataset_kind,
            )
            source_key = DatasetKey(
                provider=dataset.provider,
                dataset_kind=dataset.dataset_kind,
                symbol=dataset.symbol,
                contract_or_series=dataset.contract_or_series,
                frequency=BarFrequency.M1,
                adjustment=dataset.adjustment,
                schema_version=dataset.schema_version,
            )
            try:
                if self._publisher is None:
                    raise RuntimeError("AGGREGATE_PUBLISHER_UNAVAILABLE")
                if self._catalog is not None:
                    assert_no_gap_intersection(
                        self._catalog,
                        dataset=source_key,
                        start=target.start,
                        end=target.end,
                    )
                source = self._market_data.get_bars(
                    BarQuery(
                        dataset_kind=source_key.dataset_kind,
                        symbol=source_key.symbol,
                        contract_or_series=source_key.contract_or_series,
                        frequency=BarFrequency.M1,
                        start=target.start,
                        end=target.end,
                    )
                )
                if getattr(source, "quality_status", "passed") == "failed":
                    raise DataGapError(facts={"reason": "failed_quality"})
                sessions = tuple(
                    self._session_provider(source_key, target.start, target.end)
                )
                bars = aggregate_bars(
                    getattr(source, "bars", ()),
                    target_frequency=target.frequency,
                    sessions=sessions,
                    requested_window=(target.start, target.end),
                )
                self._publisher(
                    bars,
                    dataset=dataset,
                    source=source,
                    aggregation_sessions=sessions,
                )
                published += 1
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.PASSED,
                        detail={
                            "bar_count": len(bars),
                            "provider": dataset.provider,
                            "dataset_kind": dataset.dataset_kind.value,
                            "symbol": dataset.symbol,
                            "contract_or_series": dataset.contract_or_series,
                            "frequency": dataset.frequency.value,
                            "adjustment": dataset.adjustment,
                            "schema_version": dataset.schema_version,
                            "source_frequency": BarFrequency.M1.value,
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001 - per-target isolation
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.ERROR,
                        error=PublicError(
                            code=(
                                str(exc)
                                if str(exc) == "AGGREGATE_PUBLISHER_UNAVAILABLE"
                                else getattr(exc, "code", "AGGREGATE_FAILED")
                            ),
                            type=type(exc).__name__,
                        ),
                        detail={"published": False},
                    )
                )
        return CommandResult(
            command="data.aggregate",
            status=overall_batch_status(results),
            readonly=False,
            effects=EffectSummary(
                writes_staging=published > 0,
                writes_canonical=published > 0,
                writes_postgresql=published > 0,
                writes_historical_active=published > 0,
            ),
            targets=tuple(results),
            extras={"publication_count": published, "calls_rqdata": False},
        )

    def run(self, request: AggregateRequest) -> CommandResult:
        return self.execute(self.plan(request))


def supports_aggregate_frequency(value: object) -> bool:
    from app.data_core.contracts import BarFrequency

    try:
        parsed = value if isinstance(value, BarFrequency) else BarFrequency(str(value))
    except (TypeError, ValueError):
        return False
    return parsed in DERIVED_FREQUENCIES
