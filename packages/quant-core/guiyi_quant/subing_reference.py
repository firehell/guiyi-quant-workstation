"""Pure historical observation references; signal-close prices are not fills."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import (
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    localcontext,
)
from hashlib import sha256
import json
import math
from typing import Literal, TypeAlias

from .reference_trading.contracts import (
    ActionKind as UnifiedActionKind,
    BoundaryReason,
    CompletedReferenceBar,
    ReferenceAction as UnifiedReferenceAction,
    ReferenceBoundary,
    ReferenceState as UnifiedReferenceState,
    StreamIdentity,
    TradeStatus as UnifiedTradeStatus,
)
from .reference_trading.reducer import reduce_reference

from .indicators.subing_ths import (
    SUBING_THS_FORMULA_VERSION,
    SubingThs15mKernel,
    SubingThs15mState,
)

FORMULA_VERSION = SUBING_THS_FORMULA_VERSION
REFERENCE_MODEL_VERSION = "subing_reference_reverse_close_v1"
REFERENCE_MODEL_VERSION_V2 = "subing_reference_reverse_close_quality_segment_v2"
FORMULA_VERSIONS = {
    "15m": FORMULA_VERSION,
    "30m": "subing_ths_30m_v1",
    "60m": "subing_ths_60m_v1",
    "1d": "subing_ths_1d_v1",
}
ReferenceReadiness: TypeAlias = Literal[
    "ready", "warming", "WARMING",
    "INDICATOR_READY_CROSS_UNEVALUABLE", "CROSS_EVALUATED",
]


class ReferenceProjectionError(ValueError):
    """Invalid or conflicting projection input; callers must fail closed."""


@dataclass(frozen=True, slots=True)
class ReferenceBar:
    bar_end: datetime
    trading_day: date
    close: Decimal


@dataclass(frozen=True, slots=True)
class ReferenceSegment:
    physical_contract: str
    segment_id: str
    bars: tuple[ReferenceBar, ...]
    owner_since: date
    owner_through: date
    interrupted_at: datetime | None = None
    calculation_segment_id: str | None = None
    quality_interrupted_at: datetime | None = None
    quality_interruption_trading_day: date | None = None
    quality_classification: Literal["PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"] | None = None


@dataclass(frozen=True, slots=True)
class ReferenceSignal:
    signal_id: str
    bar_end: datetime
    trading_day: date
    physical_contract: str
    segment_id: str
    calculation_segment_id: str
    direction: Literal["buy", "sell"]
    reference_price: Decimal
    action: Literal[
        "OPEN_LONG",
        "OPEN_SHORT",
        "REVERSE_TO_LONG",
        "REVERSE_TO_SHORT",
        "SAME_DIRECTION",
    ]
    entry_trade_id: str | None
    closed_trade_id: str | None
    closed_return_pct: Decimal | None
    dif: Decimal | None = None
    dea: Decimal | None = None
    macd: Decimal | None = None
    ema21: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ReferenceTrade:
    reference_trade_id: str
    side: Literal["LONG", "SHORT"]
    physical_contract: str
    segment_id: str
    calculation_segment_id: str
    entry_signal_id: str
    entry_bar_end: datetime
    entry_trading_day: date
    entry_reference_price: Decimal
    exit_signal_id: str | None = None
    exit_bar_end: datetime | None = None
    exit_trading_day: date | None = None
    exit_reference_price: Decimal | None = None
    status: Literal["OPEN", "CLOSED", "ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"] = "OPEN"
    holding_bars: int = 0
    reference_return_pct: Decimal | None = None
    mark_bar_end: datetime | None = None
    mark_reference_price: Decimal | None = None
    mark_change_pct: Decimal | None = None
    interrupted_at: datetime | None = None
    interruption_reason: Literal["PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"] | None = None
    interruption_trading_day: date | None = None
    initial: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceSummary:
    closed_count: int
    win_count: int
    loss_count: int
    flat_count: int
    open_count: int
    interrupted_count: int
    rollover_interrupted_count: int
    data_interrupted_count: int
    initial_count: int
    win_rate_pct: Decimal | None
    mean_return_pct: Decimal | None
    sum_return_percentage_points: Decimal


@dataclass(frozen=True, slots=True)
class ReferenceProjection:
    signals: tuple[ReferenceSignal, ...]
    trades: tuple[ReferenceTrade, ...]
    summary: ReferenceSummary
    readiness: ReferenceReadiness = "ready"
    indicators: tuple[ReferenceIndicator, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceIndicator:
    bar_end: datetime
    physical_contract: str
    segment_id: str
    calculation_segment_id: str
    dif: Decimal | None
    dea: Decimal | None
    macd: Decimal | None
    ema21: Decimal | None


@dataclass(slots=True)
class SubingReplayState:
    """Bounded state for one physical calculation segment.

    It owns no event history.  The caller consumes the optional signal/closed
    trade emitted by each step, which makes a full projection and incremental
    replay use precisely the same formula and lifecycle transition.
    """

    kernel_state: SubingThs15mState
    current: ReferenceTrade | None = None
    entry_index: int = 0
    processed_count: int = 0
    ready_in_window: bool = False
    reference_state: UnifiedReferenceState | None = None


def seed_subing_replay_state() -> SubingReplayState:
    return SubingReplayState(SubingThs15mKernel().initial_state())


def _conflict() -> None:
    raise ReferenceProjectionError("SUBING_REFERENCE_DATA_CONFLICT")


def _aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _identity(*parts: str) -> str:
    return sha256(
        json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _return(trade: ReferenceTrade, price: Decimal) -> Decimal:
    change = price - trade.entry_reference_price
    if trade.side == "SHORT":
        change = -change
    return change / trade.entry_reference_price * 100


def _stream_identity(
    symbol: str, frequency: str, quality_segmented: bool,
) -> StreamIdentity:
    return StreamIdentity(
        strategy_code="subing_reference",
        formula_versions=(FORMULA_VERSIONS[frequency],),
        profile_id=f"subing_reference_{frequency}_v1",
        reference_model_version=(
            REFERENCE_MODEL_VERSION_V2 if quality_segmented else REFERENCE_MODEL_VERSION
        ),
        futures_adaptation_version="subing_actual_dominant_v1",
        product=symbol.upper(),
        frequency=frequency,
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


def _trade_base(
    symbol: str, segment: ReferenceSegment, frequency: str, quality_segmented: bool,
) -> tuple[str, ...]:
    calculation_segment_id = segment.calculation_segment_id or segment.segment_id
    base: tuple[str, ...] = (
        symbol, segment.physical_contract, segment.segment_id,
        FORMULA_VERSIONS[frequency],
        REFERENCE_MODEL_VERSION_V2 if quality_segmented else REFERENCE_MODEL_VERSION,
    )
    if quality_segmented:
        base += (calculation_segment_id,)
    if frequency != "15m":
        base += (frequency,)
    return base


def _legacy_trade(
    trade: object, base: tuple[str, ...], since: date,
) -> ReferenceTrade:
    from .reference_trading.contracts import ReferenceTrade as UnifiedTrade

    if not isinstance(trade, UnifiedTrade):
        raise TypeError("trade must be unified ReferenceTrade")
    entry_signal_id = trade.entry_action_id.removesuffix(":open")
    status = trade.status.value
    return ReferenceTrade(
        reference_trade_id=_identity("trade", *base, entry_signal_id),
        side=trade.side.value,
        physical_contract=trade.physical_contract,
        segment_id=trade.owner_segment_id,
        calculation_segment_id=trade.calculation_segment_id,
        entry_signal_id=entry_signal_id,
        entry_bar_end=trade.entry_bar_end,
        entry_trading_day=trade.entry_trading_day,
        entry_reference_price=trade.entry_reference_price,
        exit_signal_id=(
            None if trade.exit_action_id is None
            else trade.exit_action_id.removesuffix(":close")
        ),
        exit_bar_end=trade.exit_bar_end,
        exit_trading_day=trade.exit_trading_day,
        exit_reference_price=trade.exit_reference_price,
        status=status,
        holding_bars=trade.holding_bars,
        reference_return_pct=trade.reference_return,
        mark_bar_end=trade.mark_bar_end,
        mark_reference_price=trade.mark_reference_price,
        mark_change_pct=trade.mark_return,
        initial=trade.entry_trading_day < since,
    )


def _replay_subing_step(
    symbol: str,
    segment: ReferenceSegment,
    frequency: str,
    quality_segmented: bool,
    state: SubingReplayState,
    bar: ReferenceBar,
    *,
    since: date,
    through: date,
) -> tuple[SubingReplayState, ReferenceSignal | None, ReferenceTrade | None, ReferenceIndicator | None]:
    """Advance one completed bar for one already-validated calculation segment."""

    if not isinstance(state, SubingReplayState):
        raise TypeError("state must be SubingReplayState")
    calculation_segment_id = segment.calculation_segment_id or segment.segment_id
    kernel = SubingThs15mKernel()
    state.kernel_state, result = kernel.step(
        state.kernel_state, float(bar.close), bar_end=bar.bar_end.isoformat()
    )
    state.processed_count += 1
    if not result.valid:
        _conflict()
    in_owner = segment.owner_since <= bar.trading_day <= segment.owner_through
    in_window = in_owner and since <= bar.trading_day <= through
    if result.ready and in_window:
        state.ready_in_window = True
    indicator = None
    if in_window:
        indicator = ReferenceIndicator(
            bar.bar_end, segment.physical_contract, segment.segment_id,
            calculation_segment_id,
            Decimal(str(result.dif)) if result.dif is not None else None,
            Decimal(str(result.dea)) if result.dea is not None else None,
            Decimal(str(result.macd)) if result.macd is not None else None,
            Decimal(str(result.ema21)) if result.ema21 is not None else None,
        )
    if not in_owner:
        return state, None, None, indicator
    base = _trade_base(symbol, segment, frequency, quality_segmented)
    stream = _stream_identity(symbol, frequency, quality_segmented)
    if state.reference_state is None:
        state.reference_state = UnifiedReferenceState.flat(stream)
    elif state.reference_state.stream != stream:
        _conflict()
    prior = state.current
    actions: list[UnifiedReferenceAction] = []
    emitted_signal = None
    signal_id: str | None = None
    direction: Literal["buy", "sell"] | None = None
    action_name: Literal[
        "OPEN_LONG", "OPEN_SHORT", "REVERSE_TO_LONG", "REVERSE_TO_SHORT", "SAME_DIRECTION",
    ] | None = None
    for found_direction in result.result_codes:
        # The formula can emit at most one signal per completed bar.  Retain the
        # guard so a future kernel change fails closed instead of inventing an
        # ambiguous action ordering.
        if direction is not None:
            _conflict()
        direction = found_direction
        signal_id = _identity(
            "signal", *base, bar.bar_end.astimezone(timezone.utc).isoformat(), direction,
        )
        side: Literal["LONG", "SHORT"] = "LONG" if direction == "buy" else "SHORT"
        action_name = "SAME_DIRECTION"
        if prior is None or prior.side != side:
            action_name = (
                "OPEN_LONG" if side == "LONG" else "OPEN_SHORT"
            ) if prior is None else (
                "REVERSE_TO_LONG" if side == "LONG" else "REVERSE_TO_SHORT"
            )
            if prior is not None:
                assert state.reference_state.open_trade is not None
                actions.append(UnifiedReferenceAction(
                    stream=stream, source_action_id=f"{signal_id}:close",
                    physical_contract=segment.physical_contract,
                    owner_segment_id=segment.segment_id,
                    calculation_segment_id=calculation_segment_id,
                    bar_end=bar.bar_end, trading_day=bar.trading_day, sequence=0,
                    kind=UnifiedActionKind.CLOSE, reference_price=bar.close,
                    entry_action_id=state.reference_state.open_trade.entry_action_id,
                    reference_price_type="subing_signal_close",
                ))
            actions.append(UnifiedReferenceAction(
                stream=stream, source_action_id=f"{signal_id}:open",
                physical_contract=segment.physical_contract,
                owner_segment_id=segment.segment_id,
                calculation_segment_id=calculation_segment_id,
                bar_end=bar.bar_end, trading_day=bar.trading_day,
                sequence=1 if prior is not None else 0,
                kind=(
                    UnifiedActionKind.OPEN_LONG if side == "LONG"
                    else UnifiedActionKind.OPEN_SHORT
                ),
                reference_price=bar.close,
                reference_price_type="subing_signal_close",
            ))

    transition = reduce_reference(
        state.reference_state,
        actions=tuple(actions),
        completed_bar=CompletedReferenceBar(
            physical_contract=segment.physical_contract,
            owner_segment_id=segment.segment_id,
            calculation_segment_id=calculation_segment_id,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            reference_price=bar.close,
        ),
        return_policy="delta_over_entry",
    )
    state.reference_state = transition.state
    emitted_closed = None
    for changed in transition.changed_trades:
        if changed.status is UnifiedTradeStatus.CLOSED:
            emitted_closed = _legacy_trade(changed, base, since)
    state.current = (
        None
        if transition.state.open_trade is None
        else _legacy_trade(transition.state.open_trade, base, since)
    )
    if signal_id is not None and direction is not None and action_name is not None:
        closed_id = None if emitted_closed is None else emitted_closed.reference_trade_id
        closed_return = None if emitted_closed is None else emitted_closed.reference_return_pct
        if in_window:
            emitted_signal = ReferenceSignal(
                signal_id, bar.bar_end, bar.trading_day, segment.physical_contract,
                segment.segment_id, calculation_segment_id, direction, bar.close, action_name,
                None if state.current is None else state.current.reference_trade_id,
                closed_id, closed_return,
                Decimal(str(result.dif)) if result.dif is not None else None,
                Decimal(str(result.dea)) if result.dea is not None else None,
                Decimal(str(result.macd)) if result.macd is not None else None,
                Decimal(str(result.ema21)) if result.ema21 is not None else None,
            )
    return state, emitted_signal, emitted_closed, indicator


def replay_subing_step(
    symbol: str,
    segment: ReferenceSegment,
    frequency: str,
    quality_segmented: bool,
    state: SubingReplayState,
    bar: ReferenceBar,
    *,
    since: date,
    through: date,
) -> tuple[SubingReplayState, ReferenceSignal | None, ReferenceTrade | None, ReferenceIndicator | None]:
    """Advance one bar with the projection's fixed Decimal arithmetic policy."""

    with localcontext(
        Context(
            prec=28,
            rounding=ROUND_HALF_EVEN,
            Emin=-999999,
            Emax=999999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation, DivisionByZero, Overflow],
        )
    ):
        return _replay_subing_step(
            symbol, segment, frequency, quality_segmented, state, bar,
            since=since, through=through,
        )


def _validate(
    symbol: str,
    segments: tuple[ReferenceSegment, ...],
    since: date,
    through: date,
    as_of: datetime,
) -> None:
    if not isinstance(symbol, str) or not symbol.strip() or not _aware(as_of):
        _conflict()
    if (
        type(since) is not date
        or type(through) is not date
        or since > through
        or not segments
    ):
        _conflict()
    previous: ReferenceSegment | None = None
    identities = set()
    for segment in segments:
        calculation_id = segment.calculation_segment_id or segment.segment_id
        if (
            not segment.physical_contract
            or not segment.segment_id
            or not calculation_id
            or not segment.bars
            or type(segment.owner_since) is not date
            or type(segment.owner_through) is not date
            or segment.owner_since > segment.owner_through
            or calculation_id in identities
        ):
            _conflict()
        identities.add(calculation_id)
        if segment.interrupted_at is not None and not _aware(segment.interrupted_at):
            _conflict()
        if segment.quality_interrupted_at is not None and (
            not _aware(segment.quality_interrupted_at)
            or segment.quality_classification not in ("PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE")
        ):
            _conflict()
        if (
            (segment.quality_interrupted_at is None)
            != (segment.quality_classification is None)
            or (segment.quality_interrupted_at is None)
            != (segment.quality_interruption_trading_day is None)
        ):
            _conflict()
        last = None
        own_seen = False
        for bar in segment.bars:
            if (
                not _aware(bar.bar_end)
                or type(bar.trading_day) is not date
                or not isinstance(bar.close, Decimal)
                or not bar.close.is_finite()
                or bar.close <= 0
                or not math.isfinite(float(bar.close))
            ):
                _conflict()
            if last is not None and (
                bar.bar_end <= last.bar_end or bar.trading_day < last.trading_day
            ):
                _conflict()
            if bar.trading_day > segment.owner_through:
                _conflict()
            if bar.trading_day >= segment.owner_since:
                own_seen = True
                if (
                    segment.interrupted_at is not None
                    and bar.bar_end >= segment.interrupted_at
                ):
                    _conflict()
                if (
                    segment.quality_interrupted_at is not None
                    and bar.bar_end >= segment.quality_interrupted_at
                ):
                    _conflict()
            last = bar
        if not own_seen:
            _conflict()
        if previous is not None:
            first_own = next(
                b for b in segment.bars if b.trading_day >= segment.owner_since
            )
            same_owner = (
                previous.physical_contract == segment.physical_contract
                and previous.segment_id == segment.segment_id
                and previous.owner_since == segment.owner_since
            )
            if same_owner:
                if (
                    previous.quality_interrupted_at is None
                    or previous.quality_interrupted_at > first_own.bar_end
                    or previous.bars[-1].bar_end >= segment.bars[0].bar_end
                ):
                    _conflict()
            elif (
                previous.owner_through >= segment.owner_since
                or previous.interrupted_at is None
                or previous.interrupted_at > first_own.bar_end
            ):
                _conflict()
        previous = segment


def project_reference(
    symbol: str,
    segments: tuple[ReferenceSegment, ...],
    *,
    since: date,
    through: date,
    as_of: datetime,
    frequency: str = "15m",
    quality_segmented: bool = False,
) -> ReferenceProjection:
    """Replay physical prefixes, then project each rank1 ownership independently.

    The reader establishes coverage and completed-bar facts. Prefix bars warm the
    sole formula kernel but cannot open references before that segment owns rank1.
    Dates are exchange trading days, not calendar dates of night-session bars.
    """
    # Freeze the model arithmetic independently of caller context, including
    # rounding and traps, while preserving the caller's context on return.
    with localcontext(
        Context(
            prec=28,
            rounding=ROUND_HALF_EVEN,
            Emin=-999999,
            Emax=999999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation, DivisionByZero, Overflow],
        )
    ):
        return _project_reference(
            symbol, segments, since=since, through=through, as_of=as_of,
            frequency=frequency, quality_segmented=quality_segmented,
        )


def _project_reference(
    symbol: str,
    segments: tuple[ReferenceSegment, ...],
    *,
    since: date,
    through: date,
    as_of: datetime,
    frequency: str,
    quality_segmented: bool,
) -> ReferenceProjection:
    """Replay physical prefixes, then project each rank1 ownership independently.

    The reader establishes coverage and completed-bar facts. Prefix bars warm the
    sole formula kernel but cannot open references before that segment owns rank1.
    Dates are exchange trading days, not calendar dates of night-session bars.
    """
    _validate(symbol, segments, since, through, as_of)
    if frequency not in FORMULA_VERSIONS:
        _conflict()
    if quality_segmented and frequency != "1d":
        _conflict()
    signals: list[ReferenceSignal] = []
    trades: list[ReferenceTrade] = []
    indicators: list[ReferenceIndicator] = []
    warming = False
    latest_processed_count = 0
    for segment in segments:
        state = seed_subing_replay_state()
        for bar in segment.bars:
            if bar.bar_end > as_of or bar.trading_day > through:
                break
            state, signal, closed, indicator = replay_subing_step(
                symbol, segment, frequency, quality_segmented, state, bar,
                since=since, through=through,
            )
            if indicator is not None:
                indicators.append(indicator)
            if closed is not None:
                trades.append(closed)
            if signal is not None:
                signals.append(signal)
        current = state.current
        if current is not None:
            quality_interruption = segment.quality_interrupted_at
            interruption = segment.interrupted_at
            # Future ownership metadata must not change a historical prefix.
            if (
                quality_segmented
                and quality_interruption is not None
                and quality_interruption <= as_of
            ):
                assert state.reference_state is not None
                transition = reduce_reference(
                    state.reference_state,
                    boundaries=(ReferenceBoundary(
                        stream=state.reference_state.stream,
                        reason=BoundaryReason.DATA_INTERRUPTED,
                        physical_contract=segment.physical_contract,
                        owner_segment_id=segment.segment_id,
                        calculation_segment_id=(segment.calculation_segment_id or segment.segment_id),
                        bar_end=quality_interruption,
                        trading_day=segment.quality_interruption_trading_day,
                    ),),
                    return_policy="delta_over_entry",
                )
                state.reference_state = transition.state
                current = replace(
                    _legacy_trade(
                        transition.changed_trades[-1],
                        _trade_base(symbol, segment, frequency, quality_segmented), since,
                    ),
                    interrupted_at=quality_interruption,
                    interruption_reason=segment.quality_classification,
                    interruption_trading_day=segment.quality_interruption_trading_day,
                )
            elif (
                interruption is not None
                and interruption <= as_of
                and segment.owner_through < through
            ):
                assert state.reference_state is not None
                transition = reduce_reference(
                    state.reference_state,
                    boundaries=(ReferenceBoundary(
                        stream=state.reference_state.stream,
                        reason=BoundaryReason.ROLLOVER,
                        physical_contract=segment.physical_contract,
                        owner_segment_id=segment.segment_id,
                        calculation_segment_id=(segment.calculation_segment_id or segment.segment_id),
                        bar_end=interruption,
                        trading_day=segment.owner_through,
                    ),),
                    return_policy="delta_over_entry",
                )
                state.reference_state = transition.state
                current = replace(
                    _legacy_trade(
                        transition.changed_trades[-1],
                        _trade_base(symbol, segment, frequency, quality_segmented), since,
                    ),
                    interrupted_at=interruption,
                )
            trades.append(current)
        if not state.ready_in_window:
            warming = True
        latest_processed_count = state.processed_count
    owner_ends = {
        (segment.calculation_segment_id or segment.segment_id): segment.owner_through
        for segment in segments
    }
    selected = tuple(
        t
        for t in trades
        if t.entry_trading_day <= through
        and (t.exit_trading_day is None or t.exit_trading_day >= since)
        and (
            t.status not in ("ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED")
            or (
                t.status == "DATA_INTERRUPTED"
                and t.interruption_trading_day is not None
                and t.interruption_trading_day >= since
            )
            or (
                t.status == "ROLLOVER_INTERRUPTED"
                and owner_ends[t.calculation_segment_id] >= since
            )
        )
    )
    regular = tuple(t for t in selected if not t.initial)
    returns = tuple(
        t.reference_return_pct
        for t in regular
        if t.status == "CLOSED" and t.reference_return_pct is not None
    )
    total = sum(returns, Decimal(0))
    wins = sum(r > 0 for r in returns)
    summary = ReferenceSummary(
        len(returns),
        wins,
        sum(r < 0 for r in returns),
        sum(r == 0 for r in returns),
        sum(t.status == "OPEN" for t in regular),
        sum(t.status in ("ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED") for t in regular),
        sum(t.status == "ROLLOVER_INTERRUPTED" for t in regular),
        sum(t.status == "DATA_INTERRUPTED" for t in regular),
        sum(t.initial for t in selected),
        Decimal(wins) / len(returns) * 100 if returns else None,
        total / len(returns) if returns else None,
        total,
    )
    readiness: ReferenceReadiness = "warming" if warming else "ready"
    if quality_segmented:
        readiness = (
            "WARMING" if (
                latest_processed_count < 34
                or (
                    segments[-1].quality_interrupted_at is not None
                    and segments[-1].quality_interrupted_at <= as_of
                )
            )
            else "INDICATOR_READY_CROSS_UNEVALUABLE" if latest_processed_count == 34
            else "CROSS_EVALUATED"
        )
    return ReferenceProjection(tuple(signals), selected, summary, readiness, tuple(indicators))
