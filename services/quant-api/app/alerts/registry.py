"""Static metadata for the single active HTDY Alert rule."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


class AlertRuleKind(StrEnum):
    INDICATOR_OBSERVATION = "indicator_observation"


HTDY_ALERT_RULE_CODE: Final[Literal["htdy_original_15m"]] = "htdy_original_15m"


@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    rule_code: str
    display_name: str
    kind: AlertRuleKind
    input_frequencies: tuple[str, ...]
    series_kind: str


HTDY_RULE = AlertRuleDefinition(
    rule_code=HTDY_ALERT_RULE_CODE,
    display_name="火天大有",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    input_frequencies=("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
    series_kind="actual_dominant",
)

_DEFINITIONS = (HTDY_RULE,)
_BY_CODE = {definition.rule_code: definition for definition in _DEFINITIONS}


def alert_rule_definitions() -> tuple[AlertRuleDefinition, ...]:
    return _DEFINITIONS


def get_alert_rule_definition(rule_code: str) -> AlertRuleDefinition:
    return _BY_CODE[str(rule_code).strip()]
