"""Read-only orchestration for the exact JDJ active60 robustness report."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Protocol

from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_research import (
    JdjBatchResearchResult,
    JdjDetailedCandidateResult,
    JdjEventOutcomeRecord,
    JdjSourceUnavailableError,
)
from .jdj_robustness import (
    JdjActive60RobustnessProtocol,
    JdjActive60RobustnessProtocolError,
    JdjActive60RobustnessReport,
    JdjActive60RobustnessRequest,
    JdjRobustnessHorizonSummary,
    JdjRobustnessSectorHorizonSummary,
    JdjRobustnessSectorSummary,
    JdjRobustnessStatus,
    JdjRobustnessSymbolResult,
    JdjRobustnessYearSummary,
    require_exact_jdj_active60_robustness_protocol,
)
from app.market_data.price_outcome import PriceDirectionalOutcome


_YEARS = (2023, 2024, 2025, 2026)
_COMMAND = (
    "guiyi research candidate-robustness "
    "--protocol jdj_active60_robustness_v1"
)


class _JdjBatchRunner(Protocol):
    def run_batch(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> JdjBatchResearchResult: ...


class JdjActive60RobustnessService:
    def __init__(
        self,
        protocol: JdjActive60RobustnessProtocol,
        *,
        jdj_research: _JdjBatchRunner,
    ) -> None:
        self._protocol = protocol
        self._jdj_research = jdj_research

    def run(
        self,
        request: JdjActive60RobustnessRequest,
    ) -> JdjActive60RobustnessReport:
        protocol = require_exact_jdj_active60_robustness_protocol(
            self._protocol
        )
        if (
            not isinstance(request, JdjActive60RobustnessRequest)
            or request.protocol_id != protocol.protocol_id
        ):
            raise JdjActive60RobustnessProtocolError()

        rows_by_identity: dict[
            tuple[str, str],
            JdjRobustnessSymbolResult,
        ] = {}
        for symbol in protocol.cross_symbol_products:
            try:
                batch = self._jdj_research.run_batch(
                    symbol=symbol,
                    since=protocol.common_since,
                    through=protocol.common_through,
                )
            except JdjSourceUnavailableError:
                for candidate_id in protocol.candidate_ids:
                    rows_by_identity[candidate_id, symbol] = _unavailable_row(
                        protocol,
                        candidate_id=candidate_id,
                        symbol=symbol,
                    )
                continue
            _validate_batch(protocol, batch, symbol=symbol)
            for detailed in batch.candidates:
                candidate_id = detailed.result.candidate_id
                rows_by_identity[candidate_id, symbol] = _available_row(
                    protocol,
                    batch,
                    detailed,
                )

        rows = tuple(
            rows_by_identity[candidate_id, symbol]
            for candidate_id in protocol.candidate_ids
            for symbol in protocol.cross_symbol_products
        )
        sectors = tuple(
            _sector_summary(
                protocol,
                rows,
                candidate_id=candidate_id,
                sector=sector,
            )
            for candidate_id in protocol.candidate_ids
            for sector in protocol.sector_groups
        )
        return JdjActive60RobustnessReport(
            schema_version=protocol.schema_version,
            command=_COMMAND,
            protocol_id=protocol.protocol_id,
            frozen_at=protocol.frozen_at,
            research_only=protocol.research_only,
            readonly=protocol.readonly,
            common_since=protocol.common_since,
            common_through=protocol.common_through,
            embargo_trading_days=protocol.embargo_trading_days,
            prospective_first_trading_day=(
                protocol.prospective_first_trading_day
            ),
            prospective_consumed=protocol.prospective_consumed,
            candidate_ids=protocol.candidate_ids,
            cross_symbol_results=rows,
            sector_summaries=sectors,
            quality_flags=_quality_flags(protocol, rows),
        )


def summarize_jdj_robustness_horizon(
    outcomes: Sequence[PriceDirectionalOutcome],
) -> JdjRobustnessHorizonSummary:
    if not outcomes:
        return JdjRobustnessHorizonSummary(0, None, None, None, None)
    sample_count = len(outcomes)
    return JdjRobustnessHorizonSummary(
        sample_count=sample_count,
        historical_positive_outcome_rate=(
            Decimal(
                sum(
                    outcome.directional_return_bps > 0
                    for outcome in outcomes
                )
            )
            / Decimal(sample_count)
        ),
        median_directional_return_bps=median(
            outcome.directional_return_bps for outcome in outcomes
        ),
        median_mfe_bps=median(outcome.mfe_bps for outcome in outcomes),
        median_mae_bps=median(outcome.mae_bps for outcome in outcomes),
    )


def _validate_batch(
    protocol: JdjActive60RobustnessProtocol,
    batch: JdjBatchResearchResult,
    *,
    symbol: str,
) -> None:
    if (
        not isinstance(batch, JdjBatchResearchResult)
        or batch.symbol != symbol
        or not (
            protocol.common_since
            <= batch.observed_since
            <= batch.observed_through
            <= protocol.common_through
        )
        or tuple(
            candidate.result.candidate_id for candidate in batch.candidates
        )
        != protocol.candidate_ids
        or any(
            not protocol.common_since
            <= record.trading_day
            <= protocol.common_through
            for candidate in batch.candidates
            for record in candidate.event_outcomes
        )
    ):
        raise JdjContextError()


def _sector_for(
    protocol: JdjActive60RobustnessProtocol,
    symbol: str,
) -> str:
    matches = tuple(
        sector
        for sector, symbols in protocol.sector_groups.items()
        if symbol in symbols
    )
    if len(matches) != 1:
        raise JdjActive60RobustnessProtocolError()
    return matches[0]


def _unavailable_row(
    protocol: JdjActive60RobustnessProtocol,
    *,
    candidate_id: str,
    symbol: str,
) -> JdjRobustnessSymbolResult:
    return JdjRobustnessSymbolResult(
        candidate_id=candidate_id,
        symbol=symbol,
        sector=_sector_for(protocol, symbol),
        status=JdjRobustnessStatus.UNAVAILABLE,
        reason_code=JdjSourceUnavailableError.code,
        observed_since=None,
        observed_through=None,
        evaluable_bar_count=None,
        event_count=None,
        long_event_count=None,
        short_event_count=None,
        event_rate_per_1000_evaluable=None,
        horizon_summary=None,
        yearly=None,
    )


def _available_row(
    protocol: JdjActive60RobustnessProtocol,
    batch: JdjBatchResearchResult,
    detailed: JdjDetailedCandidateResult,
) -> JdjRobustnessSymbolResult:
    result = detailed.result
    event_count = len(detailed.event_outcomes)
    evaluable_bar_count = result.evaluable_bar_count
    return JdjRobustnessSymbolResult(
        candidate_id=result.candidate_id,
        symbol=batch.symbol,
        sector=_sector_for(protocol, batch.symbol),
        status=JdjRobustnessStatus.AVAILABLE,
        reason_code=None,
        observed_since=batch.observed_since,
        observed_through=batch.observed_through,
        evaluable_bar_count=evaluable_bar_count,
        event_count=event_count,
        long_event_count=result.trigger_count_long,
        short_event_count=result.trigger_count_short,
        event_rate_per_1000_evaluable=(
            None
            if evaluable_bar_count == 0
            else Decimal(event_count)
            * Decimal(1000)
            / Decimal(evaluable_bar_count)
        ),
        horizon_summary={
            horizon: summarize_jdj_robustness_horizon(
                tuple(
                    outcome
                    for record in detailed.event_outcomes
                    if (outcome := record.outcomes[horizon]) is not None
                )
            )
            for horizon in protocol.horizons_bars
        },
        yearly=_yearly_summaries(protocol, detailed.event_outcomes),
    )


def _yearly_summaries(
    protocol: JdjActive60RobustnessProtocol,
    records: Sequence[JdjEventOutcomeRecord],
) -> dict[int, JdjRobustnessYearSummary]:
    summaries: dict[int, JdjRobustnessYearSummary] = {}
    for year in _YEARS:
        year_records = tuple(
            record for record in records if record.trading_day.year == year
        )
        horizon_summaries = {
            horizon: summarize_jdj_robustness_horizon(
                tuple(
                    outcome
                    for record in year_records
                    if (outcome := record.outcomes[horizon]) is not None
                )
            )
            for horizon in protocol.horizons_bars
        }
        summaries[year] = JdjRobustnessYearSummary(
            event_count=len(year_records),
            horizon_sample_count={
                horizon: value.sample_count
                for horizon, value in horizon_summaries.items()
            },
            horizon_positive_outcome_rate={
                horizon: value.historical_positive_outcome_rate
                for horizon, value in horizon_summaries.items()
            },
            horizon_median_directional_return_bps={
                horizon: value.median_directional_return_bps
                for horizon, value in horizon_summaries.items()
            },
        )
    return summaries


def _sector_summary(
    protocol: JdjActive60RobustnessProtocol,
    rows: Sequence[JdjRobustnessSymbolResult],
    *,
    candidate_id: str,
    sector: str,
) -> JdjRobustnessSectorSummary:
    sector_symbols = protocol.sector_groups[sector]
    sector_rows = tuple(
        row
        for row in rows
        if row.candidate_id == candidate_id and row.symbol in sector_symbols
    )
    available = tuple(
        row
        for row in sector_rows
        if row.status is JdjRobustnessStatus.AVAILABLE
    )
    return JdjRobustnessSectorSummary(
        candidate_id=candidate_id,
        sector=sector,
        symbol_count=len(sector_symbols),
        available_symbol_count=len(available),
        symbols_with_events=sum(
            row.event_count is not None and row.event_count > 0
            for row in available
        ),
        horizon_summary={
            horizon: _sector_horizon_summary(available, horizon=horizon)
            for horizon in protocol.horizons_bars
        },
    )


def _sector_horizon_summary(
    available_rows: Sequence[JdjRobustnessSymbolResult],
    *,
    horizon: int,
) -> JdjRobustnessSectorHorizonSummary:
    symbol_medians: list[Decimal] = []
    for row in available_rows:
        assert row.horizon_summary is not None
        value = row.horizon_summary[horizon].median_directional_return_bps
        if value is not None:
            symbol_medians.append(value)
    return JdjRobustnessSectorHorizonSummary(
        symbols_with_samples=len(symbol_medians),
        positive_median_symbol_count=sum(value > 0 for value in symbol_medians),
        zero_median_symbol_count=sum(value == 0 for value in symbol_medians),
        negative_median_symbol_count=sum(value < 0 for value in symbol_medians),
        median_of_symbol_median_return_bps=(
            median(symbol_medians) if symbol_medians else None
        ),
    )


def _quality_flags(
    protocol: JdjActive60RobustnessProtocol,
    rows: Sequence[JdjRobustnessSymbolResult],
) -> tuple[str, ...]:
    source_unavailable = any(
        row.status is JdjRobustnessStatus.UNAVAILABLE for row in rows
    )
    symbol_without_event = any(
        row.status is JdjRobustnessStatus.AVAILABLE and row.event_count == 0
        for row in rows
    )
    horizon_without_sample = any(
        row.status is JdjRobustnessStatus.AVAILABLE
        and row.horizon_summary is not None
        and any(
            summary.sample_count == 0
            for summary in row.horizon_summary.values()
        )
        for row in rows
    )
    short_history = any(
        row.status is JdjRobustnessStatus.AVAILABLE
        and row.observed_since is not None
        and row.observed_since > protocol.common_since
        for row in rows
    )
    return tuple(
        flag
        for flag, present in (
            ("SOURCE_UNAVAILABLE_PRESENT", source_unavailable),
            ("SYMBOL_WITHOUT_EVENT", symbol_without_event),
            ("HORIZON_WITHOUT_SAMPLE", horizon_without_sample),
            ("SHORT_HISTORY_PRESENT", short_history),
        )
        if present
    )
