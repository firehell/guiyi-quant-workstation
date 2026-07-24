from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
FINAL_GATE = "JM_EOD_INCREMENTAL_AUTOMATION_READY"
DAILY_GATE = "JM_EOD_ARCHIVE_DAY_PASSED"
DEPLOYMENT_GATE = "JM_EOD_AUTOMATION_DEPLOYMENT_PASSED"
TARGET_REVISION = "20260721_0025"
LAUNCHD_LABEL = "com.guiyi.quant-after-market-scheduler"
REQUIRED_PERIODS = {"1m", "5m", "15m", "30m", "60m", "1d"}
OPTIONAL_COMPLETED_PERIODS = {"1w"}
ALLOWED_WRITES = [
    "create_only_rqdata_parquet",
    "create_only_manifest_and_receipt",
    "market_data_metadata_and_quality",
    "profile_compare_and_switch",
    "after_market_scheduler_checkpoint",
]
FORBIDDEN_WRITES = ["signal_event", "notification", "strategy_signal", "order"]
FORBIDDEN_COUNTERS = (
    "signal_events",
    "signal_notifications",
    "signal_scan_tasks",
    "strategy_signals",
)


class RealAcceptanceError(RuntimeError):
    """Raised when S6-07 real acceptance evidence is incomplete or inconsistent."""


def build_real_acceptance_receipt(
    *,
    deployment_receipt_path: Path,
    enable_packet_path: Path,
    d1_enable_packet_path: Path | None = None,
    d2_outage_enable_packet_path: Path | None = None,
    d1_snapshot_path: Path,
    d2_outage_snapshot_path: Path,
    d2_completion_snapshot_path: Path,
    verifier_git: Mapping[str, str],
    deployment_is_ancestor: bool,
    d1_runtime_is_ancestor: bool = True,
    d2_outage_runtime_is_ancestor: bool = True,
) -> dict[str, Any]:
    deployment, deployment_artifact = _load_artifact(deployment_receipt_path)
    enable, enable_artifact = _load_artifact(enable_packet_path)
    d1_enable, d1_enable_artifact = _load_artifact(
        d1_enable_packet_path or enable_packet_path
    )
    outage_enable, outage_enable_artifact = _load_artifact(
        d2_outage_enable_packet_path or enable_packet_path
    )
    d1, d1_artifact = _load_artifact(d1_snapshot_path)
    outage, outage_artifact = _load_artifact(d2_outage_snapshot_path)
    completion, completion_artifact = _load_artifact(d2_completion_snapshot_path)

    _validate_deployment(deployment)
    runtime_commit = _validate_enable(enable)
    d1_runtime_commit = _validate_enable(d1_enable)
    outage_runtime_commit = _validate_enable(outage_enable)
    if not deployment_is_ancestor:
        raise RealAcceptanceError("deployment_lineage_invalid")
    if not d1_runtime_is_ancestor:
        raise RealAcceptanceError("d1_runtime_lineage_invalid")
    if not d2_outage_runtime_is_ancestor:
        raise RealAcceptanceError("d2_outage_runtime_lineage_invalid")
    _validate_verifier_git(verifier_git)

    enable_hash = str(enable["packet_hash"])
    d1_enable_hash = str(d1_enable["packet_hash"])
    d1_day = _validate_d1_snapshot(
        d1, runtime_commit=d1_runtime_commit, enable_hash=d1_enable_hash
    )
    d2_day, last_successful_before_outage = _validate_outage_snapshot(
        outage,
        runtime_commit=outage_runtime_commit,
        enable_hash=str(outage_enable["packet_hash"]),
        d1_day=d1_day,
        forbidden_baseline=d1["forbidden_counts"],
    )
    _validate_d2_completion_snapshot(
        completion,
        runtime_commit=runtime_commit,
        enable_hash=enable_hash,
        d1_day=d1_day,
        d2_day=d2_day,
        last_successful_before_outage=last_successful_before_outage,
        forbidden_baseline=d1["forbidden_counts"],
    )

    forbidden_deltas = {
        name: int(completion["forbidden_counts"][name])
        - int(d1["forbidden_counts"][name])
        for name in FORBIDDEN_COUNTERS
    }
    if any(forbidden_deltas.values()):
        raise RealAcceptanceError("forbidden_write_counter_changed")

    return {
        "schema_version": 2,
        "task_id": TASK_ID,
        "status": "completed",
        "gate": FINAL_GATE,
        "generated_at": _validated_generated_at(completion),
        "runtime_commit": runtime_commit,
        "authorization_hash": enable_hash,
        "database_revision": TARGET_REVISION,
        "deployment_lineage": {
            "deployment_commit": deployment["runtime_commit"],
            "runtime_commit": runtime_commit,
            "deployment_is_ancestor": True,
            "d1_runtime_commit": d1_runtime_commit,
            "d1_runtime_is_ancestor": True,
            "d2_outage_runtime_commit": outage_runtime_commit,
            "d2_outage_runtime_is_ancestor": True,
            "deployment_receipt": deployment_artifact,
            "service_enable_packet": enable_artifact,
            "d1_service_enable_packet": d1_enable_artifact,
            "d2_outage_service_enable_packet": outage_enable_artifact,
        },
        "verifier_git": dict(verifier_git),
        "d1": {
            "trading_day": d1_day.isoformat(),
            "batch_id": d1["d1"]["batch_id"],
            "execution_packet_hash": d1["d1"]["execution_packet_hash"],
            "receipt_sha256": d1["d1"]["receipt_sha256"],
            "runtime_commit": d1_runtime_commit,
            "authorization_hash": d1_enable_hash,
            "evidence": d1_artifact,
        },
        "d2_outage": {
            "trading_day": d2_day.isoformat(),
            "last_successful_before_outage": last_successful_before_outage.isoformat(),
            "archive_lag_trading_days": outage["health"]["archive_lag_trading_days"],
            "heartbeat": outage["health"]["scheduler_heartbeat"],
            "runtime_commit": outage_runtime_commit,
            "authorization_hash": str(outage_enable["packet_hash"]),
            "evidence": outage_artifact,
        },
        "d2": {
            "trading_day": d2_day.isoformat(),
            "batch_id": completion["d2"]["batch_id"],
            "execution_packet_hash": completion["d2"]["execution_packet_hash"],
            "receipt_sha256": completion["d2"]["receipt_sha256"],
            "evidence": completion_artifact,
        },
        "forbidden_write_counts": {
            "baseline": dict(d1["forbidden_counts"]),
            "final": dict(completion["forbidden_counts"]),
        },
        "forbidden_write_deltas": forbidden_deltas,
        "scope_boundaries": {
            "jm_eod_incremental_automation_ready": True,
            "jm_runtime_ready": False,
            "long_running_ready": False,
            "signal_event_ready": False,
            "notification_ready": False,
            "automatic_trading_ready": False,
        },
    }


def publish_real_acceptance_receipt(path: Path, receipt: Mapping[str, Any]) -> Path:
    normalized = json.loads(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, default=str)
    )
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RealAcceptanceError("real_acceptance_receipt_drift") from exc
        if current != normalized:
            raise RealAcceptanceError("real_acceptance_receipt_drift")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise RealAcceptanceError("real_acceptance_receipt_drift") from exc
    return path


def _validate_deployment(receipt: Mapping[str, Any]) -> None:
    if (
        receipt.get("task_id") != f"{TASK_ID}-DEPLOY"
        or receipt.get("status") != "completed"
        or receipt.get("gate") != DEPLOYMENT_GATE
        or receipt.get("database_revision") != TARGET_REVISION
        or receipt.get("after_market_scheduler_loaded") is not False
    ):
        raise RealAcceptanceError("deployment_receipt_invalid")
    _require_sha(
        str(receipt.get("runtime_commit") or ""),
        length=40,
        error="deployment_receipt_invalid",
    )


def _validate_enable(packet: Mapping[str, Any]) -> str:
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    facts = packet.get("bound_facts") or {}
    database = facts.get("database") or {}
    git = facts.get("git") or {}
    if (
        packet.get("schema_version") != 2
        or packet.get("task_id") != TASK_ID
        or packet.get("status") != "approval_required"
        or packet.get("product") != "jm"
        or packet.get("exchange") != "DCE"
        or packet.get("allowed_writes") != ALLOWED_WRITES
        or packet.get("forbidden_writes") != FORBIDDEN_WRITES
        or facts.get("launchd_label") != LAUNCHD_LABEL
        or database.get("alembic_revision") != TARGET_REVISION
    ):
        raise RealAcceptanceError("service_enable_packet_invalid")
    _require_sha(
        str(packet.get("packet_hash") or ""), error="service_enable_packet_invalid"
    )
    if canonical_packet_hash(dict(packet)) != packet.get("packet_hash"):
        raise RealAcceptanceError("service_enable_packet_hash_invalid")
    runtime_commit = str(git.get("commit") or "")
    _require_sha(runtime_commit, length=40, error="service_enable_packet_invalid")
    return runtime_commit


def _validate_verifier_git(identity: Mapping[str, str]) -> None:
    _require_sha(
        str(identity.get("commit") or ""),
        length=40,
        error="verifier_git_invalid",
        hexadecimal=False,
    )
    if identity.get("tracked_status_sha256") != hashlib.sha256(b"").hexdigest():
        raise RealAcceptanceError("verifier_git_invalid")


def _validate_d1_snapshot(
    snapshot: Mapping[str, Any], *, runtime_commit: str, enable_hash: str
) -> date:
    _validate_snapshot_identity(
        snapshot, "d1_normal_automatic_archive_baseline", runtime_commit, enable_hash
    )
    day = _validate_day(snapshot.get("d1") or {})
    checkpoint = snapshot.get("checkpoint") or {}
    health = snapshot.get("health") or {}
    if (
        checkpoint.get("last_successful_trading_day") != day.isoformat()
        or checkpoint.get("current_trading_day") is not None
        or checkpoint.get("retry_count") != 0
        or checkpoint.get("last_error_type") is not None
        or health.get("archive_lag_trading_days") != 0
        or health.get("active_binding_end") != day.isoformat()
        or not _all_assertions_pass(snapshot)
    ):
        raise RealAcceptanceError("d1_snapshot_invalid")
    _validate_forbidden_counts(snapshot.get("forbidden_counts"))
    return day


def _validate_outage_snapshot(
    snapshot: Mapping[str, Any],
    *,
    runtime_commit: str,
    enable_hash: str,
    d1_day: date,
    forbidden_baseline: Mapping[str, Any],
) -> tuple[date, date]:
    _validate_snapshot_identity(
        snapshot, "d2_outage_pre_restart", runtime_commit, enable_hash
    )
    d2 = snapshot.get("d2") or {}
    health = snapshot.get("health") or {}
    heartbeat = health.get("scheduler_heartbeat") or {}
    try:
        d2_day = date.fromisoformat(str(d2.get("trading_day") or ""))
        last_successful_before_outage = date.fromisoformat(
            str(
                (snapshot.get("checkpoint") or {}).get(
                    "last_successful_trading_day"
                )
                or ""
            )
        )
    except ValueError as exc:
        raise RealAcceptanceError("d2_outage_snapshot_invalid") from exc
    if (
        last_successful_before_outage < d1_day
        or d2_day <= last_successful_before_outage
        or snapshot.get("enabled") is not True
        or (snapshot.get("launchd") or {}).get("loaded") is not False
        or d2.get("receipt_absent") is not True
        or snapshot.get("d1_unchanged") is not True
        or not _all_assertions_pass(snapshot)
    ):
        raise RealAcceptanceError("d2_outage_snapshot_invalid")
    if health.get("archive_lag_trading_days") != 1:
        raise RealAcceptanceError("d2_outage_lag_invalid")
    if heartbeat.get("status") != "degraded" or heartbeat.get("error_type") not in {
        "heartbeat_missing",
        "heartbeat_stale",
    }:
        raise RealAcceptanceError("d2_outage_heartbeat_invalid")
    _require_same_counts(forbidden_baseline, snapshot.get("forbidden_counts"))
    return d2_day, last_successful_before_outage


def _validate_d2_completion_snapshot(
    snapshot: Mapping[str, Any],
    *,
    runtime_commit: str,
    enable_hash: str,
    d1_day: date,
    d2_day: date,
    last_successful_before_outage: date,
    forbidden_baseline: Mapping[str, Any],
) -> None:
    _validate_snapshot_identity(
        snapshot, "d2_automatic_catchup_completion", runtime_commit, enable_hash
    )
    day = _validate_day(snapshot.get("d2") or {})
    checkpoint = snapshot.get("checkpoint") or {}
    health = snapshot.get("health") or {}
    if snapshot.get("d1_unchanged") is not True:
        raise RealAcceptanceError("d1_immutable_verification_failed")
    if (
        day != d2_day
        or day <= d1_day
        or day <= last_successful_before_outage
        or checkpoint.get("last_successful_trading_day") != day.isoformat()
        or checkpoint.get("current_trading_day") is not None
        or checkpoint.get("retry_count") != 0
        or checkpoint.get("last_error_type") is not None
        or health.get("archive_lag_trading_days") != 0
        or health.get("active_binding_end") != day.isoformat()
        or not _all_assertions_pass(snapshot)
    ):
        raise RealAcceptanceError("d2_completion_snapshot_invalid")
    _require_same_counts(forbidden_baseline, snapshot.get("forbidden_counts"))


def _validate_snapshot_identity(
    snapshot: Mapping[str, Any],
    evidence_type: str,
    runtime_commit: str,
    enable_hash: str,
) -> None:
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("task_id") != TASK_ID
        or snapshot.get("evidence_type") != evidence_type
        or snapshot.get("status") != "passed"
        or (snapshot.get("runtime") or {}).get("commit") != runtime_commit
        or (snapshot.get("authorization") or {}).get("service_enable_packet_hash")
        != enable_hash
    ):
        raise RealAcceptanceError("real_acceptance_snapshot_identity_invalid")


def _validate_day(evidence: Mapping[str, Any]) -> date:
    try:
        trading_day = date.fromisoformat(str(evidence.get("trading_day") or ""))
    except ValueError as exc:
        raise RealAcceptanceError("daily_evidence_invalid") from exc
    assets = evidence.get("assets") or []
    periods = {str(asset.get("period")) for asset in assets}
    allowed_periods = REQUIRED_PERIODS | OPTIONAL_COMPLETED_PERIODS
    stability = evidence.get("provider_final_stability") or {}
    immutable = evidence.get("immutable_active_assets") or {}
    if (
        evidence.get("gate") != DAILY_GATE
        or not REQUIRED_PERIODS.issubset(periods)
        or not periods.issubset(allowed_periods)
        or len(assets) != len(periods)
        or any(
            asset.get("quality_status") != "passed"
            or asset.get("checksum_match") is not True
            for asset in assets
        )
        or (evidence.get("manifest") or {}).get("row_count") != len(assets)
        or stability.get("stable") is not True
        or stability.get("check_count") != 2
        or any(
            item.get("checksum_match") is not True
            for item in immutable.get("files") or []
        )
    ):
        raise RealAcceptanceError("daily_evidence_invalid")
    _require_sha(
        str(evidence.get("execution_packet_hash") or ""), error="daily_evidence_invalid"
    )
    _require_sha(
        str(evidence.get("receipt_sha256") or ""), error="daily_evidence_invalid"
    )
    _require_sha(
        str(evidence.get("parent_automation_approval_hash") or ""),
        error="daily_evidence_invalid",
    )
    return trading_day


def _validate_forbidden_counts(counts: Any) -> None:
    if not isinstance(counts, Mapping) or set(counts) != set(FORBIDDEN_COUNTERS):
        raise RealAcceptanceError("forbidden_write_counts_invalid")
    if any(
        not isinstance(counts[name], int) or counts[name] < 0
        for name in FORBIDDEN_COUNTERS
    ):
        raise RealAcceptanceError("forbidden_write_counts_invalid")


def _require_same_counts(baseline: Mapping[str, Any], current: Any) -> None:
    _validate_forbidden_counts(baseline)
    _validate_forbidden_counts(current)
    if dict(current) != dict(baseline):
        raise RealAcceptanceError("forbidden_write_counter_changed")


def _all_assertions_pass(snapshot: Mapping[str, Any]) -> bool:
    assertions = snapshot.get("assertions")
    return (
        isinstance(assertions, Mapping)
        and bool(assertions)
        and all(value is True for value in assertions.values())
    )


def _validated_generated_at(snapshot: Mapping[str, Any]) -> str:
    value = str(snapshot.get("generated_at") or "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RealAcceptanceError("real_acceptance_generated_at_invalid") from exc
    if parsed.tzinfo is None:
        raise RealAcceptanceError("real_acceptance_generated_at_invalid")
    return value


def _load_artifact(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    if not path.is_file():
        raise RealAcceptanceError("real_acceptance_artifact_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealAcceptanceError("real_acceptance_artifact_invalid") from exc
    if not isinstance(payload, dict):
        raise RealAcceptanceError("real_acceptance_artifact_invalid")
    return payload, {
        "path": str(path.resolve(strict=False)),
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(
    value: str, *, error: str, length: int = 64, hexadecimal: bool = True
) -> None:
    if len(value) != length or (
        hexadecimal and any(character not in "0123456789abcdef" for character in value)
    ):
        raise RealAcceptanceError(error)


__all__ = [
    "FINAL_GATE",
    "RealAcceptanceError",
    "build_real_acceptance_receipt",
    "publish_real_acceptance_receipt",
]
