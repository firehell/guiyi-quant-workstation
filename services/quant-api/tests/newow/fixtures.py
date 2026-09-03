"""Deterministic completed-D1 fixtures derived only from the Slice B gates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from guiyi_quant.newow.cup_handle import (
    CupBarSnapshot,
    CupHandleStateValue,
    CupPivotTrackerState,
    WilderAtrState,
)
from guiyi_quant.newow.models import CupPivot, CupPivotKind, NewowDailyBar


_START = date(2026, 1, 5)
_ONE = Decimal("1")
_PIVOT_REVERSAL = Decimal("1.25")


def _linear(start: str, end: str, count: int) -> list[Decimal]:
    first = Decimal(start)
    last = Decimal(end)
    if count == 1:
        return [last]
    step = (last - first) / Decimal(count - 1)
    return [first + step * index for index in range(count)]


def _bars(
    closes: list[Decimal],
    *,
    volumes: list[int] | None = None,
    rollover_at: int | None = None,
) -> tuple[NewowDailyBar, ...]:
    actual_volumes = volumes or [100] * len(closes)
    result: list[NewowDailyBar] = []
    for index, (close, volume) in enumerate(zip(closes, actual_volumes, strict=True)):
        bar_day = _START + timedelta(days=index)
        rolled = rollover_at is not None and index >= rollover_at
        contract = "RB2705" if rolled else "RB2701"
        segment = "rb:RB2705:2026-05-01" if rolled else "rb:RB2701:2026-01-01"
        result.append(
            NewowDailyBar(
                product="rb",
                physical_contract=contract,
                segment_id=segment,
                trading_day=bar_day,
                bar_end=datetime.combine(bar_day, datetime.min.time(), tzinfo=UTC),
                open=close,
                high=close + _ONE,
                low=close - _ONE,
                close=close,
                volume=volume,
                open_interest=200,
                source_identity=f"fixture:{contract}:{index}",
                observation_eligible=True,
                completed=True,
            )
        )
    return tuple(result)


def _base_closes() -> list[Decimal]:
    return (
        _linear("70", "100", 46)
        + _linear("98.5", "84", 12)
        + [Decimal(value) for value in ("83", "81", "80", "81", "83")]
        + _linear("84", "100", 13)
        + [Decimal(value) for value in ("99", "98", "97", "96", "95", "96", "97", "99")]
        + [Decimal("99"), Decimal("102")]
    )


def _base_volumes(length: int) -> list[int]:
    volumes = [100] * length
    for index in range(61, min(76, length)):
        volumes[index] = 120
    for index in range(76, min(83, length)):
        volumes[index] = 60
    if length > 83:
        volumes[83] = 60
    if length > 85:
        volumes[85] = 180
    return volumes


def bullish_true_cup_handle() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    return _bars(closes, volumes=_base_volumes(len(closes)))


def bearish_true_cup_handle() -> tuple[NewowDailyBar, ...]:
    bullish = bullish_true_cup_handle()
    axis = Decimal("200")
    return tuple(
        replace(
            bar,
            open=axis - bar.open,
            high=axis - bar.low,
            low=axis - bar.high,
            close=axis - bar.close,
        )
        for bar in bullish
    )


def ready_and_breakout_same_bar() -> tuple[NewowDailyBar, ...]:
    bars = list(bullish_true_cup_handle()[:84])
    bars[82] = replace(
        bars[82],
        open=Decimal("96"),
        high=Decimal("97"),
        low=Decimal("95"),
        close=Decimal("96"),
    )
    bars[-1] = replace(
        bars[-1],
        open=Decimal("102"),
        high=Decimal("103"),
        low=Decimal("101"),
        close=Decimal("102"),
        volume=180,
    )
    return tuple(bars)


def breakout_then_weakened() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes() + [Decimal("99")]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def breakout_then_archived() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes() + [Decimal("101")] * 20
    return _bars(closes, volumes=_base_volumes(len(closes)))


def ready_then_invalidated() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:84] + [Decimal("92")]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def ready_then_expired() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:84] + [Decimal("99")] * 20
    return _bars(closes, volumes=_base_volumes(len(closes)))


def v_bottom_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[46:60] = _linear("99", "86", 14)
    closes[60] = Decimal("80")
    closes[61:76] = _linear("86", "100", 15)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def wide_range_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[64:71] = [
        Decimal("89.5") if index % 2 == 0 else Decimal("90.5")
        for index in range(7)
    ]
    closes[71:76] = _linear("91", "100", 5)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def downtrend_rebound_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[:40] = _linear("99", "90", 40)
    closes[39:46] = _linear("90", "100", 7)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def pretrend_not_confirmed() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[:46] = _linear("96", "100", 46)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def shallow_cup_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[46:58] = _linear("99", "96", 12)
    closes[58:63] = [Decimal(value) for value in ("96", "95", "94", "95", "96")]
    closes[63:76] = _linear("96", "100", 13)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def cup_too_deep_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    closes[46:58] = _linear("96", "45", 12)
    closes[58:63] = [Decimal(value) for value in ("44", "42", "40", "42", "44")]
    closes[63:76] = _linear("45", "100", 13)
    return _bars(closes, volumes=_base_volumes(len(closes)))


def rim_gap_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:84]
    closes[63:76] = _linear("84", "90", 13)
    closes[76:84] = [Decimal(value) for value in ("89", "88", "86", "85", "86", "87", "88", "89")]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def handle_too_short_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:76] + [
        Decimal(value) for value in ("98", "96", "94", "99")
    ]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def handle_too_long_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:76] + _linear("99", "95", 16) + [Decimal("99")] * 4
    return _bars(closes, volumes=_base_volumes(len(closes)))


def handle_too_deep_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:76] + [
        Decimal(value) for value in ("96", "92", "86", "80", "82", "86", "92", "98")
    ]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def handle_below_mid_rejected() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()[:76] + [
        Decimal(value) for value in ("97", "94", "91", "88", "90", "93", "96", "99")
    ]
    return _bars(closes, volumes=_base_volumes(len(closes)))


def handle_volume_not_contracting() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    volumes = _base_volumes(len(closes))
    for index in range(76, 83):
        volumes[index] = 130
    return _bars(closes, volumes=volumes)


def breakout_volume_not_confirmed() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    volumes = _base_volumes(len(closes))
    volumes[85] = 80
    return _bars(closes, volumes=volumes)


def rollover_split_candidate() -> tuple[NewowDailyBar, ...]:
    closes = _base_closes()
    return _bars(closes, volumes=_base_volumes(len(closes)), rollover_at=61)


def candidate_limit_exceeded() -> RestoredCupCase:
    return restored_cup_case()


def competing_ready_and_breakout_candidates() -> RestoredCupCase:
    """Two hard-valid bodies where lower-score B is a same-bar BREAKOUT."""

    first = restored_cup_case(
        left_index=35,
        bottom_index=48,
        right_index=60,
        handle_index=65,
        handle_confirmed_index=68,
    )
    snapshots = list(first.state.eligible_bars)
    tail_closes = [
        Decimal(value)
        for value in (
            "97",
            "98",
            "94",
            "89",
            "85",
            "83",
            "81",
            "83",
            "86",
            "90",
            "92",
            "94",
            "96",
            "98",
            "99",
            "100",
            "101",
            "101",
            "102",
            "102",
            "102",
            "102",
            "101",
            "100",
            "99",
            "98.5",
            "98",
            "99",
            "100",
            "101",
        )
    ]
    volumes = [100] * len(tail_closes)
    for index in range(76, 91):
        volumes[index - 69] = 120
    for index in range(91, 98):
        volumes[index - 69] = 60
    tail_bars = _bars(
        [snapshot.bar.close for snapshot in snapshots] + tail_closes,
        volumes=[int(snapshot.bar.volume) for snapshot in snapshots] + volumes,
    )[len(snapshots) :]
    snapshots.extend(
        CupBarSnapshot(bar=bar, eligible_index=index, atr=2.0)
        for index, bar in enumerate(tail_bars, start=69)
    )

    def pivot(kind: CupPivotKind, price: str, at: int, confirmed: int) -> CupPivot:
        return CupPivot(
            kind=kind,
            price=Decimal(price),
            pivot_at=snapshots[at].bar.bar_end,
            confirmed_at=snapshots[confirmed].bar.bar_end,
            pivot_index=at,
            confirmed_index=confirmed,
            atr_at_pivot=2.0,
        )

    pivots = (
        pivot(CupPivotKind.HIGH, "100", 35, 38),
        pivot(CupPivotKind.LOW, "80", 48, 51),
        pivot(CupPivotKind.HIGH, "100", 60, 63),
        pivot(CupPivotKind.LOW, "94", 65, 68),
        pivot(CupPivotKind.HIGH, "99", 70, 73),
        pivot(CupPivotKind.LOW, "80", 75, 78),
        pivot(CupPivotKind.HIGH, "103", 90, 93),
        pivot(CupPivotKind.LOW, "97", 95, 98),
    )
    state = replace(
        first.state,
        atr_state=replace(
            first.state.atr_state,
            count=len(snapshots),
            atr=2.0,
            previous_close=snapshots[-1].bar.close,
        ),
        pivot_tracker=CupPivotTrackerState(
            leg="UP_LEG",
            extreme_high=snapshots[98],
            extreme_low=snapshots[95],
            last_pivot=pivots[-1],
            eligible_index=98,
        ),
        eligible_bars=tuple(snapshots),
        confirmed_pivots=pivots,
    )
    day = _START + timedelta(days=99)
    next_bar = replace(
        snapshots[-1].bar,
        trading_day=day,
        bar_end=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        open=Decimal("104"),
        high=Decimal("105"),
        low=Decimal("103"),
        close=Decimal("104"),
        volume=180,
        source_identity="fixture:competing:99",
    )
    return RestoredCupCase(state=state, next_bar=next_bar)


@dataclass(frozen=True, slots=True)
class RestoredCupCase:
    state: CupHandleStateValue
    next_bar: NewowDailyBar


def restored_cup_case(
    *,
    left_index: int = 30,
    bottom_index: int = 45,
    right_index: int = 60,
    handle_index: int = 65,
    handle_confirmed_index: int = 68,
    left_price: Decimal = Decimal("100"),
    bottom_price: Decimal = Decimal("80"),
    right_price: Decimal = Decimal("100"),
    handle_price: Decimal = Decimal("94"),
    atr: float = 2.0,
    pretrend: str = "rising",
    bottom_span: int = 5,
    midline_crossings: int | None = None,
    wide_crossings: bool = False,
    right_volume: int = 120,
    handle_volume: int = 60,
    baseline_volume: int = 100,
    next_close: Decimal | None = None,
    next_volume: int = 100,
) -> RestoredCupCase:
    """Build a structurally valid restored state with no synthetic invalid overlay."""

    last_index = handle_confirmed_index
    closes = [Decimal("90")] * (last_index + 1)
    if pretrend == "rising":
        closes[: left_index + 1] = _linear("80", str(left_price - _ONE), left_index + 1)
    elif pretrend == "weak":
        closes[: left_index + 1] = _linear("90", str(left_price - _ONE), left_index + 1)
    elif pretrend == "flat":
        closes[: left_index + 1] = _linear("96", str(left_price - _ONE), left_index + 1)
    elif pretrend == "downtrend_rebound":
        closes[:left_index] = _linear("99", "75", left_index)
        closes[left_index] = left_price - _ONE
    else:
        raise ValueError(f"unknown pretrend: {pretrend}")
    closes[left_index : bottom_index + 1] = _linear(
        str(left_price - _ONE), str(bottom_price + _ONE), bottom_index - left_index + 1
    )
    closes[bottom_index : right_index + 1] = _linear(
        str(bottom_price + _ONE), str(right_price - _ONE), right_index - bottom_index + 1
    )
    zone_top = bottom_price + (left_price + right_price) / Decimal("8") - bottom_price / Decimal("4")
    if midline_crossings == 4:
        midline = bottom_price + ((left_price + right_price) / 2 - bottom_price) / 2
        regions = (
            (left_index, left_index + 3, Decimal("2")),
            (left_index + 4, left_index + 7, Decimal("-2")),
            (left_index + 8, bottom_index - 3, Decimal("2")),
            (bottom_index - 2, bottom_index + 2, Decimal("-2")),
            (bottom_index + 3, right_index, Decimal("2")),
        )
        for start, end, delta in regions:
            for index in range(start, end + 1):
                closes[index] = midline + delta
        closes[left_index] = left_price - _ONE
    elif midline_crossings is not None:
        raise ValueError("only the documented four-crossing score fixture is supported")
    half_span = bottom_span // 2
    span_start = bottom_index - half_span
    span_end = bottom_index + half_span
    for index in range(span_start, span_end + 1):
        if 0 <= index <= last_index:
            closes[index] = bottom_price + _ONE
    if span_start > 0:
        closes[span_start - 1] = zone_top + Decimal("1")
    if span_end < last_index:
        closes[span_end + 1] = zone_top + Decimal("1")
    if wide_crossings:
        midline = bottom_price + ((left_price + right_price) / 2 - bottom_price) / 2
        for offset, index in enumerate(range(left_index + 2, right_index - 1)):
            closes[index] = midline + (Decimal("2") if offset % 2 == 0 else Decimal("-2"))
        closes[bottom_index] = bottom_price + _ONE
    closes[right_index] = right_price - _ONE
    if handle_index > right_index:
        closes[right_index : handle_index + 1] = _linear(
            str(right_price - _ONE), str(handle_price + _ONE), handle_index - right_index + 1
        )
    if handle_confirmed_index > handle_index:
        closes[handle_index : handle_confirmed_index + 1] = _linear(
            str(handle_price + _ONE),
            str(min(right_price - _ONE, handle_price + Decimal("5"))),
            handle_confirmed_index - handle_index + 1,
        )
    pivot_specs = (
        (
            CupPivotKind.HIGH,
            left_price,
            left_index,
            min(left_index + 3, bottom_index),
        ),
        (
            CupPivotKind.LOW,
            bottom_price,
            bottom_index,
            min(bottom_index + 3, right_index),
        ),
        (
            CupPivotKind.HIGH,
            right_price,
            right_index,
            min(right_index + 3, handle_index),
        ),
        (
            CupPivotKind.LOW,
            handle_price,
            handle_index,
            handle_confirmed_index,
        ),
    )
    for kind, price, _, confirmed in pivot_specs:
        if kind == CupPivotKind.HIGH and closes[confirmed] >= price:
            closes[confirmed] = price - Decimal("0.1")
        elif kind == CupPivotKind.LOW and closes[confirmed] <= price:
            closes[confirmed] = price + Decimal("0.1")

    pivot_atrs: dict[int, float] = {}
    for kind, price, at, confirmed in pivot_specs:
        reversal_distance = (
            price - closes[confirmed]
            if kind == CupPivotKind.HIGH
            else closes[confirmed] - price
        )
        pivot_atrs[at] = min(
            atr,
            float(reversal_distance / _PIVOT_REVERSAL) * 0.99,
        )

    volumes = [baseline_volume] * len(closes)
    for index in range(bottom_index + 1, right_index + 1):
        volumes[index] = right_volume
    for index in range(right_index + 1, handle_confirmed_index):
        volumes[index] = handle_volume
    bars = list(_bars(closes, volumes=volumes))
    snapshots = tuple(
        CupBarSnapshot(
            bar=bar,
            eligible_index=index,
            atr=pivot_atrs.get(index, atr),
        )
        for index, bar in enumerate(bars)
    )

    def pivot(kind: CupPivotKind, price: Decimal, at: int, confirmed: int) -> CupPivot:
        return CupPivot(
            kind=kind,
            price=price,
            pivot_at=bars[at].bar_end,
            confirmed_at=bars[confirmed].bar_end,
            pivot_index=at,
            confirmed_index=confirmed,
            atr_at_pivot=snapshots[at].atr,
        )

    pivots = tuple(pivot(*spec) for spec in pivot_specs)
    state = CupHandleStateValue(
        atr_state=WilderAtrState(
            count=len(bars), atr=atr, previous_close=bars[-1].close
        ),
        pivot_tracker=CupPivotTrackerState(
            leg="UP_LEG",
            extreme_high=snapshots[handle_confirmed_index],
            extreme_low=snapshots[handle_index],
            last_pivot=pivots[-1],
            eligible_index=last_index,
        ),
        eligible_bars=snapshots,
        confirmed_pivots=pivots,
        active_candidate=None,
        emitted_milestones=(),
        recent_terminal_candidate_ids=(),
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        eligible_started=True,
    )
    next_index = last_index + 1
    next_day = _START + timedelta(days=next_index)
    close = next_close if next_close is not None else right_price - _ONE
    next_bar = NewowDailyBar(
        product="rb",
        physical_contract="RB2701",
        segment_id="rb:RB2701:2026-01-01",
        trading_day=next_day,
        bar_end=datetime.combine(next_day, datetime.min.time(), tzinfo=UTC),
        open=close,
        high=close + _ONE,
        low=close - _ONE,
        close=close,
        volume=next_volume,
        open_interest=200,
        source_identity=f"fixture:RB2701:{next_index}",
        observation_eligible=True,
        completed=True,
    )
    return RestoredCupCase(state=state, next_bar=next_bar)
