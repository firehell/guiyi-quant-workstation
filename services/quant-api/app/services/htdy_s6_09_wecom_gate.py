from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


TASK_ID = "JM-LIVE-WECOM-SINGLE-S6-09"
SCHEMA_VERSION = 1
MAX_ATTEMPTS = 3
RETRY_WINDOW_SECONDS = 900
STRATEGY_CODE = "htdy_original_realtime_first_seen"
STRATEGY_VERSION = "v1.0"
SOURCE_MODE = "live_realtime_repainting"
SIGNAL_POLICY = "htdy_original_xma_15m_first_seen_v1"
EXPECTED_FLAGS = {
    "GUIYI_LIVE_RUNTIME_ENABLED": True,
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
    "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
    "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
    "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
}
EXPECTED_HEALTH = {"runtime": "ok", "live": "ok", "after_market": "ok"}


class HtDyS609GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class HtDyS609Authorization:
    event_id: int
    signal_id: int
    event_sha256: str
    packet_hash: str
    dedupe_key: str
    max_attempts: int
    retry_deadline: datetime
    rendered_message_sha256: str


def build_authorization_packet(
    *,
    current_facts: Mapping[str, Any],
    s6_08_receipt: Mapping[str, Any],
    s6_08_receipt_file_sha256: str,
    accepted_event: Mapping[str, Any],
    accepted_event_file_sha256: str,
    rendered_message_sha256: str,
    generated_at: datetime,
) -> dict[str, Any]:
    _require_aware(generated_at)
    _validate_current_facts(current_facts)
    _validate_s6_08_evidence(
        current_facts=current_facts,
        receipt=s6_08_receipt,
        receipt_file_sha256=s6_08_receipt_file_sha256,
        accepted_event=accepted_event,
        accepted_event_file_sha256=accepted_event_file_sha256,
    )
    if not _sha256(rendered_message_sha256):
        raise HtDyS609GateError("rendered_message_sha256_invalid")
    event = _mapping(current_facts.get("event"), "event_invalid")
    source = _mapping(current_facts.get("source"), "source_identity_invalid")
    runtime = _mapping(
        current_facts.get("runtime"),
        "runtime_identity_invalid",
    )
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "packet_type": "htdy_s6_09_single_wecom_authorization",
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "scope": {
            "event_id": event["id"],
            "signal_id": event["signal_id"],
            "event_sha256": canonical_hash(event),
            "event_key": event["event_key"],
            "observation_key": accepted_event["observation_key"],
            "dedupe_key": current_facts["dedupe_key"],
            "channel": "enterprise_wechat",
            "max_attempts": MAX_ATTEMPTS,
            "retry_window_seconds": RETRY_WINDOW_SECONDS,
            "rendered_message_sha256": rendered_message_sha256,
        },
        "strategy": {
            "strategy_code": STRATEGY_CODE,
            "strategy_version": STRATEGY_VERSION,
            "source_mode": SOURCE_MODE,
            "signal_policy": SIGNAL_POLICY,
            "product": "jm",
            "actual_contract": event["actual_contract"],
            "period": "15m",
            "observation_only": True,
            "auto_order": False,
        },
        "bindings": {
            "source": deepcopy(dict(source)),
            "runtime": deepcopy(dict(runtime)),
            "database_revision": current_facts["database_revision"],
            "signal_sha256": current_facts["signal_sha256"],
            "profile_id": event["profile_id"],
            "market_data_file_id": event["market_data_file_id"],
            "counts": deepcopy(dict(current_facts["counts"])),
            "hashes": deepcopy(dict(current_facts["hashes"])),
            "feature_flags": deepcopy(dict(current_facts["feature_flags"])),
            "health": deepcopy(dict(current_facts["health"])),
            "channel_configured": True,
            "event_notification_count": 0,
            "current_facts_sha256": canonical_hash(current_facts),
            "s6_08": {
                "receipt_hash": s6_08_receipt["receipt_hash"],
                "receipt_file_sha256": s6_08_receipt_file_sha256,
                "accepted_event_file_sha256": accepted_event_file_sha256,
                "child_packet_hash": accepted_event["child_packet_hash"],
            },
        },
        "allowed_writes": {
            "signal_notifications": (
                "one enterprise_wechat row for exact event and bounded "
                "attempt status transitions"
            ),
        },
        "forbidden_writes": [
            "strategy_signals",
            "signal_events",
            "signal_scan_tasks",
            "review_notes",
            "canonical_assets",
            "profile_bindings",
            "backtest_tasks",
            "orders",
            "trades",
        ],
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def verify_authorization_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    now: datetime,
    execution_started_at: datetime | None = None,
) -> HtDyS609Authorization:
    _require_aware(now)
    started_at = execution_started_at or now
    _require_aware(started_at)
    if started_at > now:
        raise HtDyS609GateError("execution_started_at_invalid")
    if (
        packet.get("schema_version") != SCHEMA_VERSION
        or packet.get("task_id") != TASK_ID
        or packet.get("packet_type")
        != "htdy_s6_09_single_wecom_authorization"
    ):
        raise HtDyS609GateError("packet_contract_invalid")
    packet_hash = str(packet.get("packet_hash") or "")
    if (
        not _sha256(approval_hash)
        or approval_hash != packet_hash
        or canonical_packet_hash(packet) != packet_hash
    ):
        raise HtDyS609GateError("approval_hash_mismatch")
    _validate_current_facts(current_facts)
    bindings = _mapping(packet.get("bindings"), "packet_bindings_invalid")
    if bindings.get("current_facts_sha256") != canonical_hash(current_facts):
        raise HtDyS609GateError("current_facts_drift")
    scope = _mapping(packet.get("scope"), "packet_scope_invalid")
    event = _mapping(current_facts.get("event"), "event_invalid")
    if (
        scope.get("event_id") != event.get("id")
        or scope.get("signal_id") != event.get("signal_id")
        or scope.get("event_sha256") != canonical_hash(event)
        or scope.get("dedupe_key") != current_facts.get("dedupe_key")
        or scope.get("max_attempts") != MAX_ATTEMPTS
        or scope.get("retry_window_seconds") != RETRY_WINDOW_SECONDS
        or not _sha256(scope.get("rendered_message_sha256"))
    ):
        raise HtDyS609GateError("packet_scope_invalid")
    return HtDyS609Authorization(
        event_id=int(scope["event_id"]),
        signal_id=int(scope["signal_id"]),
        event_sha256=str(scope["event_sha256"]),
        packet_hash=packet_hash,
        dedupe_key=str(scope["dedupe_key"]),
        max_attempts=MAX_ATTEMPTS,
        retry_deadline=started_at.astimezone(UTC)
        + timedelta(seconds=RETRY_WINDOW_SECONDS),
        rendered_message_sha256=str(scope["rendered_message_sha256"]),
    )


def canonical_packet_hash(packet: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            str(key): deepcopy(value)
            for key, value in packet.items()
            if key != "packet_hash"
        }
    )


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collect_current_facts(
    session: Any,
    *,
    source_root: Path,
    runtime_root: Path,
    environ: Mapping[str, str],
    health: Mapping[str, str],
    event_id: int = 4,
) -> dict[str, Any]:
    from sqlalchemy import select, text

    from app.models.signal import (
        SignalEvent,
        SignalNotification,
        StrategySignal,
    )
    from app.services.htdy_s6_08_runtime_gate import _database_state
    from app.services.signal_scanner import signal_payload
    from app.signal.events import signal_event_payload
    from app.signal.stage9_wechat_delivery import stage9_wechat_dedupe_key

    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
    event = session.get(SignalEvent, event_id)
    if event is None:
        raise HtDyS609GateError("event_missing")
    signal = session.get(StrategySignal, event.signal_id)
    if signal is None:
        raise HtDyS609GateError("signal_missing")
    notifications = list(
        session.scalars(
            select(SignalNotification).where(
                SignalNotification.event_id == event_id,
                SignalNotification.channel == "enterprise_wechat",
            )
        )
    )
    counts, hashes = _database_state(session)
    revision = str(
        session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    )
    facts = {
        "source": _git_identity(source_root, include_branch=True),
        "runtime": _git_identity(runtime_root, include_branch=False),
        "database_revision": revision,
        "event": signal_event_payload(event),
        "signal_sha256": canonical_hash(signal_payload(signal)),
        "event_notification_count": len(notifications),
        "event_notification": (
            _notification_identity(notifications[0])
            if len(notifications) == 1
            else None
        ),
        "dedupe_key": stage9_wechat_dedupe_key(event_id),
        "counts": counts,
        "hashes": hashes,
        "feature_flags": {
            name: (
                str(environ.get(name) or "").strip()
                if name.endswith(("_PACKET", "_HASH"))
                else _enabled(environ, name)
            )
            for name in EXPECTED_FLAGS
        },
        "webhook_present": bool(
            str(environ.get("QYWX_WEBHOOK_URL") or "").strip()
        ),
        "health": dict(health),
    }
    session.rollback()
    return facts


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HtDyS609GateError("bound_artifact_missing") from exc


def load_json_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HtDyS609GateError("bound_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise HtDyS609GateError("bound_artifact_invalid")
    return value


def verify_retry_facts(
    packet: Mapping[str, Any],
    current_facts: Mapping[str, Any],
) -> None:
    bindings = _mapping(packet.get("bindings"), "packet_bindings_invalid")
    frozen_counts = _mapping(bindings.get("counts"), "packet_bindings_invalid")
    current_counts = _mapping(
        current_facts.get("counts"),
        "counts_invalid",
    )
    for key, value in frozen_counts.items():
        expected = value
        if key == "signal_notifications":
            expected = int(value) + 1
        if current_counts.get(key) != expected:
            raise HtDyS609GateError("retry_database_drift")
    frozen_hashes = _mapping(
        bindings.get("hashes"),
        "packet_bindings_invalid",
    )
    current_hashes = _mapping(
        current_facts.get("hashes"),
        "hashes_invalid",
    )
    for key, value in frozen_hashes.items():
        if key != "forbidden_tables_sha256" and current_hashes.get(key) != value:
            raise HtDyS609GateError("retry_database_drift")
    for key in (
        "source",
        "runtime",
        "database_revision",
        "event",
        "signal_sha256",
        "dedupe_key",
        "feature_flags",
        "health",
    ):
        frozen = (
            bindings.get(key)
            if key in bindings
            else packet.get("scope", {}).get(key)
        )
        if key == "event":
            frozen = packet.get("scope", {}).get("event_sha256")
            current = canonical_hash(current_facts.get("event"))
        elif key == "dedupe_key":
            frozen = packet.get("scope", {}).get("dedupe_key")
            current = current_facts.get(key)
        else:
            current = current_facts.get(key)
        if frozen != current:
            raise HtDyS609GateError("retry_current_facts_drift")
    notification = _mapping(
        current_facts.get("event_notification"),
        "retry_notification_invalid",
    )
    if (
        current_facts.get("event_notification_count") != 1
        or notification.get("dedupe_key")
        != packet.get("scope", {}).get("dedupe_key")
        or notification.get("event_id")
        != packet.get("scope", {}).get("event_id")
        or notification.get("signal_id")
        != packet.get("scope", {}).get("signal_id")
        or notification.get("status") != "retry_pending"
        or not 1 <= int(notification.get("attempt_count") or 0) < MAX_ATTEMPTS
        or notification.get("max_attempts") != MAX_ATTEMPTS
    ):
        raise HtDyS609GateError("retry_notification_invalid")
    if current_facts.get("webhook_present") is not True:
        raise HtDyS609GateError("channel_not_configured")


def verify_final_facts(
    packet: Mapping[str, Any],
    current_facts: Mapping[str, Any],
) -> None:
    bindings = _mapping(packet.get("bindings"), "packet_bindings_invalid")
    frozen_counts = _mapping(bindings.get("counts"), "packet_bindings_invalid")
    current_counts = _mapping(
        current_facts.get("counts"),
        "counts_invalid",
    )
    for key, value in frozen_counts.items():
        expected = int(value) + (1 if key == "signal_notifications" else 0)
        if current_counts.get(key) != expected:
            raise HtDyS609GateError("final_database_drift")
    frozen_hashes = _mapping(
        bindings.get("hashes"),
        "packet_bindings_invalid",
    )
    current_hashes = _mapping(
        current_facts.get("hashes"),
        "hashes_invalid",
    )
    for key, value in frozen_hashes.items():
        if key != "forbidden_tables_sha256" and current_hashes.get(key) != value:
            raise HtDyS609GateError("final_database_drift")
    _verify_bound_non_notification_facts(packet, current_facts)
    notification = _mapping(
        current_facts.get("event_notification"),
        "final_notification_invalid",
    )
    if (
        current_facts.get("event_notification_count") != 1
        or notification.get("dedupe_key")
        != packet.get("scope", {}).get("dedupe_key")
        or notification.get("event_id")
        != packet.get("scope", {}).get("event_id")
        or notification.get("signal_id")
        != packet.get("scope", {}).get("signal_id")
        or notification.get("status") != "sent"
        or not 1 <= int(notification.get("attempt_count") or 0) <= MAX_ATTEMPTS
        or notification.get("max_attempts") != MAX_ATTEMPTS
    ):
        raise HtDyS609GateError("final_notification_invalid")


def _verify_bound_non_notification_facts(
    packet: Mapping[str, Any],
    current_facts: Mapping[str, Any],
) -> None:
    bindings = _mapping(packet.get("bindings"), "packet_bindings_invalid")
    scope = _mapping(packet.get("scope"), "packet_scope_invalid")
    comparisons = {
        "source": bindings.get("source"),
        "runtime": bindings.get("runtime"),
        "database_revision": bindings.get("database_revision"),
        "signal_sha256": bindings.get("signal_sha256"),
        "feature_flags": bindings.get("feature_flags"),
        "health": bindings.get("health"),
        "dedupe_key": scope.get("dedupe_key"),
    }
    for key, frozen in comparisons.items():
        if current_facts.get(key) != frozen:
            raise HtDyS609GateError("current_facts_drift")
    if canonical_hash(current_facts.get("event")) != scope.get(
        "event_sha256"
    ):
        raise HtDyS609GateError("current_facts_drift")
    if current_facts.get("webhook_present") is not True:
        raise HtDyS609GateError("channel_not_configured")


def _validate_current_facts(facts: Mapping[str, Any]) -> None:
    event = _mapping(facts.get("event"), "event_invalid")
    signal = _mapping(event.get("payload"), "event_payload_invalid").get(
        "signal"
    )
    signal = _mapping(signal, "event_payload_invalid")
    features = _mapping(signal.get("features"), "event_payload_invalid")
    lineage = _mapping(
        _mapping(event.get("payload"), "event_payload_invalid").get(
            "formal_lineage"
        ),
        "event_lineage_invalid",
    )
    if (
        event.get("id") != 4
        or event.get("signal_id") != 6
        or event.get("event_type") != "signal_created"
        or event.get("strategy_name") != STRATEGY_CODE
        or event.get("strategy_version") != STRATEGY_VERSION
        or event.get("source_mode") != SOURCE_MODE
        or event.get("product") != "jm"
        or event.get("period") != "15m"
        or event.get("direction") not in {"long", "short"}
        or signal.get("spec_source") != SIGNAL_POLICY
        or features.get("signal_policy") != SIGNAL_POLICY
        or lineage.get("schema_version") != "signal_review_lineage_v2"
    ):
        raise HtDyS609GateError("event_identity_invalid")
    if facts.get("event_notification_count") != 0:
        raise HtDyS609GateError("notification_baseline_invalid")
    if facts.get("dedupe_key") != "enterprise_wechat:signal_event:4":
        raise HtDyS609GateError("dedupe_key_invalid")
    if facts.get("database_revision") != "20260721_0025":
        raise HtDyS609GateError("database_revision_invalid")
    if dict(_mapping(facts.get("feature_flags"), "feature_flags_invalid")) != (
        EXPECTED_FLAGS
    ):
        raise HtDyS609GateError("feature_flags_invalid")
    if dict(_mapping(facts.get("health"), "health_invalid")) != EXPECTED_HEALTH:
        raise HtDyS609GateError("health_invalid")
    if facts.get("webhook_present") is not True:
        raise HtDyS609GateError("channel_not_configured")
    for key in ("source", "runtime"):
        identity = _mapping(facts.get(key), f"{key}_identity_invalid")
        if (
            identity.get("tracked_clean") is not True
            or not _hex(identity.get("commit"), 40)
            or not _hex(identity.get("tree"), 40)
        ):
            raise HtDyS609GateError(f"{key}_identity_invalid")
    if not _sha256(facts.get("signal_sha256")):
        raise HtDyS609GateError("signal_sha256_invalid")
    _mapping(facts.get("counts"), "counts_invalid")
    _mapping(facts.get("hashes"), "hashes_invalid")


def _validate_s6_08_evidence(
    *,
    current_facts: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_file_sha256: str,
    accepted_event: Mapping[str, Any],
    accepted_event_file_sha256: str,
) -> None:
    from app.services.htdy_s6_08_schema_v3 import final_receipt_hash

    event = _mapping(current_facts.get("event"), "event_invalid")
    lineage = _mapping(
        _mapping(event.get("payload"), "event_payload_invalid").get(
            "formal_lineage"
        ),
        "event_lineage_invalid",
    )
    detection = _mapping(
        lineage.get("live_detection_snapshot"),
        "event_detection_invalid",
    )
    if (
        receipt.get("schema_version") != 3
        or receipt.get("status") != "completed"
        or receipt.get("gate") != "JM_LIVE_SIGNAL_EVENT_PASSED"
        or receipt.get("gate_alias") != "LIVE_SIGNAL_EVENT_GATE_PASSED"
        or not _sha256(receipt.get("receipt_hash"))
        or not _sha256(receipt_file_sha256)
        or not _sha256(accepted_event_file_sha256)
        or final_receipt_hash(receipt) != receipt.get("receipt_hash")
    ):
        raise HtDyS609GateError("s6_08_receipt_invalid")
    if (
        accepted_event.get("status") != "first_event_committed"
        or accepted_event.get("event_id") != event.get("id")
        or accepted_event.get("event_key") != event.get("event_key")
        or accepted_event.get("observation_key")
        != detection.get("observation_key")
        or not _sha256(accepted_event.get("child_packet_hash"))
    ):
        raise HtDyS609GateError("s6_08_event_binding_invalid")


def _mapping(value: Any, reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HtDyS609GateError(reason)
    return value


def _sha256(value: Any) -> bool:
    return _hex(value, 64)


def _hex(value: Any, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise HtDyS609GateError("aware_datetime_required")


def _git_identity(root: Path, *, include_branch: bool) -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ("git", *args),
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise HtDyS609GateError("git_identity_invalid") from exc
        return result.stdout.strip()

    value: dict[str, Any] = {
        "commit": run("rev-parse", "HEAD"),
        "tree": run("rev-parse", "HEAD^{tree}"),
        "tracked_clean": (
            run(
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            )
            == ""
        ),
    }
    if include_branch:
        value["branch"] = run("branch", "--show-current")
    return value


def _notification_identity(value: Any) -> dict[str, Any]:
    return {
        "id": value.id,
        "event_id": value.event_id,
        "signal_id": value.signal_id,
        "dedupe_key": value.dedupe_key,
        "channel": value.channel,
        "status": value.status,
        "attempt_count": value.attempt_count,
        "max_attempts": value.max_attempts,
        "next_retry_at": (
            value.next_retry_at.isoformat()
            if value.next_retry_at is not None
            else None
        ),
    }


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
