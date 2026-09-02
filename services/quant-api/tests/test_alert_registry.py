from __future__ import annotations

import pytest

from app.alerts.registry import (
    AlertRuleKind,
    alert_rule_definitions,
    get_alert_rule_definition,
)


def test_registry_contains_only_htdy() -> None:
    definitions = alert_rule_definitions()
    assert tuple(item.rule_code for item in definitions) == ("htdy_original_15m",)
    rule = definitions[0]
    assert rule.display_name == "火天大有"
    assert rule.kind is AlertRuleKind.INDICATOR_OBSERVATION
    assert rule.input_frequencies == (
        "1m", "5m", "15m", "30m", "60m", "1d", "1w"
    )
    assert rule.series_kind == "actual_dominant"


def test_registry_lookup_strips_whitespace_and_rejects_unknown() -> None:
    assert get_alert_rule_definition(" htdy_original_15m ").rule_code == (
        "htdy_original_15m"
    )
    with pytest.raises(KeyError):
        get_alert_rule_definition("future_rule")
