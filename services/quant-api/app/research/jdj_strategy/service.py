"""JM-only actual-dominant Historical reference replay orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.market_data_service import MarketDataError
from app.research.jdj.jdj_context import (
    JdjBarContext,
    JdjContextError,
    build_jdj_context_series,
)
from app.research.jdj.jdj_events import JdjTriggerEvent
from app.research.jdj.jdj_key_level_breakout import reduce_jdj_key_level_breakout
from app.research.jdj.jdj_policy import JdjPolicy, is_exact_jdj_policy
from app.research.jdj.jdj_research import JDJ_CANDIDATE_SOURCE_EVENT_KINDS
from app.research.jdj.jdj_research_service import (
    _validate_event_alignment,
    _validated_segment_partitions,
)
from app.research.jdj.jdj_trend_follow import reduce_jdj_trend_follow
from app.research.jdj.jdj_trend_reentry import reduce_jdj_trend_reentry_6
from app.research.n_structure.n_structure_policy import (
    NStructurePolicy,
    is_exact_n_structure_policy,
)

from .contract import JdjStrategyContractError, JdjV1Config, load_jdj_v1_config
from .engine import JdjAction
from .replay import JdjStrategyReplayError, run_jdj_reference_segment


class JdjStrategyProfileUnavailableError(ValueError):
    code = "JDJ_STRATEGY_PROFILE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class JdjStrategyContextInvalidError(RuntimeError):
    code = "JDJ_STRATEGY_CONTEXT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class JdjStrategySegmentIdentityError(ValueError):
    code = "JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class JdjStrategySessionIdentityError(RuntimeError):
    code = "JDJ_STRATEGY_SESSION_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjStrategyReplayRequest:
    series_kind: SeriesKind | str
    symbol: str
    frequency: BarFrequency | str
    since: date
    through: date

    def __post_init__(self) -> None:
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError):
            raise JdjStrategyProfileUnavailableError() from None
        symbol = self.symbol.strip().lower() if isinstance(self.symbol, str) else ""
        if (
            series_kind is not SeriesKind.ACTUAL_DOMINANT
            or symbol != "jm"
            or frequency is not BarFrequency.M1
            or type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise JdjStrategyProfileUnavailableError()
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class JdjStrategyReplayResult:
    request: JdjStrategyReplayRequest
    actions: tuple[JdjAction, ...]
    reference_execution: bool = field(default=True, init=False)


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


class _ContractMultiplierResolver(Protocol):
    def __call__(self, *, symbol: str, contract: str) -> Decimal: ...


class _SessionTerminalResolver(Protocol):
    def __call__(
        self,
        *,
        symbol: str,
        bars_1m: Sequence[CanonicalBar],
    ) -> Mapping[date, datetime]: ...


class JdjStrategyReplayService:
    """Replay each validated physical segment independently and read-only."""

    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        jdj_policy: JdjPolicy,
        n_policy: NStructurePolicy,
        contract_multiplier_for_contract: _ContractMultiplierResolver,
        terminal_bar_ends_for_segment: _SessionTerminalResolver,
        config: JdjV1Config | None = None,
    ) -> None:
        try:
            resolved_config = config or load_jdj_v1_config()
        except JdjStrategyContractError:
            raise JdjStrategyContextInvalidError() from None
        if (
            not is_exact_jdj_policy(jdj_policy)
            or not is_exact_n_structure_policy(n_policy)
            or not callable(contract_multiplier_for_contract)
            or not callable(terminal_bar_ends_for_segment)
            or resolved_config.profile.symbol != "jm"
            or resolved_config.profile.series_kind
            != SeriesKind.ACTUAL_DOMINANT.value
            or resolved_config.profile.execution_frequency is not BarFrequency.M1
            or resolved_config.profile.trend_context_frequency is not BarFrequency.M5
        ):
            raise JdjStrategyContextInvalidError()
        self._segment_loader = segment_loader
        self._jdj_policy = jdj_policy
        self._n_policy = n_policy
        self._contract_multiplier_for_contract = contract_multiplier_for_contract
        self._terminal_bar_ends_for_segment = terminal_bar_ends_for_segment
        self._config = resolved_config

    def history(
        self,
        request: JdjStrategyReplayRequest,
    ) -> JdjStrategyReplayResult:
        if not isinstance(request, JdjStrategyReplayRequest):
            raise TypeError("request must be JdjStrategyReplayRequest")
        try:
            loaded = self._segment_loader.load(
                symbol=request.symbol,
                frequencies=(BarFrequency.M1, BarFrequency.M5),
                since=request.since,
                through=request.through,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise JdjStrategySegmentIdentityError() from None
        except MarketDataError:
            raise JdjStrategyContextInvalidError() from None

        try:
            bars_1m_by_segment, bars_5m_by_segment = (
                _validated_segment_partitions(
                    loaded,
                    symbol=request.symbol,
                    through=request.through,
                )
            )
        except ActualDominantResearchSegmentIdentityError:
            raise JdjStrategySegmentIdentityError() from None

        projected: list[JdjAction] = []
        for segment, bars_1m, bars_5m in zip(
            loaded.segments,
            bars_1m_by_segment,
            bars_5m_by_segment,
            strict=True,
        ):
            try:
                contexts = build_jdj_context_series(
                    bars_1m,
                    bars_5m,
                    contract=segment.contract,
                    segment_start_trading_day=segment.start_trading_day,
                    segment_end_trading_day=segment.end_trading_day,
                    jdj_policy=self._jdj_policy,
                    n_policy=self._n_policy,
                )
                candidate_events = self._candidate_events(
                    contexts,
                    symbol=request.symbol,
                    segment=segment,
                    bars_1m=bars_1m,
                )
            except JdjContextError:
                raise JdjStrategyContextInvalidError() from None

            multiplier = self._resolve_multiplier(
                symbol=request.symbol,
                contract=segment.contract,
            )
            terminals = self._resolve_terminals(
                symbol=request.symbol,
                bars_1m=bars_1m,
            )
            try:
                replay = run_jdj_reference_segment(
                    symbol=request.symbol,
                    segment=segment,
                    bars_1m=bars_1m,
                    contexts=contexts,
                    candidate_events=candidate_events,
                    contract_multiplier=multiplier,
                    terminal_bar_end_by_day=terminals,
                    config=self._config,
                )
            except JdjStrategyReplayError:
                raise JdjStrategyContextInvalidError() from None
            if any(
                action.contract != segment.contract
                or action.segment_start_trading_day != segment.start_trading_day
                or not (
                    segment.start_trading_day
                    <= action.trading_day
                    <= segment.end_trading_day
                )
                for action in replay.actions
            ):
                raise JdjStrategySegmentIdentityError()
            projected.extend(
                action
                for action in replay.actions
                if request.since <= action.trading_day <= request.through
            )
        return JdjStrategyReplayResult(
            request=request,
            actions=tuple(projected),
        )

    @staticmethod
    def _candidate_events(
        contexts: Sequence[JdjBarContext],
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        bars_1m: tuple[CanonicalBar, ...],
    ) -> tuple[JdjTriggerEvent, ...]:
        reducers = (
            (
                "jdj_trend_follow_1m_candidate_v1",
                reduce_jdj_trend_follow,
            ),
            (
                "jdj_trend_reentry_6_1m_candidate_v1",
                reduce_jdj_trend_reentry_6,
            ),
            (
                "jdj_key_level_breakout_1m_candidate_v1",
                reduce_jdj_key_level_breakout,
            ),
        )
        events: list[JdjTriggerEvent] = []
        for candidate_id, reducer in reducers:
            trace = reducer(
                contexts,
                symbol=symbol,
                contract=segment.contract,
                segment_start_trading_day=segment.start_trading_day,
            )
            source_event_kind = JDJ_CANDIDATE_SOURCE_EVENT_KINDS[candidate_id]
            for event in trace.events:
                _validate_event_alignment(
                    event,
                    candidate_id=candidate_id,
                    source_event_kind=source_event_kind,
                    symbol=symbol,
                    segment=segment,
                    bars_1m=bars_1m,
                )
                events.append(event)
        return tuple(
            sorted(events, key=lambda event: (event.observed_at, event.event_id))
        )

    def _resolve_multiplier(self, *, symbol: str, contract: str) -> Decimal:
        try:
            value = self._contract_multiplier_for_contract(
                symbol=symbol,
                contract=contract,
            )
        except JdjStrategyContextInvalidError:
            raise
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value <= 0
        ):
            raise JdjStrategyContextInvalidError()
        return value

    def _resolve_terminals(
        self,
        *,
        symbol: str,
        bars_1m: tuple[CanonicalBar, ...],
    ) -> Mapping[date, datetime]:
        try:
            resolved = self._terminal_bar_ends_for_segment(
                symbol=symbol,
                bars_1m=bars_1m,
            )
        except JdjStrategySessionIdentityError:
            raise
        if not isinstance(resolved, Mapping):
            raise JdjStrategySessionIdentityError()
        bars_by_day = {
            day: {bar.bar_end for bar in bars_1m if bar.trading_day == day}
            for day in {bar.trading_day for bar in bars_1m}
        }
        if set(resolved) != set(bars_by_day) or any(
            not isinstance(terminal, datetime)
            or terminal.tzinfo is None
            or terminal.astimezone(UTC) not in bars_by_day[day]
            for day, terminal in resolved.items()
        ):
            raise JdjStrategySessionIdentityError()
        return resolved


__all__ = [
    "JdjStrategyContextInvalidError",
    "JdjStrategyProfileUnavailableError",
    "JdjStrategyReplayRequest",
    "JdjStrategyReplayResult",
    "JdjStrategyReplayService",
    "JdjStrategySegmentIdentityError",
    "JdjStrategySessionIdentityError",
]
