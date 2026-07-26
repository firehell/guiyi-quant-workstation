"""Pure schema-v3 authorization contracts for HTDY S6-08.

The builders and verifiers in this module perform no filesystem, database,
Runtime, scheduler, or notification actions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
import hashlib
import json
from typing import Any


SCHEMA_VERSION = 3
TASK_ID = "JM-LIVE-SIGNAL-EVENT-S6-08"
PARENT_PACKET_TYPE = "htdy_s6_08_bounded_parent"
CHILD_PACKET_TYPE = "htdy_s6_08_exact_daily_child"
CODE_GATE = "HTDY_S6_08_SCHEMA_V3_CODE_VERIFIED"
REQUIRED_DB_REVISION = "20260721_0025"
MAX_TRADING_DAYS = 5
STRATEGY_CODE = "htdy_original_realtime_first_seen"
STRATEGY_VERSION = "v1.0"
INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
SOURCE_MODE = "live_realtime_repainting"
SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"

HASH_BINDING_KEYS = frozenset(
    {
        "deployment_receipt_sha256",
        "s6_07_final_receipt_sha256",
        "service_bundle_sha256",
        "source_sha256",
        "policy_sha256",
        "writer_sha256",
    }
)
BINDING_KEYS = frozenset(
    {
        *HASH_BINDING_KEYS,
        "runtime_commit",
        "database_revision",
    }
)
COUNTER_KEYS = frozenset(
    {
        "strategy_signals",
        "signal_events",
        "signal_notifications",
        "signal_scan_tasks",
        "orders",
        "trades",
    }
)
FORBIDDEN_COUNTER_KEYS = (
    "signal_notifications",
    "signal_scan_tasks",
    "orders",
    "trades",
)


class HtDySchemaV3GateError(RuntimeError):
    """Raised when a schema-v3 packet or result fails closed."""


def canonical_packet_hash(packet: Mapping[str, Any]) -> str:
    payload = {
        str(key): deepcopy(value)
        for key, value in packet.items()
        if key != "packet_hash"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_parent_authorization(
    *,
    trading_days: Sequence[date],
    deployment_receipt_sha256: str,
    s6_07_final_receipt_sha256: str,
    service_bundle_sha256: str,
    runtime_commit: str,
    database_revision: str,
    source_sha256: str,
    policy_sha256: str,
    writer_sha256: str,
) -> dict[str, Any]:
    days = _trading_days(trading_days)
    bindings = {
        "deployment_receipt_sha256": deployment_receipt_sha256,
        "s6_07_final_receipt_sha256": s6_07_final_receipt_sha256,
        "service_bundle_sha256": service_bundle_sha256,
        "runtime_commit": runtime_commit,
        "database_revision": database_revision,
        "source_sha256": source_sha256,
        "policy_sha256": policy_sha256,
        "writer_sha256": writer_sha256,
    }
    _validate_bindings(bindings)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": PARENT_PACKET_TYPE,
        "task_id": TASK_ID,
        "authorization_mode": "bounded_parent_exact_daily_child",
        "trading_days": [item.isoformat() for item in days],
        "bindings": bindings,
        "strategy": _strategy_contract(),
        "event_contract": _event_contract(),
        "scope": _scope_contract(),
        "required_pre_state": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
            "old_schema_v2_authorization_active": False,
        },
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def verify_parent_authorization(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_bindings: Mapping[str, Any],
) -> None:
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise HtDySchemaV3GateError("schema_version_invalid")
    if (
        packet.get("packet_type") != PARENT_PACKET_TYPE
        or packet.get("task_id") != TASK_ID
        or packet.get("authorization_mode")
        != "bounded_parent_exact_daily_child"
    ):
        raise HtDySchemaV3GateError("parent_identity_invalid")
    _verify_hash(packet, approval_hash)
    _parse_packet_days(packet.get("trading_days"))
    if packet.get("strategy") != _strategy_contract():
        raise HtDySchemaV3GateError("strategy_contract_invalid")
    if packet.get("event_contract") != _event_contract():
        raise HtDySchemaV3GateError("event_contract_invalid")
    if packet.get("scope") != _scope_contract():
        raise HtDySchemaV3GateError("scope_contract_invalid")
    expected_pre_state = {
        "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
        "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        "old_schema_v2_authorization_active": False,
    }
    if packet.get("required_pre_state") != expected_pre_state:
        raise HtDySchemaV3GateError("pre_state_contract_invalid")
    bindings = packet.get("bindings")
    if not isinstance(bindings, Mapping):
        raise HtDySchemaV3GateError("bindings_invalid")
    _validate_bindings(bindings)
    if dict(current_bindings) != dict(bindings):
        raise HtDySchemaV3GateError("binding_drift")


def build_daily_child_authorization(
    *,
    parent_packet: Mapping[str, Any],
    parent_approval_hash: str,
    trading_day: date,
    actual_contract: str,
    mapping_sha256: str,
    baseline_counts: Mapping[str, int],
) -> dict[str, Any]:
    bindings = parent_packet.get("bindings")
    if not isinstance(bindings, Mapping):
        raise HtDySchemaV3GateError("parent_bindings_invalid")
    verify_parent_authorization(
        parent_packet,
        approval_hash=parent_approval_hash,
        current_bindings=bindings,
    )
    if not _plain_date(trading_day):
        raise HtDySchemaV3GateError("child_trading_day_invalid")
    authorized_days = _parse_packet_days(parent_packet.get("trading_days"))
    if trading_day not in authorized_days:
        raise HtDySchemaV3GateError("child_day_not_authorized")
    contract = _actual_contract(actual_contract)
    if not _sha256(mapping_sha256):
        raise HtDySchemaV3GateError("mapping_sha256_invalid")
    counts = _counts(baseline_counts)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": CHILD_PACKET_TYPE,
        "task_id": TASK_ID,
        "authorization_mode": "exact_daily_child",
        "parent_packet_hash": parent_approval_hash,
        "trading_day": trading_day.isoformat(),
        "product": "jm",
        "actual_contract": contract,
        "period": "15m",
        "mapping_sha256": mapping_sha256,
        "baseline_counts": counts,
        "event_contract": _event_contract(),
        "scope": _scope_contract(),
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def verify_daily_child_authorization(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    parent_packet: Mapping[str, Any],
    parent_approval_hash: str,
    current_trading_day: date,
    current_actual_contract: str,
    current_mapping_sha256: str,
    current_counts: Mapping[str, int],
) -> None:
    bindings = parent_packet.get("bindings")
    if not isinstance(bindings, Mapping):
        raise HtDySchemaV3GateError("parent_bindings_invalid")
    verify_parent_authorization(
        parent_packet,
        approval_hash=parent_approval_hash,
        current_bindings=bindings,
    )
    _validate_child_packet(packet, approval_hash)
    if packet.get("parent_packet_hash") != parent_approval_hash:
        raise HtDySchemaV3GateError("parent_packet_hash_mismatch")
    authorized_days = _parse_packet_days(parent_packet.get("trading_days"))
    try:
        packet_day = date.fromisoformat(str(packet.get("trading_day") or ""))
    except ValueError as exc:
        raise HtDySchemaV3GateError("child_trading_day_invalid") from exc
    if (
        packet_day not in authorized_days
        or not _plain_date(current_trading_day)
        or packet_day != current_trading_day
    ):
        raise HtDySchemaV3GateError("child_trading_day_drift")
    if (
        packet.get("actual_contract")
        != _actual_contract(current_actual_contract)
    ):
        raise HtDySchemaV3GateError("actual_contract_drift")
    if (
        not _sha256(current_mapping_sha256)
        or packet.get("mapping_sha256") != current_mapping_sha256
    ):
        raise HtDySchemaV3GateError("mapping_drift")
    if _counts(current_counts) != packet.get("baseline_counts"):
        raise HtDySchemaV3GateError("baseline_drift")


def verify_daily_execution(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    events: Sequence[Mapping[str, Any]],
    final_counts: Mapping[str, int],
) -> dict[str, Any]:
    _validate_child_packet(packet, approval_hash)
    baseline = _counts(packet.get("baseline_counts"))
    final = _counts(final_counts)
    if not events:
        raise HtDySchemaV3GateError("event_required")
    seen_keys: set[str] = set()
    for event in events:
        _validate_event(event, packet, seen_keys)
    created = len(events)
    if (
        final["strategy_signals"] - baseline["strategy_signals"] != created
        or final["signal_events"] - baseline["signal_events"] != created
    ):
        raise HtDySchemaV3GateError("allowed_write_delta_invalid")
    forbidden_deltas = {
        key: final[key] - baseline[key]
        for key in FORBIDDEN_COUNTER_KEYS
    }
    if any(value != 0 for value in forbidden_deltas.values()):
        raise HtDySchemaV3GateError("forbidden_write_delta_invalid")
    return {
        "status": "passed",
        "gate": CODE_GATE,
        "trading_day": packet["trading_day"],
        "created_events": created,
        "forbidden_write_deltas": forbidden_deltas,
    }


def _validate_child_packet(
    packet: Mapping[str, Any],
    approval_hash: str,
) -> None:
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise HtDySchemaV3GateError("schema_version_invalid")
    if (
        packet.get("packet_type") != CHILD_PACKET_TYPE
        or packet.get("task_id") != TASK_ID
        or packet.get("authorization_mode") != "exact_daily_child"
        or packet.get("product") != "jm"
        or packet.get("period") != "15m"
    ):
        raise HtDySchemaV3GateError("child_identity_invalid")
    _verify_hash(packet, approval_hash)
    _actual_contract(packet.get("actual_contract"))
    if not _sha256(str(packet.get("mapping_sha256") or "")):
        raise HtDySchemaV3GateError("mapping_sha256_invalid")
    _counts(packet.get("baseline_counts"))
    if packet.get("event_contract") != _event_contract():
        raise HtDySchemaV3GateError("event_contract_invalid")
    if packet.get("scope") != _scope_contract():
        raise HtDySchemaV3GateError("scope_contract_invalid")


def _validate_event(
    event: Mapping[str, Any],
    packet: Mapping[str, Any],
    seen_keys: set[str],
) -> None:
    event_key = str(event.get("event_key") or "")
    payload = event.get("payload")
    lineage = (
        payload.get("formal_lineage")
        if isinstance(payload, Mapping)
        else None
    )
    indicator = (
        lineage.get("indicator")
        if isinstance(lineage, Mapping)
        else None
    )
    expected_indicator = {
        "indicator_code": INDICATOR_CODE,
        "indicator_version": INDICATOR_VERSION,
        "signal_policy": SIGNAL_POLICY,
        "future_looking": True,
        "repainting_accepted": True,
        "first_seen_no_retraction": True,
        "historical_backtest_allowed": False,
        "notification_ready": False,
        "auto_order": False,
    }
    if (
        not event_key
        or event_key in seen_keys
        or event.get("event_type") != "signal_created"
        or event.get("source_mode") != SOURCE_MODE
        or event.get("strategy_name") != STRATEGY_CODE
        or event.get("strategy_version") != STRATEGY_VERSION
        or event.get("product") != "jm"
        or event.get("actual_contract") != packet.get("actual_contract")
        or event.get("dominant_mapping_date") != packet.get("trading_day")
        or event.get("period") != "15m"
        or event.get("direction") not in {"long", "short"}
        or not isinstance(lineage, Mapping)
        or lineage.get("schema_version") != "signal_review_lineage_v2"
        or indicator != expected_indicator
    ):
        raise HtDySchemaV3GateError("event_contract_invalid")
    seen_keys.add(event_key)


def _strategy_contract() -> dict[str, Any]:
    return {
        "strategy_code": STRATEGY_CODE,
        "strategy_version": STRATEGY_VERSION,
        "indicator_code": INDICATOR_CODE,
        "indicator_version": INDICATOR_VERSION,
        "source_mode": SOURCE_MODE,
        "signal_policy": SIGNAL_POLICY,
        "product": "jm",
        "period": "15m",
        "partial_allowed": True,
        "future_looking": True,
        "repainting_accepted": True,
        "first_seen_no_retraction": True,
        "historical_backtest_allowed": False,
        "auto_order": False,
    }


def _event_contract() -> dict[str, Any]:
    return {
        "allowed_event_types": ["signal_created"],
        "signal_changed_allowed": False,
        "dedupe_excludes": [
            "direction",
            "source_revision",
            "snapshot_sha256",
        ],
        "lineage_schema_version": "signal_review_lineage_v2",
        "first_seen_no_retraction": True,
    }


def _scope_contract() -> dict[str, Any]:
    return {
        "strategy_signals": "scoped_first_seen_only",
        "signal_events": "scoped_signal_created_only",
        "signal_notifications": "forbidden",
        "signal_scan_tasks": "forbidden",
        "historical_or_canonical_assets": "forbidden",
        "profile_active_bindings": "forbidden",
        "backtest": "forbidden",
        "orders": "forbidden",
        "trades": "forbidden",
        "wechat_send": "forbidden",
        "auto_order": False,
    }


def _verify_hash(packet: Mapping[str, Any], approval_hash: str) -> None:
    packet_hash = str(packet.get("packet_hash") or "")
    if (
        not _sha256(approval_hash)
        or packet_hash != approval_hash
        or canonical_packet_hash(packet) != packet_hash
    ):
        raise HtDySchemaV3GateError("packet_hash_invalid")


def _validate_bindings(bindings: Mapping[str, Any]) -> None:
    if set(bindings) != BINDING_KEYS:
        raise HtDySchemaV3GateError("bindings_invalid")
    if any(
        not _sha256(str(bindings.get(key) or ""))
        for key in HASH_BINDING_KEYS
    ):
        raise HtDySchemaV3GateError("bindings_invalid")
    runtime_commit = str(bindings.get("runtime_commit") or "")
    if (
        len(runtime_commit) != 40
        or not _hex(runtime_commit)
        or bindings.get("database_revision") != REQUIRED_DB_REVISION
    ):
        raise HtDySchemaV3GateError("bindings_invalid")


def _trading_days(values: Sequence[date]) -> tuple[date, ...]:
    if (
        not values
        or len(values) > MAX_TRADING_DAYS
        or any(not _plain_date(value) for value in values)
        or len(set(values)) != len(values)
    ):
        raise HtDySchemaV3GateError("trading_days_bounded")
    return tuple(sorted(values))


def _parse_packet_days(value: Any) -> tuple[date, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_TRADING_DAYS
    ):
        raise HtDySchemaV3GateError("trading_days_bounded")
    try:
        parsed = tuple(date.fromisoformat(str(item)) for item in value)
    except ValueError as exc:
        raise HtDySchemaV3GateError("trading_days_bounded") from exc
    if tuple(sorted(parsed)) != parsed or len(set(parsed)) != len(parsed):
        raise HtDySchemaV3GateError("trading_days_bounded")
    return parsed


def _actual_contract(value: Any) -> str:
    contract = str(value or "").strip().upper()
    if (
        not contract
        or contract.endswith(".MAIN")
        or not contract.startswith("JM")
        or not contract[2:].isdigit()
    ):
        raise HtDySchemaV3GateError("actual_contract_invalid")
    return contract


def _counts(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != COUNTER_KEYS:
        raise HtDySchemaV3GateError("counter_shape_invalid")
    counts: dict[str, int] = {}
    for key in COUNTER_KEYS:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise HtDySchemaV3GateError("counter_shape_invalid")
        counts[key] = item
    return counts


def _sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and _hex(value)


def _hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _plain_date(value: Any) -> bool:
    from datetime import datetime

    return isinstance(value, date) and not isinstance(value, datetime)
