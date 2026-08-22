"""Read-only projection of N lineage consumed by exact JDJ events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from typing import Protocol, cast

from app.research.candidate_convergence.artifact_source import (
    VerifiedJsonArtifact,
)
from app.research.candidate_convergence.five_candidate_relationships import (
    CandidateDependencyResult,
    DependencyRole,
    FiveCandidateRelationshipProtocol,
    FiveCandidateRelationshipProtocolError,
    FiveCandidateRelationshipReport,
    FiveCandidateRelationshipRequest,
    FiveCandidateRelationshipSourceError,
    ExistingRelationshipReference,
    JdjExactOverlapResult,
    RelationshipCatalogEntry,
    RelationshipKind,
)
from app.research.candidate_convergence.jdj_exact_overlap import (
    summarize_exact_jdj_overlap,
)
from app.research.candidate_convergence.identities import FIVE_CANDIDATE_ORDER
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_events import JdjKeyLevelBreakoutTriggerEvent
from app.research.jdj.jdj_research import (
    JdjBatchResearchResult,
    JdjResearchResult,
    JdjSourceUnavailableError,
)


_KEY_LEVEL_BREAKOUT = FIVE_CANDIDATE_ORDER[4]


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
        dossier_source: VerifiedJsonArtifact | None = None,
        subing_n_source: VerifiedJsonArtifact | None = None,
    ) -> None:
        if not isinstance(protocol, FiveCandidateRelationshipProtocol):
            raise FiveCandidateRelationshipProtocolError()
        self._protocol = protocol
        self._jdj_research = jdj_research
        self._dossier_source = dossier_source
        self._subing_n_source = subing_n_source

    def run(
        self,
        request: FiveCandidateRelationshipRequest,
    ) -> FiveCandidateRelationshipReport:
        protocol = replace(self._protocol)
        if (
            not isinstance(request, FiveCandidateRelationshipRequest)
            or request.protocol_id != protocol.protocol_id
        ):
            raise FiveCandidateRelationshipProtocolError()
        _validate_verified_sources(
            protocol,
            dossier_source=self._dossier_source,
            subing_n_source=self._subing_n_source,
        )
        dependency_rows = self.project_n_jdj_dependencies()
        overlap_rows = self.project_jdj_exact_overlaps()
        has_unavailable = (
            any(row.status == "unavailable" for row in dependency_rows)
            or any(row.status == "unavailable" for row in overlap_rows)
        )
        return FiveCandidateRelationshipReport(
            schema_version=1,
            command=(
                "guiyi research candidate-relationships "
                "--protocol five_candidate_relationship_topology_v1"
            ),
            status="ok",
            protocol_id=protocol.protocol_id,
            frozen_at=protocol.frozen_at,
            research_only=True,
            readonly=True,
            prospective_consumed=False,
            candidate_order=protocol.candidate_order,
            pair_order=protocol.pair_order,
            relationship_catalog=tuple(
                RelationshipCatalogEntry(left, right, kind)
                for (left, right), kind in zip(
                    protocol.pair_order,
                    protocol.relationship_kinds,
                    strict=True,
                )
            ),
            existing_relationship_references=(
                ExistingRelationshipReference(
                    left_candidate_id=protocol.pair_order[0][0],
                    right_candidate_id=protocol.pair_order[0][1],
                    relation_kind=RelationshipKind.EXISTING_EVENT_RELATIONSHIP,
                    source=protocol.subing_n_source,
                    recompute=False,
                ),
            ),
            n_jdj_dependency_results=dependency_rows,
            jdj_exact_overlap_results=overlap_rows,
            quality_flags=(
                ("JDJ_SOURCE_UNAVAILABLE_PRESENT",)
                if has_unavailable
                else ()
            ),
            safety={
                "future_outcomes": False,
                "parameter_perturbation": False,
                "automatic_scoring": False,
                "automatic_ranking": False,
                "automatic_promotion": False,
            },
        )

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

    def project_jdj_exact_overlaps(
        self,
    ) -> tuple[JdjExactOverlapResult, ...]:
        protocol = replace(self._protocol)
        rows_by_identity: dict[
            tuple[str, str, str],
            JdjExactOverlapResult,
        ] = {}
        for symbol in protocol.cross_symbol_products:
            try:
                batch = self._jdj_research.run_batch(
                    symbol=symbol,
                    since=protocol.jdj_overlap_since,
                    through=protocol.jdj_overlap_through,
                )
            except JdjSourceUnavailableError:
                for left_candidate_id, right_candidate_id in (
                    protocol.jdj_overlap_pair_order
                ):
                    rows_by_identity[
                        left_candidate_id,
                        right_candidate_id,
                        symbol,
                    ] = _unavailable_overlap_row(
                        left_candidate_id=left_candidate_id,
                        right_candidate_id=right_candidate_id,
                        symbol=symbol,
                    )
                continue

            validated_results = _validate_batch(
                protocol,
                batch,
                symbol=symbol,
                since=protocol.jdj_overlap_since,
                through=protocol.jdj_overlap_through,
            )
            results_by_candidate = {
                result.candidate_id: result for result in validated_results
            }
            for left_candidate_id, right_candidate_id in (
                protocol.jdj_overlap_pair_order
            ):
                rows_by_identity[
                    left_candidate_id,
                    right_candidate_id,
                    symbol,
                ] = summarize_exact_jdj_overlap(
                    results_by_candidate[left_candidate_id],
                    results_by_candidate[right_candidate_id],
                    symbol=symbol,
                )

        return tuple(
            rows_by_identity[left_candidate_id, right_candidate_id, symbol]
            for left_candidate_id, right_candidate_id in (
                protocol.jdj_overlap_pair_order
            )
            for symbol in protocol.cross_symbol_products
        )


def _validate_batch(
    protocol: FiveCandidateRelationshipProtocol,
    batch: object,
    *,
    symbol: str,
    since: date | None = None,
    through: date | None = None,
) -> tuple[JdjResearchResult, ...]:
    if not isinstance(batch, JdjBatchResearchResult):
        raise JdjContextError()
    validated_batch = replace(batch)
    requested_since = since if since is not None else protocol.n_jdj_since
    requested_through = (
        through if through is not None else protocol.n_jdj_through
    )
    if (
        validated_batch.symbol != symbol
        or not (
            requested_since
            <= validated_batch.observed_since
            <= validated_batch.observed_through
            <= requested_through
        )
        or tuple(
            detailed.result.candidate_id
            for detailed in validated_batch.candidates
        )
        != protocol.n_jdj_candidate_order
        or any(
            detailed.result.products != (symbol,)
            for detailed in validated_batch.candidates
        )
    ):
        raise JdjContextError()

    validated_results: list[JdjResearchResult] = []
    for detailed in validated_batch.candidates:
        result = detailed.result
        validated_result = replace(result)
        validated_events = tuple(
            replace(event) for event in validated_result.events
        )
        validated_result = replace(validated_result, events=validated_events)
        if any(
            not (
                validated_batch.observed_since
                <= event.trading_day
                <= validated_batch.observed_through
                and requested_since
                <= event.trading_day
                <= requested_through
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


def _unavailable_overlap_row(
    *,
    left_candidate_id: str,
    right_candidate_id: str,
    symbol: str,
) -> JdjExactOverlapResult:
    return JdjExactOverlapResult(
        left_candidate_id=left_candidate_id,
        right_candidate_id=right_candidate_id,
        symbol=symbol,
        status="unavailable",
        reason_code=JdjSourceUnavailableError.code,
        left_event_count=None,
        right_event_count=None,
        exact_same_boundary_same_direction_count=None,
        exact_same_boundary_opposite_direction_count=None,
        left_events_with_same_direction_match=None,
        right_events_with_same_direction_match=None,
    )


def _validate_verified_sources(
    protocol: FiveCandidateRelationshipProtocol,
    *,
    dossier_source: VerifiedJsonArtifact | None,
    subing_n_source: VerifiedJsonArtifact | None,
) -> None:
    if (
        not isinstance(dossier_source, VerifiedJsonArtifact)
        or dossier_source.ref != protocol.dossier_source
        or not isinstance(subing_n_source, VerifiedJsonArtifact)
        or subing_n_source.ref != protocol.subing_n_source
    ):
        raise FiveCandidateRelationshipSourceError()
    dossier = dossier_source.payload
    subing_n = subing_n_source.payload
    try:
        dossier_identity_valid = (
            dossier.get("schema_version") == 1
            and dossier.get("command")
            == (
                "guiyi research candidate-dossier "
                "--protocol five_candidate_research_dossier_v1"
            )
            and dossier.get("status") == "ok"
            and dossier.get("protocol_id")
            == "five_candidate_research_dossier_v1"
            and dossier.get("research_only") is True
            and dossier.get("readonly") is True
            and dossier.get("prospective_consumed") is False
            and tuple(cast(Iterable[object], dossier["candidate_order"]))
            == protocol.candidate_order
        )
        relationships = tuple(
            cast(
                Iterable[Mapping[str, object]],
                subing_n["relationships"],
            )
        )
        subing_n_identity_valid = (
            subing_n.get("schema_version") == 1
            and subing_n.get("command") == "research.candidate-robustness"
            and subing_n.get("status") == "ok"
            and subing_n.get("protocol_id")
            == "multi_candidate_robustness_v1"
            and subing_n.get("research_only") is True
            and subing_n.get("readonly") is True
            and subing_n.get("common_retrospective")
            == {"since": "2023-01-01", "through": "2026-08-18"}
            and tuple(
                (
                    relationship["source_candidate_id"],
                    relationship["target_candidate_id"],
                )
                for relationship in relationships
            )
            == (
                (protocol.candidate_order[0], protocol.candidate_order[1]),
                (protocol.candidate_order[1], protocol.candidate_order[0]),
            )
        )
    except (KeyError, TypeError):
        raise FiveCandidateRelationshipSourceError() from None
    if not dossier_identity_valid or not subing_n_identity_valid:
        raise FiveCandidateRelationshipSourceError()
