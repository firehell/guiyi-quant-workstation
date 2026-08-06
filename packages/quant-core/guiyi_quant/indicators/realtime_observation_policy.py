"""Fail-closed identity policy for the HTDY repainting observation pilot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RealtimeRepaintingObservationPolicy:
    policy_id: str = "htdy_original_xma_15m_first_seen_v1"
    strategy_code: str = "htdy_original_realtime_first_seen"
    strategy_version: str = "v1.0"
    indicator_code: str = "huotian_dayou_original_v0"
    indicator_version: str = "original-v0"
    product: str = "jm"
    contract_mode: str = "actual_rank1"
    main_contract_rank: int = 1
    period: str = "15m"
    source_mode: str = "live_realtime_repainting"
    detection_mode: str = "first_seen"
    partial_allowed: bool = True
    future_looking: bool = True
    repainting_accepted: bool = True
    first_seen_no_retraction: bool = True
    historical_backtest_allowed: bool = False
    auto_order: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClosedBarRealtimeObservationPolicy:
    """Closed-bar observation policy: evaluate only a confirmed 15m close."""

    policy_id: str = "htdy_original_xma_15m_close_first_seen_v1"
    strategy_code: str = "htdy_original_realtime_first_seen"
    strategy_version: str = "v1.1"
    indicator_code: str = "huotian_dayou_original_v0"
    indicator_version: str = "original-v0"
    product: str = "jm"
    contract_mode: str = "actual_rank1"
    main_contract_rank: int = 1
    period: str = "15m"
    source_mode: str = "live_realtime_repainting"
    detection_mode: str = "first_seen"
    decision_trigger: str = "confirmed_15m_close"
    partial_allowed: bool = False
    future_looking: bool = True
    repainting_accepted: bool = True
    first_seen_no_retraction: bool = True
    historical_backtest_allowed: bool = False
    auto_order: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CANONICAL_POLICY = RealtimeRepaintingObservationPolicy()
_CANONICAL_FIELDS = _CANONICAL_POLICY.to_dict()
_CLOSED_BAR_POLICY = ClosedBarRealtimeObservationPolicy()
_CLOSED_BAR_FIELDS = _CLOSED_BAR_POLICY.to_dict()


def require_realtime_repainting_observation_policy(
    raw: Mapping[str, Any] | RealtimeRepaintingObservationPolicy | None,
) -> RealtimeRepaintingObservationPolicy:
    """Return the frozen policy only when every identity and safety field matches."""

    if raw is None:
        raise ValueError("REALTIME_REPAINTING_OBSERVATION_POLICY_INVALID: policy is required")
    payload = raw.to_dict() if isinstance(raw, RealtimeRepaintingObservationPolicy) else dict(raw)
    if set(payload) != set(_CANONICAL_FIELDS):
        raise ValueError("REALTIME_REPAINTING_OBSERVATION_POLICY_INVALID: fields must exactly match frozen policy")
    for field, expected in _CANONICAL_FIELDS.items():
        if payload[field] != expected or type(payload[field]) is not type(expected):
            raise ValueError(f"REALTIME_REPAINTING_OBSERVATION_POLICY_INVALID: {field} drifted")
    return _CANONICAL_POLICY


def realtime_observation_policy_sha256() -> str:
    """Hash the canonical UTF-8 JSON representation of the frozen policy."""

    canonical = json.dumps(_CANONICAL_FIELDS, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def require_closed_bar_realtime_observation_policy(
    raw: Mapping[str, Any] | ClosedBarRealtimeObservationPolicy | None,
) -> ClosedBarRealtimeObservationPolicy:
    if raw is None:
        raise ValueError("CLOSED_BAR_REALTIME_OBSERVATION_POLICY_INVALID: policy is required")
    payload = raw.to_dict() if isinstance(raw, ClosedBarRealtimeObservationPolicy) else dict(raw)
    if set(payload) != set(_CLOSED_BAR_FIELDS):
        raise ValueError("CLOSED_BAR_REALTIME_OBSERVATION_POLICY_INVALID: fields must exactly match frozen policy")
    for field, expected in _CLOSED_BAR_FIELDS.items():
        if payload[field] != expected or type(payload[field]) is not type(expected):
            raise ValueError(f"CLOSED_BAR_REALTIME_OBSERVATION_POLICY_INVALID: {field} drifted")
    return _CLOSED_BAR_POLICY


def closed_bar_observation_policy_sha256() -> str:
    canonical = json.dumps(
        _CLOSED_BAR_FIELDS,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
