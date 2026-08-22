"""Read-only projection of N lineage consumed by exact JDJ events."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Protocol

from app.research.candidate_convergence.five_candidate_relationships import (
    CandidateDependencyResult,
    DependencyRole,
    FiveCandidateRelationshipProtocol,
    FiveCandidateRelationshipProtocolError,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_events import JdjKeyLevelBreakoutTriggerEvent
from app.research.jdj.jdj_research import (
    JdjBatchResearchResult,
    JdjResearchResult,
    JdjSourceUnavailableError,
)


_KEY_LEVEL_BREAKOUT = "jdj_key_level_breakout_1m_candidate_v1"


class _JdjBatchRunner(Protocol):
    def run_batch(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> JdjBatchResearchResult: ...


class FiveCandidateRelationshipService:
    def __init__(
        self,
        protocol: FiveCandidateRelationshipProtocol,
        *,
        jdj_research: _JdjBatchRunner,
    ) -> None:
        if not isinstance(protocol, FiveCandidateRelationshipProtocol):
            raise FiveCandidateRelationshipProtocolError()
        self._protocol = protocol
        self._jdj_research = jdj_research

    def project_n_jdj_dependencies(
        self,
    ) -> tuple[CandidateDependencyResult, ...]:
        protocol = replace(self._protocol)
        rows_by_identity: dict[tuple[str, str], CandidateDependencyResult] = {}
        for symbol in protocol.cross_symbol_products:
            try:
                batch = self._jdj_research.run_batch(
                    symbol=symbol,
                    since=protocol.n_jdj_since,
                    through=protocol.n_jdj_through,
                )
            except JdjSourceUnavailableError:
                for candidate_id, role in protocol.n_jdj_dependency_roles:
                    rows_by_identity[candidate_id, symbol] = _unavailable_row(
                        candidate_id=candidate_id,
                        symbol=symbol,
                        role=role,
                    )
                continue

            validated_results = _validate_batch(protocol, batch, symbol=symbol)
            for result, (candidate_id, role) in zip(
                validated_results,
                protocol.n_jdj_dependency_roles,
                strict=True,
            ):
                events = result.events
                rows_by_identity[candidate_id, symbol] = CandidateDependencyResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    dependency_role=role,
                    status="available",
                    reason_code=None,
                    event_count=len(events),
                    events_with_trend_snapshot_lineage=sum(
                        event.trend_snapshot_observed_at is not None
                        for event in events
                    ),
                    events_with_exact_pivot_lineage=(
                        sum(
                            bool(event.key_level_pivot_id)
                            for event in events
                            if isinstance(
                                event,
                                JdjKeyLevelBreakoutTriggerEvent,
                            )
                        )
                        if candidate_id == _KEY_LEVEL_BREAKOUT
                        else None
                    ),
                )

        return tuple(
            rows_by_identity[candidate_id, symbol]
            for candidate_id in protocol.n_jdj_candidate_order
            for symbol in protocol.cross_symbol_products
        )


def _validate_batch(
    protocol: FiveCandidateRelationshipProtocol,
    batch: object,
    *,
    symbol: str,
) -> tuple[JdjResearchResult, ...]:
    if (
        not isinstance(batch, JdjBatchResearchResult)
        or batch.symbol != symbol
        or not (
            protocol.n_jdj_since
            <= batch.observed_since
            <= batch.observed_through
            <= protocol.n_jdj_through
        )
        or tuple(
            detailed.result.candidate_id for detailed in batch.candidates
        )
        != protocol.n_jdj_candidate_order
        or any(
            detailed.result.products != (symbol,)
            for detailed in batch.candidates
        )
    ):
        raise JdjContextError()

    validated_results: list[JdjResearchResult] = []
    for detailed in batch.candidates:
        result = detailed.result
        validated_result = replace(result)
        validated_events = tuple(
            replace(event) for event in validated_result.events
        )
        validated_result = replace(validated_result, events=validated_events)
        if any(
            not (
                batch.observed_since
                <= event.trading_day
                <= batch.observed_through
                and protocol.n_jdj_since
                <= event.trading_day
                <= protocol.n_jdj_through
            )
            for event in validated_result.events
        ):
            raise JdjContextError()
        validated_results.append(validated_result)
    return tuple(validated_results)


def _unavailable_row(
    *,
    candidate_id: str,
    symbol: str,
    role: DependencyRole,
) -> CandidateDependencyResult:
    return CandidateDependencyResult(
        candidate_id=candidate_id,
        symbol=symbol,
        dependency_role=role,
        status="unavailable",
        reason_code=JdjSourceUnavailableError.code,
        event_count=None,
        events_with_trend_snapshot_lineage=None,
        events_with_exact_pivot_lineage=None,
    )
