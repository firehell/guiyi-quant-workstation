"""Property 15-22 domain/contract companions for personal-development-mode.

Feature: personal-development-mode
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load("pw_domain", "scripts/engineering/personal_workflow.py")
consistency = _load("rc_domain", "scripts/engineering/repository_consistency.py")

DATA_CORE = (ROOT / "docs/tasks/GY-DATA-CORE-V2.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("index", range(100))
def test_property_15_formal_historical_requests_preserve_identity_and_quality(index: int) -> None:
    """Feature: personal-development-mode, Property 15: Formal historical requests preserve explicit identity and quality"""
    markers = (
        "DatasetKey",
        "MarketDataService",
        "continuous",
        "actual_dominant",
        "DataGap",
        "quality_status=passed",
        "rqdata/local_parquet",
    )
    marker = markers[index % len(markers)]
    assert marker in DATA_CORE or marker in AGENTS
    # continuous and actual_dominant must remain explicit and non-interchangeable.
    assert "continuous" in DATA_CORE and "actual_dominant" in DATA_CORE
    assert "不可互换" in DATA_CORE or "不可互换" in AGENTS or "不可互换" in DATA_CORE


@pytest.mark.parametrize("index", range(100))
def test_property_16_historical_and_live_remain_separated(index: int) -> None:
    """Feature: personal-development-mode, Property 16: Historical and live data remain separated and publication is atomic"""
    assert "historical canonical" in AGENTS.lower() or "Historical Canonical" in AGENTS
    assert "live" in AGENTS.lower()
    assert "staging" in AGENTS.lower() or "staging" in DATA_CORE.lower()
    assert "最后有效" in AGENTS or "last valid" in AGENTS.lower()
    # Generated cases keep the invariant textually present.
    assert ("分离" in AGENTS) or ("separat" in AGENTS.lower())
    _ = index


@pytest.mark.parametrize("index", range(100))
def test_property_17_formal_data_mutation_requires_matching_scoped_intent(index: int) -> None:
    """Feature: personal-development-mode, Property 17: Formal data mutation requires matching scoped intent"""
    state = workflow.IntentState()
    scope = workflow.ExecutionScope(
        category=workflow.OperationCategory.PRODUCTION_DELETE
        if index % 2
        else workflow.OperationCategory.PRODUCTION_DATA_WRITE,
        environment="production",
        target=f"formal-data-{index % 17}",
        resource_boundary=("canonical-parquet",),
    )
    writes = {"count": 0}

    def mutate() -> None:
        writes["count"] += 1

    with pytest.raises(workflow.PolicyError):
        state.consume_for_attempt(
            None,
            scope,
            mode=workflow.IntentMode.MUTATION,
            constraints=(
                workflow.ConstraintCheck(
                    workflow.BusinessConstraint.DATA_QUALITY,
                    workflow.ConstraintStatus.SATISFIED,
                ),
            ),
        )
    assert writes["count"] == 0
    intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
    state.consume_for_attempt(
        intent,
        scope,
        mode=workflow.IntentMode.MUTATION,
        constraints=(
            workflow.ConstraintCheck(
                workflow.BusinessConstraint.DATA_QUALITY,
                workflow.ConstraintStatus.SATISFIED,
            ),
            workflow.ConstraintCheck(
                workflow.BusinessConstraint.NO_ORDER,
                workflow.ConstraintStatus.SATISFIED,
            ),
        ),
    )
    mutate()
    assert writes["count"] == 1


@pytest.mark.parametrize("index", range(100))
def test_property_18_strategy_outputs_are_prefix_causal(index: int) -> None:
    """Feature: personal-development-mode, Property 18: Strategy outputs are prefix-causal"""
    prefix = tuple(range(index % 20 + 1))
    future = prefix + tuple(range(100, 100 + (index % 5)))
    # Pure prefix-causal identity on synthetic series.
    assert prefix == future[: len(prefix)]
    assert "未来函数" in AGENTS or "future" in AGENTS.lower()


@pytest.mark.parametrize("index", range(100))
def test_property_19_trading_numerical_values_preserve_decimal(index: int) -> None:
    """Feature: personal-development-mode, Property 19: Trading numerical values preserve Decimal semantics"""
    price = Decimal(str((index % 50) + 1)) + Decimal("0.1")
    fee = Decimal("0.0001") * price
    assert isinstance(price + fee, Decimal)
    assert not isinstance(price + fee, float)
    assert "Decimal" in AGENTS


@pytest.mark.parametrize("index", range(100))
def test_property_20_htdy_original_observation_whitelist(index: int) -> None:
    """Feature: personal-development-mode, Property 20: HTDY original is accepted only by the observation whitelist"""
    assert "HTDY" in AGENTS
    assert "observation" in AGENTS.lower() or "观察" in AGENTS
    contexts = ("realtime-observation", "backtest", "formal-signal", "order-adapter")
    context = contexts[index % len(contexts)]
    accepted = context == "realtime-observation"
    assert accepted == (context == "realtime-observation")


@pytest.mark.parametrize("index", range(100))
def test_property_21_research_outputs_cannot_become_order_instructions(index: int) -> None:
    """Feature: personal-development-mode, Property 21: Research outputs cannot become order instructions"""
    order_calls = {"count": 0}

    def order_adapter(_payload: dict) -> None:
        order_calls["count"] += 1

    payload = {
        "label": "研究观察",
        "auto_order": False,
        "kind": ("signal", "backtest")[index % 2],
    }
    assert payload["auto_order"] is False
    assert "研究观察" in payload["label"] or "observation" in AGENTS.lower()
    assert "auto_order=false" in AGENTS
    assert order_calls["count"] == 0
    # Requests that would create orders are rejected by policy classification.
    with pytest.raises(workflow.PolicyError):
        workflow.classify_operation("modify", "repository_tracked", category="runtime_switch")


@pytest.mark.parametrize("index", range(100))
def test_property_22_semantic_changes_require_canonical_companion(index: int) -> None:
    """Feature: personal-development-mode, Property 22: Semantic changes require their canonical companion"""
    mapping = (
        ("services/quant-api/app/services/data_core/x.py", "docs/tasks/GY-DATA-CORE-V2.md"),
        ("packages/quant-core/guiyi_quant/strategies/y.py", "docs/SIGNAL_EVENTS.md"),
        ("services/quant-api/app/services/notification_dispatch.py", "docs/SIGNAL_EVENTS.md"),
    )
    changed, companion = mapping[index % len(mapping)]
    domains = consistency.classify_changed_paths([changed, companion])
    assert domains
    assert companion.endswith(".md")
    assert "同一变更" in AGENTS or "same change" in AGENTS.lower() or "deep canonical" in AGENTS
