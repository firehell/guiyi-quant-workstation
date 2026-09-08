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
from typing import Literal

from .indicators.subing_ths import SUBING_THS_FORMULA_VERSION, SubingThs15mKernel

FORMULA_VERSION = SUBING_THS_FORMULA_VERSION
REFERENCE_MODEL_VERSION = "subing_reference_reverse_close_v1"


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


@dataclass(frozen=True, slots=True)
class ReferenceSignal:
    signal_id: str
    bar_end: datetime
    trading_day: date
    physical_contract: str
    segment_id: str
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


@dataclass(frozen=True, slots=True)
class ReferenceTrade:
    reference_trade_id: str
    side: Literal["LONG", "SHORT"]
    physical_contract: str
    segment_id: str
    entry_signal_id: str
    entry_bar_end: datetime
    entry_trading_day: date
    entry_reference_price: Decimal
    exit_signal_id: str | None = None
    exit_bar_end: datetime | None = None
    exit_trading_day: date | None = None
    exit_reference_price: Decimal | None = None
    status: Literal["OPEN", "CLOSED", "ROLLOVER_INTERRUPTED"] = "OPEN"
    holding_bars: int = 0
    reference_return_pct: Decimal | None = None
    mark_bar_end: datetime | None = None
    mark_reference_price: Decimal | None = None
    mark_change_pct: Decimal | None = None
    interrupted_at: datetime | None = None
    initial: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceSummary:
    closed_count: int
    win_count: int
    loss_count: int
    flat_count: int
    open_count: int
    interrupted_count: int
    initial_count: int
    win_rate_pct: Decimal | None
    mean_return_pct: Decimal | None
    sum_return_percentage_points: Decimal


@dataclass(frozen=True, slots=True)
class ReferenceProjection:
    signals: tuple[ReferenceSignal, ...]
    trades: tuple[ReferenceTrade, ...]
    summary: ReferenceSummary


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
        if (
            not segment.physical_contract
            or not segment.segment_id
            or not segment.bars
            or type(segment.owner_since) is not date
            or type(segment.owner_through) is not date
            or segment.owner_since > segment.owner_through
            or segment.segment_id in identities
        ):
            _conflict()
        identities.add(segment.segment_id)
        if previous is not None and previous.owner_through >= segment.owner_since:
            _conflict()
        if segment.interrupted_at is not None and not _aware(segment.interrupted_at):
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
            last = bar
        if not own_seen:
            _conflict()
        if previous is not None:
            first_own = next(
                b for b in segment.bars if b.trading_day >= segment.owner_since
            )
            if (
                previous.interrupted_at is None
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
            symbol, segments, since=since, through=through, as_of=as_of
        )


def _project_reference(
    symbol: str,
    segments: tuple[ReferenceSegment, ...],
    *,
    since: date,
    through: date,
    as_of: datetime,
) -> ReferenceProjection:
    """Replay physical prefixes, then project each rank1 ownership independently.

    The reader establishes coverage and completed-bar facts. Prefix bars warm the
    sole formula kernel but cannot open references before that segment owns rank1.
    Dates are exchange trading days, not calendar dates of night-session bars.
    """
    _validate(symbol, segments, since, through, as_of)
    signals: list[ReferenceSignal] = []
    trades: list[ReferenceTrade] = []
    for segment in segments:
        kernel = SubingThs15mKernel()
        state = kernel.initial_state()
        current: ReferenceTrade | None = None
        entry_index = 0
        base = (
            symbol,
            segment.physical_contract,
            segment.segment_id,
            FORMULA_VERSION,
            REFERENCE_MODEL_VERSION,
        )
        for index, bar in enumerate(segment.bars):
            if bar.bar_end > as_of or bar.trading_day > through:
                break
            state, result = kernel.step(
                state, float(bar.close), bar_end=bar.bar_end.isoformat()
            )
            if not result.valid:
                _conflict()
            if bar.trading_day < segment.owner_since:
                continue
            if current is not None:
                current = replace(
                    current,
                    holding_bars=index - entry_index,
                    mark_bar_end=bar.bar_end,
                    mark_reference_price=bar.close,
                    mark_change_pct=_return(current, bar.close),
                )
            for direction in result.result_codes:
                signal_id = _identity(
                    "signal",
                    *base,
                    bar.bar_end.astimezone(timezone.utc).isoformat(),
                    direction,
                )
                side: Literal["LONG", "SHORT"] = (
                    "LONG" if direction == "buy" else "SHORT"
                )
                closed_id = None
                closed_return = None
                action: Literal[
                    "OPEN_LONG",
                    "OPEN_SHORT",
                    "REVERSE_TO_LONG",
                    "REVERSE_TO_SHORT",
                    "SAME_DIRECTION",
                ] = "SAME_DIRECTION"
                if current is None or current.side != side:
                    if current is None:
                        action = "OPEN_LONG" if side == "LONG" else "OPEN_SHORT"
                    else:
                        action = (
                            "REVERSE_TO_LONG" if side == "LONG" else "REVERSE_TO_SHORT"
                        )
                    if current is not None:
                        closed_return = _return(current, bar.close)
                        current = replace(
                            current,
                            status="CLOSED",
                            exit_signal_id=signal_id,
                            exit_bar_end=bar.bar_end,
                            exit_trading_day=bar.trading_day,
                            exit_reference_price=bar.close,
                            reference_return_pct=closed_return,
                            mark_bar_end=None,
                            mark_reference_price=None,
                            mark_change_pct=None,
                        )
                        closed_id = current.reference_trade_id
                        trades.append(current)
                    current = ReferenceTrade(
                        reference_trade_id=_identity("trade", *base, signal_id),
                        side=side,
                        physical_contract=segment.physical_contract,
                        segment_id=segment.segment_id,
                        entry_signal_id=signal_id,
                        entry_bar_end=bar.bar_end,
                        entry_trading_day=bar.trading_day,
                        entry_reference_price=bar.close,
                        mark_bar_end=bar.bar_end,
                        mark_reference_price=bar.close,
                        mark_change_pct=Decimal(0),
                        initial=bar.trading_day < since,
                    )
                    entry_index = index
                if since <= bar.trading_day <= through:
                    signals.append(
                        ReferenceSignal(
                            signal_id,
                            bar.bar_end,
                            bar.trading_day,
                            segment.physical_contract,
                            segment.segment_id,
                            direction,
                            bar.close,
                            action,
                            current.reference_trade_id,
                            closed_id,
                            closed_return,
                        )
                    )
        if current is not None:
            interruption = segment.interrupted_at
            # Future ownership metadata must not change a historical prefix.
            if (
                interruption is not None
                and interruption <= as_of
                and segment.owner_through < through
            ):
                current = replace(
                    current,
                    status="ROLLOVER_INTERRUPTED",
                    interrupted_at=interruption,
                    mark_bar_end=None,
                    mark_reference_price=None,
                    mark_change_pct=None,
                )
            trades.append(current)
    owner_ends = {segment.segment_id: segment.owner_through for segment in segments}
    selected = tuple(
        t
        for t in trades
        if t.entry_trading_day <= through
        and (t.exit_trading_day is None or t.exit_trading_day >= since)
        and (t.status != "ROLLOVER_INTERRUPTED" or owner_ends[t.segment_id] >= since)
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
        sum(t.status == "ROLLOVER_INTERRUPTED" for t in regular),
        sum(t.initial for t in selected),
        Decimal(wins) / len(returns) * 100 if returns else None,
        total / len(returns) if returns else None,
        total,
    )
    return ReferenceProjection(tuple(signals), selected, summary)
