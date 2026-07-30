from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = REPO_ROOT / "config" / "observation_plans.yaml"


def test_canonical_registry_loads_one_exact_read_only_plan() -> None:
    from app.services.observation_plans import ObservationPlanRegistry

    registry = ObservationPlanRegistry.from_file(PLAN_PATH)
    plan = registry.require_active_plan()

    assert registry.config_sha256 == sha256(PLAN_PATH.read_bytes()).hexdigest()
    assert registry.schema_version == 1
    assert len(registry.plans) == 1
    assert plan.plan_id == "jm_htdy_original_realtime_first_seen_v1"
    assert plan.enabled is True
    assert plan.product == "jm"
    assert plan.contract_selector == "dominant_rank1"
    assert plan.period == "15m"
    assert plan.strategy_code == "htdy_original_realtime_first_seen"
    assert plan.strategy_version == "v1.0"
    assert plan.trigger_policy == "realtime_first_seen"
    assert plan.purpose == "observation_only"
    assert plan.notification_enabled is False


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("product: jm", "product: rb", "OBSERVATION_PLAN_ACTIVE_CONTRACT_MISMATCH"),
        (
            "period: 15m",
            "period: 5m",
            "OBSERVATION_PLAN_ACTIVE_CONTRACT_MISMATCH",
        ),
        (
            "plan_id: su_bing_disabled_placeholder_v1\n    enabled: false",
            "plan_id: su_bing_disabled_placeholder_v1\n    enabled: true",
            "OBSERVATION_PLAN_ACTIVE_COUNT",
        ),
        (
            "notification:\n      enabled: false",
            "notification:\n      enabled: true",
            "OBSERVATION_PLAN_ACTIVE_CONTRACT_MISMATCH",
        ),
    ],
)
def test_registry_fail_closes_active_contract_drift(
    tmp_path: Path,
    old: str,
    new: str,
    reason: str,
) -> None:
    from app.services.observation_plans import ObservationPlanRegistry

    text = PLAN_PATH.read_text(encoding="utf-8")
    if old.startswith("plan_id: su_bing_disabled_placeholder_v1"):
        text += """
  - plan_id: su_bing_disabled_placeholder_v1
    enabled: false
    product: jm
    contract_selector: dominant_rank1
    period: 15m
    strategy:
      code: su_bing_placeholder
      version: v0
    trigger_policy: confirmed_close
    purpose: observation_only
    notification:
      enabled: false
"""
    assert old in text
    path = tmp_path / "plans.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ValueError, match=reason):
        ObservationPlanRegistry.from_file(path)


def test_registry_allows_disabled_placeholder_but_never_activates_it(
    tmp_path: Path,
) -> None:
    from app.services.observation_plans import ObservationPlanRegistry

    path = tmp_path / "plans.yaml"
    path.write_text(
        PLAN_PATH.read_text(encoding="utf-8")
        + """
  - plan_id: su_bing_disabled_placeholder_v1
    enabled: false
    product: jm
    contract_selector: dominant_rank1
    period: 15m
    strategy:
      code: su_bing_placeholder
      version: v0
    trigger_policy: confirmed_close
    purpose: observation_only
    notification:
      enabled: false
""",
        encoding="utf-8",
    )

    registry = ObservationPlanRegistry.from_file(path)

    assert len(registry.plans) == 2
    assert registry.require_active_plan().plan_id == (
        "jm_htdy_original_realtime_first_seen_v1"
    )
    placeholder = registry.get("su_bing_disabled_placeholder_v1")
    assert placeholder.enabled is False


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("schema_version: 2\nplans: []\n", "OBSERVATION_PLAN_SCHEMA_VERSION"),
        ("schema_version: 1\nplans: []\n", "OBSERVATION_PLAN_ACTIVE_COUNT"),
        (
            "schema_version: 1\nplans: not-a-list\n",
            "OBSERVATION_PLAN_PLANS_TYPE",
        ),
        (
            "schema_version: 1\nplans:\n  - enabled: true\n",
            "OBSERVATION_PLAN_FIELDS",
        ),
    ],
)
def test_registry_rejects_malformed_documents(
    tmp_path: Path,
    text: str,
    reason: str,
) -> None:
    from app.services.observation_plans import ObservationPlanRegistry

    path = tmp_path / "plans.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=reason):
        ObservationPlanRegistry.from_file(path)
