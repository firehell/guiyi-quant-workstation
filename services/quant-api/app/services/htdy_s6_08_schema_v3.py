"""Pure schema-v3 authorization contracts for HTDY S6-08.

The builders and verifiers in this module perform no filesystem, database,
Runtime, scheduler, or notification actions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, time
import hashlib
import json
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 3
TASK_ID = "JM-LIVE-SIGNAL-EVENT-S6-08"
PARENT_PACKET_TYPE = "htdy_s6_08_bounded_parent"
CHILD_PACKET_TYPE = "htdy_s6_08_exact_daily_child"
CODE_GATE = "HTDY_S6_08_SCHEMA_V3_CODE_VERIFIED"
REQUIRED_DB_REVISION = "20260721_0025"
MAX_TRADING_DAYS = 5
FROZEN_TRADING_DAYS = (
    date(2026, 7, 27),
    date(2026, 7, 28),
    date(2026, 7, 29),
    date(2026, 7, 30),
    date(2026, 7, 31),
)
STRATEGY_CODE = "htdy_original_realtime_first_seen"
STRATEGY_VERSION = "v1.0"
INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
SOURCE_MODE = "live_realtime_repainting"
SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"

LEGACY_HASH_BINDING_KEYS = frozenset(
    {
        "deployment_receipt_sha256",
        "s6_07_final_receipt_sha256",
        "service_bundle_sha256",
        "source_sha256",
        "policy_sha256",
        "writer_sha256",
    }
)
LEGACY_BINDING_KEYS = frozenset(
    {
        *LEGACY_HASH_BINDING_KEYS,
        "runtime_commit",
        "database_revision",
    }
)
FULL_BINDING_KEYS = frozenset(
    {
        "deployment_packet_sha256",
        "s6_07_rebind_packet_sha256",
        "s6_07_final_receipt",
        "database_recovery_receipt",
        "parent_mapping",
        "service_bundle_sha256",
        "runtime",
        "database_revision",
        "actual_contract_resolver_sha256",
        "profile",
        "source_sha256",
        "policy_sha256",
        "writer_sha256",
        "web",
        "feature_flags",
        "baseline",
        "output",
        "launchd",
        "no_migration",
    }
)
LEGACY_COUNTER_KEYS = frozenset(
    {
        "strategy_signals",
        "signal_events",
        "signal_notifications",
        "signal_scan_tasks",
        "orders",
        "trades",
    }
)
FULL_COUNTER_KEYS = frozenset(
    {
        *LEGACY_COUNTER_KEYS,
        "review_notes",
        "backtest_tasks",
        "profile_bindings",
        "canonical_assets",
    }
)
LEGACY_FORBIDDEN_COUNTER_KEYS = (
    "signal_notifications",
    "signal_scan_tasks",
    "orders",
    "trades",
)
FULL_HASH_KEYS = frozenset(
    {
        "backtest_state_sha256",
        "profile_bindings_sha256",
        "canonical_assets_sha256",
        "forbidden_tables_sha256",
    }
)


class HtDySchemaV3GateError(RuntimeError):
    """Raised when a schema-v3 packet or result fails closed."""


def validate_frozen_parent_window(
    *,
    generated_on: date | None = None,
    generated_at: datetime | None = None,
    verified_trading_days: Sequence[date],
    first_day_htdy_event_count: int = 0,
    first_day_child_present: bool = False,
) -> None:
    if tuple(verified_trading_days) != FROZEN_TRADING_DAYS:
        raise HtDySchemaV3GateError(
            "frozen_window_calendar_incomplete"
        )
    if generated_at is None:
        if not _plain_date(generated_on):
            raise HtDySchemaV3GateError("generated_on_invalid")
        if generated_on >= FROZEN_TRADING_DAYS[0]:
            raise HtDySchemaV3GateError("frozen_window_already_started")
        return
    if generated_on is not None:
        raise HtDySchemaV3GateError("generated_time_ambiguous")
    if generated_at.tzinfo is None:
        raise HtDySchemaV3GateError("generated_at_invalid")
    local = generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
    first_day = FROZEN_TRADING_DAYS[0]
    if local.date() < first_day:
        return
    if local.date() > first_day:
        raise HtDySchemaV3GateError(
            "frozen_window_preopen_deadline_passed"
        )
    if (
        type(first_day_htdy_event_count) is not int
        or first_day_htdy_event_count != 0
        or first_day_child_present is not False
    ):
        raise HtDySchemaV3GateError(
            "frozen_window_first_day_state_not_clean"
        )
    if local.time() >= time(8, 30):
        raise HtDySchemaV3GateError(
            "frozen_window_preopen_deadline_passed"
        )


def build_final_receipt(
    *,
    child_packet: Mapping[str, Any],
    verification: Mapping[str, Any],
    service_parent_packet_sha256: str,
    deployment_receipt_sha256: str,
    s6_07_rebind_receipt_sha256: str,
) -> dict[str, Any]:
    for value in (
        service_parent_packet_sha256,
        deployment_receipt_sha256,
        s6_07_rebind_receipt_sha256,
    ):
        if not _sha256(value):
            raise HtDySchemaV3GateError("final_receipt_binding_invalid")
    if (
        verification.get("status") != "passed"
        or verification.get("canonical_gate")
        != "JM_LIVE_SIGNAL_EVENT_PASSED"
        or verification.get("gate_alias")
        != "LIVE_SIGNAL_EVENT_GATE_PASSED"
        or verification.get("trading_ready") is not False
        or verification.get("notification_ready") is not False
        or verification.get("long_running_ready") is not False
    ):
        raise HtDySchemaV3GateError("final_verification_invalid")
    receipt: dict[str, Any] = {
        "schema_version": 3,
        "task_id": TASK_ID,
        "status": "completed",
        "gate": "JM_LIVE_SIGNAL_EVENT_PASSED",
        "gate_alias": "LIVE_SIGNAL_EVENT_GATE_PASSED",
        "trading_day": child_packet.get("trading_day"),
        "daily_child_packet_sha256": child_packet.get("packet_hash"),
        "service_parent_packet_sha256": service_parent_packet_sha256,
        "deployment_receipt_sha256": deployment_receipt_sha256,
        "s6_07_rebind_receipt_sha256": s6_07_rebind_receipt_sha256,
        "verification": deepcopy(dict(verification)),
        "historical_validation": False,
        "runtime_ready": False,
        "trading_ready": False,
        "notification_ready": False,
        "long_running_ready": False,
        "automatic_trading_ready": False,
    }
    receipt["receipt_hash"] = final_receipt_hash(receipt)
    return receipt


def final_receipt_hash(receipt: Mapping[str, Any]) -> str:
    payload = {
        str(key): deepcopy(value)
        for key, value in receipt.items()
        if key != "receipt_hash"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def publish_final_receipt_create_only(
    path: Any,
    receipt: Mapping[str, Any],
) -> None:
    from pathlib import Path

    from app.services.htdy_s6_08_approval_artifacts import (
        write_json_create_only,
    )

    expected = final_receipt_hash(receipt)
    if receipt.get("receipt_hash") != expected:
        raise HtDySchemaV3GateError("final_receipt_hash_invalid")
    write_json_create_only(Path(path), receipt)


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
    bindings: Mapping[str, Any] | None = None,
    deployment_receipt_sha256: str | None = None,
    s6_07_final_receipt_sha256: str | None = None,
    service_bundle_sha256: str | None = None,
    runtime_commit: str | None = None,
    database_revision: str | None = None,
    source_sha256: str | None = None,
    policy_sha256: str | None = None,
    writer_sha256: str | None = None,
) -> dict[str, Any]:
    days = _trading_days(trading_days)
    if bindings is None:
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
    frozen_bindings = deepcopy(dict(bindings))
    _validate_bindings(frozen_bindings)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": PARENT_PACKET_TYPE,
        "task_id": TASK_ID,
        "authorization_mode": "bounded_parent_exact_daily_child",
        "trading_days": [item.isoformat() for item in days],
        "bindings": frozen_bindings,
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
    current_parent_bindings: Mapping[str, Any] | None = None,
    trading_day: date,
    actual_contract: str,
    mapping_sha256: str,
    source_facts: Mapping[str, Any] | None = None,
    baseline_counts: Mapping[str, int],
    baseline_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    bindings = parent_packet.get("bindings")
    if not isinstance(bindings, Mapping):
        raise HtDySchemaV3GateError("parent_bindings_invalid")
    if current_parent_bindings is None:
        if set(bindings) == FULL_BINDING_KEYS:
            raise HtDySchemaV3GateError("current_parent_bindings_required")
        current_parent_bindings = bindings
    verify_parent_authorization(
        parent_packet,
        approval_hash=parent_approval_hash,
        current_bindings=current_parent_bindings,
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
    frozen_source_facts = (
        _source_facts(source_facts)
        if source_facts is not None
        else None
    )
    frozen_hashes = (
        _state_hashes(baseline_hashes)
        if baseline_hashes is not None
        else None
    )
    if set(bindings) == FULL_BINDING_KEYS and (
        frozen_source_facts is None or frozen_hashes is None
    ):
        raise HtDySchemaV3GateError("child_full_facts_required")
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
        **(
            {"source_facts": frozen_source_facts}
            if frozen_source_facts is not None
            else {}
        ),
        **(
            {"baseline_hashes": frozen_hashes}
            if frozen_hashes is not None
            else {}
        ),
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
    current_parent_bindings: Mapping[str, Any] | None = None,
    current_trading_day: date,
    current_actual_contract: str,
    current_mapping_sha256: str,
    current_source_facts: Mapping[str, Any] | None = None,
    current_counts: Mapping[str, int],
    current_hashes: Mapping[str, str] | None = None,
) -> None:
    bindings = parent_packet.get("bindings")
    if not isinstance(bindings, Mapping):
        raise HtDySchemaV3GateError("parent_bindings_invalid")
    if current_parent_bindings is None:
        if set(bindings) == FULL_BINDING_KEYS:
            raise HtDySchemaV3GateError("current_parent_bindings_required")
        current_parent_bindings = bindings
    verify_parent_authorization(
        parent_packet,
        approval_hash=parent_approval_hash,
        current_bindings=current_parent_bindings,
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
    if "source_facts" in packet:
        try:
            normalized_source_facts = _source_facts(current_source_facts)
        except HtDySchemaV3GateError as exc:
            raise HtDySchemaV3GateError("source_facts_drift") from exc
        if normalized_source_facts != packet.get("source_facts"):
            raise HtDySchemaV3GateError("source_facts_drift")
    if "baseline_hashes" in packet:
        if (
            current_hashes is None
            or _state_hashes(current_hashes)
            != packet.get("baseline_hashes")
        ):
            raise HtDySchemaV3GateError("baseline_hash_drift")


def verify_daily_execution(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    events: Sequence[Mapping[str, Any]],
    final_counts: Mapping[str, int],
    final_hashes: Mapping[str, str] | None = None,
    idempotency_result: Mapping[str, int] | None = None,
    final_flags: Mapping[str, Any] | None = None,
    health: Mapping[str, Any] | None = None,
    review_deep_links: Sequence[Mapping[str, Any]] | None = None,
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
    forbidden_keys = (
        FULL_COUNTER_KEYS - {"strategy_signals", "signal_events"}
        if set(baseline) == FULL_COUNTER_KEYS
        else LEGACY_FORBIDDEN_COUNTER_KEYS
    )
    forbidden_deltas = {
        key: final[key] - baseline[key]
        for key in forbidden_keys
    }
    if any(value != 0 for value in forbidden_deltas.values()):
        raise HtDySchemaV3GateError("forbidden_write_delta_invalid")
    result = {
        "status": "passed",
        "gate": CODE_GATE,
        "trading_day": packet["trading_day"],
        "created_events": created,
        "forbidden_write_deltas": forbidden_deltas,
    }
    if "baseline_hashes" not in packet:
        return result
    if (
        final_hashes is None
        or _state_hashes(final_hashes) != packet.get("baseline_hashes")
    ):
        raise HtDySchemaV3GateError("forbidden_hash_drift")
    probe = dict(idempotency_result or {})
    if (
        probe.get("created") != 0
        or probe.get("changed") != 0
        or not isinstance(probe.get("unchanged"), int)
        or int(probe["unchanged"]) < 1
    ):
        raise HtDySchemaV3GateError("idempotency_probe_invalid")
    expected_flags = {
        "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
        "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
    }
    if dict(final_flags or {}) != expected_flags:
        raise HtDySchemaV3GateError("final_flags_not_cleared")
    if dict(health or {}) != {
        "runtime": "ok",
        "live": "ok",
        "after_market": "ok",
    }:
        raise HtDySchemaV3GateError("runtime_health_invalid")
    links = list(review_deep_links or [])
    if not links or any(item.get("readable") is not True for item in links):
        raise HtDySchemaV3GateError("review_deep_link_invalid")
    return {
        **result,
        "canonical_gate": "JM_LIVE_SIGNAL_EVENT_PASSED",
        "gate_alias": "LIVE_SIGNAL_EVENT_GATE_PASSED",
        "historical_validation": False,
        "trading_ready": False,
        "notification_ready": False,
        "long_running_ready": False,
        "idempotency_probe": probe,
    }


def verify_runtime_first_event(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    events: Sequence[Mapping[str, Any]],
    final_counts: Mapping[str, int],
    final_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Freeze exactly one first natural event before the probe cycle."""

    _validate_child_packet(packet, approval_hash)
    if len(events) != 1:
        raise HtDySchemaV3GateError("first_natural_event_count_invalid")
    event = events[0]
    _validate_event(event, packet, set())
    baseline = _counts(packet.get("baseline_counts"))
    final = _counts(final_counts)
    expected = {
        **baseline,
        "strategy_signals": baseline["strategy_signals"] + 1,
        "signal_events": baseline["signal_events"] + 1,
    }
    if final != expected:
        raise HtDySchemaV3GateError("first_natural_event_delta_invalid")
    if (
        "baseline_hashes" not in packet
        or _state_hashes(final_hashes) != packet.get("baseline_hashes")
    ):
        raise HtDySchemaV3GateError("forbidden_hash_drift")
    lineage = event["payload"]["formal_lineage"]
    event_id = event.get("id")
    detection = lineage.get("live_detection_snapshot")
    observation_key = (
        detection.get("observation_key")
        if isinstance(detection, Mapping)
        else None
    )
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
        or not isinstance(observation_key, str)
        or not observation_key
    ):
        raise HtDySchemaV3GateError("first_natural_event_identity_invalid")
    return {
        "event_id": event_id,
        "event_key": str(event["event_key"]),
        "observation_key": observation_key,
    }


def verify_runtime_idempotency_probe(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    accepted_event: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    current_counts: Mapping[str, int],
    current_hashes: Mapping[str, str],
    runtime_result: Mapping[str, Any],
) -> None:
    """Require one same-event unchanged probe and reject every new key."""

    _validate_child_packet(packet, approval_hash)
    if len(events) != 1:
        raise HtDySchemaV3GateError("idempotency_probe_invalid")
    event = events[0]
    try:
        frozen = verify_runtime_first_event(
            packet,
            approval_hash=approval_hash,
            events=events,
            final_counts=current_counts,
            final_hashes=current_hashes,
        )
    except HtDySchemaV3GateError as exc:
        raise HtDySchemaV3GateError("idempotency_probe_invalid") from exc
    if frozen != dict(accepted_event):
        raise HtDySchemaV3GateError("idempotency_probe_invalid")
    result = dict(runtime_result)
    if (
        result.get("created") != 0
        or result.get("changed") != 0
        or result.get("blocked") != 0
        or not isinstance(result.get("unchanged"), int)
        or isinstance(result.get("unchanged"), bool)
        or int(result["unchanged"]) < 1
        or result.get("event_ids") != [event["id"]]
    ):
        raise HtDySchemaV3GateError("idempotency_probe_invalid")


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
    if "source_facts" in packet:
        _source_facts(packet.get("source_facts"))
    if "baseline_hashes" in packet:
        _state_hashes(packet.get("baseline_hashes"))
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
        "live_confirmed_required": False,
        "partial_allowed": True,
        "confirmed_allowed": True,
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
        or not isinstance(indicator, Mapping)
        or any(
            indicator.get(key) != value
            for key, value in expected_indicator.items()
        )
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
        "confirmed_allowed": True,
        "live_confirmed_required": False,
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
    if set(bindings) == LEGACY_BINDING_KEYS:
        if any(
            not _sha256(str(bindings.get(key) or ""))
            for key in LEGACY_HASH_BINDING_KEYS
        ):
            raise HtDySchemaV3GateError("bindings_invalid")
        runtime_commit = str(bindings.get("runtime_commit") or "")
        if (
            len(runtime_commit) != 40
            or not _hex(runtime_commit)
            or bindings.get("database_revision") != REQUIRED_DB_REVISION
        ):
            raise HtDySchemaV3GateError("bindings_invalid")
        return
    if set(bindings) != FULL_BINDING_KEYS:
        raise HtDySchemaV3GateError("bindings_invalid")
    for key in (
        "deployment_packet_sha256",
        "s6_07_rebind_packet_sha256",
        "service_bundle_sha256",
        "actual_contract_resolver_sha256",
        "source_sha256",
        "policy_sha256",
        "writer_sha256",
    ):
        if not _sha256(str(bindings.get(key) or "")):
            raise HtDySchemaV3GateError("bindings_invalid")
    receipt = bindings.get("s6_07_final_receipt")
    recovery_receipt = bindings.get("database_recovery_receipt")
    parent_mapping = bindings.get("parent_mapping")
    runtime = bindings.get("runtime")
    profile = bindings.get("profile")
    web = bindings.get("web")
    flags = bindings.get("feature_flags")
    baseline = bindings.get("baseline")
    output = bindings.get("output")
    launchd = bindings.get("launchd")
    if not all(
        isinstance(value, Mapping)
        for value in (
            receipt,
            recovery_receipt,
            parent_mapping,
            runtime,
            profile,
            web,
            flags,
            baseline,
            output,
            launchd,
        )
    ):
        raise HtDySchemaV3GateError("bindings_invalid")
    if (
        not str(receipt.get("path") or "").endswith("completion_receipt.json")
        or not _sha256(str(receipt.get("sha256") or ""))
        or not str(recovery_receipt.get("path") or "").endswith(
            "recovery_receipt.json"
        )
        or not _sha256(str(recovery_receipt.get("sha256") or ""))
        or not _sha256(
            str(recovery_receipt.get("receipt_hash") or "")
        )
        or not _valid_parent_mapping(parent_mapping)
        or not str(runtime.get("root") or "").startswith("/")
        or len(str(runtime.get("commit") or "")) != 40
        or not _hex(str(runtime.get("commit") or ""))
        or not _sha256(str(runtime.get("tree_sha256") or ""))
        or runtime.get("tracked_clean") is not True
        or bindings.get("database_revision") != REQUIRED_DB_REVISION
        or profile.get("profile_id") != "live_observation_v1"
        or not isinstance(profile.get("market_data_file_id"), int)
        or int(profile["market_data_file_id"]) <= 0
        or not str(profile.get("data_version") or "")
        or not _sha256(str(profile.get("checksum") or ""))
        or not _sha256(str(web.get("bundle_sha256") or ""))
        or not _sha256(str(web.get("source_sha256") or ""))
        or dict(flags)
        != {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        }
        or _counts(baseline.get("counts")) != dict(baseline.get("counts"))
        or _state_hashes(baseline.get("hashes"))
        != dict(baseline.get("hashes"))
        or not str(output.get("root") or "").startswith("/")
        or not isinstance(output.get("device"), int)
        or not str(output.get("mount") or "").startswith("/")
        or launchd.get("label") != "com.guiyi.quant-runtime-scheduler"
        or not _sha256(str(launchd.get("plist_sha256") or ""))
        or bindings.get("no_migration") is not True
    ):
        raise HtDySchemaV3GateError("bindings_invalid")


def _valid_parent_mapping(value: Mapping[str, Any]) -> bool:
    if set(value) != {"trade_date", "contract_code", "sha256"}:
        return False
    try:
        mapping_day = date.fromisoformat(str(value.get("trade_date") or ""))
        contract = _actual_contract(value.get("contract_code"))
    except (ValueError, HtDySchemaV3GateError):
        return False
    return (
        _plain_date(mapping_day)
        and mapping_day < FROZEN_TRADING_DAYS[0]
        and contract == value.get("contract_code")
        and _sha256(str(value.get("sha256") or ""))
    )


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
    keys = frozenset(value) if isinstance(value, Mapping) else frozenset()
    if (
        not isinstance(value, Mapping)
        or keys not in {LEGACY_COUNTER_KEYS, FULL_COUNTER_KEYS}
    ):
        raise HtDySchemaV3GateError("counter_shape_invalid")
    counts: dict[str, int] = {}
    for key in value:
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise HtDySchemaV3GateError("counter_shape_invalid")
        counts[key] = item
    return counts


def _state_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != FULL_HASH_KEYS:
        raise HtDySchemaV3GateError("state_hash_shape_invalid")
    result = {str(key): str(item) for key, item in value.items()}
    if any(not _sha256(item) for item in result.values()):
        raise HtDySchemaV3GateError("state_hash_shape_invalid")
    return result


def _source_facts(value: Any) -> dict[str, Any]:
    expected = {
        "profile_sha256",
        "source_sha256",
        "policy_sha256",
        "runtime_heartbeat_sha256",
        "autosend_enabled",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HtDySchemaV3GateError("source_facts_invalid")
    result = deepcopy(dict(value))
    if (
        any(
            not _sha256(str(result.get(key) or ""))
            for key in expected - {"autosend_enabled"}
        )
        or result.get("autosend_enabled") is not False
    ):
        raise HtDySchemaV3GateError("source_facts_invalid")
    return result


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
