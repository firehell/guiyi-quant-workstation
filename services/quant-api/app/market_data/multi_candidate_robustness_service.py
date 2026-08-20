from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from statistics import median
from typing import Protocol

from .actual_dominant_research import ActualDominantResearchSegmentIdentityError
from .market_data_service import MarketDataError
from .multi_candidate_robustness import (
    CandidateSymbolRobustness,
    CandidateSymbolStatus,
    CommonPriceHorizonSummary,
    CrossSymbolCandidateSummary,
    HorizonSignSummary,
)
from .multi_candidate_robustness_policy import MultiCandidateRobustnessProtocol
from .n_structure_research_service import (
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from .subing_lifecycle_research_service import LifecycleResearchRequest


class _Runner(Protocol):
    def run(self, request: object) -> object: ...


class MultiCandidateRobustnessSourceError(ValueError):
    code = "MULTI_CANDIDATE_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MultiCandidateRobustnessService:
    def __init__(
        self,
        protocol: MultiCandidateRobustnessProtocol,
        *,
        subing_research: _Runner,
        n_research: _Runner,
    ) -> None:
        self._protocol = protocol
        self._subing = subing_research
        self._n = n_research

    def _cross_symbol_results(
        self,
    ) -> tuple[tuple[CandidateSymbolRobustness, ...], tuple[CrossSymbolCandidateSummary, ...]]:
        rows: list[CandidateSymbolRobustness] = []
        for ref, runner in zip(
            self._protocol.candidates,
            (self._subing, self._n),
            strict=True,
        ):
            for symbol in self._protocol.cross_symbol_products:
                request: object = (
                    LifecycleResearchRequest(self._protocol.common_since, self._protocol.common_through, symbol)
                    if ref.source_kind == "subing_lifecycle"
                    else NStructureResearchRequest(self._protocol.common_since, self._protocol.common_through, symbol)
                )
                try:
                    source = runner.run(request)
                except (
                    MarketDataError,
                    ActualDominantResearchSegmentIdentityError,
                    NStructureSourceUnavailableError,
                    NStructureSegmentIdentityError,
                ):
                    rows.append(self._unavailable(ref.candidate_id, ref.source_kind, symbol, ref.evaluable_unit, ref.horizon_semantics))
                    continue
                if getattr(source, "products", None) != (symbol,):
                    raise MultiCandidateRobustnessSourceError()
                rows.append(self._available(ref.candidate_id, ref.source_kind, symbol, ref.evaluable_unit, ref.horizon_semantics, source))
        normalized = tuple(rows)
        return normalized, tuple(
            self._summarize(candidate_id, normalized)
            for candidate_id in (ref.candidate_id for ref in self._protocol.candidates)
        )

    @staticmethod
    def _available(candidate_id: str, source_kind: str, symbol: str, unit: str, semantics: str, source: object) -> CandidateSymbolRobustness:
        if source_kind == "subing_lifecycle":
            event_count = source.funnel_counts["ENTRY_CONFIRMED"]  # type: ignore[attr-defined]
            evaluable_count = source.evaluable_boundary_count  # type: ignore[attr-defined]
        else:
            event_count = sum(source.completed_n_counts.values())  # type: ignore[attr-defined]
            evaluable_count = source.evaluable_bar_count  # type: ignore[attr-defined]
        horizons = {
            horizon: CommonPriceHorizonSummary(
                value.sample_count,
                value.median_directional_return_bps,
                value.median_mfe_bps,
                value.median_mae_bps,
            )
            for horizon, value in source.horizon_summary.items()  # type: ignore[attr-defined]
        }
        rate = None if evaluable_count == 0 else Decimal(event_count) * Decimal(1000) / Decimal(evaluable_count)
        return CandidateSymbolRobustness(candidate_id, source_kind, symbol, CandidateSymbolStatus.AVAILABLE, None, event_count, evaluable_count, unit, rate, semantics, horizons)

    @staticmethod
    def _unavailable(candidate_id: str, source_kind: str, symbol: str, unit: str, semantics: str) -> CandidateSymbolRobustness:
        return CandidateSymbolRobustness(candidate_id, source_kind, symbol, CandidateSymbolStatus.UNAVAILABLE, "MULTI_CANDIDATE_SOURCE_UNAVAILABLE", None, None, unit, None, semantics, None)

    @staticmethod
    def _summarize(candidate_id: str, rows: Sequence[CandidateSymbolRobustness]) -> CrossSymbolCandidateSummary:
        selected = tuple(row for row in rows if row.candidate_id == candidate_id)
        available = tuple(row for row in selected if row.status is CandidateSymbolStatus.AVAILABLE)
        rates = sorted(row.event_rate_per_1000_evaluable for row in available if row.event_rate_per_1000_evaluable is not None)
        signs = {}
        for horizon in (3, 5, 8):
            values = tuple(
                metric
                for row in available
                if row.horizon_summary is not None
                and row.horizon_summary[horizon].sample_count > 0
                and (
                    metric := row.horizon_summary[
                        horizon
                    ].median_directional_return_bps
                )
                is not None
            )
            signs[horizon] = HorizonSignSummary(len(values), sum(value > 0 for value in values), sum(value == 0 for value in values), sum(value < 0 for value in values))
        return CrossSymbolCandidateSummary(candidate_id, 60, len(available), 60 - len(available), sum((row.event_count or 0) > 0 for row in available), sum(row.event_count == 0 for row in available), len(rates), min(rates) if rates else None, median(rates) if rates else None, max(rates) if rates else None, signs)
