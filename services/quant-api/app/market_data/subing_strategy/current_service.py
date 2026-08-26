"""Read-only current-segment projection for SuBing Strategy V1."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from ..actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
    ActualDominantResearchSeries,
)
from ..aggregation import SessionWindow
from ..domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from ..market_data_service import MarketDataError
from ..market_read_service import MarketReadState
from ..subing_calibration import SubingCalibration, is_accepted_subing_calibration
from ..subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchItem,
    SubingDailyWatchSnapshot,
)
from ..subing_daily_watch_calendar import SubingDailyWatchCalendarError
from ..subing_daily_watch_store import SubingDailyWatchStoreError
from ..subing_lifecycle_policy import SubingLifecyclePolicy
from .contracts import (
    SubingStrategyDirection,
    SubingStrategyEpisode,
    SubingStrategyPositionState,
)
from .direction_context import (
    SubingStrategyContextIdentityError,
    SubingStrategyDirectionContext,
)
from .engine import SubingStrategyPendingAction
from .machine import SubingStrategyMachineError
from .policy import SubingStrategyPolicy
from .replay import SubingStrategyReplayError, replay_subing_strategy_segment


_FREQUENCIES = (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15)
_DIRECTION_BY_DECISION = {
    SubingDailyWatchDecision.LONG_WATCH: SubingStrategyDirection.LONG_ONLY,
    SubingDailyWatchDecision.SHORT_WATCH: SubingStrategyDirection.SHORT_ONLY,
    SubingDailyWatchDecision.EXCLUDED: SubingStrategyDirection.NO_NEW_ENTRY,
    SubingDailyWatchDecision.UNAVAILABLE: SubingStrategyDirection.UNAVAILABLE,
}
_CONTEXT_IDENTITY_REASONS = frozenset(
    {
        "DATA_IDENTITY_MISMATCH",
        "DOMINANT_SEGMENT_UNAVAILABLE",
        "PRODUCT_METADATA_UNAVAILABLE",
    }
)


class SubingStrategyCurrentSourceUnavailableError(RuntimeError):
    code = "SUBING_STRATEGY_CURRENT_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyCurrentSourceIdentityError(RuntimeError):
    code = "SUBING_STRATEGY_CURRENT_SOURCE_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class SubingStrategyCurrentActiveProductError(ValueError):
    code = "SUBING_STRATEGY_CURRENT_ACTIVE_PRODUCT_INVALID"

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

    def sessions(
        self,
        *,
        symbol: str,
        trading_days: Sequence[date],
    ) -> Mapping[date, tuple[SessionWindow, ...]]: ...


class _MarketRead(Protocol):
    def state(self, identity: SeriesPageQuery, now: datetime) -> MarketReadState: ...

    def live_snapshot(
        self,
        identity: SeriesPageQuery,
        after: datetime | None,
        now: datetime,
    ) -> tuple[CanonicalBar, ...]: ...


class _DirectionContextResolver(Protocol):
    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]: ...


class _CurrentSnapshotStore(Protocol):
    def read_current(self) -> SubingDailyWatchSnapshot | None: ...


class _SegmentSummary(Protocol):
    symbol: str
    contract: str
    start_trading_day: date
    end_trading_day: date


@dataclass(frozen=True, slots=True)
class SubingStrategyCurrentRequest:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency

    def __post_init__(self) -> None:
        try:
            series_kind = SeriesKind(self.series_kind)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError):
            raise ValueError("INVALID_SUBING_STRATEGY_CURRENT_REQUEST") from None
        symbol = self.symbol
        if (
            not isinstance(symbol, str)
            or not symbol.strip()
            or not symbol.strip().isascii()
            or not symbol.strip().isalpha()
            or series_kind is not SeriesKind.ACTUAL_DOMINANT
            or frequency is not BarFrequency.M15
        ):
            raise ValueError("INVALID_SUBING_STRATEGY_CURRENT_REQUEST")
        object.__setattr__(self, "series_kind", series_kind)
        object.__setattr__(self, "symbol", symbol.strip().lower())
        object.__setattr__(self, "frequency", frequency)


@dataclass(frozen=True, slots=True)
class SubingStrategyCurrentProjection:
    policy: SubingStrategyPolicy
    request: SubingStrategyCurrentRequest
    contract: str
    segment_start_trading_day: date
    source_mode: Literal["canonical", "canonical_live"]
    cutoff: datetime
    position_state: SubingStrategyPositionState
    pending_action: SubingStrategyPendingAction | None
    current_episode: SubingStrategyEpisode | None
    latest_completed_episode: SubingStrategyEpisode | None
    direction_context: SubingStrategyDirectionContext


class SubingStrategyCurrentProjectionService:
    def __init__(
        self,
        segment_loader: _ResearchSegmentLoader,
        *,
        products: tuple[str, ...],
        market_read: _MarketRead,
        current_segment: Callable[[str, date], _SegmentSummary],
        historical_direction_context_resolver: _DirectionContextResolver,
        current_snapshot_store: _CurrentSnapshotStore,
        target_trading_day: Callable[[datetime], date],
        previous_trading_day: Callable[[date], date],
        calibration: SubingCalibration,
        lifecycle_policy: SubingLifecyclePolicy,
        strategy_policy: SubingStrategyPolicy,
    ) -> None:
        normalized = tuple(product.strip().lower() for product in products)
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(
                not product or not product.isascii() or not product.isalpha()
                for product in normalized
            )
        ):
            raise SubingStrategyCurrentActiveProductError()
        if (
            not is_accepted_subing_calibration(calibration)
            or not isinstance(lifecycle_policy, SubingLifecyclePolicy)
            or not isinstance(strategy_policy, SubingStrategyPolicy)
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        self._segment_loader = segment_loader
        self._products = normalized
        self._market_read = market_read
        self._current_segment = current_segment
        self._historical_direction_context_resolver = (
            historical_direction_context_resolver
        )
        self._current_snapshot_store = current_snapshot_store
        self._target_trading_day = target_trading_day
        self._previous_trading_day = previous_trading_day
        self._calibration = calibration
        self._lifecycle_policy = lifecycle_policy
        self._strategy_policy = strategy_policy

    def current(
        self,
        request: SubingStrategyCurrentRequest,
        now: datetime,
    ) -> SubingStrategyCurrentProjection:
        if not isinstance(request, SubingStrategyCurrentRequest):
            raise TypeError("request must be SubingStrategyCurrentRequest")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("INVALID_SUBING_STRATEGY_CURRENT_REQUEST")
        if request.symbol not in self._products:
            raise SubingStrategyCurrentActiveProductError()

        target_day, source_day = self._resolve_days(now)
        segment = self._resolve_segment(request.symbol, target_day)
        canonical = self._load_canonical(
            symbol=request.symbol,
            segment=segment,
            through=source_day,
        )
        merged, live_ends = self._merge_completed_live(
            symbol=request.symbol,
            segment=segment,
            target_day=target_day,
            canonical=canonical,
            now=now,
        )
        bars_15m = merged[BarFrequency.M15]
        if not bars_15m:
            raise SubingStrategyCurrentSourceUnavailableError()
        cutoff = bars_15m[-1].bar_end
        replay_bars = {
            frequency: tuple(
                bar for bar in merged[frequency] if bar.bar_end <= cutoff
            )
            for frequency in _FREQUENCIES
        }
        source_mode: Literal["canonical", "canonical_live"] = (
            "canonical_live"
            if any(bar_end <= cutoff for bar_end in live_ends)
            else "canonical"
        )
        if any(not replay_bars[frequency] for frequency in _FREQUENCIES):
            raise SubingStrategyCurrentSourceUnavailableError()

        historical_days = tuple(
            day
            for day in dict.fromkeys(
                bar.trading_day for bar in replay_bars[BarFrequency.M15]
            )
            if day != target_day
        )
        historical_contexts = self._historical_contexts(
            request.symbol,
            historical_days,
        )
        current_context = self._current_context(
            symbol=request.symbol,
            target_day=target_day,
            source_day=source_day,
        )
        contexts = {**historical_contexts, target_day: current_context}
        replay_days = tuple(
            dict.fromkeys(bar.trading_day for bar in replay_bars[BarFrequency.M15])
        )
        sessions = self._sessions(request.symbol, replay_days)
        try:
            replayed = replay_subing_strategy_segment(
                symbol=request.symbol,
                segment=segment,
                bars_1m=replay_bars[BarFrequency.M1],
                bars_5m=replay_bars[BarFrequency.M5],
                bars_15m=replay_bars[BarFrequency.M15],
                sessions=sessions,
                direction_contexts=contexts,
                calibration=self._calibration,
                lifecycle_policy=self._lifecycle_policy,
                strategy_policy=self._strategy_policy,
                terminal_bar_end=None,
            )
        except (
            SubingStrategyReplayError,
            SubingStrategyMachineError,
            SubingStrategyContextIdentityError,
            ValueError,
        ):
            raise SubingStrategyCurrentSourceIdentityError() from None

        current_episode = next(
            (episode for episode in reversed(replayed.episodes) if episode.exit_action is None),
            None,
        )
        latest_completed = next(
            (episode for episode in reversed(replayed.episodes) if episode.exit_action is not None),
            None,
        )
        return SubingStrategyCurrentProjection(
            policy=self._strategy_policy,
            request=request,
            contract=segment.contract,
            segment_start_trading_day=segment.start_trading_day,
            source_mode=source_mode,
            cutoff=cutoff,
            position_state=replayed.final_position,
            pending_action=replayed.pending_action,
            current_episode=current_episode,
            latest_completed_episode=latest_completed,
            direction_context=current_context,
        )

    def _resolve_days(self, now: datetime) -> tuple[date, date]:
        try:
            target = self._target_trading_day(now)
            source = self._previous_trading_day(target)
        except SubingDailyWatchCalendarError:
            raise SubingStrategyCurrentSourceUnavailableError() from None
        if type(target) is not date or type(source) is not date or source >= target:
            raise SubingStrategyCurrentSourceIdentityError()
        return target, source

    def _resolve_segment(self, symbol: str, target_day: date) -> ResolvedContractSegment:
        try:
            summary = self._current_segment(symbol, target_day)
            contract = normalize_contract_for_symbol(symbol, summary.contract)
        except MarketDataError:
            raise SubingStrategyCurrentSourceUnavailableError() from None
        except (AttributeError, TypeError, ValueError):
            raise SubingStrategyCurrentSourceIdentityError() from None
        if (
            getattr(summary, "symbol", symbol) != symbol
            or contract is None
            or type(summary.start_trading_day) is not date
            or type(summary.end_trading_day) is not date
            or not summary.start_trading_day <= target_day <= summary.end_trading_day
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        return ResolvedContractSegment(
            contract,
            summary.start_trading_day,
            summary.end_trading_day,
        )

    def _load_canonical(
        self,
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        through: date,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        if segment.start_trading_day > through:
            return {frequency: () for frequency in _FREQUENCIES}
        try:
            loaded = self._segment_loader.load(
                symbol=symbol,
                frequencies=_FREQUENCIES,
                since=segment.start_trading_day,
                through=through,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingStrategyCurrentSourceIdentityError() from None
        except MarketDataError:
            raise SubingStrategyCurrentSourceUnavailableError() from None
        if (
            len(loaded.segments) != 1
            or loaded.segments[0].contract != segment.contract
            or loaded.segments[0].start_trading_day != segment.start_trading_day
            or any(loaded.results.get(frequency) is None for frequency in _FREQUENCIES)
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        canonical = {
            frequency: tuple(loaded.results[frequency].bars)
            for frequency in _FREQUENCIES
        }
        if any(
            not bars
            or any(
                bar.trading_day < segment.start_trading_day
                or bar.trading_day > through
                for bar in bars
            )
            for bars in canonical.values()
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        return canonical

    def _merge_completed_live(
        self,
        *,
        symbol: str,
        segment: ResolvedContractSegment,
        target_day: date,
        canonical: Mapping[BarFrequency, tuple[CanonicalBar, ...]],
        now: datetime,
    ) -> tuple[
        Mapping[BarFrequency, tuple[CanonicalBar, ...]],
        frozenset[datetime],
    ]:
        merged: dict[BarFrequency, tuple[CanonicalBar, ...]] = {}
        live_ends: set[datetime] = set()
        for frequency in _FREQUENCIES:
            identity = SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                frequency,
            )
            try:
                state = self._market_read.state(identity, now)
            except Exception as exc:  # noqa: BLE001 - transient read boundary
                raise SubingStrategyCurrentSourceUnavailableError() from exc
            self._validate_live_state(
                state,
                identity=identity,
                contract=segment.contract,
                target_day=target_day,
            )
            historical = canonical[frequency]
            live: tuple[CanonicalBar, ...] = ()
            if state.live_available:
                try:
                    live = self._market_read.live_snapshot(
                        identity,
                        historical[-1].bar_end if historical else None,
                        now,
                    )
                except Exception as exc:  # noqa: BLE001 - transient read boundary
                    raise SubingStrategyCurrentSourceUnavailableError() from exc
            by_end = {bar.bar_end: bar for bar in historical}
            if len(by_end) != len(historical):
                raise SubingStrategyCurrentSourceIdentityError()
            for bar in live:
                if (
                    type(bar) is not CanonicalBar
                    or bar.trading_day != target_day
                    or bar.bar_end > now
                    or bar.bar_end in by_end
                ):
                    raise SubingStrategyCurrentSourceIdentityError()
                by_end[bar.bar_end] = bar
            live_ends.update(bar.bar_end for bar in live)
            merged[frequency] = tuple(by_end[key] for key in sorted(by_end))
        return merged, frozenset(live_ends)

    @staticmethod
    def _validate_live_state(
        state: MarketReadState,
        *,
        identity: SeriesPageQuery,
        contract: str,
        target_day: date,
    ) -> None:
        if (
            state.symbol != identity.symbol
            or state.series_kind != identity.series_kind.value
            or state.frequency != identity.frequency.value
            or (state.trading_day is not None and state.trading_day != target_day)
            or (state.live_contract is not None and state.live_contract != contract)
            or (state.live_available and not state.live_eligible)
        ):
            raise SubingStrategyCurrentSourceIdentityError()

    def _historical_contexts(
        self,
        symbol: str,
        target_days: tuple[date, ...],
    ) -> Mapping[date, SubingStrategyDirectionContext]:
        if not target_days:
            return {}
        try:
            contexts = self._historical_direction_context_resolver.resolve(
                symbol,
                target_days,
            )
        except SubingStrategyContextIdentityError:
            raise SubingStrategyCurrentSourceIdentityError() from None
        if set(contexts) != set(target_days) or any(
            context.symbol != symbol or context.target_trading_day != day
            for day, context in contexts.items()
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        return contexts

    def _current_context(
        self,
        *,
        symbol: str,
        target_day: date,
        source_day: date,
    ) -> SubingStrategyDirectionContext:
        try:
            snapshot = self._current_snapshot_store.read_current()
        except SubingDailyWatchStoreError as exc:
            if exc.code in {
                "OBSERVATION_ROOT_UNCONFIGURED",
                "OBSERVATION_ROOT_UNAVAILABLE",
                "OBSERVATION_ROOT_NOT_WRITABLE",
            }:
                return _unavailable_context(
                    symbol,
                    target_day,
                    "SUBING_OBSERVATION_ROOT_UNAVAILABLE",
                )
            raise SubingStrategyCurrentSourceIdentityError() from None
        if snapshot is None:
            return _unavailable_context(
                symbol,
                target_day,
                "SUBING_DAILY_WATCH_NOT_GENERATED",
            )
        if snapshot.target_trading_day != target_day:
            return _unavailable_context(
                symbol,
                target_day,
                "SUBING_DAILY_WATCH_STALE",
            )
        if (
            snapshot.source_trading_day != source_day
            or tuple(item.symbol for item in snapshot.items) != self._products
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        item = snapshot.items[self._products.index(symbol)]
        return _context_from_item(item, target_day=target_day, source_day=source_day)

    def _sessions(
        self,
        symbol: str,
        trading_days: tuple[date, ...],
    ) -> tuple[SessionWindow, ...]:
        try:
            by_day = self._segment_loader.sessions(
                symbol=symbol,
                trading_days=trading_days,
            )
        except ActualDominantResearchSegmentIdentityError:
            raise SubingStrategyCurrentSourceIdentityError() from None
        except MarketDataError:
            raise SubingStrategyCurrentSourceUnavailableError() from None
        if set(by_day) != set(trading_days) or any(
            not windows
            or any(type(window) is not SessionWindow for window in windows)
            for windows in by_day.values()
        ):
            raise SubingStrategyCurrentSourceIdentityError()
        return tuple(
            sorted(
                (window for day in trading_days for window in by_day[day]),
                key=lambda window: window.start,
            )
        )


def _context_from_item(
    item: SubingDailyWatchItem,
    *,
    target_day: date,
    source_day: date,
) -> SubingStrategyDirectionContext:
    if item.decision is SubingDailyWatchDecision.UNAVAILABLE:
        reasons = item.unavailable_reasons
    else:
        reasons = item.reason_codes
    if frozenset(reasons) & _CONTEXT_IDENTITY_REASONS:
        raise SubingStrategyCurrentSourceIdentityError()
    facts = tuple(fact for fact in (item.daily, item.hourly) if fact is not None)
    contracts = {fact.contract for fact in facts}
    if (
        any(fact.trading_day != source_day for fact in facts)
        or len(contracts) > 1
        or (item.decision is not SubingDailyWatchDecision.UNAVAILABLE and len(facts) != 2)
    ):
        raise SubingStrategyCurrentSourceIdentityError()
    return SubingStrategyDirectionContext(
        symbol=item.symbol,
        target_trading_day=target_day,
        source_trading_day=source_day,
        direction=_DIRECTION_BY_DECISION[item.decision],
        reason_codes=reasons,
        daily_bar_end=item.daily.bar_end if item.daily is not None else None,
        hourly_bar_end=item.hourly.bar_end if item.hourly is not None else None,
        physical_contract=next(iter(contracts), None),
    )


def _unavailable_context(
    symbol: str,
    target_day: date,
    reason: str,
) -> SubingStrategyDirectionContext:
    return SubingStrategyDirectionContext(
        symbol=symbol,
        target_trading_day=target_day,
        source_trading_day=None,
        direction=SubingStrategyDirection.UNAVAILABLE,
        reason_codes=(reason,),
        daily_bar_end=None,
        hourly_bar_end=None,
        physical_contract=None,
    )
