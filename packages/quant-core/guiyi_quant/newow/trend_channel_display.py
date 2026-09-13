"""Independent HHV10/LLV10 facts for the Newow trend chart layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .oscillation_channel import CHANNEL_FORMULA_VERSION, ChannelPoint, calculate_channel_series
from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
)


TREND_CHANNEL_PERIOD = 10
TREND_CHANNEL_LAYER = "trend_channel"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_TREND_CHANNEL_INVALID_IDENTITY")


@dataclass(frozen=True, slots=True)
class TrendChannelPoint:
    bar_end: datetime
    upper: Decimal | None
    lower: Decimal | None
    formula_version: str
    availability: FeatureStatus
    physical_contract: str
    segment_id: str
    source_identity: str

    def __post_init__(self) -> None:
        for value in (
            self.formula_version,
            self.physical_contract,
            self.segment_id,
            self.source_identity,
        ):
            _text(value)
        if self.formula_version != CHANNEL_FORMULA_VERSION:
            raise ValueError("NEWOW_TREND_CHANNEL_FORMULA_MISMATCH")
        if not isinstance(self.availability, FeatureStatus):
            raise ValueError("NEWOW_TREND_CHANNEL_INVALID_STATUS")
        ready = self.availability.status is FeatureRuntimeStatus.READY
        if ready != (self.upper is not None and self.lower is not None):
            raise ValueError("NEWOW_TREND_CHANNEL_VALUE_STATUS_CONFLICT")
        if ready and (
            not isinstance(self.upper, Decimal)
            or not isinstance(self.lower, Decimal)
            or not self.upper.is_finite()
            or not self.lower.is_finite()
            or self.upper <= 0
            or self.lower <= 0
            or self.upper < self.lower
        ):
            raise ValueError("NEWOW_TREND_CHANNEL_INVALID_VALUE")


@dataclass(frozen=True, slots=True)
class TrendChannelLayer:
    points: tuple[TrendChannelPoint, ...]
    formula_version: str = CHANNEL_FORMULA_VERSION
    period: int = TREND_CHANNEL_PERIOD
    kind: str = TREND_CHANNEL_LAYER

    def __post_init__(self) -> None:
        if (
            self.kind != TREND_CHANNEL_LAYER
            or self.formula_version != CHANNEL_FORMULA_VERSION
            or self.period != TREND_CHANNEL_PERIOD
        ):
            raise ValueError("NEWOW_TREND_CHANNEL_LAYER_IDENTITY_MISMATCH")
        points = tuple(self.points)
        if any(
            not isinstance(point, TrendChannelPoint)
            or point.formula_version != self.formula_version
            for point in points
        ):
            raise ValueError("NEWOW_TREND_CHANNEL_INVALID_POINT")
        object.__setattr__(self, "points", points)


def _status(status: FeatureRuntimeStatus, reason: str | None = None) -> FeatureStatus:
    return FeatureStatus(status, EvidenceStatus.ACTIVE_CODE_VERIFIED, reason)


def _key(item: ProductBar) -> tuple[datetime, str, str, str]:
    bar = item.bar
    return (bar.bar_end, bar.physical_contract, bar.segment_id, bar.source_identity)


def build_trend_channel_layer(
    replay_bars: tuple[ProductBar, ...],
    visible_bars: tuple[ProductBar, ...],
) -> TrendChannelLayer:
    """Project aligned display facts without changing the trend strategy replay.

    `replay_bars` is the authoritative lifecycle prefix. `visible_bars` defines
    the exact output order and may be a page or window subset of that prefix.
    """

    replay = tuple(replay_bars)
    visible = tuple(visible_bars)
    if any(not isinstance(item, ProductBar) for item in (*replay, *visible)):
        raise ValueError("NEWOW_TREND_CHANNEL_INVALID_BAR")

    calculated: dict[
        tuple[datetime, str, str, str], tuple[ChannelPoint | None, str | None]
    ] = {}
    owners_by_time: dict[datetime, set[tuple[str, str, str]]] = {}
    run: list[ProductBar] = []
    run_owner: tuple[str, str] | None = None

    def flush() -> None:
        nonlocal run
        if not run:
            return

        def record(
            item: ProductBar, value: ChannelPoint | None, reason: str | None
        ) -> None:
            key = _key(item)
            calculated[key] = (
                (None, "NEWOW_TREND_CHANNEL_OWNER_CONFLICT")
                if key in calculated
                else (value, reason)
            )
            owners_by_time.setdefault(item.bar.bar_end, set()).add(key[1:])

        time_counts: dict[datetime, int] = {}
        for item in run:
            time_counts[item.bar.bar_end] = time_counts.get(item.bar.bar_end, 0) + 1
        duplicate_times = {bar_end for bar_end, count in time_counts.items() if count > 1}
        times = [item.bar.bar_end for item in run]
        if any(left > right for left, right in zip(times, times[1:])):
            for item in run:
                record(item, None, "NEWOW_TREND_CHANNEL_ORDER_CONFLICT")
            run = []
            return

        trusted: list[ProductBar] = []
        prefix_tainted = False
        for item in run:
            if item.bar.bar_end in duplicate_times:
                record(item, None, "NEWOW_TREND_CHANNEL_OWNER_CONFLICT")
                trusted = []
                prefix_tainted = True
                continue
            trusted.append(item)
            trusted = trusted[-TREND_CHANNEL_PERIOD:]
            if prefix_tainted and len(trusted) < TREND_CHANNEL_PERIOD:
                record(item, None, "NEWOW_TREND_CHANNEL_WARMUP_INSUFFICIENT")
                continue
            value = calculate_channel_series(
                tuple(candidate.bar for candidate in trusted),
                period=TREND_CHANNEL_PERIOD,
            )[-1]
            record(item, value, None)
        run = []

    for item in replay:
        owner = (item.bar.physical_contract, item.bar.segment_id)
        if run_owner is not None and owner != run_owner:
            flush()
        run_owner = owner
        run.append(item)
    flush()

    points: list[TrendChannelPoint] = []
    for item in visible:
        bar = item.bar
        key = _key(item)
        calculated_point = calculated.get(key)
        upper: Decimal | None
        lower: Decimal | None
        if calculated_point is not None and calculated_point[0] is not None:
            value = calculated_point[0]
            upper, lower = value.upper, value.lower
            availability = _status(FeatureRuntimeStatus.READY)
        else:
            upper = lower = None
            seen_owners = owners_by_time.get(bar.bar_end, set())
            reason = (
                calculated_point[1]
                if calculated_point is not None
                else "NEWOW_TREND_CHANNEL_OWNER_CONFLICT"
                if seen_owners
                else "NEWOW_TREND_CHANNEL_BAR_MISSING"
            )
            availability = _status(FeatureRuntimeStatus.UNAVAILABLE, reason)
        points.append(
            TrendChannelPoint(
                bar.bar_end,
                upper,
                lower,
                CHANNEL_FORMULA_VERSION,
                availability,
                bar.physical_contract,
                bar.segment_id,
                bar.source_identity,
            )
        )
    return TrendChannelLayer(tuple(points))
