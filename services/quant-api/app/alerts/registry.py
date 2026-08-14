"""Code-defined Alert rule metadata.

The registry is intentionally static: database rows hold enablement and scope,
while rule semantics remain defined and reviewed in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AlertRuleKind(StrEnum):
    """Supported Alert V2 rule behavior categories."""

    INDICATOR_OBSERVATION = "indicator_observation"
    FORMAL_SIGNAL = "formal_signal"


@dataclass(frozen=True, slots=True)
class AlertRuleDefinition:
    """Immutable metadata required to route one code-defined Alert rule."""

    rule_code: str
    display_name: str
    kind: AlertRuleKind
    input_frequencies: tuple[str, ...]
    series_kind: str


HTDY_RULE = AlertRuleDefinition(
    rule_code="htdy_original_15m",
    display_name="火天大有",
    kind=AlertRuleKind.INDICATOR_OBSERVATION,
    input_frequencies=("15m",),
    series_kind="actual_dominant",
)
SUBING_RULE = AlertRuleDefinition(
    rule_code="subing_entry_signal_v1",
    display_name="苏冰入场信号",
    kind=AlertRuleKind.FORMAL_SIGNAL,
    input_frequencies=("5m", "15m"),
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
