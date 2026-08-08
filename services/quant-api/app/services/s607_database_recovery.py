from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


class S607DatabaseRecoveryError(RuntimeError):
    pass


SEMANTIC_RECOVERY_PACKET_HASH = (
    "443adda6d2b3f0e82edaeff1d72e9ff4"
    "a6d194b0f1d78928a034f175f513c2f3"
)


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


def verify_semantic_recovery_receipt(
    receipt: Mapping[str, Any],
) -> None:
    payload = {
        str(key): deepcopy(value)
        for key, value in receipt.items()
        if key != "receipt_hash"
    }
    before = receipt.get("before")
    after = receipt.get("after")
    before_counts = (
        before.get("row_counts") if isinstance(before, Mapping) else None
    )
    after_counts = (
        after.get("row_counts") if isinstance(after, Mapping) else None
    )
    if (
        receipt.get("schema_version") != 1
        or receipt.get("task_id")
        != "S6-07-DATABASE-REVISION-DRIFT-RECOVERY"
        or receipt.get("status") != "completed"
        or receipt.get("packet_hash") != SEMANTIC_RECOVERY_PACKET_HASH
        or receipt.get("receipt_hash") != canonical_hash(payload)
        or not isinstance(before_counts, Mapping)
        or not isinstance(after_counts, Mapping)
        or before_counts.get("profile_active_bindings") != 5124
        or after_counts.get("profile_active_bindings") != 5131
        or before_counts.get("after_market_scheduler_checkpoints") != 0
        or after_counts.get("after_market_scheduler_checkpoints") != 1
        or receipt.get("forbidden_tables_unchanged") is not True
        or receipt.get("report_14_unchanged") is not True
        or receipt.get("task_23_report_15_database_write") is not False
    ):
        raise S607DatabaseRecoveryError(
            "semantic_recovery_receipt_invalid"
        )


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
            "after_market_scheduler_checkpoints",
        ],
        "forbidden_tables": [
            "backtest_tasks",
            "backtest_reports",
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
    semantic = manifest.get("schema_version") == 2
    packet: dict[str, Any] = {
        "schema_version": 2 if semantic else 1,
        "packet_type": (
            "s607_database_semantic_recovery_v2"
            if semantic
            else "s607_database_data_recovery_v1"
        ),
        "task_id": "S6-07-DATABASE-REVISION-DRIFT-RECOVERY",
        "status": "approval_required",
        "writes_authorized": False,
        "manifest": deepcopy(dict(manifest)),
        "source": deepcopy(dict(source)),
        "allowed_operations": [
            (
                "restore_exact_business_rows_with_declared_synthesized_audit_fields"
                if semantic
                else "restore_exact_bound_database_rows"
            )
        ],
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
    schema_version = packet.get("schema_version")
    expected_type = {
        1: "s607_database_data_recovery_v1",
        2: "s607_database_semantic_recovery_v2",
    }.get(schema_version)
    if (
        expected_type is None
        or packet.get("packet_type") != expected_type
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


def build_semantic_recovery_manifest(
    *,
    current_facts: Mapping[str, Any],
    profile_active_bindings: Sequence[Mapping[str, Any]],
    scheduler_checkpoint: Mapping[str, Any],
    evidence: Mapping[str, Any],
    backup: Mapping[str, Any],
    isolated_restore_drill: Mapping[str, Any],
    synthesized_fields: Mapping[str, str],
    external_lineage_exception: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_current_facts(current_facts)
    bindings = [deepcopy(dict(item)) for item in profile_active_bindings]
    _validate_semantic_bindings(bindings)
    checkpoint = deepcopy(dict(scheduler_checkpoint))
    _validate_semantic_checkpoint(checkpoint)
    _validate_semantic_evidence(evidence)
    _validate_backup(backup)
    _validate_isolated_drill(isolated_restore_drill)
    _validate_external_lineage_exception(external_lineage_exception)
    if not synthesized_fields or any(
        not str(key) or not str(value)
        for key, value in synthesized_fields.items()
    ):
        raise S607DatabaseRecoveryError("recovery_synthesized_fields_invalid")
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "task_id": "S6-07-DATABASE-REVISION-DRIFT-RECOVERY",
        "status": "ready",
        "recovery_mode": "bounded_semantic_reconstruction",
        "migration_allowed": False,
        "current_facts": deepcopy(dict(current_facts)),
        "recovery_rows": {
            "profile_active_bindings": bindings,
            "scheduler_checkpoint": checkpoint,
        },
        "evidence": deepcopy(dict(evidence)),
        "backup": deepcopy(dict(backup)),
        "isolated_restore_drill": deepcopy(dict(isolated_restore_drill)),
        "synthesized_fields": deepcopy(dict(synthesized_fields)),
        "external_lineage_exception": deepcopy(
            dict(external_lineage_exception)
        ),
        "unproven_fields": [],
        "allowed_tables": [
            "profile_active_bindings",
            "after_market_scheduler_checkpoints",
        ],
        "forbidden_tables": [
            "backtest_tasks",
            "backtest_reports",
            "signal_events",
            "signal_notifications",
            "strategy_signals",
            "orders",
            "trades",
        ],
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    return manifest


def derive_semantic_recovery_rows(
    *,
    created_audit: Mapping[str, Any],
    superseded_audit: Mapping[str, Any],
    completion_snapshot: Mapping[str, Any],
    completion_snapshot_sha256: str,
    recovered_at: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _datetime(recovered_at)
    if not _sha256(completion_snapshot_sha256):
        raise S607DatabaseRecoveryError(
            "recovery_completion_snapshot_invalid"
        )
    created_rows = created_audit.get("profile_switches")
    superseded_rows = superseded_audit.get("profile_switches")
    if not isinstance(created_rows, list) or not isinstance(
        superseded_rows, list
    ):
        raise S607DatabaseRecoveryError(
            "recovery_profile_audit_invalid"
        )
    superseded_by_previous: dict[int, str] = {}
    for row in superseded_rows:
        if not isinstance(row, Mapping):
            raise S607DatabaseRecoveryError(
                "recovery_profile_audit_invalid"
            )
        previous_id = row.get("previous_binding_id")
        if isinstance(previous_id, int) and 5240 <= previous_id <= 5246:
            if previous_id in superseded_by_previous:
                raise S607DatabaseRecoveryError(
                    "recovery_profile_audit_duplicate"
                )
            superseded_by_previous[previous_id] = str(
                row.get("activated_at") or ""
            )
    bindings: list[dict[str, Any]] = []
    for row in created_rows:
        if not isinstance(row, Mapping):
            raise S607DatabaseRecoveryError(
                "recovery_profile_audit_invalid"
            )
        binding_id = row.get("binding_id")
        if not isinstance(binding_id, int) or not 5240 <= binding_id <= 5246:
            continue
        activated_at = str(row.get("activated_at") or "")
        superseded_at = superseded_by_previous.get(binding_id, "")
        _datetime(activated_at)
        _datetime(superseded_at)
        bindings.append(
            {
                "id": binding_id,
                "profile_id": str(row.get("profile_id") or ""),
                "instrument_symbol": str(
                    row.get("instrument_symbol") or ""
                ),
                "contract_code": str(row.get("contract_code") or ""),
                "contract_role": "actual_contract",
                "period": str(row.get("period") or ""),
                "data_version": str(
                    row.get("next_data_version") or ""
                ),
                "market_data_file_id": row.get(
                    "next_market_data_file_id"
                ),
                "binding_status": "superseded",
                "activated_at": activated_at,
                "superseded_at": superseded_at,
                "created_at": activated_at,
                "updated_at": superseded_at,
            }
        )
    bindings.sort(key=lambda item: int(item["id"]))
    _validate_semantic_bindings(bindings)

    authorization = completion_snapshot.get("authorization")
    checkpoint_source = completion_snapshot.get("checkpoint")
    if not isinstance(authorization, Mapping) or not isinstance(
        checkpoint_source, Mapping
    ):
        raise S607DatabaseRecoveryError(
            "recovery_completion_snapshot_invalid"
        )
    checkpoint = {
        "product": "jm",
        "exchange_code": "DCE",
        "status": checkpoint_source.get("status"),
        "authorization_hash": authorization.get(
            "service_enable_packet_hash"
        ),
        "last_successful_trading_day": checkpoint_source.get(
            "last_successful_trading_day"
        ),
        "current_trading_day": checkpoint_source.get(
            "current_trading_day"
        ),
        "last_attempt_at": checkpoint_source.get("last_attempt_at"),
        "last_success_at": checkpoint_source.get("last_success_at"),
        "next_retry_at": checkpoint_source.get("next_retry_at"),
        "retry_count": checkpoint_source.get("retry_count"),
        "last_error_type": checkpoint_source.get("last_error_type"),
        "last_error_at": checkpoint_source.get("last_error_at"),
        "last_execution_packet_hash": checkpoint_source.get(
            "last_execution_packet_hash"
        ),
        "last_receipt_path": checkpoint_source.get(
            "last_receipt_path"
        ),
        "last_result": {
            "status": "semantic_rebuild_from_s607_d2_completion",
            "semantic_reconstruction": True,
            "source_snapshot_sha256": completion_snapshot_sha256,
        },
        "created_at": recovered_at,
        "updated_at": recovered_at,
    }
    _validate_semantic_checkpoint(checkpoint)
    return bindings, checkpoint


def apply_semantic_recovery(
    session: Any,
    *,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_facts: Mapping[str, Any],
    current_source: Mapping[str, Any],
) -> dict[str, int]:
    del session, packet, approval_hash, current_facts, current_source
    raise S607DatabaseRecoveryError(
        "profile_binding_after_market_semantic_recovery_retired"
    )


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
    if value.get("schema_version") == 2:
        if (
            value.get("task_id")
            != "S6-07-DATABASE-REVISION-DRIFT-RECOVERY"
            or value.get("status") != "ready"
            or value.get("recovery_mode")
            != "bounded_semantic_reconstruction"
            or value.get("migration_allowed") is not False
            or value.get("unproven_fields") != []
            or value.get("allowed_tables")
            != [
                "profile_active_bindings",
                "after_market_scheduler_checkpoints",
            ]
            or value.get("forbidden_tables")
            != [
                "backtest_tasks",
                "backtest_reports",
                "signal_events",
                "signal_notifications",
                "strategy_signals",
                "orders",
                "trades",
            ]
            or canonical_hash(value) != value.get("manifest_hash")
        ):
            raise S607DatabaseRecoveryError("recovery_manifest_invalid")
        _validate_current_facts(value.get("current_facts") or {})
        rows = value.get("recovery_rows")
        if not isinstance(rows, Mapping):
            raise S607DatabaseRecoveryError("recovery_rows_invalid")
        _validate_semantic_bindings(
            rows.get("profile_active_bindings") or []
        )
        _validate_semantic_checkpoint(
            rows.get("scheduler_checkpoint") or {}
        )
        _validate_semantic_evidence(value.get("evidence") or {})
        _validate_backup(value.get("backup") or {})
        _validate_isolated_drill(
            value.get("isolated_restore_drill") or {}
        )
        _validate_external_lineage_exception(
            value.get("external_lineage_exception") or {}
        )
        synthesized = value.get("synthesized_fields")
        if not isinstance(synthesized, Mapping) or not synthesized:
            raise S607DatabaseRecoveryError(
                "recovery_synthesized_fields_invalid"
            )
        return
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


def _validate_semantic_bindings(value: Any) -> None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or [item.get("id") for item in value if isinstance(item, Mapping)]
        != list(range(5240, 5247))
    ):
        raise S607DatabaseRecoveryError("recovery_bindings_invalid")
    required = {
        "id",
        "profile_id",
        "instrument_symbol",
        "contract_code",
        "contract_role",
        "period",
        "data_version",
        "market_data_file_id",
        "binding_status",
        "activated_at",
        "superseded_at",
        "created_at",
        "updated_at",
    }
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != required
            or item.get("instrument_symbol") != "jm"
            or item.get("contract_code") != "JM2609"
            or item.get("contract_role") != "actual_contract"
            or item.get("binding_status") != "superseded"
            or not isinstance(item.get("market_data_file_id"), int)
        ):
            raise S607DatabaseRecoveryError("recovery_bindings_invalid")
        for key in (
            "activated_at",
            "superseded_at",
            "created_at",
            "updated_at",
        ):
            _datetime(item.get(key))


def _validate_semantic_checkpoint(value: Mapping[str, Any]) -> None:
    required = {
        "product",
        "exchange_code",
        "status",
        "authorization_hash",
        "last_successful_trading_day",
        "current_trading_day",
        "last_attempt_at",
        "last_success_at",
        "next_retry_at",
        "retry_count",
        "last_error_type",
        "last_error_at",
        "last_execution_packet_hash",
        "last_receipt_path",
        "last_result",
        "created_at",
        "updated_at",
    }
    result = value.get("last_result")
    if (
        set(value) != required
        or value.get("product") != "jm"
        or value.get("exchange_code") != "DCE"
        or value.get("status") != "idle"
        or not _sha256(value.get("authorization_hash"))
        or value.get("last_successful_trading_day") != "2026-07-24"
        or value.get("current_trading_day") is not None
        or value.get("retry_count") != 0
        or value.get("last_error_type") is not None
        or value.get("last_error_at") is not None
        or not _sha256(value.get("last_execution_packet_hash"))
        or not str(value.get("last_receipt_path") or "").endswith(
            "completion_receipt.json"
        )
        or not isinstance(result, Mapping)
        or result.get("semantic_reconstruction") is not True
        or result.get("status")
        != "semantic_rebuild_from_s607_d2_completion"
        or not _sha256(result.get("source_snapshot_sha256"))
    ):
        raise S607DatabaseRecoveryError("recovery_checkpoint_invalid")
    _date_or_none(value.get("last_successful_trading_day"))
    for key in (
        "last_attempt_at",
        "last_success_at",
        "created_at",
        "updated_at",
    ):
        _datetime(value.get(key))
    for key in ("next_retry_at", "last_error_at"):
        _datetime_or_none(value.get(key))


def _validate_semantic_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "profile_bindings_created",
        "profile_bindings_superseded",
        "scheduler_checkpoint",
        "external_backtest_lineage",
    }
    if set(value) != required:
        raise S607DatabaseRecoveryError("recovery_evidence_invalid")
    for item in value.values():
        if (
            not isinstance(item, Mapping)
            or not Path(str(item.get("path") or "")).is_absolute()
            or not _sha256(item.get("sha256"))
        ):
            raise S607DatabaseRecoveryError("recovery_evidence_invalid")


def _validate_backup(value: Mapping[str, Any]) -> None:
    if (
        value.get("mode") != "database-only"
        or not Path(str(value.get("path") or "")).is_absolute()
        or not _sha256(value.get("manifest_sha256"))
        or not _sha256(value.get("dump_sha256"))
    ):
        raise S607DatabaseRecoveryError("recovery_backup_invalid")


def _validate_isolated_drill(value: Mapping[str, Any]) -> None:
    if (
        value.get("status") != "passed"
        or value.get("cleanup_complete") is not True
        or not Path(str(value.get("path") or "")).is_absolute()
        or not _sha256(value.get("sha256"))
    ):
        raise S607DatabaseRecoveryError(
            "recovery_isolated_drill_invalid"
        )


def _validate_external_lineage_exception(
    value: Mapping[str, Any],
) -> None:
    if (
        value.get("task_id") != 23
        or value.get("report_id") != 15
        or value.get("database_write") is not False
        or not _sha256(value.get("evidence_sha256"))
    ):
        raise S607DatabaseRecoveryError(
            "recovery_external_lineage_invalid"
        )


def _datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise S607DatabaseRecoveryError(
            "recovery_datetime_invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise S607DatabaseRecoveryError("recovery_datetime_invalid")
    return parsed


def _datetime_or_none(value: Any) -> datetime | None:
    return None if value is None else _datetime(value)


def _date_or_none(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise S607DatabaseRecoveryError("recovery_date_invalid") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.isoformat(timespec="microseconds")
    return value.isoformat()


def _binding_payload(value: Any) -> dict[str, Any]:
    return {
        "id": value.id,
        "profile_id": value.profile_id,
        "instrument_symbol": value.instrument_symbol,
        "contract_code": value.contract_code,
        "contract_role": value.contract_role,
        "period": value.period,
        "data_version": value.data_version,
        "market_data_file_id": value.market_data_file_id,
        "binding_status": value.binding_status,
        "activated_at": _iso(value.activated_at),
        "superseded_at": _iso(value.superseded_at),
        "created_at": _iso(value.created_at),
        "updated_at": _iso(value.updated_at),
    }


def _checkpoint_payload(value: Any) -> dict[str, Any]:
    return {
        "product": value.product,
        "exchange_code": value.exchange_code,
        "status": value.status,
        "authorization_hash": value.authorization_hash,
        "last_successful_trading_day": _iso(
            value.last_successful_trading_day
        ),
        "current_trading_day": _iso(value.current_trading_day),
        "last_attempt_at": _iso(value.last_attempt_at),
        "last_success_at": _iso(value.last_success_at),
        "next_retry_at": _iso(value.next_retry_at),
        "retry_count": value.retry_count,
        "last_error_type": value.last_error_type,
        "last_error_at": _iso(value.last_error_at),
        "last_execution_packet_hash": value.last_execution_packet_hash,
        "last_receipt_path": value.last_receipt_path,
        "last_result": value.last_result,
        "created_at": _iso(value.created_at),
        "updated_at": _iso(value.updated_at),
    }


def _sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _commit(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(character in "0123456789abcdef" for character in text)
