from __future__ import annotations

import pytest

from app.alerts.registry import (
    AlertRuleKind,
    alert_rule_definitions,
    get_alert_rule_definition,
)


def test_registry_has_exact_two_v2_rules() -> None:
    definitions = alert_rule_definitions()
    assert tuple(item.rule_code for item in definitions) == (
        "htdy_original_15m",
        "subing_entry_signal_v1",
    )

    htdy = get_alert_rule_definition("htdy_original_15m")
    assert htdy.display_name == "火天大有"
    assert htdy.kind is AlertRuleKind.INDICATOR_OBSERVATION
    assert htdy.input_frequencies == ("15m",)
    assert htdy.series_kind == "actual_dominant"

    subing = get_alert_rule_definition("subing_entry_signal_v1")
    assert subing.display_name == "苏冰入场信号"
    assert subing.kind is AlertRuleKind.FORMAL_SIGNAL
    assert subing.input_frequencies == ("5m", "15m")
    assert subing.series_kind == "actual_dominant"


def test_rule_lookup_normalizes_surrounding_whitespace() -> None:
    definition = get_alert_rule_definition("  subing_entry_signal_v1  ")

    assert definition.rule_code == "subing_entry_signal_v1"


def test_unknown_rule_definition_fails_closed() -> None:
    with pytest.raises(KeyError):
        get_alert_rule_definition("unknown_rule")
