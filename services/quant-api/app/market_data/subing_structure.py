from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
import re

from .domain import BarFrequency, CanonicalBar
from .subing_research import SubingDirection


class PivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"


class SubingStructureContractError(ValueError):
    code = "SUBING_STRUCTURE_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


_CONTRACT_PATTERN = re.compile(r"[A-Z]+[0-9]{3,4}\Z")


@dataclass(frozen=True, slots=True)
class ConfirmedPivot:
    pivot_id: str
    kind: PivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date

    def __post_init__(self) -> None:
        if (
            not isinstance(self.pivot_id, str)
            or not isinstance(self.kind, PivotKind)
            or not isinstance(self.source_timeframe, BarFrequency)
            or self.source_timeframe is not BarFrequency.M5
            or not _is_normalized_contract(self.contract)
            or type(self.segment_start_trading_day) is not date
            or not _is_aware_datetime(self.pivot_time)
            or not _is_aware_datetime(self.confirmed_at)
            or not isinstance(self.price, Decimal)
            or not self.price.is_finite()
        ):
            raise SubingStructureContractError()

        pivot_time = self.pivot_time.astimezone(UTC)
        confirmed_at = self.confirmed_at.astimezone(UTC)
        if pivot_time >= confirmed_at:
            raise SubingStructureContractError()
        expected_id = _canonical_pivot_id(
            contract=self.contract,
            segment_start_trading_day=self.segment_start_trading_day,
            source_timeframe=self.source_timeframe,
            kind=self.kind,
            pivot_time=pivot_time,
        )
        if self.pivot_id != expected_id:
            raise SubingStructureContractError()
        object.__setattr__(self, "pivot_time", pivot_time)
        object.__setattr__(self, "confirmed_at", confirmed_at)


@dataclass(frozen=True, slots=True)
class BreakoutAssessment:
    pivot_id: str
    observed_at: datetime
    direction: SubingDirection
    reference_price: Decimal
    intrabar_touched: bool
    close_beyond_level: bool
    crossed_on_close: bool
    volume_ratio_prev: Decimal | None
    open_interest_delta: Decimal | None


@dataclass(frozen=True, slots=True)
class RetestAssessment:
    pivot_id: str
    observed_at: datetime
    touched_reference: bool
    close_preserved_side: bool
    hard_invalidated: bool


def confirmed_pivots(
    bars: Sequence[CanonicalBar],
    *,
    source_timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    trading_day: date,
) -> tuple[ConfirmedPivot, ...]:
    """Return strict 2-left/2-right pivots confirmed within one trading day."""

    if source_timeframe is not BarFrequency.M5:
        raise ValueError("SUBING_PIVOT_SOURCE_TIMEFRAME_INVALID")
    if not contract.strip():
        raise ValueError("SUBING_PIVOT_CONTRACT_INVALID")
    if any(
        not isinstance(bar, CanonicalBar)
        or bar.trading_day < segment_start_trading_day
        for bar in bars
    ):
        raise ValueError("SUBING_PIVOT_SEGMENT_INVALID")
    if any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:])):
        raise ValueError("SUBING_PIVOT_BARS_NOT_STRICTLY_ORDERED")

    day_bars = tuple(bar for bar in bars if bar.trading_day == trading_day)
    pivots: list[ConfirmedPivot] = []
    for index in range(2, len(day_bars) - 2):
        center = day_bars[index]
        neighbors = (
            day_bars[index - 2],
            day_bars[index - 1],
            day_bars[index + 1],
            day_bars[index + 2],
        )
        confirmed_at = day_bars[index + 2].bar_end
        if all(center.high > bar.high for bar in neighbors):
            pivots.append(
                _pivot(
                    kind=PivotKind.HIGH,
                    bar=center,
                    confirmed_at=confirmed_at,
                    source_timeframe=source_timeframe,
                    contract=contract,
                    segment_start_trading_day=segment_start_trading_day,
                )
            )
        if all(center.low < bar.low for bar in neighbors):
            pivots.append(
                _pivot(
                    kind=PivotKind.LOW,
                    bar=center,
                    confirmed_at=confirmed_at,
                    source_timeframe=source_timeframe,
                    contract=contract,
                    segment_start_trading_day=segment_start_trading_day,
                )
            )
    return tuple(pivots)


def assess_pivot_breakout(
    previous: CanonicalBar,
    current: CanonicalBar,
    *,
    pivot: ConfirmedPivot,
    direction: SubingDirection,
) -> BreakoutAssessment:
    """Assess a causal close cross against one already confirmed Pivot."""

    _require_matching_pivot_direction(pivot, direction)
    if previous.bar_end >= current.bar_end:
        raise ValueError("SUBING_STRUCTURE_BARS_NOT_STRICTLY_ORDERED")
    if direction is SubingDirection.LONG:
        intrabar_touched = current.high >= pivot.price
        close_beyond_level = current.close > pivot.price
        crossed = previous.close <= pivot.price and close_beyond_level
    else:
        intrabar_touched = current.low <= pivot.price
        close_beyond_level = current.close < pivot.price
        crossed = previous.close >= pivot.price and close_beyond_level
    return BreakoutAssessment(
        pivot_id=pivot.pivot_id,
        observed_at=current.bar_end,
        direction=direction,
        reference_price=pivot.price,
        intrabar_touched=intrabar_touched,
        close_beyond_level=close_beyond_level,
        crossed_on_close=pivot.confirmed_at < current.bar_end and crossed,
        volume_ratio_prev=(
            current.volume / previous.volume if previous.volume > 0 else None
        ),
        open_interest_delta=(
            current.open_interest - previous.open_interest
            if current.open_interest is not None
            and previous.open_interest is not None
            else None
        ),
    )


def assess_pivot_retest(
    current: CanonicalBar,
    *,
    pivot: ConfirmedPivot,
    direction: SubingDirection,
) -> RetestAssessment:
    """Assess an exact, zero-tolerance retest of a bound Pivot level."""

    _require_matching_pivot_direction(pivot, direction)
    if current.bar_end <= pivot.confirmed_at:
        raise ValueError("SUBING_RETEST_BEFORE_PIVOT_CONFIRMATION")
    if direction is SubingDirection.LONG:
        touched_reference = current.low <= pivot.price
        close_preserved_side = current.close >= pivot.price
        hard_invalidated = current.close < pivot.price
    else:
        touched_reference = current.high >= pivot.price
        close_preserved_side = current.close <= pivot.price
        hard_invalidated = current.close > pivot.price
    return RetestAssessment(
        pivot_id=pivot.pivot_id,
        observed_at=current.bar_end,
        touched_reference=touched_reference,
        close_preserved_side=close_preserved_side,
        hard_invalidated=hard_invalidated,
    )


def _pivot(
    *,
    kind: PivotKind,
    bar: CanonicalBar,
    confirmed_at: datetime,
    source_timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
) -> ConfirmedPivot:
    pivot_id = _canonical_pivot_id(
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        source_timeframe=source_timeframe,
        kind=kind,
        pivot_time=bar.bar_end,
    )
    return ConfirmedPivot(
        pivot_id=pivot_id,
        kind=kind,
        source_timeframe=source_timeframe,
        pivot_time=bar.bar_end,
        confirmed_at=confirmed_at,
        price=bar.high if kind is PivotKind.HIGH else bar.low,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )


def _canonical_pivot_id(
    *,
    contract: str,
    segment_start_trading_day: date,
    source_timeframe: BarFrequency,
    kind: PivotKind,
    pivot_time: datetime,
) -> str:
    return ":".join(
        (
            contract,
            segment_start_trading_day.isoformat(),
            source_timeframe.value,
            kind.value,
            pivot_time.astimezone(UTC).isoformat(),
        )
    )


def _is_normalized_contract(value: object) -> bool:
    if not isinstance(value, str) or _CONTRACT_PATTERN.fullmatch(value) is None:
        return False
    return 1 <= int(value[-2:]) <= 12


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _require_matching_pivot_direction(
    pivot: ConfirmedPivot,
    direction: SubingDirection,
) -> None:
    expected_kind = {
        SubingDirection.LONG: PivotKind.HIGH,
        SubingDirection.SHORT: PivotKind.LOW,
    }.get(direction)
    if expected_kind is None or pivot.kind is not expected_kind:
        raise ValueError("SUBING_STRUCTURE_DIRECTION_INVALID")
