from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    AfterMarketSchedulerCheckpoint,
    DataDownloadTask,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash


RECOVERY_TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DAY"
REQUIRED_PERIODS = frozenset({"1m", "5m", "15m", "30m", "60m", "1d"})
FORBIDDEN_COUNT_TABLES = {
    "signal_events": "signal_events",
    "signal_notifications": "signal_notifications",
    "signal_scan_tasks": "signal_scan_tasks",
    "strategy_signals": "strategy_signals",
}


class CheckpointRecoveryError(RuntimeError):
    """Raised when immutable S6-07 evidence cannot safely restore the checkpoint."""


def collect_checkpoint_recovery_bound_facts(
    session: Session,
    *,
    receipt_path: Path,
    outage_path: Path,
    failed_packet_path: Path,
) -> dict[str, Any]:
    receipt = _read_object(receipt_path, "recovery_last_success_receipt_missing")
    outage = _read_object(outage_path, "recovery_outage_snapshot_missing")
    packet = _read_object(failed_packet_path, "recovery_failed_execution_packet_missing")
    task_no = (
        f"archive:s607:jm:{str((packet.get('bound_facts') or {}).get('actual_contract') or '').upper()}:"
        f"{str((packet.get('bound_facts') or {}).get('trading_day') or '')}:"
        f"{str(packet.get('packet_hash') or '')[:12]}"
    )
    task = session.scalar(select(DataDownloadTask).where(DataDownloadTask.task_no == task_no))
    if task is None:
        raise CheckpointRecoveryError("recovery_failed_task_missing")
    asset_ids = [int(row["market_data_file_id"]) for row in receipt.get("assets") or []]
    database_assets = [
        {
            "market_data_file_id": row.id,
            "period": row.period,
            "data_version": row.data_version,
            "canonical_path": row.file_path,
            "checksum": row.checksum,
            "quality_status": row.quality_status,
        }
        for row in session.scalars(select(MarketDataFile).where(MarketDataFile.id.in_(asset_ids)))
    ]
    expected_binding_rows = list((receipt.get("consumer_profile_smoke") or {}).get("rows") or [])
    database_bindings: list[dict[str, Any]] = []
    for expected in expected_binding_rows:
        rows = list(
            session.scalars(
                select(ProfileActiveBinding).where(
                    ProfileActiveBinding.profile_id == expected["profile_id"],
                    ProfileActiveBinding.contract_code == expected["contract"],
                    ProfileActiveBinding.period == expected["period"],
                    ProfileActiveBinding.binding_status == "active",
                )
            )
        )
        if len(rows) != 1:
            raise CheckpointRecoveryError("recovery_active_binding_not_unique")
        row = rows[0]
        database_bindings.append(
            {
                "profile_id": row.profile_id,
                "contract": row.contract_code,
                "period": row.period,
                "data_version": row.data_version,
                "market_data_file_id": row.market_data_file_id,
                "quality_status": expected.get("quality_status"),
                "binding_status": row.binding_status,
            }
        )
    forbidden_counts = {
        key: _table_count(session, table)
        for key, table in FORBIDDEN_COUNT_TABLES.items()
    }
    return build_checkpoint_recovery_bound_facts(
        receipt=receipt,
        receipt_path=receipt_path,
        outage=outage,
        outage_path=outage_path,
        packet=packet,
        packet_path=failed_packet_path,
        failed_task={
            "task_no": task.task_no,
            "status": task.status,
            "error_message": task.error_message,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "result": task.result,
        },
        database_assets=database_assets,
        database_bindings=database_bindings,
        forbidden_counts=forbidden_counts,
    )


def build_checkpoint_recovery_bound_facts(
    *,
    receipt: Mapping[str, Any],
    receipt_path: Path,
    outage: Mapping[str, Any],
    outage_path: Path,
    packet: Mapping[str, Any],
    packet_path: Path,
    failed_task: Mapping[str, Any],
    database_assets: list[Mapping[str, Any]],
    database_bindings: list[Mapping[str, Any]],
    forbidden_counts: Mapping[str, int],
) -> dict[str, Any]:
    _validate_receipt(receipt)
    _validate_outage(outage, receipt=receipt, receipt_path=receipt_path)
    if canonical_packet_hash(dict(packet)) != packet.get("packet_hash"):
        raise CheckpointRecoveryError("recovery_execution_packet_hash_invalid")
    packet_facts = packet.get("bound_facts") or {}
    authorization_hash = str((outage.get("authorization") or {}).get("service_enable_packet_hash") or "")
    success_day = str(receipt.get("trading_day") or "")
    failed_day = str((outage.get("d2") or {}).get("trading_day") or "")
    if (
        packet.get("task_id") != RECOVERY_TASK_ID
        or packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet_facts.get("trading_day") != failed_day
        or packet_facts.get("actual_contract") != receipt.get("actual_contract")
        or packet_facts.get("parent_automation_approval_hash") != authorization_hash
    ):
        raise CheckpointRecoveryError("recovery_execution_packet_invalid")
    task_result = failed_task.get("result") or {}
    expected_task_no = (
        f"archive:s607:jm:{receipt['actual_contract']}:{failed_day}:"
        f"{str(packet['packet_hash'])[:12]}"
    )
    if (
        failed_task.get("task_no") != expected_task_no
        or failed_task.get("status") != "failed"
        or task_result.get("task_id") != RECOVERY_TASK_ID
        or task_result.get("packet_hash") != packet.get("packet_hash")
        or not task_result.get("error_type")
        or task_result.get("active_binding_changed") is not False
        or int(task_result.get("attempt_count") or 0) != 1
        or not failed_task.get("started_at")
        or not failed_task.get("finished_at")
    ):
        raise CheckpointRecoveryError("recovery_failed_task_invalid")
    _validate_database_assets(receipt, database_assets)
    _validate_database_bindings(receipt, database_bindings)
    expected_forbidden = outage.get("forbidden_counts") or {}
    if dict(forbidden_counts) != expected_forbidden:
        raise CheckpointRecoveryError("recovery_forbidden_counter_drift")
    recovery_facts = {
        "schema_version": 1,
        "restore_state": {
            "product": "jm",
            "exchange_code": "DCE",
            "status": "blocked",
            "authorization_hash": authorization_hash,
            "last_successful_trading_day": success_day,
            "current_trading_day": failed_day,
            "last_attempt_at": failed_task["started_at"],
            "last_success_at": None,
            "next_retry_at": None,
            "retry_count": 1,
            "last_error_type": str(task_result["error_type"]),
            "last_error_at": failed_task["finished_at"],
            "last_execution_packet_hash": str(receipt["packet_hash"]),
            "last_receipt_path": str(receipt_path.resolve(strict=False)),
        },
        "evidence": {
            "last_success_receipt": _file_identity(receipt_path, packet_hash=str(receipt["packet_hash"])),
            "outage_snapshot": _file_identity(outage_path),
            "failed_execution_packet": _file_identity(
                packet_path,
                packet_hash=str(packet["packet_hash"]),
            ),
            "failed_download_task": {
                "task_no": failed_task["task_no"],
                "error_type": task_result["error_type"],
                "attempt_count": 1,
                "started_at": failed_task["started_at"],
                "finished_at": failed_task["finished_at"],
            },
        },
        "database_verification": {
            "asset_count": len(database_assets),
            "active_binding_count": len(database_bindings),
            "asset_identity_sha256": _canonical_sha256(database_assets),
            "active_binding_identity_sha256": _canonical_sha256(database_bindings),
            "forbidden_counts": dict(forbidden_counts),
        },
    }
    validate_checkpoint_recovery_bound_facts(recovery_facts)
    return recovery_facts


def restore_checkpoint_from_recovery(
    session: Session,
    recovery_facts: Mapping[str, Any],
) -> AfterMarketSchedulerCheckpoint:
    state = recovery_facts.get("restore_state") or {}
    _validate_restore_state(state)
    existing = session.scalar(select(AfterMarketSchedulerCheckpoint).limit(1))
    if existing is not None:
        if verify_checkpoint_matches_recovery(session, recovery_facts):
            return existing
        raise CheckpointRecoveryError("recovery_checkpoint_not_empty")
    checkpoint = AfterMarketSchedulerCheckpoint(
        product=str(state["product"]),
        exchange_code=str(state["exchange_code"]),
        status=str(state["status"]),
        authorization_hash=str(state["authorization_hash"]),
        last_successful_trading_day=date.fromisoformat(str(state["last_successful_trading_day"])),
        current_trading_day=date.fromisoformat(str(state["current_trading_day"])),
        last_attempt_at=datetime.fromisoformat(str(state["last_attempt_at"])),
        last_success_at=None,
        next_retry_at=None,
        retry_count=int(state["retry_count"]),
        last_error_type=str(state["last_error_type"]),
        last_error_at=datetime.fromisoformat(str(state["last_error_at"])),
        last_execution_packet_hash=str(state["last_execution_packet_hash"]),
        last_receipt_path=str(state["last_receipt_path"]),
        last_result={
            "status": "checkpoint_recovered_from_immutable_evidence",
            "failed_trading_day": state["current_trading_day"],
            "recovery_evidence_sha256": _canonical_sha256(recovery_facts.get("evidence") or {}),
            "manual_retry_required": True,
        },
    )
    session.add(checkpoint)
    session.flush()
    return checkpoint


def validate_checkpoint_recovery_bound_facts(
    recovery_facts: Mapping[str, Any],
) -> None:
    if recovery_facts.get("schema_version") != 1:
        raise CheckpointRecoveryError("recovery_schema_invalid")
    state = recovery_facts.get("restore_state") or {}
    _validate_restore_state(state)
    evidence = recovery_facts.get("evidence") or {}
    expected_evidence = {
        "last_success_receipt",
        "outage_snapshot",
        "failed_execution_packet",
        "failed_download_task",
    }
    if set(evidence) != expected_evidence:
        raise CheckpointRecoveryError("recovery_evidence_invalid")
    for name in ("last_success_receipt", "outage_snapshot", "failed_execution_packet"):
        identity = evidence.get(name) or {}
        if (
            not Path(str(identity.get("path") or "")).is_absolute()
            or len(str(identity.get("sha256") or "")) != 64
        ):
            raise CheckpointRecoveryError("recovery_evidence_invalid")
    if (
        evidence["last_success_receipt"].get("packet_hash")
        != state.get("last_execution_packet_hash")
        or Path(str(evidence["last_success_receipt"].get("path") or "")).resolve(strict=False)
        != Path(str(state.get("last_receipt_path") or "")).resolve(strict=False)
    ):
        raise CheckpointRecoveryError("recovery_receipt_identity_invalid")
    task = evidence.get("failed_download_task") or {}
    failed_packet = evidence.get("failed_execution_packet") or {}
    failed_day = str(state.get("current_trading_day") or "")
    if (
        len(str(failed_packet.get("packet_hash") or "")) != 64
        or str(failed_packet["packet_hash"])[:12] not in str(task.get("task_no") or "")
        or failed_day not in str(task.get("task_no") or "")
        or task.get("error_type") != state.get("last_error_type")
        or task.get("attempt_count") != state.get("retry_count")
        or task.get("started_at") != state.get("last_attempt_at")
        or task.get("finished_at") != state.get("last_error_at")
    ):
        raise CheckpointRecoveryError("recovery_failed_task_identity_invalid")
    database = recovery_facts.get("database_verification") or {}
    forbidden = database.get("forbidden_counts") or {}
    if (
        database.get("asset_count") not in {6, 7}
        or database.get("active_binding_count") != 7
        or len(str(database.get("asset_identity_sha256") or "")) != 64
        or len(str(database.get("active_binding_identity_sha256") or "")) != 64
        or set(forbidden) != set(FORBIDDEN_COUNT_TABLES)
        or any(not isinstance(value, int) or value < 0 for value in forbidden.values())
    ):
        raise CheckpointRecoveryError("recovery_database_verification_invalid")


def verify_checkpoint_matches_recovery(
    session: Session,
    recovery_facts: Mapping[str, Any],
) -> bool:
    state = recovery_facts.get("restore_state") or {}
    checkpoint = session.scalar(
        select(AfterMarketSchedulerCheckpoint).where(
            AfterMarketSchedulerCheckpoint.product == state.get("product")
        )
    )
    if checkpoint is None:
        return False
    return (
        checkpoint.exchange_code == state.get("exchange_code")
        and checkpoint.status == state.get("status")
        and checkpoint.authorization_hash == state.get("authorization_hash")
        and checkpoint.last_successful_trading_day
        == date.fromisoformat(str(state.get("last_successful_trading_day")))
        and checkpoint.current_trading_day
        == date.fromisoformat(str(state.get("current_trading_day")))
        and checkpoint.retry_count == state.get("retry_count")
        and checkpoint.last_error_type == state.get("last_error_type")
        and checkpoint.last_execution_packet_hash == state.get("last_execution_packet_hash")
        and checkpoint.last_receipt_path == state.get("last_receipt_path")
        and (checkpoint.last_result or {}).get("manual_retry_required") is True
    )


def _validate_receipt(receipt: Mapping[str, Any]) -> None:
    smoke = receipt.get("consumer_profile_smoke") or {}
    periods = {str(row.get("period")) for row in receipt.get("assets") or []}
    if (
        receipt.get("status") != "completed"
        or receipt.get("gate") != "JM_EOD_ARCHIVE_DAY_PASSED"
        or not receipt.get("trading_day")
        or not receipt.get("actual_contract")
        or len(str(receipt.get("packet_hash") or "")) != 64
        or (receipt.get("registered_asset_smoke") or {}).get("status") != "passed"
        or smoke.get("status") != "passed"
        or int(smoke.get("verified_candidate_count") or 0) != 7
        or len(smoke.get("rows") or []) != 7
        or not REQUIRED_PERIODS.issubset(periods)
    ):
        raise CheckpointRecoveryError("recovery_last_success_receipt_invalid")


def _validate_outage(
    outage: Mapping[str, Any],
    *,
    receipt: Mapping[str, Any],
    receipt_path: Path,
) -> None:
    checkpoint = outage.get("checkpoint") or {}
    assertions = outage.get("assertions") or {}
    immutable = outage.get("immutable_evidence") or {}
    required_assertions = {
        "eligible_day_discovered_by_calendar",
        "scheduler_label_unloaded",
        "watermark_not_advanced",
        "archive_lag_is_one",
        "d2_receipt_absent",
        "d2_not_manually_archived",
        "d1_and_previous_assets_immutable",
        "forbidden_counts_unchanged",
        "authorization_matches_checkpoint",
    }
    if (
        outage.get("status") != "passed"
        or outage.get("evidence_type") != "d2_outage_pre_restart"
        or checkpoint.get("last_successful_trading_day") != receipt.get("trading_day")
        or checkpoint.get("authorization_hash")
        != (outage.get("authorization") or {}).get("service_enable_packet_hash")
        or checkpoint.get("last_execution_packet_hash") != receipt.get("packet_hash")
        or Path(str(checkpoint.get("last_receipt_path") or "")).resolve(strict=False)
        != receipt_path.resolve(strict=False)
        or (outage.get("d2") or {}).get("receipt_absent") is not True
        or (outage.get("d2") or {}).get("manifest_absent") is not True
        or (outage.get("d2") or {}).get("manual_trading_day_used") is not False
        or not all(assertions.get(key) is True for key in required_assertions)
        or immutable.get("mismatch_count") != 0
        or Path(str(immutable.get("previous_receipt_path") or "")).resolve(strict=False)
        != receipt_path.resolve(strict=False)
        or immutable.get("previous_receipt_sha256") != _sha256_file(receipt_path)
        or date.fromisoformat(str((outage.get("d2") or {}).get("trading_day")))
        <= date.fromisoformat(str(receipt.get("trading_day")))
    ):
        raise CheckpointRecoveryError("recovery_outage_snapshot_invalid")


def _validate_database_assets(
    receipt: Mapping[str, Any],
    database_assets: list[Mapping[str, Any]],
) -> None:
    expected = sorted(
        (
            int(row["market_data_file_id"]),
            str(row["period"]),
            str(row["data_version"]),
            str(row["canonical_path"]),
            str(row["checksum"]),
            str(row["quality_status"]),
        )
        for row in receipt.get("assets") or []
    )
    actual = sorted(
        (
            int(row["market_data_file_id"]),
            str(row["period"]),
            str(row["data_version"]),
            str(row["canonical_path"]),
            str(row["checksum"]),
            str(row["quality_status"]),
        )
        for row in database_assets
    )
    if actual != expected or any(row[-1] != "passed" for row in actual):
        raise CheckpointRecoveryError("recovery_database_asset_drift")


def _validate_database_bindings(
    receipt: Mapping[str, Any],
    database_bindings: list[Mapping[str, Any]],
) -> None:
    expected = sorted(
        (
            str(row["profile_id"]),
            str(row["contract"]),
            str(row["period"]),
            str(row["data_version"]),
            int(row["market_data_file_id"]),
        )
        for row in (receipt.get("consumer_profile_smoke") or {}).get("rows") or []
    )
    actual = sorted(
        (
            str(row["profile_id"]),
            str(row["contract"]),
            str(row["period"]),
            str(row["data_version"]),
            int(row["market_data_file_id"]),
        )
        for row in database_bindings
        if row.get("binding_status") == "active" and row.get("quality_status") == "passed"
    )
    if actual != expected:
        raise CheckpointRecoveryError("recovery_database_binding_drift")


def _validate_restore_state(state: Mapping[str, Any]) -> None:
    if (
        state.get("product") != "jm"
        or state.get("exchange_code") != "DCE"
        or state.get("status") != "blocked"
        or len(str(state.get("authorization_hash") or "")) != 64
        or int(state.get("retry_count") or 0) != 1
        or not state.get("last_successful_trading_day")
        or not state.get("current_trading_day")
        or not state.get("last_attempt_at")
        or not state.get("last_error_at")
        or not state.get("last_error_type")
        or len(str(state.get("last_execution_packet_hash") or "")) != 64
        or not Path(str(state.get("last_receipt_path") or "")).is_absolute()
    ):
        raise CheckpointRecoveryError("recovery_restore_state_invalid")


def _table_count(session: Session, table: str) -> int:
    from sqlalchemy import text

    return int(session.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())


def _read_object(path: Path, missing_error: str) -> dict[str, Any]:
    if not path.is_file():
        raise CheckpointRecoveryError(missing_error)
    try:
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckpointRecoveryError(f"{missing_error}_invalid") from exc
    if not isinstance(payload, dict):
        raise CheckpointRecoveryError(f"{missing_error}_invalid")
    return payload


def _file_identity(path: Path, *, packet_hash: str | None = None) -> dict[str, Any]:
    if not path.is_file() or not path.is_absolute():
        raise CheckpointRecoveryError("recovery_evidence_path_invalid")
    return {
        "path": str(path.resolve(strict=False)),
        "sha256": _sha256_file(path),
        **({"packet_hash": packet_hash} if packet_hash is not None else {}),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    import json

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
