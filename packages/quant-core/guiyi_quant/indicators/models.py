from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal


IndicatorStatus = Literal[
    "draft",
    "compatibility_validated",
    "validated",
    "strategy_candidate",
    "live_candidate",
    "alert_capable",
    "observation_only",
    "retired",
]
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
class FormalPolicy:
    policy_id: str
    indicator_family: str
    seed_policy: SeedPolicy | None
    smoothing_policy: AtrSmoothingPolicy | None
    histogram_scale: HistogramScale | None
    lookback: str
    confirmed_only: bool
    frozen_legacy: bool
    allowed_consumers: tuple[str, ...]
    blocked_consumers: tuple[str, ...]
    notes: str = ""


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
    formal_policy_id: str
    confirmed_only: bool
    seed_policy: SeedPolicy | None = None
    smoothing_policy: AtrSmoothingPolicy | None = None
    histogram_scale: HistogramScale | None = None

    def __post_init__(self) -> None:
        validate_definition_capabilities(self)


def validate_definition_capabilities(definition: IndicatorDefinition) -> None:
    """Raise ValueError when lifecycle status conflicts with capability flags."""

    status = definition.status
    if definition.confirmed_only != definition.closed_bar_only:
        raise ValueError("confirmed_only must match closed_bar_only")

    if status in {"draft", "compatibility_validated"}:
        if definition.backtest_capable or definition.live_capable or definition.alert_capable:
            raise ValueError(f"{status} cannot be backtest/live/alert capable")
    elif status == "observation_only":
        if definition.backtest_capable or definition.live_capable or definition.alert_capable:
            raise ValueError("observation_only cannot be backtest/live/alert capable")
    elif status == "strategy_candidate":
        if not definition.backtest_capable:
            raise ValueError("strategy_candidate requires backtest_capable=True")
        if not definition.confirmed_only or definition.repainting_risk != "none":
            raise ValueError("strategy_candidate must be confirmed_only with repainting_risk=none")
        if definition.live_capable or definition.alert_capable:
            raise ValueError("strategy_candidate cannot be live/alert capable")
    elif status == "validated":
        if definition.repainting_risk != "none":
            raise ValueError("validated indicators must have repainting_risk=none")
        if not definition.confirmed_only:
            raise ValueError("validated indicators must be confirmed_only")
    elif status == "alert_capable":
        if not definition.confirmed_only or definition.repainting_risk != "none":
            raise ValueError("alert_capable must be confirmed_only with repainting_risk=none")
        if not definition.live_capable or not definition.alert_capable:
            raise ValueError("status=alert_capable requires live_capable=True and alert_capable=True")
    elif status == "live_candidate":
        if not definition.confirmed_only or definition.repainting_risk != "none":
            raise ValueError("live_candidate must be confirmed_only with repainting_risk=none")
        if not definition.live_capable:
            raise ValueError("status=live_candidate requires live_capable=True")
        if definition.alert_capable:
            raise ValueError("live_candidate cannot be alert capable")
    elif status == "retired":
        if (
            definition.web_capable
            or definition.backtest_capable
            or definition.live_capable
            or definition.alert_capable
        ):
            raise ValueError("retired indicators cannot expose any consumer capability")


def definition_to_metadata(definition: IndicatorDefinition) -> dict[str, Any]:
    """Serialize registry definition for future report metadata persistence."""

    payload = asdict(definition)
    payload["inputs"] = list(definition.input_fields)
    payload["parameters"] = dict(definition.default_parameters)
    return payload


def build_indicator_definition(**kwargs: Any) -> IndicatorDefinition:
    """Construct and validate an IndicatorDefinition."""

    if "confirmed_only" not in kwargs and "closed_bar_only" in kwargs:
        kwargs["confirmed_only"] = kwargs["closed_bar_only"]
    if "closed_bar_only" not in kwargs and "confirmed_only" in kwargs:
        kwargs["closed_bar_only"] = kwargs["confirmed_only"]
    return IndicatorDefinition(**kwargs)
