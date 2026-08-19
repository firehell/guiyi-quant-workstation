"""Read-only Historical Shadow orchestration for Futures Mirror V1."""

from __future__ import annotations

import importlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol, cast

from .domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    MarketSeriesResult,
    SeriesKind,
    SeriesQuery,
    normalize_contract_for_symbol,
)


_HORIZONS = (1, 3, 5, 10)
_KERNEL_MODULE_PARTS = (
    "guiyi_quant",
    "indicators",
    "main_force_mirror_futures",
)
_KERNEL_FUNCTION = "compute_main_force_mirror_futures"


@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesResearchRequest:
    symbol: str
    series_kind: SeriesKind
    contract: str | None
    frequency: BarFrequency
    since: date
    through: date

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        symbol = self.symbol.strip().lower()
        if not symbol.isascii() or not symbol.isalpha():
            raise ValueError("symbol must contain ASCII letters only")
        try:
            series_kind = SeriesKind(self.series_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("series kind is unsupported") from exc
        try:
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError) as exc:
            raise ValueError("frequency is unsupported") from exc
        if frequency is not BarFrequency.H1:
            raise ValueError("frequency must be 60m")
        if series_kind not in {SeriesKind.ACTUAL_DOMINANT, SeriesKind.CONTRACT}:
            raise ValueError("series kind is unsupported")
        contract = self.contract
        if series_kind is SeriesKind.CONTRACT:
            contract = normalize_contract_for_symbol(symbol, contract)
            if contract is None:
                raise ValueError("contract code is required and must match symbol")
        elif contract is not None:
            raise ValueError("contract is forbidden for actual-dominant series")
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
        ):
            raise ValueError("trading-day window is invalid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesEvent:
    indicator_code: str
    indicator_version: str
    parameters_hash: str
    symbol: str
    series_kind: SeriesKind
    physical_contract: str
    trading_day: date
    bar_end: datetime
    caution_direction: str
    score: float
    reason_codes: tuple[str, ...]
    state: str


@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesHorizonSummary:
    horizon_bars: int
    sample_count: int
    reversal_returns: tuple[float, ...]
    warning_mfe: tuple[float, ...]
    warning_mae: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorFuturesResearchResult:
    products: tuple[str, ...]
    bars_valid_count: int
    bars_state_ready_count: int
    bars_caution_ready_count: int
    event_count_long: int
    event_count_short: int
    conflict_count: int
    missing_oi_count: int
    segment_reset_count: int
    timestamp_invalid_count: int
    state_distribution: Mapping[str, int]
    reason_code_distribution: Mapping[str, int]
    score_distribution: tuple[int, ...]
    horizon_summary: Mapping[int, MainForceMirrorFuturesHorizonSummary]


class _MarketDataReader(Protocol):
    def query(self, request: SeriesQuery) -> MarketSeriesResult: ...

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult: ...

    def query_contract_trading_days(
        self,
        request: ContractTradingDayQuery,
    ) -> MarketSeriesResult: ...


class _KernelResult(Protocol):
    metadata: Mapping[str, object]
    valid: Sequence[bool]
    state_ready: Sequence[bool]
    caution_ready: Sequence[bool]
    reason: Sequence[str | None]
    caution_availability_reason: Sequence[str | None]
    state: Sequence[str | None]
    long_caution_score: Sequence[float]
    short_caution_score: Sequence[float]
    caution: Sequence[str | None]
    caution_reason_codes: Sequence[tuple[str, ...]]


class _KernelCallable(Protocol):
    def __call__(
        self,
        *,
        datetimes: Sequence[datetime],
        physical_contract: Sequence[str],
        open_: Sequence[float],
        high: Sequence[float],
        low: Sequence[float],
        close: Sequence[float],
        volume: Sequence[float],
        open_interest: Sequence[float | None],
    ) -> _KernelResult: ...


class MainForceMirrorFuturesResearchError(RuntimeError):
    """Stable public read-only Shadow failure without storage details."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load_main_force_mirror_futures_kernel() -> _KernelCallable:
    """Load the fixed Python V1 authority through one runtime boundary."""
    try:
        module = importlib.import_module(".".join(_KERNEL_MODULE_PARTS))
    except ImportError as exc:
        raise MainForceMirrorFuturesResearchError(
            "MFM_FUTURES_V1_KERNEL_UNAVAILABLE"
        ) from exc
    candidate = getattr(module, _KERNEL_FUNCTION, None)
    if not callable(candidate):
        raise MainForceMirrorFuturesResearchError("MFM_FUTURES_V1_KERNEL_UNAVAILABLE")
    return cast(_KernelCallable, candidate)


compute_main_force_mirror_futures = _load_main_force_mirror_futures_kernel()


def _extract_events(
    *,
    request: MainForceMirrorFuturesResearchRequest,
    bars: tuple[CanonicalBar, ...],
    physical_contracts: tuple[str, ...],
    observation: _KernelResult,
) -> tuple[MainForceMirrorFuturesEvent, ...]:
    """Project directional Kernel cautions into immutable event identities."""

    metadata = observation.metadata
    indicator_code = metadata.get("indicator_code")
    indicator_version = metadata.get("indicator_version")
    parameters_hash = metadata.get("parameters_hash")
    if not all(
        isinstance(value, str) and value
        for value in (indicator_code, indicator_version, parameters_hash)
    ):
        raise MainForceMirrorFuturesResearchError(
            "MFM_FUTURES_V1_INDICATOR_IDENTITY_INVALID"
        )
    indicator_code = cast(str, indicator_code)
    indicator_version = cast(str, indicator_version)
    parameters_hash = cast(str, parameters_hash)
    events: list[MainForceMirrorFuturesEvent] = []
    for index, caution in enumerate(observation.caution):
        if caution not in {"long_chase_caution", "short_chase_caution"}:
            continue
        state = observation.state[index]
        if not isinstance(state, str) or not state:
            raise MainForceMirrorFuturesResearchError(
                "MFM_FUTURES_V1_EVENT_IDENTITY_INVALID"
            )
        score_value = (
            observation.long_caution_score[index]
            if caution == "long_chase_caution"
            else observation.short_caution_score[index]
        )
        score = float(score_value)
        events.append(
            MainForceMirrorFuturesEvent(
                indicator_code=indicator_code,
                indicator_version=indicator_version,
                parameters_hash=parameters_hash,
                symbol=request.symbol,
                series_kind=request.series_kind,
                physical_contract=physical_contracts[index],
                trading_day=bars[index].trading_day,
                bar_end=bars[index].bar_end,
                caution_direction=caution,
                score=score,
                reason_codes=tuple(observation.caution_reason_codes[index]),
                state=state,
            )
        )
    return tuple(events)


def _summarize_horizons(
    *,
    events: tuple[MainForceMirrorFuturesEvent, ...],
    bars: tuple[CanonicalBar, ...],
    physical_contracts: tuple[str, ...],
) -> Mapping[int, MainForceMirrorFuturesHorizonSummary]:
    """Calculate forward outcomes without crossing one physical segment."""

    bar_index = {bar.bar_end: index for index, bar in enumerate(bars)}
    outcomes: dict[int, dict[str, list[float]]] = {
        horizon: {"reversal": [], "mfe": [], "mae": []} for horizon in _HORIZONS
    }
    for event in events:
        index = bar_index[event.bar_end]
        event_close = float(bars[index].close)
        if event_close == 0.0:
            continue
        for horizon in _HORIZONS:
            target_index = index + horizon
            if target_index >= len(bars):
                continue
            if any(
                contract != event.physical_contract
                for contract in physical_contracts[index : target_index + 1]
            ):
                continue
            target_close = float(bars[target_index].close)
            future = bars[index + 1 : target_index + 1]
            future_low = min(float(bar.low) for bar in future)
            future_high = max(float(bar.high) for bar in future)
            if event.caution_direction == "long_chase_caution":
                reversal = (event_close - target_close) / event_close
                warning_mfe = (event_close - future_low) / event_close
                warning_mae = (future_high - event_close) / event_close
            else:
                reversal = (target_close - event_close) / event_close
                warning_mfe = (future_high - event_close) / event_close
                warning_mae = (event_close - future_low) / event_close
            outcomes[horizon]["reversal"].append(reversal)
            outcomes[horizon]["mfe"].append(warning_mfe)
            outcomes[horizon]["mae"].append(warning_mae)
    return MappingProxyType(
        {
            horizon: MainForceMirrorFuturesHorizonSummary(
                horizon_bars=horizon,
                sample_count=len(values["reversal"]),
                reversal_returns=tuple(values["reversal"]),
                warning_mfe=tuple(values["mfe"]),
                warning_mae=tuple(values["mae"]),
            )
            for horizon, values in outcomes.items()
        }
    )


class MainForceMirrorFuturesResearchService:
    """Evaluate Futures V1 once over one exact Historical market sequence."""

    def __init__(self, market_data: _MarketDataReader) -> None:
        if (
            not callable(getattr(market_data, "query", None))
            or not callable(
                getattr(market_data, "query_actual_dominant_trading_days", None)
            )
            or not callable(getattr(market_data, "query_contract_trading_days", None))
        ):
            raise TypeError("market_data must implement the read-only query contract")
        self._market_data = market_data

    def run(
        self,
        request: MainForceMirrorFuturesResearchRequest,
    ) -> MainForceMirrorFuturesResearchResult:
        if not isinstance(request, MainForceMirrorFuturesResearchRequest):
            raise TypeError("request must be MainForceMirrorFuturesResearchRequest")
        market_result = self._query(request)
        bars = tuple(
            bar
            for bar in market_result.bars
            if request.since <= bar.trading_day <= request.through
        )
        physical_contracts = self._physical_contracts(
            request,
            bars,
            market_result,
        )
        observation = compute_main_force_mirror_futures(
            datetimes=[bar.bar_end for bar in bars],
            physical_contract=physical_contracts,
            open_=[float(bar.open) for bar in bars],
            high=[float(bar.high) for bar in bars],
            low=[float(bar.low) for bar in bars],
            close=[float(bar.close) for bar in bars],
            volume=[float(bar.volume) for bar in bars],
            open_interest=[
                None if bar.open_interest is None else float(bar.open_interest)
                for bar in bars
            ],
        )
        state_distribution = Counter(
            str(value) for value in observation.state if value is not None
        )
        events = _extract_events(
            request=request,
            bars=bars,
            physical_contracts=physical_contracts,
            observation=observation,
        )
        reason_distribution = Counter(
            reason for event in events for reason in event.reason_codes
        )
        return MainForceMirrorFuturesResearchResult(
            products=(request.symbol,),
            bars_valid_count=sum(bool(value) for value in observation.valid),
            bars_state_ready_count=sum(
                bool(value) for value in observation.state_ready
            ),
            bars_caution_ready_count=sum(
                bool(value) for value in observation.caution_ready
            ),
            event_count_long=sum(
                event.caution_direction == "long_chase_caution" for event in events
            ),
            event_count_short=sum(
                event.caution_direction == "short_chase_caution" for event in events
            ),
            conflict_count=sum(
                value == "MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT"
                for value in observation.caution_availability_reason
            ),
            missing_oi_count=sum(
                value == "MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE"
                for value in observation.reason
            ),
            segment_reset_count=sum(
                current != previous
                for previous, current in zip(
                    physical_contracts,
                    physical_contracts[1:],
                    strict=False,
                )
            ),
            timestamp_invalid_count=sum(
                value == "MFM_FUTURES_V1_TIMESTAMP_INVALID"
                for value in observation.reason
            ),
            state_distribution=MappingProxyType(
                dict(sorted(state_distribution.items()))
            ),
            reason_code_distribution=MappingProxyType(
                dict(sorted(reason_distribution.items()))
            ),
            score_distribution=tuple(int(event.score) for event in events),
            horizon_summary=_summarize_horizons(
                events=events,
                bars=bars,
                physical_contracts=physical_contracts,
            ),
        )

    def _query(
        self,
        request: MainForceMirrorFuturesResearchRequest,
    ) -> MarketSeriesResult:
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return self._market_data.query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    request.symbol,
                    request.frequency,
                    request.since,
                    request.through,
                )
            )
        assert request.contract is not None
        return self._market_data.query_contract_trading_days(
            ContractTradingDayQuery(
                symbol=request.symbol,
                contract=request.contract,
                frequency=request.frequency,
                since=request.since,
                through=request.through,
            )
        )

    @staticmethod
    def _physical_contracts(
        request: MainForceMirrorFuturesResearchRequest,
        bars: tuple[CanonicalBar, ...],
        market_result: MarketSeriesResult,
    ) -> tuple[str, ...]:
        if request.series_kind is SeriesKind.CONTRACT:
            assert request.contract is not None
            return (request.contract,) * len(bars)

        contracts: list[str] = []
        for bar in bars:
            matches = tuple(
                segment
                for segment in market_result.resolved_contract_segments
                if segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            if len(matches) > 1:
                raise MainForceMirrorFuturesResearchError(
                    "MFM_FUTURES_V1_SEGMENT_CONFLICT"
                )
            if not matches:
                raise MainForceMirrorFuturesResearchError(
                    "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING"
                )
            contract = normalize_contract_for_symbol(
                request.symbol,
                matches[0].contract,
            )
            if contract is None:
                raise MainForceMirrorFuturesResearchError(
                    "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING"
                )
            contracts.append(contract)
        return tuple(contracts)
