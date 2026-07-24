from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash
from app.models.data_center import AfterMarketSchedulerCheckpoint
from app.services.after_market_archive_gate import (
    ArchiveGateError,
    ArchiveGateIdentity,
    _recover_committed_archive,
    collect_delegated_archive_packet,
    execute_archive,
    validate_approval_packet,
)
from app.services.provider_readiness import ProviderReadinessError
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import OperationalError


PRODUCT = "jm"
EXCHANGE = "DCE"
TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
ENABLE_PACKET_SCHEMA_VERSION = 2
REQUIRED_ALEMBIC_REVISION = "20260721_0025"
DAILY_TASK_ID = f"{TASK_ID}-DAY"
DAILY_SUCCESS_GATE = "JM_EOD_ARCHIVE_DAY_PASSED"
SAFE_DELAY_MINUTES = 120
MAX_CATCHUP_DAYS = 5
RETRY_DELAYS_MINUTES = (5, 15, 30, 60, 120, 240)
ALLOWED_WRITES = (
    "create_only_rqdata_parquet",
    "create_only_manifest_and_receipt",
    "market_data_metadata_and_quality",
    "profile_compare_and_switch",
    "after_market_scheduler_checkpoint",
)
FORBIDDEN_WRITES = ("signal_event", "notification", "strategy_signal", "order")
SHANGHAI = ZoneInfo("Asia/Shanghai")
S6_07_DAILY_IDENTITY = ArchiveGateIdentity(
    task_id=DAILY_TASK_ID,
    batch_prefix="s607",
    success_gate=DAILY_SUCCESS_GATE,
    audit_namespace="jm_eod_incremental_s6_07",
    strict_recovery=True,
)


class AfterMarketAutomationError(RuntimeError):
    """Raised when the S6-07 scheduler cannot proceed safely."""


@dataclass(frozen=True)
class EligibilityResult:
    days: tuple[date, ...]
    latest_completed_trading_day: date
    latest_eligible_trading_day: date | None
    archive_lag_trading_days: int


@dataclass(frozen=True)
class AutomationPolicy:
    safe_delay_minutes: int = SAFE_DELAY_MINUTES
    max_catchup_days: int = MAX_CATCHUP_DAYS
    retry_delays_minutes: tuple[int, ...] = RETRY_DELAYS_MINUTES
    provider_stability_checks: int = 2
    provider_stability_interval_seconds: int = 30
    scan_interval_seconds: int = 300
    heartbeat_interval_seconds: int = 60
    lock_lease_seconds: int = 180


@dataclass(frozen=True)
class DailyArchiveResult:
    status: str
    packet_hash: str | None = None
    receipt_path: str | None = None
    error_type: str | None = None
    retryable: bool = False
    details: dict[str, Any] | None = None


class AfterMarketAutomationService:
    def __init__(
        self,
        *,
        session: Session,
        clock: Any,
        daily_runner: Callable[[date], DailyArchiveResult],
        now: datetime | None = None,
        policy: AutomationPolicy | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        self.daily_runner = daily_runner
        self.now = now or datetime.now(UTC)
        self.policy = policy or AutomationPolicy()

    def run_once(self, *, checkpoint: AfterMarketSchedulerCheckpoint) -> dict[str, Any]:
        if checkpoint.status == "blocked":
            return self._payload(checkpoint)
        if checkpoint.next_retry_at is not None and _local_naive(self.now) < _local_naive(checkpoint.next_retry_at):
            return self._payload(checkpoint)
        if checkpoint.last_successful_trading_day is None:
            raise AfterMarketAutomationError("scheduler_watermark_missing")
        eligibility = discover_eligible_trading_days(
            last_successful_trading_day=checkpoint.last_successful_trading_day,
            now=self.now,
            clock=self.clock,
            product=checkpoint.product,
            exchange=checkpoint.exchange_code,
            safe_delay_minutes=self.policy.safe_delay_minutes,
            max_catchup_days=self.policy.max_catchup_days,
        )
        if not eligibility.days:
            checkpoint.status = "idle"
            checkpoint.current_trading_day = None
            checkpoint.next_retry_at = None
            _set_checkpoint_last_result(checkpoint, self._eligibility_payload(eligibility))
            self.session.commit()
            return self._payload(checkpoint)

        for trading_day in eligibility.days:
            checkpoint.status = "running"
            checkpoint.current_trading_day = trading_day
            checkpoint.last_attempt_at = self.now
            self.session.commit()
            try:
                outcome = self.daily_runner(trading_day)
            except Exception as exc:  # noqa: BLE001 - scheduler converts failures into durable state.
                error_type, retryable = classify_scheduler_exception(exc)
                outcome = DailyArchiveResult(status="failed", error_type=error_type, retryable=retryable)
            if outcome.status in {"success", "already_archived"}:
                checkpoint.status = "success"
                checkpoint.last_successful_trading_day = trading_day
                checkpoint.current_trading_day = None
                checkpoint.last_success_at = self.now
                checkpoint.next_retry_at = None
                checkpoint.retry_count = 0
                checkpoint.last_error_type = None
                checkpoint.last_error_at = None
                checkpoint.last_execution_packet_hash = outcome.packet_hash
                checkpoint.last_receipt_path = outcome.receipt_path
                _set_checkpoint_last_result(checkpoint, {
                    "status": outcome.status,
                    "trading_day": trading_day.isoformat(),
                    **(outcome.details or {}),
                })
                self.session.commit()
                continue
            if outcome.status == "waiting_provider":
                checkpoint.status = "waiting_provider"
                checkpoint.next_retry_at = self.now + timedelta(seconds=self.policy.scan_interval_seconds)
                _set_checkpoint_last_result(
                    checkpoint,
                    {"status": outcome.status, "trading_day": trading_day.isoformat()},
                )
                self.session.commit()
                return self._payload(checkpoint)
            checkpoint.retry_count += 1
            checkpoint.last_error_type = outcome.error_type or "after_market_archive_failed"
            checkpoint.last_error_at = self.now
            _set_checkpoint_last_result(checkpoint, {
                "status": "failed",
                "trading_day": trading_day.isoformat(),
                "error_type": checkpoint.last_error_type,
                "retryable": outcome.retryable,
            })
            if outcome.retryable and checkpoint.retry_count <= len(self.policy.retry_delays_minutes):
                checkpoint.status = "retry_wait"
                delay = self.policy.retry_delays_minutes[checkpoint.retry_count - 1]
                checkpoint.next_retry_at = self.now + timedelta(minutes=delay)
            else:
                checkpoint.status = "blocked"
                checkpoint.next_retry_at = None
            self.session.commit()
            return self._payload(checkpoint)
        return self._payload(checkpoint)

    @staticmethod
    def reset_failed_day(
        checkpoint: AfterMarketSchedulerCheckpoint,
        *,
        trading_day: date,
        confirmed: bool,
    ) -> None:
        if not confirmed:
            raise AfterMarketAutomationError("explicit_retry_confirmation_required")
        if checkpoint.status != "blocked" or checkpoint.current_trading_day != trading_day:
            raise AfterMarketAutomationError("retry_day_mismatch")
        checkpoint.status = "retry_wait"
        checkpoint.retry_count = 0
        checkpoint.next_retry_at = None
        checkpoint.last_error_type = None
        checkpoint.last_error_at = None
        _set_checkpoint_last_result(
            checkpoint,
            {"status": "manual_retry_armed", "trading_day": trading_day.isoformat()},
        )

    @staticmethod
    def _eligibility_payload(result: EligibilityResult) -> dict[str, Any]:
        return {
            "status": "idle",
            "latest_completed_trading_day": result.latest_completed_trading_day.isoformat(),
            "latest_eligible_trading_day": (
                result.latest_eligible_trading_day.isoformat() if result.latest_eligible_trading_day else None
            ),
            "archive_lag_trading_days": result.archive_lag_trading_days,
        }

    @staticmethod
    def _payload(checkpoint: AfterMarketSchedulerCheckpoint) -> dict[str, Any]:
        return {
            "status": checkpoint.status,
            "last_successful_trading_day": (
                checkpoint.last_successful_trading_day.isoformat()
                if checkpoint.last_successful_trading_day
                else None
            ),
            "current_trading_day": checkpoint.current_trading_day.isoformat() if checkpoint.current_trading_day else None,
            "retry_count": checkpoint.retry_count,
            "next_retry_at": checkpoint.next_retry_at.isoformat() if checkpoint.next_retry_at else None,
            "last_error_type": checkpoint.last_error_type,
        }


def run_delegated_archive_day(
    *,
    session: Session,
    client: Any,
    output_root: Path,
    project_root: Path,
    trading_day: date,
    now: datetime,
    git_identity: dict[str, Any],
    database_identity: dict[str, Any],
    parent_automation_approval_hash: str,
    policy: AutomationPolicy | None = None,
) -> DailyArchiveResult:
    selected_policy = policy or AutomationPolicy()
    ensure_output_root_available(output_root)
    batch_id = f"{S6_07_DAILY_IDENTITY.batch_prefix}_{trading_day:%Y%m%d}_{str(git_identity['commit'])[:8]}"
    audit_root = output_root / "reports" / S6_07_DAILY_IDENTITY.audit_namespace / batch_id
    packet_path = audit_root / "execution_packet.json"
    if packet_path.is_file():
        try:
            existing_packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AfterMarketAutomationError("daily_execution_packet_drift") from exc
        validate_approval_packet(
            existing_packet,
            output_root=output_root,
            identity=S6_07_DAILY_IDENTITY,
        )
        existing_bound = existing_packet.get("bound_facts") or {}
        if (
            existing_bound.get("parent_automation_approval_hash") != parent_automation_approval_hash
            or existing_bound.get("trading_day") != trading_day.isoformat()
            or (existing_bound.get("git") or {}).get("commit") != git_identity.get("commit")
        ):
            raise AfterMarketAutomationError("daily_execution_packet_drift")
        recovered = _recover_committed_archive(
            session,
            packet=existing_packet,
            project_root=project_root,
            identity=S6_07_DAILY_IDENTITY,
        )
        if recovered is not None:
            return DailyArchiveResult(
                status="already_archived",
                packet_hash=str(existing_packet["packet_hash"]),
                receipt_path=str(recovered["receipt_path"]),
                details={"gate": S6_07_DAILY_IDENTITY.success_gate, "evidence_reverified": True},
            )
    try:
        packet = collect_delegated_archive_packet(
            session,
            client=client,
            output_root=output_root,
            trading_day=trading_day,
            now=now,
            git_identity=git_identity,
            database_identity=database_identity,
            parent_automation_approval_hash=parent_automation_approval_hash,
            readiness_timeout_seconds=0,
            readiness_poll_seconds=selected_policy.scan_interval_seconds,
            provider_stability_checks=selected_policy.provider_stability_checks,
            provider_stability_interval_seconds=selected_policy.provider_stability_interval_seconds,
            identity=S6_07_DAILY_IDENTITY,
        )
    except ProviderReadinessError as exc:
        reason = str(exc).split(":", 1)[0]
        waiting_reasons = {
            "provider_data_pending",
            "provider_data_stale",
            "provider_expected_date_mismatch",
            "provider_target_rows_missing",
            "provider_target_row_count_mismatch",
        }
        if reason in waiting_reasons:
            return DailyArchiveResult(status="waiting_provider", error_type=reason)
        return DailyArchiveResult(status="failed", error_type=reason, retryable=True)
    audit_root = Path(str(packet["execution_plan"]["audit_root"]))
    packet_path = audit_root / "execution_packet.json"
    _write_create_only_packet(packet_path, packet)
    result = execute_archive(
        session,
        client=client,
        packet=packet,
        approval_hash=str(packet["packet_hash"]),
        current_packet=packet,
        output_root=output_root,
        project_root=project_root,
        identity=S6_07_DAILY_IDENTITY,
    )
    status = str(result.get("status") or "failed")
    if status not in {"success", "already_archived"}:
        return DailyArchiveResult(
            status="failed",
            packet_hash=str(packet["packet_hash"]),
            error_type=str(result.get("error_type") or "after_market_archive_failed"),
            retryable=False,
        )
    return DailyArchiveResult(
        status=status,
        packet_hash=str(packet["packet_hash"]),
        receipt_path=str(audit_root / "completion_receipt.json"),
        details={"gate": result.get("gate") or DAILY_SUCCESS_GATE},
    )


def load_or_seed_checkpoint(
    session: Session,
    *,
    authorization_hash: str,
    foundation_receipt: dict[str, Any],
    allow_authorization_rotation: bool = False,
    authorization_rotation_failed_day: date | None = None,
) -> AfterMarketSchedulerCheckpoint:
    _validate_foundation_receipt(foundation_receipt)
    checkpoint = session.scalar(
        select(AfterMarketSchedulerCheckpoint).where(AfterMarketSchedulerCheckpoint.product == PRODUCT)
    )
    if checkpoint is not None:
        if checkpoint.authorization_hash != authorization_hash:
            idle_rotation = _checkpoint_can_rotate_authorization(checkpoint)
            failed_day_rotation = _checkpoint_can_rotate_failed_day_authorization(
                checkpoint,
                authorization_rotation_failed_day,
            )
            if not allow_authorization_rotation or not (idle_rotation or failed_day_rotation):
                raise AfterMarketAutomationError("checkpoint_authorization_hash_mismatch")
            previous_authorization_hash = checkpoint.authorization_hash
            checkpoint.authorization_hash = authorization_hash
            previous_result = checkpoint.last_result or {}
            authorization_history = list(previous_result.get("authorization_history") or [])
            authorization_history.append(
                {
                    "previous_authorization_hash": previous_authorization_hash,
                    "authorization_hash": authorization_hash,
                    "rotated_at": datetime.now(UTC).isoformat(),
                    "reason": (
                        "explicit_failed_day_retry"
                        if failed_day_rotation
                        else "idle_authorization_rotation"
                    ),
                }
            )
            checkpoint.last_result = {**previous_result, "authorization_history": authorization_history}
            session.flush()
        return checkpoint
    checkpoint = AfterMarketSchedulerCheckpoint(
        product=PRODUCT,
        exchange_code=EXCHANGE,
        status="idle",
        authorization_hash=authorization_hash,
        last_successful_trading_day=date.fromisoformat(str(foundation_receipt["trading_day"])),
        retry_count=0,
        last_result={
            "status": "seeded_from_jm_archive_passed",
            "foundation_packet_hash": foundation_receipt["packet_hash"],
        },
    )
    session.add(checkpoint)
    session.flush()
    return checkpoint


def _checkpoint_can_rotate_authorization(checkpoint: AfterMarketSchedulerCheckpoint) -> bool:
    return (
        checkpoint.status in {"idle", "success"}
        and checkpoint.current_trading_day is None
        and checkpoint.retry_count == 0
        and checkpoint.next_retry_at is None
        and checkpoint.last_error_type is None
        and checkpoint.last_error_at is None
    )


def _checkpoint_can_rotate_failed_day_authorization(
    checkpoint: AfterMarketSchedulerCheckpoint,
    failed_day: date | None,
) -> bool:
    return (
        failed_day is not None
        and checkpoint.status == "blocked"
        and checkpoint.current_trading_day == failed_day
        and checkpoint.retry_count > 0
        and checkpoint.next_retry_at is None
        and checkpoint.last_error_type is not None
        and checkpoint.last_error_at is not None
    )


def _set_checkpoint_last_result(
    checkpoint: AfterMarketSchedulerCheckpoint,
    payload: dict[str, Any],
) -> None:
    authorization_history = list((checkpoint.last_result or {}).get("authorization_history") or [])
    checkpoint.last_result = {
        **payload,
        **({"authorization_history": authorization_history} if authorization_history else {}),
    }


def _write_create_only_packet(path: Path, packet: dict[str, Any]) -> None:
    import json

    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AfterMarketAutomationError("daily_execution_packet_drift") from exc
        if current != packet:
            raise AfterMarketAutomationError("daily_execution_packet_drift")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def classify_scheduler_exception(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, AfterMarketAutomationError):
        return str(exc).split(":", 1)[0], False
    if isinstance(exc, ArchiveGateError):
        reason = str(exc).split(":", 1)[0]
        permanent_prefixes = (
            "approval_",
            "bound_fact_",
            "execution_contract_",
            "registered_asset_",
            "consumer_",
            "immutable_",
            "quality_",
            "parent_automation_",
            "provider_final_minute_key_mismatch",
            "provider_final_hash_unstable",
            "jm_actual_contract_required",
        )
        return reason, not reason.startswith(permanent_prefixes)
    return type(exc).__name__, isinstance(exc, (ConnectionError, TimeoutError, OSError, OperationalError))


def build_enable_approval_packet(
    *,
    bound_facts: dict[str, Any],
    foundation_receipt: dict[str, Any],
    foundation_receipt_path: Path,
    policy: AutomationPolicy,
) -> dict[str, Any]:
    _validate_foundation_receipt(foundation_receipt)
    packet: dict[str, Any] = {
        "schema_version": ENABLE_PACKET_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "approval_required",
        "product": PRODUCT,
        "exchange": EXCHANGE,
        "writes_authorized": False,
        "authorization_mode": "service_scope",
        "bound_facts": bound_facts,
        "foundation_receipt": {
            "path": str(foundation_receipt_path.resolve(strict=False)),
            "sha256": _file_sha256(foundation_receipt_path),
            "gate": foundation_receipt["gate"],
            "trading_day": foundation_receipt["trading_day"],
            "actual_contract": foundation_receipt["actual_contract"],
            "packet_hash": foundation_receipt["packet_hash"],
        },
        "policy": _policy_payload(policy),
        "allowed_writes": list(ALLOWED_WRITES),
        "forbidden_writes": list(FORBIDDEN_WRITES),
        "invalidation_rule": "any bound fact, foundation receipt, policy, or packet hash drift invalidates approval",
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def validate_enable_approval_packet(
    packet: dict[str, Any],
    *,
    approval_hash: str,
    current_bound_facts: dict[str, Any],
    foundation_receipt: dict[str, Any],
) -> dict[str, Any]:
    if packet.get("schema_version") != ENABLE_PACKET_SCHEMA_VERSION or packet.get("task_id") != TASK_ID:
        raise AfterMarketAutomationError("automation_approval_identity_invalid")
    if packet.get("product") != PRODUCT or packet.get("exchange") != EXCHANGE:
        raise AfterMarketAutomationError("automation_approval_scope_invalid")
    if (
        packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("authorization_mode") != "service_scope"
    ):
        raise AfterMarketAutomationError("automation_approval_mode_invalid")
    if packet.get("allowed_writes") != list(ALLOWED_WRITES) or packet.get("forbidden_writes") != list(FORBIDDEN_WRITES):
        raise AfterMarketAutomationError("automation_write_scope_invalid")
    packet_hash = str(packet.get("packet_hash") or "")
    if approval_hash != packet_hash or canonical_packet_hash(packet) != packet_hash:
        raise AfterMarketAutomationError("automation_approval_hash_invalid")
    if packet.get("bound_facts") != current_bound_facts:
        raise AfterMarketAutomationError("automation_bound_fact_drift")
    _validate_bound_facts(current_bound_facts)
    _validate_foundation_receipt(foundation_receipt)
    foundation = packet.get("foundation_receipt") or {}
    foundation_path = Path(str(foundation.get("path") or ""))
    if foundation.get("sha256") != _file_sha256(foundation_path):
        raise AfterMarketAutomationError("automation_foundation_receipt_drift")
    for field in ("gate", "trading_day", "actual_contract", "packet_hash"):
        if foundation.get(field) != foundation_receipt.get(field):
            raise AfterMarketAutomationError("automation_foundation_receipt_drift")
    _validate_policy_payload(packet.get("policy") or {})
    return packet


def _policy_payload(policy: AutomationPolicy) -> dict[str, Any]:
    payload = asdict(policy)
    payload["retry_delays_minutes"] = list(policy.retry_delays_minutes)
    return payload


def _validate_policy_payload(payload: dict[str, Any]) -> None:
    expected = _policy_payload(AutomationPolicy())
    if payload != expected:
        raise AfterMarketAutomationError("automation_policy_invalid")


def _validate_bound_facts(facts: dict[str, Any]) -> None:
    git = facts.get("git") or {}
    database = facts.get("database") or {}
    if len(str(git.get("commit") or "")) != 40 or len(str(git.get("tracked_status_sha256") or "")) != 64:
        raise AfterMarketAutomationError("automation_git_identity_invalid")
    if len(str(facts.get("dependency_lock_sha256") or "")) != 64:
        raise AfterMarketAutomationError("automation_dependency_identity_invalid")
    if not str(database.get("driver") or "").startswith("postgresql") or not database.get("database"):
        raise AfterMarketAutomationError("automation_database_identity_invalid")
    if database.get("alembic_revision") != REQUIRED_ALEMBIC_REVISION:
        raise AfterMarketAutomationError("automation_database_revision_invalid")
    if not Path(str(facts.get("runtime_root") or "")).is_absolute():
        raise AfterMarketAutomationError("automation_runtime_root_invalid")
    if not Path(str(facts.get("output_root") or "")).is_absolute():
        raise AfterMarketAutomationError("automation_output_root_invalid")
    if not isinstance(facts.get("output_device"), int):
        raise AfterMarketAutomationError("automation_output_device_invalid")
    if facts.get("launchd_label") != "com.guiyi.quant-after-market-scheduler":
        raise AfterMarketAutomationError("automation_launchd_label_invalid")


def _validate_foundation_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("gate") != "JM_ARCHIVE_PASSED" or receipt.get("status") != "completed":
        raise AfterMarketAutomationError("jm_archive_passed_receipt_required")
    if not receipt.get("trading_day") or not receipt.get("actual_contract") or not receipt.get("packet_hash"):
        raise AfterMarketAutomationError("foundation_receipt_incomplete")
    for field in ("registered_asset_smoke", "consumer_profile_smoke", "immutable_active_assets"):
        if (receipt.get(field) or {}).get("status") != "passed":
            raise AfterMarketAutomationError(f"foundation_receipt_{field}_not_passed")


def _file_sha256(path: Path) -> str:
    import hashlib

    if not path.is_file():
        raise AfterMarketAutomationError("automation_foundation_receipt_missing")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_eligible_trading_days(
    *,
    last_successful_trading_day: date,
    now: datetime,
    clock: Any,
    product: str = PRODUCT,
    exchange: str = EXCHANGE,
    safe_delay_minutes: int = SAFE_DELAY_MINUTES,
    max_catchup_days: int = MAX_CATCHUP_DAYS,
) -> EligibilityResult:
    current = _local_naive(now)
    latest_completed = clock.latest_completed_trading_day(product=product, exchange=exchange, now=now)
    if latest_completed <= last_successful_trading_day:
        return EligibilityResult((), latest_completed, None, 0)
    candidates, complete = clock.trading_days_between(
        last_successful_trading_day + timedelta(days=1),
        latest_completed,
        exchange=exchange,
    )
    if not complete:
        raise AfterMarketAutomationError("trading_calendar_incomplete")
    eligible: list[date] = []
    for trading_day in candidates:
        final_close = clock.final_close_at(trading_day, product=product, exchange=exchange)
        if final_close is None:
            raise AfterMarketAutomationError(f"trading_session_close_missing:{trading_day.isoformat()}")
        if current >= _local_naive(final_close) + timedelta(minutes=max(0, safe_delay_minutes)):
            eligible.append(trading_day)
    return EligibilityResult(
        days=tuple(eligible[: max(1, int(max_catchup_days))]),
        latest_completed_trading_day=latest_completed,
        latest_eligible_trading_day=eligible[-1] if eligible else None,
        archive_lag_trading_days=len(eligible),
    )


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI).replace(tzinfo=None)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_output_root_available(output_root: Path, *, expected_device: int | None = None) -> int:
    if not output_root.is_dir():
        raise AfterMarketAutomationError("output_root_unavailable")
    device = output_root.stat().st_dev
    if expected_device is not None and device != expected_device:
        raise AfterMarketAutomationError("output_root_device_drift")
    return device
