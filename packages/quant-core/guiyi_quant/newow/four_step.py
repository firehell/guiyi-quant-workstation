"""Day-only four-step page replay from ordered, same-owner source actions."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Literal

MODEL_VERSION = "newow_dual_four_step_page_v1"
FUTURES_ADAPTER_VERSION = "guiyi_newow_four_step_segment_valuation_v1"
PAGE_SOURCE_SHA256 = "487a23ba40dcba03918ed76fe48187d8d7f1cf8ea692c44b4bd58be636e39e7b"
PAGE_MIN_BARS = 60


@dataclass(frozen=True, slots=True)
class FourStepEvent:
    index: int
    source: Literal["oscillation", "trend"]
    kind: Literal["BUILD", "CLEAR"]
    reference_price: Decimal
    sequence: int = 0

    @property
    def order(self) -> tuple[int, bool, bool, int]:
        return (self.index, self.kind == "BUILD", self.source == "trend", self.sequence)


@dataclass(frozen=True, slots=True)
class FourStepTrade:
    entry_index: int
    exit_index: int
    return_pct: Decimal
    reason: str
    has_trend_leg: bool


@dataclass(frozen=True, slots=True)
class FourStepReplay:
    trades: tuple[FourStepTrade, ...]
    page_baseline: tuple[FourStepTrade, ...]


@dataclass(frozen=True, slots=True)
class FourStepSummary:
    trade_count: int
    win_rate: int
    average_return_pct: Decimal
    worst_return_pct: Decimal
    average_holding_bars: int
    trend_leg_count: int
    trend_exit_count: int
    terminal_valuation_count: int


def fold_four_step(
    bar_count: int, terminal_price: Decimal, events: Iterable[FourStepEvent], *,
    minimum_bars: int = PAGE_MIN_BARS,
) -> FourStepReplay:
    if bar_count < minimum_bars:
        return FourStepReplay((), ())
    if not terminal_price.is_finite() or terminal_price <= 0:
        raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
    opened: FourStepEvent | None = None
    added: FourStepEvent | None = None
    baseline: FourStepEvent | None = None
    trades: list[FourStepTrade] = []
    control: list[FourStepTrade] = []

    def close(index: int, price: Decimal, reason: str) -> None:
        nonlocal opened, added, baseline
        if opened is not None:
            legs = (opened,) if added is None else (opened, added)
            result = sum((price / leg.reference_price - 1 for leg in legs), Decimal(0))
            trades.append(FourStepTrade(opened.index, index, result * 100 / len(legs), reason, added is not None))
            opened = added = None
        if baseline is not None:
            result = (price / baseline.reference_price - 1) * 100
            control.append(FourStepTrade(baseline.index, index, result, reason, False))
            baseline = None

    for event in sorted(events, key=lambda item: item.order):
        price = event.reference_price
        if not 0 <= event.index < bar_count or not price.is_finite() or price <= 0:
            continue
        if event.kind == "CLEAR":
            # Both page arms receive trend exits, despite the source card's baseline label.
            close(event.index, price, "TREND_CLEAR" if event.source == "trend" else "OSCILLATION_CLEAR")
        elif event.source == "oscillation":
            if opened is None:
                opened = baseline = event
        elif opened is not None and added is None:
            added = event
    close(bar_count - 1, terminal_price, "TERMINAL_VALUATION")
    return FourStepReplay(tuple(trades), tuple(control))


def summarize_four_step(trades: Iterable[FourStepTrade]) -> FourStepSummary | None:
    rows = tuple(trades)
    if not rows:
        return None
    n = len(rows)

    def rounded(value: Decimal, step: str) -> Decimal:
        return value.quantize(Decimal(step), rounding=ROUND_HALF_UP)

    return FourStepSummary(
        n, int(rounded(Decimal(sum(row.return_pct > 0 for row in rows)) * 100 / n, "1")),
        rounded(sum((row.return_pct for row in rows), Decimal(0)) / n, ".01"),
        rounded(min(row.return_pct for row in rows), ".01"),
        int(rounded(Decimal(sum(row.exit_index - row.entry_index for row in rows)) / n, "1")),
        sum(row.has_trend_leg for row in rows), sum(row.reason == "TREND_CLEAR" for row in rows),
        sum(row.reason == "TERMINAL_VALUATION" for row in rows),
    )
