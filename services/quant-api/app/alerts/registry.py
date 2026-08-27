"""Code-defined Alert rule metadata.

The registry is intentionally static: database rows hold enablement and scope,
while rule semantics remain defined and reviewed in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


class AlertRuleKind(StrEnum):
    """Supported Alert V2 rule behavior categories."""

    INDICATOR_OBSERVATION = "indicator_observation"
    STRATEGY_ACTION = "strategy_action"


HTDY_ALERT_RULE_CODE: Final[Literal["htdy_original_15m"]] = "htdy_original_15m"
SUBING_STRATEGY_RULE_CODE: Final[Literal["subing_strategy_v1"]] = (
    "subing_strategy_v1"
)


@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    """Immutable metadata required to route one code-defined Alert rule."""

    rule_code: str
    display_name: str
    kind: AlertRuleKind
    input_frequencies: tuple[str, ...]
    series_kind: str


HTDY_RULE = AlertRuleDefinition(
    # Legacy stable database identity; the suffix no longer defines capability.
    rule_code=HTDY_ALERT_RULE_CODE,
    display_name="火天大有",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    input_frequencies=("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
    series_kind="actual_dominant",
)
SUBING_RULE = AlertRuleDefinition(
    rule_code=SUBING_STRATEGY_RULE_CODE,
    display_name="苏冰策略",
    kind=AlertRuleKind.STRATEGY_ACTION,
    input_frequencies=("1m", "5m", "15m"),
    series_kind="actual_dominant",
)

_ALERT_RULE_DEFINITIONS = (HTDY_RULE, SUBING_RULE)
_ALERT_RULE_DEFINITIONS_BY_CODE = {
    definition.rule_code: definition for definition in _ALERT_RULE_DEFINITIONS
}


def alert_rule_definitions() -> tuple[AlertRuleDefinition, ...]:
    """Return all supported rules in stable presentation order."""

    return _ALERT_RULE_DEFINITIONS


def get_alert_rule_definition(rule_code: str) -> AlertRuleDefinition:
    """Resolve a supported rule code or fail closed with ``KeyError``."""

    normalized = str(rule_code).strip()
    return _ALERT_RULE_DEFINITIONS_BY_CODE[normalized]
