"""In-memory active60 evaluator for completed-Live SuBing Strategy facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, TypeAlias

from app.market_data.aggregation import (
    AggregationError,
    SessionWindow,
    bucket_window_for_bar,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
)
from app.market_data.subing_strategy.machine import (
    SubingStrategyMachineError,
    SubingStrategyMachineState,
    SubingStrategyInterval,
    SubingStrategySourceIdentity,
    step_subing_strategy_machine,
)
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)


_RuntimeState = Literal["warming", "ready", "unavailable"]
_RuntimeCompletedBar: TypeAlias = Completed1mBar | Completed5mBar | Completed15mBar
_RUNTIME_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.M5,
    BarFrequency.M15,
)
_PUBLIC_PRODUCT_MACHINE_REASONS = frozenset(
    {
        "BOUNDARY_COMPANION_MISSING",
        "CONFLICTING_DUPLICATE",
        "CONFLICTING_TERMINAL",
        "DIRECTION_CONTEXT_UNAVAILABLE",
        "FACTOR_UNAVAILABLE_AT_DECISION",
        "INTERVAL_IDENTITY_INVALID",
        "LIFECYCLE_UNAVAILABLE",
        "RESTORE_IDENTITY_INVALID",
        "ROLLOVER_IDENTITY_INVALID",
        "SEGMENT_TERMINATED",
        "SOURCE_IDENTITY_INCONSISTENT",
        "SOURCE_IDENTITY_INVALID",
        "SOURCE_IDENTITY_MISMATCH",
        "STALE_INPUT",
        "STALE_SEGMENT_INPUT",
        "TERMINAL_IDENTITY_INVALID",
        "UNSCHEDULED_15M_BOUNDARY",
    }
)


class SubingStrategyRuntimeProductSourceError(RuntimeError):
    """Explicit per-product read failure whose private detail is never published."""


@dataclass(frozen=True, slots=True)
class SubingStrategyRuntimeProductStatus:
    symbol: str
    state: _RuntimeState
    cutoff_1m: datetime | None
    cutoff_5m: datetime | None
    cutoff_15m: datetime | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubingStrategyRuntimeActionFact:
    action: SubingStrategyAction
    episode: SubingStrategyEpisode | None

    def __post_init__(self) -> None:
        if not isinstance(self.action, SubingStrategyAction):
            raise ValueError("SUBING_STRATEGY_RUNTIME_ACTION_FACT_INVALID")
        is_open = self.action.kind in {
            SubingStrategyActionKind.OPEN_LONG,
            SubingStrategyActionKind.OPEN_SHORT,
        }
        if is_open:
            valid = self.episode is None
        else:
            valid = (
                isinstance(self.episode, SubingStrategyEpisode)
                and self.episode.episode_id == self.action.episode_id
                and self.episode.exit_action == self.action
            )
        if not valid:
            raise ValueError("SUBING_STRATEGY_RUNTIME_ACTION_FACT_INVALID")


@dataclass(frozen=True, slots=True)
class SubingStrategyRuntimeResult:
    action_facts: tuple[SubingStrategyRuntimeActionFact, ...]
    product_status: SubingStrategyRuntimeProductStatus

    def __post_init__(self) -> None:
        if (
            type(self.action_facts) is not tuple
            or type(self.product_status) is not SubingStrategyRuntimeProductStatus
            or any(
                type(fact) is not SubingStrategyRuntimeActionFact
                or fact.action.symbol != self.product_status.symbol
                for fact in self.action_facts
            )
        ):
            raise ValueError("SUBING_STRATEGY_RUNTIME_RESULT_INVALID")


class _RestoreReader(Protocol):
    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState: ...

    def restore_rollover(
        self,
        *,
        symbol: str,
        trading_day: date,
        previous_identity: SubingStrategySourceIdentity,
        terminal: AuthoritativeSegmentTerminal,
    ) -> SubingStrategyMachineState: ...


class _CurrentReader(Protocol):
    def read_completed_bars(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]: ...

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]: ...

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None: ...


@dataclass(slots=True)
class _ProductRuntime:
    symbol: str
    state: SubingStrategyMachineState | None = None
    availability: _RuntimeState = "warming"
    reason_codes: tuple[str, ...] = ()
    ready_cutoff_1m: datetime | None = None
    ready_cutoff_5m: datetime | None = None
    ready_cutoff_15m: datetime | None = None


class SubingStrategyRuntimeEvaluator:
    """Restore and advance one isolated shared machine per active product."""

    def __init__(
        self,
        products: Sequence[str],
        *,
        restore_reader: _RestoreReader,
        current_reader: _CurrentReader,
    ) -> None:
        normalized = tuple(products)
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(
                type(symbol) is not str
                or symbol != symbol.strip().lower()
                or not symbol.isascii()
                or not symbol.isalpha()
                for symbol in normalized
            )
        ):
            raise ValueError("SUBING_STRATEGY_RUNTIME_PRODUCTS_INVALID")
        self._products = {
            symbol: _ProductRuntime(symbol=symbol) for symbol in normalized
        }
        self._restore_reader = restore_reader
        self._current_reader = current_reader
        self._started_at: datetime | None = None

    @property
    def products(self) -> tuple[str, ...]:
        return tuple(self._products)

    def restore_all(
        self,
        *,
        started_at: datetime,
    ) -> tuple[SubingStrategyRuntimeResult, ...]:
        started_at = _utc_instant(started_at)
        self._started_at = started_at
        results: list[SubingStrategyRuntimeResult] = []
        for product in self._products.values():
            product.state = None
            product.availability = "warming"
            product.reason_codes = ()
            product.ready_cutoff_1m = None
            product.ready_cutoff_5m = None
            product.ready_cutoff_15m = None
            try:
                restored = self._restore_reader.restore(
                    symbol=product.symbol,
                    started_at=started_at,
                )
                if (
                    type(restored) is not SubingStrategyMachineState
                    or restored.symbol != product.symbol
                ):
                    raise SubingStrategyMachineError("RESTORE_IDENTITY_INVALID")
                _source_identity(restored)
                product.state = restored
            except (
                SubingStrategyRuntimeProductSourceError,
                SubingStrategyMachineError,
            ) as exc:
                self._degrade(
                    product,
                    _public_reason(exc, "RESTORE_UNAVAILABLE"),
                )
            results.append(self._result(product))
        return tuple(results)

    def final_catch_up(
        self,
        *,
        ready_at: datetime,
    ) -> tuple[SubingStrategyRuntimeResult, ...]:
        ready_at = _utc_instant(ready_at)
        if self._started_at is None or ready_at < self._started_at:
            raise ValueError("SUBING_STRATEGY_RUNTIME_NOT_RESTORED")
        results: list[SubingStrategyRuntimeResult] = []
        for product in self._products.values():
            state = product.state
            if product.availability != "warming" or state is None:
                results.append(self._result(product))
                continue
            identity = _source_identity(state)
            cutoffs = _cutoffs(state)
            try:
                current = self._current_reader.read_completed_bars(
                    symbol=product.symbol,
                    source_identity=identity,
                    after_1m=cutoffs[0],
                    after_5m=cutoffs[1],
                    after_15m=cutoffs[2],
                    through=ready_at,
                )
                events = _completed_events(current, through=ready_at)
                for event in events:
                    state = self._with_authoritative_interval(
                        state,
                        event,
                        source_identity=identity,
                    )
                    state, _ = step_subing_strategy_machine(
                        state,
                        event,
                        source_identity=identity,
                    )
                product.state = state
                (
                    product.ready_cutoff_1m,
                    product.ready_cutoff_5m,
                    product.ready_cutoff_15m,
                ) = _cutoffs(state)
                product.availability = "ready"
            except (
                SubingStrategyRuntimeProductSourceError,
                SubingStrategyMachineError,
            ) as exc:
                self._degrade(
                    product,
                    _public_reason(exc, "CURRENT_UNAVAILABLE"),
                )
            results.append(self._result(product))
        return tuple(results)

    def process_completed_bar(
        self,
        bar: CanonicalBar,
        frequency: BarFrequency,
        *,
        source_identity: SubingStrategySourceIdentity,
    ) -> SubingStrategyRuntimeResult:
        if not isinstance(source_identity, SubingStrategySourceIdentity):
            raise ValueError("SUBING_STRATEGY_RUNTIME_SOURCE_IDENTITY_INVALID")
        product = self._products.get(source_identity.symbol)
        if product is None:
            raise ValueError("SUBING_STRATEGY_RUNTIME_PRODUCT_UNKNOWN")
        state = product.state
        if product.availability == "unavailable" or state is None:
            return self._result(product)
        try:
            if source_identity != _source_identity(state):
                raise SubingStrategyMachineError("SOURCE_IDENTITY_MISMATCH")
            event = _completed_event(bar, frequency)
            state = self._with_authoritative_interval(
                state,
                event,
                source_identity=source_identity,
            )
            state, output = step_subing_strategy_machine(
                state,
                event,
                source_identity=source_identity,
            )
            product.state = state
        except (
            SubingStrategyRuntimeProductSourceError,
            SubingStrategyMachineError,
        ) as exc:
            self._degrade(
                product,
                _public_reason(exc, "COMPLETED_BAR_UNAVAILABLE"),
            )
            return self._result(product)
        return self._result(
            product,
            action_facts=(
                _action_facts(state, output.actions)
                if product.availability == "ready"
                and _after_ready_cutoff(product, event)
                else ()
            ),
        )

    def process_canonical_updated(
        self,
        trading_day: date,
    ) -> tuple[SubingStrategyRuntimeResult, ...]:
        if type(trading_day) is not date:
            raise ValueError("SUBING_STRATEGY_RUNTIME_TRADING_DAY_INVALID")
        results: list[SubingStrategyRuntimeResult] = []
        for product in self._products.values():
            state = product.state
            if product.availability == "unavailable" or state is None:
                results.append(self._result(product))
                continue
            identity = _source_identity(state)
            try:
                terminal = self._current_reader.read_authoritative_terminal(
                    symbol=product.symbol,
                    trading_day=trading_day,
                    source_identity=identity,
                )
                if terminal is None:
                    results.append(self._result(product))
                    continue
                if (
                    type(terminal) is not AuthoritativeSegmentTerminal
                    or terminal.terminal_bar.trading_day != trading_day
                ):
                    raise SubingStrategyMachineError("TERMINAL_IDENTITY_INVALID")
                if state.watermarks.terminal_at is not None:
                    if (
                        terminal.symbol == state.symbol
                        and terminal.contract == state.contract
                        and terminal.segment_start_trading_day
                        == state.segment_start_trading_day
                        and terminal.terminal_bar.bar_end
                        == state.watermarks.terminal_at
                        and terminal.terminal_bar == state.watermarks.latest_15m
                    ):
                        results.append(self._result(product))
                        continue
                    raise SubingStrategyMachineError("CONFLICTING_TERMINAL")
                next_state = self._restore_reader.restore_rollover(
                    symbol=product.symbol,
                    trading_day=trading_day,
                    previous_identity=identity,
                    terminal=terminal,
                )
                _validate_rollover_state(
                    next_state,
                    symbol=product.symbol,
                    previous_identity=identity,
                )
                state, output = step_subing_strategy_machine(
                    state,
                    terminal,
                    source_identity=identity,
                )
                action_facts = _action_facts(state, output.actions)
                product.state = next_state
                if product.availability == "ready":
                    (
                        product.ready_cutoff_1m,
                        product.ready_cutoff_5m,
                        product.ready_cutoff_15m,
                    ) = _cutoffs(next_state)
                results.append(
                    self._result(
                        product,
                        action_facts=(
                            action_facts if product.availability == "ready" else ()
                        ),
                    )
                )
            except (
                SubingStrategyRuntimeProductSourceError,
                SubingStrategyMachineError,
            ) as exc:
                self._degrade(
                    product,
                    _public_reason(exc, "TERMINAL_UNAVAILABLE"),
                )
                results.append(self._result(product))
        return tuple(results)

    def current_state(self, symbol: str) -> SubingStrategyMachineState | None:
        product = self._products.get(symbol)
        if product is None:
            raise ValueError("SUBING_STRATEGY_RUNTIME_PRODUCT_UNKNOWN")
        return product.state

    def _with_authoritative_interval(
        self,
        state: SubingStrategyMachineState,
        event: _RuntimeCompletedBar,
        *,
        source_identity: SubingStrategySourceIdentity,
    ) -> SubingStrategyMachineState:
        observed = (
            state.watermarks.latest_1m
            if isinstance(event, Completed1mBar)
            else state.pending_boundary_5m.bar
            if isinstance(event, Completed5mBar)
            and state.pending_boundary_5m is not None
            else state.watermarks.latest_5m
            if isinstance(event, Completed5mBar)
            else state.pending_boundary_15m.bar
            if state.pending_boundary_15m is not None
            else state.watermarks.latest_15m
        )
        if observed is not None and observed.bar_end == event.bar.bar_end:
            return state
        sessions = self._current_reader.read_session_windows(
            symbol=state.symbol,
            trading_day=event.bar.trading_day,
            source_identity=source_identity,
        )
        session = _session_for_bar(sessions, event.bar.bar_end)
        try:
            bucket = bucket_window_for_bar(
                session,
                BarFrequency.M15,
                event.bar.bar_end,
            )
        except AggregationError:
            raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID") from None
        first_1m = bucket.start + timedelta(minutes=1)
        matches = tuple(
            interval
            for interval in state.intervals
            if interval.effective_bar_end == bucket.end
        )
        if len(matches) > 1:
            raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
        if matches:
            interval = matches[0]
            if interval.first_1m_bar_end != first_1m:
                raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
            authoritative_open = (
                event.bar.bar_end == first_1m
                or isinstance(event, Completed15mBar)
                and event.bar.bar_end == bucket.end
                or isinstance(event, Completed5mBar)
                and event.bar.bar_end == bucket.start + timedelta(minutes=5)
            )
            if authoritative_open and interval.expected_open != event.bar.open:
                raise SubingStrategyMachineError("SOURCE_IDENTITY_INCONSISTENT")
            return state
        if isinstance(event, Completed1mBar) and event.bar.bar_end > first_1m:
            pending = state.pending_action
            if pending is not None and pending.decision_at < bucket.end:
                return replace(state, pending_action=None)
            return state
        interval = SubingStrategyInterval(
            effective_bar_end=bucket.end,
            first_1m_bar_end=first_1m,
            expected_open=event.bar.open,
        )
        intervals = tuple(
            sorted(
                (*state.intervals, interval), key=lambda item: item.effective_bar_end
            )
        )
        if any(
            left.effective_bar_end >= right.effective_bar_end
            or left.first_1m_bar_end >= right.first_1m_bar_end
            or left.effective_bar_end >= right.first_1m_bar_end
            for left, right in zip(intervals, intervals[1:])
        ):
            raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
        return replace(state, intervals=intervals)

    @staticmethod
    def _degrade(product: _ProductRuntime, reason: str) -> None:
        product.availability = "unavailable"
        product.reason_codes = (reason,)

    @staticmethod
    def _result(
        product: _ProductRuntime,
        *,
        action_facts: tuple[SubingStrategyRuntimeActionFact, ...] = (),
    ) -> SubingStrategyRuntimeResult:
        cutoffs = _cutoffs(product.state) if product.state is not None else (None,) * 3
        return SubingStrategyRuntimeResult(
            action_facts=action_facts,
            product_status=SubingStrategyRuntimeProductStatus(
                symbol=product.symbol,
                state=product.availability,
                cutoff_1m=cutoffs[0],
                cutoff_5m=cutoffs[1],
                cutoff_15m=cutoffs[2],
                reason_codes=product.reason_codes,
            ),
        )


def _action_facts(
    state: SubingStrategyMachineState,
    actions: tuple[SubingStrategyAction, ...],
) -> tuple[SubingStrategyRuntimeActionFact, ...]:
    facts: list[SubingStrategyRuntimeActionFact] = []
    for action in actions:
        if action.kind in {
            SubingStrategyActionKind.OPEN_LONG,
            SubingStrategyActionKind.OPEN_SHORT,
        }:
            episode = None
        else:
            matches = tuple(
                episode
                for episode in state.closed_episodes
                if episode.episode_id == action.episode_id
                and episode.exit_action == action
            )
            if len(matches) != 1:
                raise SubingStrategyMachineError("ACTION_EPISODE_INVALID")
            episode = matches[0]
        facts.append(SubingStrategyRuntimeActionFact(action, episode))
    return tuple(facts)


def _source_identity(state: SubingStrategyMachineState) -> SubingStrategySourceIdentity:
    return SubingStrategySourceIdentity(
        symbol=state.symbol,
        contract=state.contract,
        segment_start_trading_day=state.segment_start_trading_day,
    )


def _validate_rollover_state(
    state: SubingStrategyMachineState,
    *,
    symbol: str,
    previous_identity: SubingStrategySourceIdentity,
) -> None:
    if type(state) is not SubingStrategyMachineState or state.symbol != symbol:
        raise SubingStrategyMachineError("ROLLOVER_IDENTITY_INVALID")
    identity = _source_identity(state)
    if (
        identity == previous_identity
        or identity.segment_start_trading_day
        <= previous_identity.segment_start_trading_day
        or state.position is not None
        or state.pending_action is not None
        or state.actions
        or state.current_episode is not None
        or state.closed_episodes
        or state.watermarks.terminal_at is not None
    ):
        raise SubingStrategyMachineError("ROLLOVER_IDENTITY_INVALID")


def _cutoffs(
    state: SubingStrategyMachineState,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    return (
        state.watermarks.latest_1m.bar_end
        if state.watermarks.latest_1m is not None
        else None,
        state.watermarks.latest_5m.bar_end
        if state.watermarks.latest_5m is not None
        else None,
        state.watermarks.latest_15m.bar_end
        if state.watermarks.latest_15m is not None
        else None,
    )


def _completed_event(
    bar: CanonicalBar,
    frequency: BarFrequency,
) -> _RuntimeCompletedBar:
    if type(bar) is not CanonicalBar:
        raise ValueError("SUBING_STRATEGY_RUNTIME_BAR_INVALID")
    try:
        normalized = BarFrequency(frequency)
    except (TypeError, ValueError):
        raise ValueError("SUBING_STRATEGY_RUNTIME_FREQUENCY_INVALID") from None
    if normalized is BarFrequency.M1:
        return Completed1mBar(bar)
    if normalized is BarFrequency.M5:
        return Completed5mBar(bar)
    if normalized is BarFrequency.M15:
        return Completed15mBar(bar)
    raise ValueError("SUBING_STRATEGY_RUNTIME_FREQUENCY_INVALID")


def _completed_events(
    current: Mapping[BarFrequency, tuple[CanonicalBar, ...]],
    *,
    through: datetime,
) -> tuple[_RuntimeCompletedBar, ...]:
    if not isinstance(current, Mapping):
        raise ValueError("SUBING_STRATEGY_RUNTIME_CURRENT_INVALID")
    events: list[_RuntimeCompletedBar] = []
    for raw_frequency, bars in current.items():
        try:
            frequency = BarFrequency(raw_frequency)
        except (TypeError, ValueError):
            raise ValueError("SUBING_STRATEGY_RUNTIME_CURRENT_INVALID") from None
        if frequency not in _RUNTIME_FREQUENCIES or type(bars) is not tuple:
            raise ValueError("SUBING_STRATEGY_RUNTIME_CURRENT_INVALID")
        for bar in bars:
            if type(bar) is not CanonicalBar or bar.bar_end > through:
                raise ValueError("SUBING_STRATEGY_RUNTIME_CURRENT_INVALID")
            events.append(_completed_event(bar, frequency))
    events.sort(
        key=lambda event: (
            event.bar.bar_end,
            0
            if isinstance(event, Completed1mBar)
            else 1
            if isinstance(event, Completed5mBar)
            else 2,
        )
    )
    return tuple(events)


def _after_ready_cutoff(
    product: _ProductRuntime,
    event: _RuntimeCompletedBar,
) -> bool:
    cutoff = (
        product.ready_cutoff_1m
        if isinstance(event, Completed1mBar)
        else product.ready_cutoff_5m
        if isinstance(event, Completed5mBar)
        else product.ready_cutoff_15m
    )
    return cutoff is None or event.bar.bar_end > cutoff


def _session_for_bar(
    sessions: tuple[SessionWindow, ...],
    bar_end: datetime,
) -> SessionWindow:
    if (
        type(sessions) is not tuple
        or not sessions
        or any(type(session) is not SessionWindow for session in sessions)
        or any(left.end > right.start for left, right in zip(sessions, sessions[1:]))
    ):
        raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
    matches = tuple(
        session for session in sessions if session.start < bar_end <= session.end
    )
    if len(matches) != 1:
        raise SubingStrategyMachineError("INTERVAL_IDENTITY_INVALID")
    return matches[0]


def _public_reason(
    exc: SubingStrategyRuntimeProductSourceError | SubingStrategyMachineError,
    fallback: str,
) -> str:
    if isinstance(exc, SubingStrategyRuntimeProductSourceError):
        return fallback
    if exc.reason not in _PUBLIC_PRODUCT_MACHINE_REASONS:
        raise exc
    return exc.reason


def _utc_instant(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("SUBING_STRATEGY_RUNTIME_TIME_INVALID")
    return value.astimezone(UTC)


__all__ = [
    "SubingStrategyRuntimeActionFact",
    "SubingStrategyRuntimeEvaluator",
    "SubingStrategyRuntimeProductStatus",
    "SubingStrategyRuntimeProductSourceError",
    "SubingStrategyRuntimeResult",
]
