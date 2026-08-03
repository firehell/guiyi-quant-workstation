"""Versioned, fail-closed observation plan configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml


_DOCUMENT_FIELDS = frozenset({"schema_version", "plans"})
_PLAN_FIELDS = frozenset(
    {
        "plan_id",
        "enabled",
        "product",
        "contract_selector",
        "period",
        "strategy",
        "trigger_policy",
        "purpose",
        "notification",
    }
)
_STRATEGY_FIELDS = frozenset({"code", "version"})
_NOTIFICATION_FIELDS = frozenset({"enabled"})
_ACTIVE_CONTRACT = {
    "plan_id": "jm_htdy_original_realtime_first_seen_v1",
    "enabled": True,
    "product": "jm",
    "contract_selector": "dominant_rank1",
    "period": "15m",
    "strategy_code": "htdy_original_realtime_first_seen",
    "strategy_version": "v1.0",
    "trigger_policy": "realtime_first_seen",
    "purpose": "observation_only",
    "notification_enabled": False,
}


@dataclass(frozen=True)
class ObservationPlan:
    plan_id: str
    enabled: bool
    product: str
    contract_selector: str
    period: str
    strategy_code: str
    strategy_version: str
    trigger_policy: str
    purpose: str
    notification_enabled: bool


@dataclass(frozen=True)
class ObservationPlanRegistry:
    schema_version: int
    plans: tuple[ObservationPlan, ...]
    config_sha256: str
    _by_id: Mapping[str, ObservationPlan]

    @classmethod
    def from_file(cls, path: str | Path) -> ObservationPlanRegistry:
        config_path = Path(path)
        raw = config_path.read_bytes()
        try:
            document = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ValueError("OBSERVATION_PLAN_YAML_INVALID") from exc
        root = _require_mapping(document, "OBSERVATION_PLAN_DOCUMENT_TYPE")
        if set(root) != _DOCUMENT_FIELDS:
            raise ValueError("OBSERVATION_PLAN_DOCUMENT_FIELDS")
        schema_version = root["schema_version"]
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != 1
        ):
            raise ValueError("OBSERVATION_PLAN_SCHEMA_VERSION")
        raw_plans = root["plans"]
        if not isinstance(raw_plans, list):
            raise ValueError("OBSERVATION_PLAN_PLANS_TYPE")
        plans = tuple(_parse_plan(item) for item in raw_plans)
        by_id = {plan.plan_id: plan for plan in plans}
        if len(by_id) != len(plans):
            raise ValueError("OBSERVATION_PLAN_DUPLICATE_ID")
        active = tuple(plan for plan in plans if plan.enabled)
        if len(active) != 1:
            raise ValueError("OBSERVATION_PLAN_ACTIVE_COUNT")
        require_supported_observation_plan(active[0])
        return cls(
            schema_version=schema_version,
            plans=plans,
            config_sha256=sha256(raw).hexdigest(),
            _by_id=MappingProxyType(by_id),
        )

    def require_active_plan(self) -> ObservationPlan:
        active = tuple(plan for plan in self.plans if plan.enabled)
        if len(active) != 1:
            raise ValueError("OBSERVATION_PLAN_ACTIVE_COUNT")
        return require_supported_observation_plan(active[0])

    def get(self, plan_id: str) -> ObservationPlan:
        try:
            return self._by_id[plan_id]
        except KeyError as exc:
            raise ValueError("OBSERVATION_PLAN_NOT_FOUND") from exc


def require_supported_observation_plan(plan: ObservationPlan) -> ObservationPlan:
    if not isinstance(plan, ObservationPlan):
        raise ValueError("OBSERVATION_PLAN_TYPE")
    if not plan.enabled:
        raise ValueError("STRATEGY_ADAPTER_PLAN_DISABLED")
    actual = {
        field: getattr(plan, field)
        for field in _ACTIVE_CONTRACT
    }
    if actual != _ACTIVE_CONTRACT:
        raise ValueError("OBSERVATION_PLAN_ACTIVE_CONTRACT_MISMATCH")
    return plan


def _parse_plan(value: Any) -> ObservationPlan:
    plan = _require_mapping(value, "OBSERVATION_PLAN_FIELDS")
    if set(plan) != _PLAN_FIELDS:
        raise ValueError("OBSERVATION_PLAN_FIELDS")
    strategy = _require_mapping(plan["strategy"], "OBSERVATION_PLAN_STRATEGY_FIELDS")
    notification = _require_mapping(
        plan["notification"], "OBSERVATION_PLAN_NOTIFICATION_FIELDS"
    )
    if set(strategy) != _STRATEGY_FIELDS:
        raise ValueError("OBSERVATION_PLAN_STRATEGY_FIELDS")
    if set(notification) != _NOTIFICATION_FIELDS:
        raise ValueError("OBSERVATION_PLAN_NOTIFICATION_FIELDS")
    enabled = _require_bool(plan["enabled"], "OBSERVATION_PLAN_ENABLED_TYPE")
    notification_enabled = _require_bool(
        notification["enabled"], "OBSERVATION_PLAN_NOTIFICATION_ENABLED_TYPE"
    )
    return ObservationPlan(
        plan_id=_require_text(plan["plan_id"], "OBSERVATION_PLAN_ID_TYPE"),
        enabled=enabled,
        product=_require_text(plan["product"], "OBSERVATION_PLAN_PRODUCT_TYPE"),
        contract_selector=_require_text(
            plan["contract_selector"], "OBSERVATION_PLAN_CONTRACT_SELECTOR_TYPE"
        ),
        period=_require_text(plan["period"], "OBSERVATION_PLAN_PERIOD_TYPE"),
        strategy_code=_require_text(
            strategy["code"], "OBSERVATION_PLAN_STRATEGY_CODE_TYPE"
        ),
        strategy_version=_require_text(
            strategy["version"], "OBSERVATION_PLAN_STRATEGY_VERSION_TYPE"
        ),
        trigger_policy=_require_text(
            plan["trigger_policy"], "OBSERVATION_PLAN_TRIGGER_POLICY_TYPE"
        ),
        purpose=_require_text(plan["purpose"], "OBSERVATION_PLAN_PURPOSE_TYPE"),
        notification_enabled=notification_enabled,
    )


def _require_mapping(value: Any, reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ValueError(reason)
    return value


def _require_text(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(reason)
    return value


def _require_bool(value: Any, reason: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(reason)
    return value
