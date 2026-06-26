from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.vnpy_integration.errors import BacktestConfigurationError

ExecutionTiming = Literal["next_bar_open"]

DEFAULT_EXECUTION_TIMING: ExecutionTiming = "next_bar_open"
ALLOWED_EXECUTION_TIMINGS: frozenset[str] = frozenset({DEFAULT_EXECUTION_TIMING})


@dataclass(frozen=True)
class PendingSignalFill:
    signal_bar_index: int
    execution_bar_index: int
    execution_timing: ExecutionTiming
    direction: str
    reason: str


def validate_execution_timing(timing: str) -> ExecutionTiming:
    normalized = timing.strip()
    if normalized not in ALLOWED_EXECUTION_TIMINGS:
        allowed = ", ".join(sorted(ALLOWED_EXECUTION_TIMINGS))
        raise BacktestConfigurationError(f"execution_timing must be one of: {allowed}")
    return normalized  # type: ignore[return-value]


def signal_bar_index_to_fill_bar_index(signal_bar_index: int) -> int:
    """Completed-bar signal at index N must fill at bar N+1 open."""
    if signal_bar_index < 0:
        raise BacktestConfigurationError("signal_bar_index cannot be negative")
    return signal_bar_index + 1


def schedule_signal_fill(
    *,
    signal_bar_index: int,
    direction: str,
    reason: str,
    execution_timing: str = DEFAULT_EXECUTION_TIMING,
) -> PendingSignalFill:
    validated_timing = validate_execution_timing(execution_timing)
    return PendingSignalFill(
        signal_bar_index=signal_bar_index,
        execution_bar_index=signal_bar_index_to_fill_bar_index(signal_bar_index),
        execution_timing=validated_timing,
        direction=direction,
        reason=reason,
    )
