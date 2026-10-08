"""Static metadata for Alert Runtime rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


class AlertRuleKind(StrEnum):
    INDICATOR_OBSERVATION = "indicator_observation"


class AlertEventMode(StrEnum):
    FIRST_SEEN = "first_seen"
    EXACT = "exact"


HTDY_ALERT_RULE_CODE: Final[Literal["htdy_original_15m"]] = "htdy_original_15m"
SUBING_THS_ALERT_RULE_CODE: Final[Literal["subing_ths_alert_15m_v1"]] = (
    "subing_ths_alert_15m_v1"
)


@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    rule_code: str
    display_name: str
    kind: AlertRuleKind
    event_mode: AlertEventMode
    input_frequencies: tuple[str, ...]
    series_kind: str
    notification_enabled: bool = True


HTDY_RULE = AlertRuleDefinition(
    rule_code=HTDY_ALERT_RULE_CODE,
    display_name="火天大有",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    event_mode=AlertEventMode.FIRST_SEEN,
    input_frequencies=("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
    series_kind="actual_dominant",
)

SUBING_SIGNAL_FREQUENCIES = ("5m", "15m", "30m", "60m", "1d", "1w")
SUBING_FORMULA_VERSIONS = {
    "5m": "subing_ths_5m_v1", "15m": "subing_ths_15m_v3",
    "30m": "subing_ths_30m_v1", "60m": "subing_ths_60m_v1",
    "1d": "subing_ths_1d_v1", "1w": "subing_ths_1w_v1",
}

SUBING_THS_RULE = AlertRuleDefinition(
    rule_code=SUBING_THS_ALERT_RULE_CODE,
    display_name="苏冰预警",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    event_mode=AlertEventMode.EXACT,
    input_frequencies=SUBING_SIGNAL_FREQUENCIES,
    series_kind="actual_dominant",
    notification_enabled=False,
)

_DEFINITIONS = (HTDY_RULE, SUBING_THS_RULE)
_BY_CODE = {definition.rule_code: definition for definition in _DEFINITIONS}


def alert_rule_definitions() -> tuple[AlertRuleDefinition, ...]:
    return _DEFINITIONS


def get_alert_rule_definition(rule_code: str) -> AlertRuleDefinition:
    return _BY_CODE[str(rule_code).strip()]
