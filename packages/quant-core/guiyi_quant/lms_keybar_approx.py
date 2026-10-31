"""Explicit keybar hypotheses; morphology and later observations, never decisions."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Iterable, Literal

from .lms405 import Bar

VERSION = 'lms-keybar-approx-v1'
INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class Frame:
    bar: Bar
    previous: Bar | None
    ibar: bool | None
    pinbar: Literal['LONG', 'SHORT'] | None
    body: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    rule_version: str = VERSION

    @property
    def bar_end(self) -> datetime:
        return self.bar.end

    @property
    def confirmed_at(self) -> datetime:
        return self.bar.end

    @property
    def has_pattern(self) -> bool:
        return self.ibar is True or self.pinbar is not None


@dataclass(frozen=True)
class NextCloseObservation:
    contract: str
    signal_bar_end: datetime
    observed_at: datetime
    signal_high: Decimal
    signal_low: Decimal
    next_close: Decimal
    close_above_high: bool
    close_below_low: bool
    rule_version: str = VERSION


def _check(bar: Bar) -> None:
    if not isinstance(bar, Bar):
        raise ValueError('BAR_REQUIRED')
    bar.__post_init__()
    if bar.completed is not True or bar.start is None or bar.end - bar.start != INTERVAL:
        raise ValueError('COMPLETED_5M_REQUIRED')


def _pair(previous: Bar, current: Bar) -> None:
    _check(previous)
    _check(current)
    if previous.contract != current.contract:
        raise ValueError('CONTRACT_BOUNDARY')
    if current.end <= previous.end or current.start < previous.end:
        raise ValueError('BAR_ORDER_OR_OVERLAP')


def classify(previous: Bar | None, current: Bar) -> Frame:
    """Confirm at current.end. Missing parent leaves ibar unknown, not false.

    Adjacent means adjacent supplied Bars; no mother-Bar search or active signal.
    This version accepts completed physical 5m Bars only. Session gaps are allowed;
    source coverage/session provenance remains the frozen export's responsibility.
    """
    _check(current)
    if previous is not None:
        _pair(previous, current)
    values = (current.open, current.high, current.low, current.close)
    # Exact subtraction and x3 even when the caller changes Decimal precision.
    precision = max(v.adjusted() for v in values) - min(v.as_tuple().exponent for v in values) + 4
    with localcontext() as ctx:
        ctx.prec = max(28, precision)
        body = abs(current.close - current.open)
        upper = current.high - max(current.open, current.close)
        lower = min(current.open, current.close) - current.low
        pinbar = None
        if body > 0:
            if lower >= 3 * body and upper <= body:
                pinbar = 'LONG'
            elif upper >= 3 * body and lower <= body:
                pinbar = 'SHORT'
    inside = None if previous is None else (
        current.high < previous.high and current.low > previous.low
    )
    return Frame(current, previous, inside, pinbar, body, upper, lower)


def observe_next(frame: Frame, signal: Bar, following: Bar) -> NextCloseObservation:
    """Observe the next supplied Bar at its own close, separately from morphology.

    Caller supplies the immediate next row, with no skipped rows. Crossed wicks
    imply neither intrabar ordering nor execution; only the close is compared.
    """
    _pair(signal, following)
    if frame != classify(frame.previous, signal) or not frame.has_pattern:
        raise ValueError('SIGNAL_FRAME_MISMATCH_OR_NO_PATTERN')
    return NextCloseObservation(
        signal.contract, signal.end, following.end, signal.high, signal.low,
        following.close, following.close > signal.high, following.close < signal.low,
    )


def replay(bars: Iterable[Bar]) -> tuple[list[Frame], list[NextCloseObservation]]:
    """Append-only frames/observations; a terminal signal has no observation yet."""
    frames, observations = [], []
    previous = None
    for current in bars:
        frame = classify(previous, current)
        if frames and frames[-1].has_pattern:
            observations.append(observe_next(frames[-1], previous, current))
        frames.append(frame)
        previous = current
    return frames, observations
