"""Sequential causal N-structure Swing reduction within one rank-1 segment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
import re

from app.market_data.domain import BarFrequency, CanonicalBar


class NSwingLeg(StrEnum):
    UNRESOLVED = "unresolved"
    UP = "up"
    DOWN = "down"


class NSwingPivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"


class NStructureContractError(ValueError):
    code = "N_STRUCTURE_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class NStructureSeriesError(ValueError):
    code = "N_STRUCTURE_SERIES_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


_CONTRACT_PATTERN = re.compile(r"[A-Z]+[0-9]{3,4}\Z")


@dataclass(frozen=True, slots=True)
class NSwingPivot:
    pivot_id: str
    epoch: int
    kind: NSwingPivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date

    def __post_init__(self) -> None:
        if (
            not isinstance(self.pivot_id, str)
            or type(self.epoch) is not int
            or self.epoch < 0
            or not isinstance(self.kind, NSwingPivotKind)
            or self.source_timeframe is not BarFrequency.M5
            or not _is_aware_datetime(self.pivot_time)
            or not _is_aware_datetime(self.confirmed_at)
            or not isinstance(self.price, Decimal)
            or not self.price.is_finite()
            or self.price <= 0
            or not _is_normalized_contract(self.contract)
            or type(self.segment_start_trading_day) is not date
        ):
            raise NStructureContractError()

        pivot_time = self.pivot_time.astimezone(UTC)
        confirmed_at = self.confirmed_at.astimezone(UTC)
        if pivot_time >= confirmed_at:
            raise NStructureContractError()
        expected_id = _canonical_pivot_id(
            contract=self.contract,
            segment_start_trading_day=self.segment_start_trading_day,
            source_timeframe=self.source_timeframe,
            epoch=self.epoch,
            kind=self.kind,
            pivot_time=pivot_time,
        )
        if self.pivot_id != expected_id:
            raise NStructureContractError()
        object.__setattr__(self, "pivot_time", pivot_time)
        object.__setattr__(self, "confirmed_at", confirmed_at)


@dataclass(frozen=True, slots=True)
class NSwingTrace:
    contract: str
    segment_start_trading_day: date
    pivots: tuple[NSwingPivot, ...]
    ambiguous_outside_reset_at: tuple[datetime, ...]
    final_epoch: int
    final_leg: NSwingLeg


def reduce_n_swings(
    bars: Sequence[CanonicalBar],
    *,
    source_timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
) -> NSwingTrace:
    """Reduce one exact contract segment using previous/current bar facts only."""

    _validate_series(
        bars,
        source_timeframe=source_timeframe,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        segment_end_trading_day=segment_end_trading_day,
    )
    pivots: list[NSwingPivot] = []
    outside_resets: list[datetime] = []
    epoch = 0
    leg = NSwingLeg.UNRESOLVED
    running_extreme: CanonicalBar | None = None

    if bars:
        previous = bars[0]
        for current in bars[1:]:
            outside = (
                current.high > previous.high and current.low < previous.low
            )
            if outside:
                epoch += 1
                outside_resets.append(current.bar_end)
                leg = NSwingLeg.UNRESOLVED
                running_extreme = None
            elif leg is NSwingLeg.UNRESOLVED:
                if (
                    current.high > previous.high
                    and current.low >= previous.low
                ):
                    leg = NSwingLeg.UP
                    running_extreme = current
                elif (
                    current.low < previous.low
                    and current.high <= previous.high
                ):
                    leg = NSwingLeg.DOWN
                    running_extreme = current
            elif leg is NSwingLeg.UP:
                assert running_extreme is not None
                if current.low >= previous.low:
                    if current.high > running_extreme.high:
                        running_extreme = current
                else:
                    pivots.append(
                        _pivot(
                            kind=NSwingPivotKind.HIGH,
                            bar=running_extreme,
                            confirmed_at=current.bar_end,
                            source_timeframe=source_timeframe,
                            epoch=epoch,
                            contract=contract,
                            segment_start_trading_day=segment_start_trading_day,
                        )
                    )
                    leg = NSwingLeg.DOWN
                    running_extreme = current
            else:
                assert leg is NSwingLeg.DOWN
                assert running_extreme is not None
                if current.high <= previous.high:
                    if current.low < running_extreme.low:
                        running_extreme = current
                else:
                    pivots.append(
                        _pivot(
                            kind=NSwingPivotKind.LOW,
                            bar=running_extreme,
                            confirmed_at=current.bar_end,
                            source_timeframe=source_timeframe,
                            epoch=epoch,
                            contract=contract,
                            segment_start_trading_day=segment_start_trading_day,
                        )
                    )
                    leg = NSwingLeg.UP
                    running_extreme = current
            previous = current

    return NSwingTrace(
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
        pivots=tuple(pivots),
        ambiguous_outside_reset_at=tuple(outside_resets),
        final_epoch=epoch,
        final_leg=leg,
    )


def _validate_series(
    bars: Sequence[CanonicalBar],
    *,
    source_timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
) -> None:
    if (
        source_timeframe is not BarFrequency.M5
        or not _is_normalized_contract(contract)
        or type(segment_start_trading_day) is not date
        or type(segment_end_trading_day) is not date
        or segment_start_trading_day > segment_end_trading_day
        or any(not isinstance(bar, CanonicalBar) for bar in bars)
        or any(
            not segment_start_trading_day
            <= bar.trading_day
            <= segment_end_trading_day
            for bar in bars
        )
        or any(
            previous.bar_end >= current.bar_end
            for previous, current in zip(bars, bars[1:])
        )
    ):
        raise NStructureSeriesError()


def _pivot(
    *,
    kind: NSwingPivotKind,
    bar: CanonicalBar,
    confirmed_at: datetime,
    source_timeframe: BarFrequency,
    epoch: int,
    contract: str,
    segment_start_trading_day: date,
) -> NSwingPivot:
    return NSwingPivot(
        pivot_id=_canonical_pivot_id(
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            source_timeframe=source_timeframe,
            epoch=epoch,
            kind=kind,
            pivot_time=bar.bar_end,
        ),
        epoch=epoch,
        kind=kind,
        source_timeframe=source_timeframe,
        pivot_time=bar.bar_end,
        confirmed_at=confirmed_at,
        price=bar.high if kind is NSwingPivotKind.HIGH else bar.low,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )


def _canonical_pivot_id(
    *,
    contract: str,
    segment_start_trading_day: date,
    source_timeframe: BarFrequency,
    epoch: int,
    kind: NSwingPivotKind,
    pivot_time: datetime,
) -> str:
    return ":".join(
        (
            contract,
            segment_start_trading_day.isoformat(),
            source_timeframe.value,
            str(epoch),
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
