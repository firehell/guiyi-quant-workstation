from __future__ import annotations

import pytest

from app.alerts.registry import (
    AlertEventMode,
    AlertRuleKind,
    SUBING_THS_ALERT_RULE_CODE,
    alert_rule_definitions,
    get_alert_rule_definition,
)


def test_registry_contains_htdy_and_subing_ths_with_distinct_event_modes() -> None:
    definitions = alert_rule_definitions()
    assert tuple(item.rule_code for item in definitions) == (
        "htdy_original_15m",
        SUBING_THS_ALERT_RULE_CODE,
    )
    htdy, subing = definitions
    assert htdy.display_name == "火天大有"
    assert htdy.kind is AlertRuleKind.INDICATOR_OBSERVATION
    assert htdy.event_mode is AlertEventMode.FIRST_SEEN
    assert htdy.input_frequencies == (
        "1m", "5m", "15m", "30m", "60m", "1d", "1w"
    )
    assert htdy.series_kind == "actual_dominant"
    assert subing.display_name == "苏冰预警"
    assert subing.kind is AlertRuleKind.INDICATOR_OBSERVATION
    assert subing.event_mode is AlertEventMode.EXACT
    assert subing.input_frequencies == ("15m",)
    assert subing.series_kind == "actual_dominant"


def test_registry_lookup_strips_whitespace_and_rejects_unknown() -> None:
    assert get_alert_rule_definition(" htdy_original_15m ").rule_code == (
        "htdy_original_15m"
    )
    with pytest.raises(KeyError):
        get_alert_rule_definition("future_rule")
