from __future__ import annotations

import argparse


def test_alert_registry_is_htdy_only() -> None:
    from app.alerts.registry import alert_rule_definitions, get_alert_rule_definition

    assert [definition.rule_code for definition in alert_rule_definitions()] == [
        "htdy_original_15m"
    ]

    try:
        get_alert_rule_definition("subing_strategy_v1")
    except KeyError:
        pass
    else:
        raise AssertionError("retired SuBing Rule must not resolve")


def test_public_api_exposes_no_subing_routes() -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert not {
        "/api/v1/market/research/subing",
        "/api/v1/market/research/subing-daily-watch/current",
        "/api/v1/market/research/subing-strategy/historical",
        "/api/v1/market/research/subing-strategy/current",
        "/api/v1/market/research/subing-strategy/performance",
        "/api/alerts/strategy-actions/current",
    } & paths


def test_cli_has_no_research_domain() -> None:
    from app.guiyi_cli.main import build_parser

    parser = build_parser()
    domain_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(domain_action.choices) == {"data", "runtime"}


def test_alert_models_have_only_htdy_scope_and_event_fields() -> None:
    from app.alerts.models import AlertEvent, AlertRule

    assert "scope_products" not in AlertRule.__table__.columns
    assert "scope_product_frequencies" in AlertRule.__table__.columns
    assert "action_id" not in AlertEvent.__table__.columns
    assert "strategy_payload" not in AlertEvent.__table__.columns


def test_indicator_policies_expose_no_strategy_compatibility() -> None:
    from guiyi_quant.indicators import formal_policy_registry

    assert "fastapi_atr_wilder_first_tr_v1" not in formal_policy_registry
    assert all(
        consumer != "legacy_strategy_compatibility"
        for policy in formal_policy_registry.values()
        for consumer in policy.allowed_consumers
    )
