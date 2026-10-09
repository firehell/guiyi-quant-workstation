"""Public v3.3.79 oscillation experiments: separate marker and reference paths.

These are page-parity experiments, never executable fills or formal strategies.
The ordinary path intentionally allows HHV exit/re-entry on the same bar.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from math import floor

from .page_performance import _number, _sum_js

from .models import NewowDailyBar
from .oscillation_channel import (
    ChannelPoint,
    OscillationAction,
    OscillationScore,
    _signal,
)


class ExperimentKind(StrEnum):
    TEST1 = "osc-test"
    TEST2 = "osc-test2"
    TEST3 = "osc-test3"
    TEST4 = "osc-test4"

    @property
    def formula_version(self) -> str:
        return f"newow_{self.value.replace('-', '_')}_page_v3379_v1"


@dataclass(frozen=True, slots=True)
class ExperimentSignal:
    action: OscillationAction
    price: Decimal
    score: int
    break_label: str | None
    facts: OscillationScore
    formula_version: str
    stop_loss: bool = False
    confirm_exit: bool = False


@dataclass(frozen=True, slots=True)
class ExperimentState:
    highs: tuple[Decimal, ...] = ()
    lows: tuple[Decimal, ...] = ()
    closes: tuple[Decimal, ...] = ()
    volumes: tuple[int, ...] = ()
    history_count: int = 0
    index: int = -1
    previous_ma: Decimal | None = None
    earlier_ma: Decimal | None = None
    entry_price: Decimal | None = None
    target_price: Decimal | None = None
    sell_reference: Decimal | None = None
    sell_reference_index: int | None = None
    physical_contract: str | None = None
    segment_id: str | None = None
    product: str | None = None
    kind: str | None = None
    last_bar_end: str | None = None

    @property
    def holding(self) -> bool:
        return self.entry_price is not None


@dataclass(frozen=True, slots=True)
class ExperimentStepResult:
    state: ExperimentState
    channel: ChannelPoint | None
    signals: tuple[ExperimentSignal, ...]


def _validate_state(state: ExperimentState) -> None:
    if not isinstance(state, ExperimentState):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    windows = (state.highs, state.lows, state.closes, state.volumes)
    if not 0 <= state.history_count <= 10 or any(
        len(v) != state.history_count for v in windows
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if any(not isinstance(v, tuple) for v in windows):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if type(state.index) is not int or type(state.history_count) is not int:
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.index < -1 or (state.history_count == 0 and state != ExperimentState()):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    values = (
        *state.highs,
        *state.lows,
        *state.closes,
        state.previous_ma,
        state.earlier_ma,
        state.entry_price,
        state.target_price,
        state.sell_reference,
    )
    if any(
        v is not None and (not isinstance(v, Decimal) or not v.is_finite() or v <= 0)
        for v in values
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if any(type(v) is not int or v < 0 for v in state.volumes):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.history_count and (
        not state.product
        or not state.physical_contract
        or not state.segment_id
        or not state.last_bar_end
        or state.kind not in ExperimentKind
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.history_count and (
        state.history_count != min(state.index + 1, 10)
        or state.previous_ma is None
        or (state.index == 0) != (state.earlier_ma is None)
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if any(
        low > high or not low <= close <= high
        for low, high, close in zip(state.lows, state.highs, state.closes, strict=True)
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.last_bar_end:
        try:
            time = datetime.fromisoformat(state.last_bar_end)
        except (TypeError, ValueError) as exc:
            raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID") from exc
        if time.tzinfo is None or time.utcoffset() is None:
            raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if (state.sell_reference is None) != (state.sell_reference_index is None):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.sell_reference_index is not None and (
        not state.holding
        or type(state.sell_reference_index) is not int
        or state.kind != ExperimentKind.TEST4
        or not 0 <= state.sell_reference_index <= state.index
    ):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")
    if state.holding != (state.target_price is not None):
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID")


def restore_experiment_state(payload: Mapping[str, object]) -> ExperimentState:
    """Restore dataclass payload; corrupted checkpoints fail closed, never reset quietly."""
    try:
        state = ExperimentState(**dict(payload))
        _validate_state(state)
    except (TypeError, ValueError) as exc:
        raise ValueError("NEWOW_EXPERIMENT_STATE_INVALID") from exc
    return state


def step_experiment(
    state: ExperimentState,
    bar: NewowDailyBar,
    kind: ExperimentKind,
    *,
    path: str = "markers",
) -> ExperimentStepResult:
    kind = ExperimentKind(kind)
    _validate_state(state)
    if path not in ("markers", "ordinary"):
        raise ValueError("NEWOW_EXPERIMENT_PATH_INVALID")
    owner = (bar.product, bar.physical_contract, bar.segment_id)
    if (
        state.history_count
        and (state.product, state.physical_contract, state.segment_id) != owner
    ):
        state = ExperimentState()
    if state.kind is not None and state.kind != kind:
        raise ValueError("NEWOW_EXPERIMENT_KIND_MISMATCH")
    if state.last_bar_end and bar.bar_end <= datetime.fromisoformat(state.last_bar_end):
        raise ValueError("NEWOW_EXPERIMENT_BAR_ORDER_INVALID")
    highs, lows, closes, volumes = (
        (getattr(state, name) + (value,))[-10:]
        for name, value in (
            ("highs", bar.high),
            ("lows", bar.low),
            ("closes", bar.close),
            ("volumes", bar.volume),
        )
    )
    upper, lower = max(highs), min(lows)
    width = upper - lower
    channel = ChannelPoint(
        upper, lower, width, None if width == 0 else (bar.close - lower) / width, 10
    )
    n = replace(
        state,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        history_count=len(highs),
        index=state.index + 1,
        earlier_ma=state.previous_ma,
        previous_ma=Decimal(
            str(_sum_js(float(c) for c in reversed(closes)) / len(closes))
        ),
        product=bar.product,
        physical_contract=bar.physical_contract,
        segment_id=bar.segment_id,
        kind=kind.value,
        last_bar_end=bar.bar_end.isoformat(),
    )
    signals: list[ExperimentSignal] = []
    sold = False

    def emit(
        action: OscillationAction,
        price: Decimal,
        *,
        stop: bool = False,
        confirm: bool = False,
    ) -> None:
        if stop:
            facts = OscillationScore(0, 0, 0, 0, 0.0, 0.0, 0.0)
            signals.append(
                ExperimentSignal(
                    action, price, 0, None, facts, kind.formula_version, True
                )
            )
        else:
            scoring_channel = (
                replace(channel, upper=n.sell_reference) if confirm else channel
            )
            scored = _signal(bar, scoring_channel, volumes, action)
            signals.append(
                ExperimentSignal(
                    action,
                    price,
                    scored.score,
                    scored.break_label,
                    scored.facts,
                    kind.formula_version,
                    False,
                    confirm,
                )
            )

    def clear(price: Decimal, *, stop: bool = False, confirm: bool = False) -> None:
        nonlocal n, sold
        emit(OscillationAction.CLEAR, price, stop=stop, confirm=confirm)
        n = replace(
            n,
            entry_price=None,
            target_price=None,
            sell_reference=None,
            sell_reference_index=None,
        )
        sold = stop or confirm or path == "markers"

    if len(highs) == 10 and (path == "markers" or bar.observation_eligible):
        if n.holding:
            stop_price = Decimal(
                str(
                    float(n.entry_price)
                    * (1 - (0.12 if kind is ExperimentKind.TEST4 else 0.07))
                )
            )
            if bar.low <= stop_price:
                clear(min(stop_price, bar.open), stop=True)
        if n.holding:
            if kind is ExperimentKind.TEST4:
                if bar.high >= upper:
                    n = replace(
                        n, sell_reference=bar.close, sell_reference_index=n.index
                    )
                elif (
                    n.sell_reference is not None
                    and n.index > n.sell_reference_index
                    and bar.low <= n.sell_reference
                ):
                    clear(min(n.sell_reference, bar.open), confirm=True)
            elif bar.high >= (
                n.target_price if kind is ExperimentKind.TEST2 else upper
            ):
                clear(
                    max(n.target_price, bar.open)
                    if kind is ExperimentKind.TEST2
                    else bar.high
                )
        ma_ok = (
            state.previous_ma is not None
            and state.earlier_ma is not None
            and state.previous_ma > state.earlier_ma
        )
        if (
            not n.holding
            and not sold
            and bar.low <= lower
            and (kind is not ExperimentKind.TEST3 or ma_ok)
        ):
            emit(OscillationAction.BUILD, bar.low)
            n = replace(
                n,
                entry_price=bar.low,
                target_price=upper,
                sell_reference=None,
                sell_reference_index=None,
            )
    # Ineligible history warms formula state but is not a formal observed marker.
    return ExperimentStepResult(
        n,
        channel if len(highs) == 10 else None,
        tuple(signals) if bar.observation_eligible else (),
    )


def calculate_experiment_series(
    bars: tuple[NewowDailyBar, ...],
    kind: ExperimentKind,
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> tuple[ExperimentStepResult, ...]:
    state = ExperimentState()
    result = []
    for index, bar in enumerate(bars):
        if check_cancelled is not None and index % 256 == 0:
            check_cancelled()
        row = step_experiment(state, bar, kind)
        result.append(row)
        state = row.state
    if check_cancelled is not None:
        check_cancelled()
    return tuple(result)


def _reference(
    bars: tuple[NewowDailyBar, ...],
    kind: ExperimentKind | None,
    *,
    terminal_eligible: bool = True,
    check_cancelled: Callable[[], None] | None = None,
) -> dict[str, object] | None:
    if check_cancelled is not None:
        check_cancelled()
    if len(bars) < 11:
        return None
    if len({(b.product, b.physical_contract, b.segment_id) for b in bars}) != 1:
        raise ValueError("NEWOW_EXPERIMENT_REFERENCE_MIXED_SEGMENT")
    if any(a.bar_end >= b.bar_end for a, b in zip(bars, bars[1:])):
        raise ValueError("NEWOW_EXPERIMENT_BAR_ORDER_INVALID")
    state = ExperimentState()
    entry: tuple[int, Decimal] | None = None
    peak_high = Decimal(0)
    trades: list[dict[str, object]] = []
    dates, equity = [], []
    cumulative = peak = drawdown = 0.0
    wins = 0

    def close(
        i: int,
        price: Decimal,
        stop: bool = False,
        confirm: bool = False,
        force: bool = False,
    ) -> None:
        nonlocal entry, cumulative, wins, drawdown
        start, purchase = entry
        pct = (float(price) - float(purchase)) / float(purchase) * 100
        cumulative += pct
        wins += int(pct > 0)
        if kind is None:
            drawdown = max(drawdown, -pct)
        trades.append(
            {
                "entry_index": start,
                "exit_index": i,
                "entry_bar_end": bars[start].bar_end.isoformat(),
                "exit_bar_end": bars[i].bar_end.isoformat(),
                "entry_reference_price": _number(float(purchase), 2),
                "exit_reference_price": _number(float(price), 2),
                "return_percentage_points": _number(pct, 2),
                "physical_contract": bars[i].physical_contract,
                "segment_id": bars[i].segment_id,
                "stop_loss": stop,
                "confirm_exit": confirm,
                "force_close": force,
            }
        )
        entry = None

    for i, bar in enumerate(bars):
        if check_cancelled is not None and i % 256 == 0:
            check_cancelled()
        if kind is not None:
            row = step_experiment(state, bar, kind, path="ordinary")
            state = row.state
            for signal in row.signals:
                if signal.action is OscillationAction.BUILD:
                    entry = (i, signal.price)
                else:
                    close(i, signal.price, signal.stop_loss, signal.confirm_exit)
        else:
            window = bars[max(0, i - 9) : i + 1]
            if i >= 9 and bar.observation_eligible:
                high = max(b.high for b in window)
                low = min(b.low for b in window)
                if entry is None and bar.low <= low:
                    entry = (i, bar.low)
                    peak_high = high
                if entry is not None:
                    peak_high = max(peak_high, high)
                    if bar.high >= high:
                        close(i, peak_high)
        if i >= 9 and bar.observation_eligible:
            current = cumulative + (
                (float(bar.close) - float(entry[1])) / float(entry[1]) * 100
                if entry is not None and kind is not None
                else 0
            )
            if kind is not None:
                peak = max(peak, current)
                drawdown = max(drawdown, peak - current)
            dates.append(bar.bar_end.isoformat())
            equity.append(_number(current, 4))
    if (
        kind is not None
        and entry is not None
        and terminal_eligible
        and bars[-1].observation_eligible
    ):
        close(len(bars) - 1, bars[-1].close, force=True)
    count = len(trades)
    if check_cancelled is not None:
        check_cancelled()
    return {
        "model_version": "newow_oscillation_experiment_ordinary_v3379_v1"
        if kind
        else "newow_base_oscillation_ideal_v3379_v1",
        "page_parity": True,
        "executable": False,
        "hindsight": kind is None,
        "summary": {
            "cum_return_percentage_points": _number(cumulative, 2),
            "accuracy_pct": str(floor(wins / count * 100 + 0.5)) if count else "0",
            "max_drawdown_percentage_points": _number(drawdown, 2),
            "trade_count": count,
        },
        "dates": dates,
        "equity": equity,
        "trades": trades,
    }


def run_experiment_reference(
    bars: tuple[NewowDailyBar, ...],
    kind: ExperimentKind,
    *,
    terminal_eligible: bool = True,
    check_cancelled: Callable[[], None] | None = None,
) -> dict[str, object] | None:
    return _reference(
        bars,
        ExperimentKind(kind),
        terminal_eligible=terminal_eligible,
        check_cancelled=check_cancelled,
    )


def run_base_oscillation_ideal(
    bars: tuple[NewowDailyBar, ...],
    *,
    check_cancelled: Callable[[], None] | None = None,
) -> dict[str, object] | None:
    """All four experimental theoretical tabs use this same basic, no-stop path."""
    return _reference(bars, None, check_cancelled=check_cancelled)
