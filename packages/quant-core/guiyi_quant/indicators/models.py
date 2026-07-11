from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal


IndicatorStatus = Literal["draft", "observation_only", "validated", "deprecated"]
RepaintingRisk = Literal["none", "unknown", "known"]
SeedPolicy = Literal["sma_window", "first_value"]
HistogramScale = Literal[1, 2]
AtrSmoothingPolicy = Literal["wilder_sma_seed", "wilder_first_tr", "ema_first_tr"]


def parameters_hash(parameters: dict[str, Any]) -> str:
    """Return a stable short hash for indicator parameters."""

    payload = json.dumps(parameters, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class IndicatorPoint:
    bar_end: str | None
    value: float | None
    ready: bool
    valid: bool
    reason: str | None = None


@dataclass(frozen=True)
class IndicatorSeries:
    indicator_code: str
    indicator_version: str
    parameters: dict[str, Any]
    parameters_hash: str
    points: list[IndicatorPoint]
    repainting_risk: RepaintingRisk
    calculation_basis: dict[str, Any]


@dataclass(frozen=True)
class MacdSeries:
    indicator_code: str
    indicator_version: str
    parameters: dict[str, Any]
    parameters_hash: str
    dif: IndicatorSeries
    dea: IndicatorSeries
    histogram: IndicatorSeries
    repainting_risk: RepaintingRisk
    calculation_basis: dict[str, Any]


@dataclass(frozen=True)
class IndicatorDefinition:
    indicator_code: str
    indicator_version: str
    display_name: str
    display_type: Literal["overlay", "marker", "subpane"]
    input_fields: tuple[str, ...]
    supported_intervals: tuple[str, ...]
    default_parameters: dict[str, Any]
    lookback_bars: int
    warmup_bars: int
    calculation_source: str
    closed_bar_only: bool
    status: IndicatorStatus
    repainting_risk: RepaintingRisk
    repainting_notes: str
    web_capable: bool
    backtest_capable: bool
    live_capable: bool
    alert_capable: bool
    default_visible: bool
    default_color: str
    output_schema: Literal["value", "signal_state", "channel"]
