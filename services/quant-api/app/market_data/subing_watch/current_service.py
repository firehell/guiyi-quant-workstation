"""Read-only current and restore projections for SuBing Watch 15m."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from guiyi_quant.indicators.subing_watch_15m import (
    SubingWatchKernelHigherTimeframe,
    SubingWatchKernelState,
)

from ..actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
    ActualDominantResearchSourceTradingDayMissingError,
)
from ..domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from ..market_data_service import MarketDataError
from ..market_read_service import MarketObservationSnapshot, MarketReadState
from .contracts import (
    SubingWatchEvaluation,
    SubingWatchPolicy,
    SubingWatchSourceIdentity,
)
from .replay import SubingWatchReplayError, replay_subing_watch_segment


class SubingWatchCurrentSourceUnavailableError(RuntimeError):
    code = "SUBING_WATCH_CURRENT_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingWatchCurrentSourceIdentityError(RuntimeError):
    code = "SUBING_WATCH_CURRENT_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingWatchCurrentActiveProductError(ValueError):
    code = "SUBING_WATCH_CURRENT_ACTIVE_PRODUCT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class _ResearchSegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


class _MarketRead(Protocol):
    def observation_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
        *,
        inclusive_after: bool = False,
    ) -> MarketObservationSnapshot: ...


class _SegmentSummary(Protocol):
    @property
    def symbol(self) -> str: ...

    @property
    def contract(self) -> str: ...

    @property
    def start_trading_day(self) -> date: ...

    @property
    def end_trading_day(self) -> date: ...


@dataclass(frozen=True, slots=True)
class SubingWatchCurrentRequest:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency

    def __post_init__(self) -> None:
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError):
            raise ValueError("INVALID_SUBING_WATCH_CURRENT_REQUEST") from None
        symbol = self.symbol
        if (
            not isinstance(symbol, str)
            or symbol != symbol.strip().lower()
            or not symbol.isascii()
            or not symbol.isalpha()
            or series_kind is not SeriesKind.ACTUAL_DOMINANT
            or frequency is not BarFrequency.M15
        ):
            raise ValueError("INVALID_SUBING_WATCH_CURRENT_REQUEST")
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SubingWatchProjection:
    policy: SubingWatchPolicy
    request: SubingWatchCurrentRequest
    source_identity: SubingWatchSourceIdentity
    source_mode: Literal["canonical", "canonical_live"]
    coverage: tuple[datetime, datetime]
    cutoff: datetime
    evaluations: tuple[SubingWatchEvaluation, ...]
    final_state: SubingWatchKernelState
    latest_higher_timeframe: SubingWatchKernelHigherTimeframe | None


@dataclass(frozen=True, slots=True)
class SubingWatchRestoreState:
    policy: SubingWatchPolicy
    source_identity: SubingWatchSourceIdentity
    source_mode: Literal["canonical", "canonical_live"]
    coverage: tuple[datetime, datetime]
    cutoff: datetime
    state: SubingWatchKernelState
    last_evaluation: SubingWatchEvaluation
    latest_higher_timeframe: SubingWatchKernelHigherTimeframe | None


@dataclass(frozen=True, slots=True)
class _PreparedProjection:
    source_identity: SubingWatchSourceIdentity
    source_mode: Literal["canonical", "canonical_live"]
    bars_15m: tuple[CanonicalBar, ...]
    bars_60m: tuple[CanonicalBar, ...]


class SubingWatchCurrentProjectionService:
    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: tuple[str, ...],
        market_read: _MarketRead,
        current_segment: Callable[[str, date], _SegmentSummary],
        policy: SubingWatchPolicy,
    ) -> None:
        normalized = tuple(item.strip().lower() for item in products)
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(not item or not item.isascii() or not item.isalpha() for item in normalized)
            or type(policy) is not SubingWatchPolicy
        ):
            raise SubingWatchCurrentSourceIdentityError()
        self._segment_loader = segment_loader
        self._products = frozenset(normalized)
        self._market_read = market_read
        self._current_segment = current_segment
        self._policy = policy

    def current(
        self,
        request: SubingWatchCurrentRequest,
        now: datetime,
    ) -> SubingWatchProjection:
        if type(request) is not SubingWatchCurrentRequest:
            raise TypeError("request must be SubingWatchCurrentRequest")
        if request.symbol not in self._products:
            raise SubingWatchCurrentActiveProductError()
        prepared = self._prepare(request.symbol, now)
        try:
            replayed = replay_subing_watch_segment(
                prepared.source_identity,
                prepared.bars_15m,
                prepared.bars_60m,
                self._policy,
                source_mode=prepared.source_mode,
            )
        except (SubingWatchReplayError, ValueError):
            raise SubingWatchCurrentSourceIdentityError() from None
        return SubingWatchProjection(
            policy=self._policy,
            request=request,
            source_identity=prepared.source_identity,
            source_mode=prepared.source_mode,
            coverage=replayed.coverage,
            cutoff=replayed.coverage[1],
            evaluations=replayed.evaluations,
            final_state=replayed.final_state,
            latest_higher_timeframe=replayed.latest_higher_timeframe,
        )

    def restore_state(self, symbol: str, now: datetime) -> SubingWatchRestoreState:
        request = SubingWatchCurrentRequest(
            SeriesKind.ACTUAL_DOMINANT,
            symbol,
            BarFrequency.M15,
        )
        projected = self.current(request, now)
        return SubingWatchRestoreState(
            policy=projected.policy,
            source_identity=projected.source_identity,
            source_mode=projected.source_mode,
            coverage=projected.coverage,
            cutoff=projected.cutoff,
            state=projected.final_state,
            last_evaluation=projected.evaluations[-1],
            latest_higher_timeframe=projected.latest_higher_timeframe,
        )

    def _prepare(self, symbol: str, now: datetime) -> _PreparedProjection:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise SubingWatchCurrentSourceIdentityError()
        cutoff = now.astimezone(UTC)
        identity_15m = SeriesPageQuery(
            SeriesKind.ACTUAL_DOMINANT,
            symbol,
            BarFrequency.M15,
        )
        snapshot_15m = self._read_observation(identity_15m, None, cutoff)
        if type(snapshot_15m.state) is not MarketReadState:
            raise SubingWatchCurrentSourceIdentityError()
        target_day = snapshot_15m.state.trading_day
        if type(target_day) is not date:
            raise SubingWatchCurrentSourceUnavailableError()
        segment = self._resolve_segment(symbol, target_day)
        source_identity = SubingWatchSourceIdentity(
            symbol,
            segment.contract,
            segment.start_trading_day,
        )
        canonical_15m = self._load_canonical_frequency(
            symbol,
            segment,
            target_day,
            cutoff,
            BarFrequency.M15,
        )
        self._validate_observation_snapshot(
            snapshot_15m,
            identity=identity_15m,
            target_day=target_day,
            contract=segment.contract,
        )
        bars_15m, used_live_15m = _merge_canonical_live(
            canonical_15m,
            snapshot_15m.bars,
            target_day=target_day,
            cutoff=cutoff,
        )
        if not bars_15m:
            raise SubingWatchCurrentSourceUnavailableError()
        bars_60m, used_live_60m = self._prepare_optional_higher_timeframe(
            symbol=symbol,
            segment=segment,
            target_day=target_day,
            cutoff=cutoff,
        )
        return _PreparedProjection(
            source_identity=source_identity,
            source_mode=(
                "canonical_live" if used_live_15m or used_live_60m else "canonical"
            ),
            bars_15m=bars_15m,
            bars_60m=bars_60m,
        )

    def _prepare_optional_higher_timeframe(
        self,
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        target_day: date,
        cutoff: datetime,
    ) -> tuple[tuple[CanonicalBar, ...], bool]:
        """Return only causally valid H1 context; every H1-only failure is non-gating."""

        try:
            canonical = self._load_canonical_frequency(
                symbol,
                segment,
                target_day,
                cutoff,
                BarFrequency.H1,
            )
            identity = SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                BarFrequency.H1,
            )
            snapshot = self._read_observation(
                identity,
                canonical[-1].bar_end if canonical else None,
                cutoff,
            )
            if not self._validate_observation_snapshot(
                snapshot,
                identity=identity,
                target_day=target_day,
                contract=segment.contract,
            ):
                return (), False
            return _merge_canonical_live(
                canonical,
                snapshot.bars,
                target_day=target_day,
                cutoff=cutoff,
            )
        except (
            SubingWatchCurrentSourceIdentityError,
            SubingWatchCurrentSourceUnavailableError,
        ):
            return (), False

    def _resolve_segment(
        self,
        symbol: str,
        target_day: date,
    ) -> ResolvedContractSegment:
        try:
            summary = self._current_segment(symbol, target_day)
            contract = normalize_contract_for_symbol(symbol, summary.contract)
        except MarketDataError:
            raise SubingWatchCurrentSourceUnavailableError() from None
        except (AttributeError, TypeError, ValueError):
            raise SubingWatchCurrentSourceIdentityError() from None
        if (
            getattr(summary, "symbol", symbol) != symbol
            or contract is None
            or type(summary.start_trading_day) is not date
            or type(summary.end_trading_day) is not date
            or not summary.start_trading_day <= target_day <= summary.end_trading_day
        ):
            raise SubingWatchCurrentSourceIdentityError()
        return ResolvedContractSegment(
            contract,
            summary.start_trading_day,
            summary.end_trading_day,
        )

    def _load_canonical_frequency(
        self,
        symbol: str,
        segment: ResolvedContractSegment,
        target_day: date,
        cutoff: datetime,
        frequency: BarFrequency,
    ) -> tuple[CanonicalBar, ...]:
        try:
            loaded = self._segment_loader.load(
                symbol=symbol,
                frequencies=(frequency,),
                since=segment.start_trading_day,
                through=target_day,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingWatchCurrentSourceIdentityError() from None
        except ActualDominantResearchSourceTradingDayMissingError:
            raise SubingWatchCurrentSourceUnavailableError() from None
        except MarketDataError:
            raise SubingWatchCurrentSourceUnavailableError() from None
        if (
            loaded.segments != (segment,)
            or loaded.results.get(frequency) is None
        ):
            raise SubingWatchCurrentSourceIdentityError()
        bars = loaded.results[frequency].bars
        if any(
            type(bar) is not CanonicalBar
            or not segment.start_trading_day <= bar.trading_day <= target_day
            for bar in bars
        ):
            raise SubingWatchCurrentSourceIdentityError()
        return tuple(bar for bar in bars if bar.bar_end <= cutoff)

    def _read_observation(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> MarketObservationSnapshot:
        try:
            snapshot = self._market_read.observation_snapshot(
                identity,
                after,
                now,
                inclusive_after=True,
            )
        except Exception as exc:  # noqa: BLE001 - typed external read boundary
            raise SubingWatchCurrentSourceUnavailableError() from exc
        if type(snapshot) is not MarketObservationSnapshot:
            raise SubingWatchCurrentSourceIdentityError()
        return snapshot

    @staticmethod
    def _validate_observation_snapshot(
        snapshot: MarketObservationSnapshot,
        *,
        identity: SeriesPageQuery,
        target_day: date,
        contract: str,
    ) -> bool:
        state = snapshot.state
        if (
            type(state) is not MarketReadState
            or state.symbol != identity.symbol
            or state.series_kind != identity.series_kind.value
            or state.frequency != identity.frequency.value
            or (state.live_available and not state.live_eligible)
            or state.trading_day != target_day
            or snapshot.trading_day != target_day
            or type(snapshot.bars) is not tuple
        ):
            raise SubingWatchCurrentSourceIdentityError()
        if snapshot.source == "unavailable":
            raise SubingWatchCurrentSourceUnavailableError()
        if snapshot.source == "none":
            state_contract = normalize_contract_for_symbol(
                identity.symbol,
                state.live_contract,
            )
            snapshot_contract = normalize_contract_for_symbol(
                identity.symbol,
                snapshot.contract,
            )
            if (
                state.live_available
                or snapshot.bars
                or (state.live_contract is not None and state_contract is None)
                or (snapshot.contract is not None and snapshot_contract is None)
                or snapshot_contract != state_contract
            ):
                raise SubingWatchCurrentSourceIdentityError()
            return True
        if snapshot.source != "realtime" or not state.live_available or not state.live_eligible:
            raise SubingWatchCurrentSourceIdentityError()
        state_contract = normalize_contract_for_symbol(identity.symbol, state.live_contract)
        snapshot_contract = normalize_contract_for_symbol(identity.symbol, snapshot.contract)
        if state_contract is None or snapshot_contract != state_contract:
            raise SubingWatchCurrentSourceIdentityError()
        if snapshot_contract != contract:
            if identity.frequency is BarFrequency.H1:
                return False
            raise SubingWatchCurrentSourceIdentityError()
        return True


def _merge_canonical_live(
    canonical: tuple[CanonicalBar, ...],
    live: tuple[CanonicalBar, ...],
    *,
    target_day: date,
    cutoff: datetime,
) -> tuple[tuple[CanonicalBar, ...], bool]:
    by_end: dict[datetime, CanonicalBar] = {}
    for bar in canonical:
        existing = by_end.get(bar.bar_end)
        if existing is not None and existing != bar:
            raise SubingWatchCurrentSourceIdentityError()
        by_end[bar.bar_end] = bar
    used_live = False
    if type(live) is not tuple:
        raise SubingWatchCurrentSourceIdentityError()
    for bar in live:
        if type(bar) is not CanonicalBar or bar.trading_day != target_day:
            raise SubingWatchCurrentSourceIdentityError()
        if bar.bar_end > cutoff:
            raise SubingWatchCurrentSourceIdentityError()
        existing = by_end.get(bar.bar_end)
        if existing is not None:
            if existing != bar:
                raise SubingWatchCurrentSourceIdentityError()
            continue
        by_end[bar.bar_end] = bar
        used_live = True
    return tuple(by_end[key] for key in sorted(by_end)), used_live
