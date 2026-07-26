from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


class S607DatabaseRecoveryError(RuntimeError):
    pass


def canonical_hash(payload: Mapping[str, Any]) -> str:
    value = {
        str(key): deepcopy(item)
        for key, item in payload.items()
        if key not in {"manifest_hash", "packet_hash"}
    }
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def build_recovery_manifest(
    *,
    current_facts: Mapping[str, Any],
    recovery_rows: Mapping[str, Any],
    evidence: Mapping[str, Any],
    unproven_fields: Sequence[str],
) -> dict[str, Any]:
    _validate_current_facts(current_facts)
    _validate_recovery_rows(recovery_rows)
    _validate_evidence(evidence)
    unresolved = sorted({str(item) for item in unproven_fields if str(item)})
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "task_id": "S6-07-DATABASE-REVISION-DRIFT-RECOVERY",
        "status": "blocked" if unresolved else "ready",
        "recovery_mode": "data_repair_only",
        "migration_allowed": False,
        "current_facts": deepcopy(dict(current_facts)),
        "recovery_rows": deepcopy(dict(recovery_rows)),
        "evidence": deepcopy(dict(evidence)),
        "unproven_fields": unresolved,
        "allowed_tables": [
            "profile_active_bindings",
            "backtest_tasks",
            "backtest_reports",
            "after_market_scheduler_checkpoints",
        ],
        "forbidden_tables": [
            "signal_events",
            "signal_notifications",
            "strategy_signals",
            "orders",
            "trades",
        ],
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    return manifest


def build_recovery_approval_packet(
    *,
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_manifest(manifest)
    if manifest.get("status") != "ready" or manifest.get("unproven_fields"):
        raise S607DatabaseRecoveryError("recovery_manifest_incomplete")
    _validate_source(source)
    packet: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": "s607_database_data_recovery_v1",
        "task_id": "S6-07-DATABASE-REVISION-DRIFT-RECOVERY",
        "status": "approval_required",
        "writes_authorized": False,
        "manifest": deepcopy(dict(manifest)),
        "source": deepcopy(dict(source)),
        "allowed_operations": ["restore_exact_bound_database_rows"],
        "forbidden_operations": [
            "database_migration",
            "runtime_deployment",
            "signal_event_write",
            "notification_write",
            "order_or_trade_write",
        ],
        "full_logical_backup_required": True,
        "isolated_restore_drill_required": True,
        "recovery_receipt_required": True,
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_recovery_approval_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    current_source: Mapping[str, Any],
) -> None:
    if (
        packet.get("schema_version") != 1
        or packet.get("packet_type") != "s607_database_data_recovery_v1"
        or packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("packet_hash") != approval_hash
        or canonical_hash(packet) != packet.get("packet_hash")
    ):
        raise S607DatabaseRecoveryError("recovery_approval_packet_invalid")
    manifest = packet.get("manifest")
    if not isinstance(manifest, Mapping):
        raise S607DatabaseRecoveryError("recovery_approval_packet_invalid")
    _validate_manifest(manifest)
    if manifest.get("current_facts") != dict(current_facts):
        raise S607DatabaseRecoveryError("recovery_current_fact_drift")
    _validate_source(current_source)
    if packet.get("source") != dict(current_source):
        raise S607DatabaseRecoveryError("recovery_source_drift")


def _validate_current_facts(value: Mapping[str, Any]) -> None:
    database = value.get("database")
    counts = value.get("row_counts")
    runtime = value.get("runtime")
    if (
        not isinstance(database, Mapping)
        or database.get("revision") != "20260721_0025"
        or not isinstance(database.get("oid"), int)
        or not database.get("database")
        or not isinstance(counts, Mapping)
        or not isinstance(runtime, Mapping)
        or not _sha256(runtime.get("tracked_status_sha256"))
        or not _commit(runtime.get("commit"))
    ):
        raise S607DatabaseRecoveryError("recovery_current_facts_invalid")


def _validate_recovery_rows(value: Mapping[str, Any]) -> None:
    bindings = value.get("profile_active_bindings")
    lineage = value.get("backtest_lineage")
    checkpoint = value.get("scheduler_checkpoint")
    if (
        not isinstance(bindings, list)
        or not bindings
        or not all(isinstance(item, Mapping) and isinstance(item.get("id"), int) for item in bindings)
        or not isinstance(lineage, list)
        or not lineage
        or not all(
            isinstance(item, Mapping)
            and item.get("table") in {"backtest_tasks", "backtest_reports"}
            and isinstance(item.get("id"), int)
            for item in lineage
        )
        or not isinstance(checkpoint, Mapping)
        or checkpoint.get("product") != "jm"
    ):
        raise S607DatabaseRecoveryError("recovery_rows_invalid")


def _validate_evidence(value: Mapping[str, Any]) -> None:
    required = {"profile_bindings", "backtest_lineage", "scheduler_checkpoint"}
    if set(value) != required:
        raise S607DatabaseRecoveryError("recovery_evidence_invalid")
    for item in value.values():
        if (
            not isinstance(item, Mapping)
            or not Path(str(item.get("path") or "")).is_absolute()
            or not _sha256(item.get("sha256"))
        ):
            raise S607DatabaseRecoveryError("recovery_evidence_invalid")


def _validate_manifest(value: Mapping[str, Any]) -> None:
    if (
        value.get("schema_version") != 1
        or value.get("task_id") != "S6-07-DATABASE-REVISION-DRIFT-RECOVERY"
        or value.get("recovery_mode") != "data_repair_only"
        or value.get("migration_allowed") is not False
        or canonical_hash(value) != value.get("manifest_hash")
    ):
        raise S607DatabaseRecoveryError("recovery_manifest_invalid")
    _validate_current_facts(value.get("current_facts") or {})
    _validate_recovery_rows(value.get("recovery_rows") or {})
    _validate_evidence(value.get("evidence") or {})


def _validate_source(value: Mapping[str, Any]) -> None:
    if not _commit(value.get("commit")) or not _commit(value.get("tree")):
        raise S607DatabaseRecoveryError("recovery_source_invalid")


def _sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _commit(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)
