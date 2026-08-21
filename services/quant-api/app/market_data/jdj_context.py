"""Causal projection of exact JDJ 1m EMA and pre-known 5m N facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from guiyi_quant.indicators import ema_series

from .domain import BarFrequency, CanonicalBar
from .jdj_policy import JdjPolicy, is_exact_jdj_policy
from .n_structure_policy import (
    NStructurePolicy,
    is_exact_n_structure_policy,
)
from .n_structure_segment import (
    NStructureSegmentTrace,
    evaluate_n_structure_segment,
)
from .n_structure_state import NStructureKind, NStructureSnapshot
from .n_structure_swing import (
    NStructureContractError,
    NStructureSeriesError,
    NSwingPivot,
    NSwingPivotKind,
)


class JdjContextError(ValueError):
    code = "JDJ_CONTEXT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjBarContext:
    bar: CanonicalBar
    ema20: Decimal | None
    trend_kind: NStructureKind
    trend_snapshot_observed_at: datetime | None
    trend_epoch: int | None
    eligible_high_pivot: NSwingPivot | None
    eligible_low_pivot: NSwingPivot | None

    def __post_init__(self) -> None:
        snapshot_time = self.trend_snapshot_observed_at
        if (
            not isinstance(self.bar, CanonicalBar)
            or (
                self.ema20 is not None
                and (
                    not isinstance(self.ema20, Decimal)
                    or not self.ema20.is_finite()
                )
            )
            or not isinstance(self.trend_kind, NStructureKind)
            or ((snapshot_time is None) != (self.trend_epoch is None))
            or (
                snapshot_time is not None
                and (
                    not _is_aware_datetime(snapshot_time)
                    or type(self.trend_epoch) is not int
                    or self.trend_epoch < 0
                )
            )
            or not _valid_pivot(
                self.eligible_high_pivot,
                kind=NSwingPivotKind.HIGH,
                epoch=self.trend_epoch,
            )
            or not _valid_pivot(
                self.eligible_low_pivot,
                kind=NSwingPivotKind.LOW,
                epoch=self.trend_epoch,
            )
        ):
            raise JdjContextError()
        if snapshot_time is not None:
            object.__setattr__(
                self,
                "trend_snapshot_observed_at",
                snapshot_time.astimezone(UTC),
            )


def build_jdj_context_series(
    bars_1m: Sequence[CanonicalBar],
    bars_5m: Sequence[CanonicalBar],
    *,
    contract: str,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
    jdj_policy: JdjPolicy,
    n_policy: NStructurePolicy,
) -> tuple[JdjBarContext, ...]:
    """Project exact EMA20 and only causally pre-known same-epoch N facts."""

    one_minute_bars = tuple(bars_1m)
    five_minute_bars = tuple(bars_5m)
    _validate_inputs(
        one_minute_bars,
        five_minute_bars,
        segment_start_trading_day=segment_start_trading_day,
        segment_end_trading_day=segment_end_trading_day,
        jdj_policy=jdj_policy,
        n_policy=n_policy,
    )

    ema = ema_series(
        [float(bar.close) for bar in one_minute_bars],
        20,
        bar_ends=[bar.bar_end.isoformat() for bar in one_minute_bars],
        seed_policy="sma_window",
        indicator_code="ema20",
        round_digits=6,
    )
    try:
        n_trace = evaluate_n_structure_segment(
            five_minute_bars,
            contract=contract,
            segment_start_trading_day=segment_start_trading_day,
            segment_end_trading_day=segment_end_trading_day,
            policy=n_policy,
        )
    except (NStructureContractError, NStructureSeriesError):
        raise JdjContextError() from None

    _validate_projection_facts(
        one_minute_bars,
        five_minute_bars,
        ema_points=ema.points,
        trace=n_trace,
        contract=contract,
        segment_start_trading_day=segment_start_trading_day,
    )

    snapshots_by_day = _snapshots_by_trading_day(
        n_trace.structures.snapshots,
        five_minute_bars,
    )
    pivots_by_day = _pivots_by_trading_day(
        n_trace.swings.pivots,
        five_minute_bars,
    )
    contexts: list[JdjBarContext] = []
    active_day: date | None = None
    day_snapshots: tuple[NStructureSnapshot, ...] = ()
    day_pivots: tuple[NSwingPivot, ...] = ()
    snapshot_index = 0
    pivot_index = 0
    latest_snapshot: NStructureSnapshot | None = None
    latest_pivots: dict[tuple[int, NSwingPivotKind], NSwingPivot] = {}

    for index, bar in enumerate(one_minute_bars):
        if bar.trading_day != active_day:
            active_day = bar.trading_day
            day_snapshots = snapshots_by_day.get(active_day, ())
            day_pivots = pivots_by_day.get(active_day, ())
            snapshot_index = 0
            pivot_index = 0
            latest_snapshot = None
            latest_pivots = {}
        elif index > 0:
            strict_before_boundary = one_minute_bars[index - 1].bar_end
            while (
                snapshot_index < len(day_snapshots)
                and day_snapshots[snapshot_index].observed_at
                <= strict_before_boundary
            ):
                latest_snapshot = day_snapshots[snapshot_index]
                snapshot_index += 1
            while (
                pivot_index < len(day_pivots)
                and day_pivots[pivot_index].confirmed_at
                <= strict_before_boundary
            ):
                pivot = day_pivots[pivot_index]
                key = (pivot.epoch, pivot.kind)
                previous = latest_pivots.get(key)
                if previous is None or _pivot_order_key(pivot) > _pivot_order_key(
                    previous
                ):
                    latest_pivots[key] = pivot
                pivot_index += 1

        ema_point = ema.points[index]
        ema20 = (
            Decimal(str(ema_point.value))
            if ema_point.ready
            and ema_point.valid
            and ema_point.value is not None
            else None
        )
        epoch = latest_snapshot.epoch if latest_snapshot is not None else None
        contexts.append(
            JdjBarContext(
                bar=bar,
                ema20=ema20,
                trend_kind=(
                    latest_snapshot.kind
                    if latest_snapshot is not None
                    else NStructureKind.UNDEFINED
                ),
                trend_snapshot_observed_at=(
                    latest_snapshot.observed_at
                    if latest_snapshot is not None
                    else None
                ),
                trend_epoch=epoch,
                eligible_high_pivot=(
                    latest_pivots.get((epoch, NSwingPivotKind.HIGH))
                    if epoch is not None
                    else None
                ),
                eligible_low_pivot=(
                    latest_pivots.get((epoch, NSwingPivotKind.LOW))
                    if epoch is not None
                    else None
                ),
            )
        )
    return tuple(contexts)


def _validate_inputs(
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    *,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
    jdj_policy: JdjPolicy,
    n_policy: NStructurePolicy,
) -> None:
    if (
        type(segment_start_trading_day) is not date
        or type(segment_end_trading_day) is not date
        or segment_start_trading_day > segment_end_trading_day
        or not is_exact_jdj_policy(jdj_policy)
        or not is_exact_n_structure_policy(n_policy)
        or not _valid_bar_series(
            bars_1m,
            segment_start_trading_day=segment_start_trading_day,
            segment_end_trading_day=segment_end_trading_day,
        )
        or not _valid_bar_series(
            bars_5m,
            segment_start_trading_day=segment_start_trading_day,
            segment_end_trading_day=segment_end_trading_day,
        )
    ):
        raise JdjContextError()


def _valid_bar_series(
    bars: tuple[CanonicalBar, ...],
    *,
    segment_start_trading_day: date,
    segment_end_trading_day: date,
) -> bool:
    return (
        all(isinstance(bar, CanonicalBar) for bar in bars)
        and all(
            segment_start_trading_day
            <= bar.trading_day
            <= segment_end_trading_day
            for bar in bars
        )
        and all(
            previous.bar_end < current.bar_end
            for previous, current in zip(bars, bars[1:])
        )
    )


def _validate_projection_facts(
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    *,
    ema_points: Sequence[object],
    trace: NStructureSegmentTrace,
    contract: str,
    segment_start_trading_day: date,
) -> None:
    if not isinstance(trace, NStructureSegmentTrace):
        raise JdjContextError()
    snapshots = trace.structures.snapshots
    if (
        len(ema_points) != len(bars_1m)
        or any(
            getattr(point, "bar_end", None) != bar.bar_end.isoformat()
            or (
                getattr(point, "ready", False)
                and (
                    not getattr(point, "valid", False)
                    or getattr(point, "value", None) is None
                )
            )
            for point, bar in zip(ema_points, bars_1m, strict=True)
        )
        or len(snapshots) != len(bars_5m)
        or any(
            snapshot.observed_at != bar.bar_end
            for snapshot, bar in zip(snapshots, bars_5m, strict=True)
        )
        or trace.swings.contract != contract
        or trace.swings.segment_start_trading_day
        != segment_start_trading_day
    ):
        raise JdjContextError()

    bars_by_end = {bar.bar_end: bar for bar in bars_5m}
    snapshots_by_end = {
        snapshot.observed_at: snapshot for snapshot in snapshots
    }
    for pivot in trace.swings.pivots:
        confirmation_bar = bars_by_end.get(pivot.confirmed_at)
        pivot_bar = bars_by_end.get(pivot.pivot_time)
        confirming_snapshot = snapshots_by_end.get(pivot.confirmed_at)
        if (
            pivot.contract != contract
            or pivot.segment_start_trading_day
            != segment_start_trading_day
            or pivot.source_timeframe is not BarFrequency.M5
            or confirmation_bar is None
            or pivot_bar is None
            or confirming_snapshot is None
            or pivot.epoch != confirming_snapshot.epoch
        ):
            raise JdjContextError()


def _snapshots_by_trading_day(
    snapshots: tuple[NStructureSnapshot, ...],
    bars_5m: tuple[CanonicalBar, ...],
) -> dict[date, tuple[NStructureSnapshot, ...]]:
    grouped: dict[date, list[NStructureSnapshot]] = {}
    for snapshot, bar in zip(snapshots, bars_5m, strict=True):
        grouped.setdefault(bar.trading_day, []).append(snapshot)
    return {day: tuple(items) for day, items in grouped.items()}


def _pivots_by_trading_day(
    pivots: tuple[NSwingPivot, ...],
    bars_5m: tuple[CanonicalBar, ...],
) -> dict[date, tuple[NSwingPivot, ...]]:
    day_by_end = {bar.bar_end: bar.trading_day for bar in bars_5m}
    grouped: dict[date, list[NSwingPivot]] = {}
    for pivot in pivots:
        grouped.setdefault(day_by_end[pivot.confirmed_at], []).append(pivot)
    return {
        day: tuple(sorted(items, key=_pivot_order_key))
        for day, items in grouped.items()
    }


def _valid_pivot(
    pivot: NSwingPivot | None,
    *,
    kind: NSwingPivotKind,
    epoch: int | None,
) -> bool:
    if pivot is None:
        return True
    return (
        isinstance(pivot, NSwingPivot)
        and pivot.kind is kind
        and epoch is not None
        and pivot.epoch == epoch
    )


def _pivot_order_key(pivot: NSwingPivot) -> tuple[datetime, datetime, str]:
    return (pivot.confirmed_at, pivot.pivot_time, pivot.pivot_id)


def _is_aware_datetime(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None
