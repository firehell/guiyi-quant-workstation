from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash


DEPLOYMENT_TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY"
DEPLOYMENT_SCHEMA_VERSION = 2
SOURCE_REVISION = "20260712_0022"
TARGET_REVISION = "20260721_0025"
MIGRATION_REVISIONS = ("20260712_0023", "20260718_0024", TARGET_REVISION)
SCHEMA_UPGRADE_MODE = "schema_upgrade"
CHECKPOINT_RECOVERY_MODE = "schema_upgrade_with_checkpoint_recovery"
CHECKPOINT_RECOVERY_ONLY_MODE = "checkpoint_recovery_only"
CODE_ONLY_MODE = "code_only"
CLEAN_STATUS_SHA256 = hashlib.sha256(b"").hexdigest()
ROW_COUNT_TABLES = (
    "backtest_tasks",
    "backtest_reports",
    "signal_scan_tasks",
    "strategy_signals",
    "signal_events",
)
COMMON_ALLOWED_OPERATIONS = (
    "runtime_fetch_approved_commit",
    "runtime_detach_to_approved_commit",
    "purge_runtime_python_bytecode",
    "recreate_locked_dependency_environment",
    "locked_dependency_sync",
    "refresh_hash_bound_shared_python_runner_without_restarting_other_labels",
    "api_bound_plist_bootout_bootstrap_only",
    "create_only_deployment_receipt",
)
SCHEMA_UPGRADE_ALLOWED_OPERATIONS = (
    *COMMON_ALLOWED_OPERATIONS[:5],
    "schema_only_alembic_upgrade_0022_to_0025",
    *COMMON_ALLOWED_OPERATIONS[5:],
)
CHECKPOINT_RECOVERY_ALLOWED_OPERATIONS = (
    *COMMON_ALLOWED_OPERATIONS[:5],
    "schema_only_alembic_upgrade_0022_to_0025",
    "restore_single_blocked_checkpoint_from_bound_evidence",
    *COMMON_ALLOWED_OPERATIONS[5:],
)
CHECKPOINT_RECOVERY_ONLY_ALLOWED_OPERATIONS = (
    *COMMON_ALLOWED_OPERATIONS[:5],
    "preserve_database_revision_0025",
    "restore_single_blocked_checkpoint_from_bound_evidence",
    *COMMON_ALLOWED_OPERATIONS[5:],
)
CODE_ONLY_ALLOWED_OPERATIONS = (
    *COMMON_ALLOWED_OPERATIONS[:5],
    "preserve_database_revision_0025",
    *COMMON_ALLOWED_OPERATIONS[5:],
)
FORBIDDEN_OPERATIONS = (
    "data_backfill",
    "alembic_stamp",
    "alembic_downgrade",
    "after_market_scheduler_load",
    "live_scheduler_restart",
    "rq_worker_restart",
    "web_restart",
    "foundation_checkpoint_reseed",
    "manual_daily_archive_invocation",
    "checkpoint_watermark_skip",
)


def build_deployment_approval_packet(*, bound_facts: dict[str, Any]) -> dict[str, Any]:
    _validate_bound_facts(bound_facts)
    allowed_operations = _allowed_operations(str(bound_facts["deployment_mode"]))
    packet: dict[str, Any] = {
        "schema_version": DEPLOYMENT_SCHEMA_VERSION,
        "task_id": DEPLOYMENT_TASK_ID,
        "status": "approval_required",
        "writes_authorized": False,
        "authorization_mode": "exact_deployment_hash",
        "bound_facts": bound_facts,
        "allowed_operations": list(allowed_operations),
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "invalidation_rule": "any source, runtime, database, migration, backup, row-count, checkpoint-recovery evidence, API-runner, launchd, or packet hash drift invalidates approval",
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def validate_deployment_approval_packet(
    packet: dict[str, Any],
    *,
    approval_hash: str,
    current_bound_facts: dict[str, Any],
) -> dict[str, Any]:
    if packet.get("schema_version") != DEPLOYMENT_SCHEMA_VERSION or packet.get("task_id") != DEPLOYMENT_TASK_ID:
        raise RuntimeError("deployment_approval_identity_invalid")
    if (
        packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("authorization_mode") != "exact_deployment_hash"
    ):
        raise RuntimeError("deployment_approval_mode_invalid")
    mode = str(current_bound_facts.get("deployment_mode") or "")
    if packet.get("allowed_operations") != list(_allowed_operations(mode)):
        raise RuntimeError("deployment_allowed_operations_invalid")
    if packet.get("forbidden_operations") != list(FORBIDDEN_OPERATIONS):
        raise RuntimeError("deployment_forbidden_operations_invalid")
    packet_hash = str(packet.get("packet_hash") or "")
    if approval_hash != packet_hash or canonical_packet_hash(packet) != packet_hash:
        raise RuntimeError("deployment_approval_hash_invalid")
    if packet.get("bound_facts") != current_bound_facts:
        raise RuntimeError("deployment_bound_fact_drift")
    _validate_bound_facts(current_bound_facts)
    return packet


def _validate_bound_facts(facts: dict[str, Any]) -> None:
    source_git = facts.get("source_git") or {}
    runtime = facts.get("runtime") or {}
    database = facts.get("database") or {}
    migration_chain = facts.get("migration_chain") or []
    mode = str(facts.get("deployment_mode") or "")
    backup = facts.get("schema_backup") or {}
    if set(source_git) != {"commit", "tracked_status_sha256"}:
        raise RuntimeError("deployment_source_identity_invalid")
    if (
        len(str(source_git.get("commit") or "")) != 40
        or source_git.get("tracked_status_sha256") != CLEAN_STATUS_SHA256
    ):
        raise RuntimeError("deployment_source_identity_invalid")
    if (
        not Path(str(runtime.get("root") or "")).is_absolute()
        or len(str(runtime.get("current_commit") or "")) != 40
        or runtime.get("target_commit") != source_git.get("commit")
        or runtime.get("tracked_status_sha256") != CLEAN_STATUS_SHA256
    ):
        raise RuntimeError("deployment_runtime_identity_invalid")
    schema_modes = {SCHEMA_UPGRADE_MODE, CHECKPOINT_RECOVERY_MODE}
    expected_revision = SOURCE_REVISION if mode in schema_modes else TARGET_REVISION
    if mode not in {*schema_modes, CHECKPOINT_RECOVERY_ONLY_MODE, CODE_ONLY_MODE}:
        raise RuntimeError("deployment_mode_invalid")
    if (
        not str(database.get("driver") or "").startswith("postgresql")
        or not database.get("database")
        or database.get("alembic_revision") != expected_revision
    ):
        raise RuntimeError("deployment_database_identity_invalid")
    expected_migrations = list(MIGRATION_REVISIONS) if mode in schema_modes else []
    if [item.get("revision") for item in migration_chain] != expected_migrations:
        raise RuntimeError("deployment_migration_chain_invalid")
    if any(
        len(str(item.get("sha256") or "")) != 64 or not Path(str(item.get("path") or "")).is_absolute()
        for item in migration_chain
    ):
        raise RuntimeError("deployment_migration_identity_invalid")
    if len(str(backup.get("sha256") or "")) != 64 or not Path(str(backup.get("path") or "")).is_absolute():
        raise RuntimeError("deployment_backup_identity_invalid")
    row_counts = facts.get("row_counts") or {}
    if set(row_counts) != set(ROW_COUNT_TABLES) or any(
        not isinstance(value, int) or value < 0 for value in row_counts.values()
    ):
        raise RuntimeError("deployment_row_counts_invalid")
    checkpoint_row_count = facts.get("checkpoint_row_count")
    if not isinstance(checkpoint_row_count, int) or checkpoint_row_count < 0:
        raise RuntimeError("deployment_checkpoint_row_count_invalid")
    if mode in {*schema_modes, CHECKPOINT_RECOVERY_ONLY_MODE} and checkpoint_row_count != 0:
        raise RuntimeError("deployment_checkpoint_row_count_invalid")
    recovery = facts.get("checkpoint_recovery")
    if mode in {CHECKPOINT_RECOVERY_MODE, CHECKPOINT_RECOVERY_ONLY_MODE}:
        try:
            from app.services.after_market_checkpoint_recovery import (
                validate_checkpoint_recovery_bound_facts,
            )

            validate_checkpoint_recovery_bound_facts(recovery or {})
        except RuntimeError as exc:
            raise RuntimeError("deployment_checkpoint_recovery_invalid") from exc
    elif recovery is not None:
        raise RuntimeError("deployment_checkpoint_recovery_invalid")
    api_runner = facts.get("api_runner") or {}
    expected_api_runner_keys = {
        "source_relative_path",
        "source_sha256",
        "destination_path",
        "destination_sha256",
        "launchd_plist_path",
        "launchd_plist_sha256",
        "launchd_label",
        "launchd_program_arguments",
        "launchd_project_root",
    }
    if (
        set(api_runner) != expected_api_runner_keys
        or api_runner.get("source_relative_path") != "scripts/ops/macos/run-local-service.sh"
        or any(
            len(str(api_runner.get(key) or "")) != 64
            for key in ("source_sha256", "destination_sha256", "launchd_plist_sha256")
        )
        or any(
            not Path(str(api_runner.get(key) or "")).is_absolute()
            for key in ("destination_path", "launchd_plist_path", "launchd_project_root")
        )
        or api_runner.get("launchd_label") != "com.guiyi.quant-api"
        or api_runner.get("launchd_program_arguments")
        != ["/bin/bash", api_runner.get("destination_path"), "api"]
        or api_runner.get("launchd_project_root") != runtime.get("root")
    ):
        raise RuntimeError("deployment_api_runner_identity_invalid")


def _allowed_operations(mode: str) -> tuple[str, ...]:
    if mode == SCHEMA_UPGRADE_MODE:
        return SCHEMA_UPGRADE_ALLOWED_OPERATIONS
    if mode == CHECKPOINT_RECOVERY_MODE:
        return CHECKPOINT_RECOVERY_ALLOWED_OPERATIONS
    if mode == CHECKPOINT_RECOVERY_ONLY_MODE:
        return CHECKPOINT_RECOVERY_ONLY_ALLOWED_OPERATIONS
    if mode == CODE_ONLY_MODE:
        return CODE_ONLY_ALLOWED_OPERATIONS
    raise RuntimeError("deployment_mode_invalid")
