"""Bounded heartbeats for the schema-v7 observer and dispatcher."""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
from typing import Any, Mapping


OBSERVER_HEARTBEAT_KEY = "guiyi:htdy:s610:observer:heartbeat"
DISPATCHER_HEARTBEAT_KEY = "guiyi:htdy:s610:dispatcher:heartbeat"
TERMINAL_SEAL_KEY_PREFIX = "guiyi:htdy:s610:terminal"
HEARTBEAT_TTL_SECONDS = 180


def publish_s610_service_heartbeat(
    connection: Any,
    *,
    service: str,
    authorization_hash: str,
    target_trading_day: date,
    status: str = "ok",
    details: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> None:
    if (
        service not in {"observer", "dispatcher"}
        or status not in {"ok", "failed"}
        or len(authorization_hash) != 64
        or authorization_hash != authorization_hash.lower()
    ):
        raise ValueError("S610_SERVICE_HEARTBEAT_INVALID")
    try:
        int(authorization_hash, 16)
    except ValueError as exc:
        raise ValueError("S610_SERVICE_HEARTBEAT_INVALID") from exc
    current = generated_at or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("S610_SERVICE_HEARTBEAT_INVALID")
    bounded_details = {
        str(key): value
        for key, value in dict(details or {}).items()
        if key
        in {
            "sample_hash",
            "selected_count",
            "capped_count",
            "blocked_count",
        }
        and isinstance(value, (str, int))
        and not isinstance(value, bool)
    }
    payload = {
        "generated_at": current.astimezone(UTC).isoformat(),
        "status": status,
        "service": service,
        "authorization_hash": authorization_hash,
        "target_trading_day": target_trading_day.isoformat(),
        "details": bounded_details,
    }
    key = (
        OBSERVER_HEARTBEAT_KEY
        if service == "observer"
        else DISPATCHER_HEARTBEAT_KEY
    )
    connection.setex(
        key,
        HEARTBEAT_TTL_SECONDS,
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )


def terminal_seal_key(*, authorization_hash: str, target_trading_day: date) -> str:
    return (
        f"{TERMINAL_SEAL_KEY_PREFIX}:{target_trading_day.isoformat()}:"
        f"{authorization_hash}"
    )


def publish_s610_terminal_seal(
    connection: Any,
    *,
    authorization_hash: str,
    target_trading_day: date,
    last_decision_bucket_end: str,
    observer_heartbeat: Mapping[str, Any],
    dispatcher_heartbeat: Mapping[str, Any],
    sealed_at: datetime,
    seal_path: Path | None = None,
) -> dict[str, Any]:
    from app.services.htdy_s6_10_remaining_window import canonical_hash

    if sealed_at.tzinfo is None:
        raise ValueError("S610_TERMINAL_SEAL_INVALID")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": "htdy_s6_10_terminal_runtime_seal",
        "authorization_hash": authorization_hash,
        "target_trading_day": target_trading_day.isoformat(),
        "last_decision_bucket_end": last_decision_bucket_end,
        "observer_generated_at": observer_heartbeat.get("generated_at"),
        "dispatcher_generated_at": dispatcher_heartbeat.get("generated_at"),
        "sealed_at": sealed_at.astimezone(UTC).isoformat(),
    }
    if (
        any(
            heartbeat.get("authorization_hash") != authorization_hash
            or heartbeat.get("target_trading_day")
            != target_trading_day.isoformat()
            or heartbeat.get("status") != "ok"
            for heartbeat in (observer_heartbeat, dispatcher_heartbeat)
        )
        or observer_heartbeat.get("service") != "observer"
        or dispatcher_heartbeat.get("service") != "dispatcher"
    ):
        raise ValueError("S610_TERMINAL_SEAL_INVALID")
    payload["seal_hash"] = canonical_hash(payload)
    if seal_path is not None:
        existing_file = load_s610_terminal_seal(seal_path)
        if existing_file:
            if (
                not _terminal_seal_hash_valid(existing_file)
                or not _same_terminal_scope(existing_file, payload)
            ):
                raise ValueError("S610_TERMINAL_SEAL_ALREADY_EXISTS")
            payload = existing_file
        else:
            _publish_create_only_json(seal_path, payload)
    key = terminal_seal_key(
        authorization_hash=authorization_hash,
        target_trading_day=target_trading_day,
    )
    existing = connection.get(key)
    if existing is not None:
        raw = existing.decode("utf-8") if isinstance(existing, bytes) else str(existing)
        existing_payload = json.loads(raw)
        if not _same_terminal_scope(existing_payload, payload):
            raise ValueError("S610_TERMINAL_SEAL_ALREADY_EXISTS")
        return existing_payload
    connection.set(
        key,
        json.dumps(payload, ensure_ascii=True, sort_keys=True),
        nx=True,
    )
    return payload


def load_s610_terminal_seal(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_terminal_scope(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    keys = (
        "schema_version",
        "seal_type",
        "authorization_hash",
        "target_trading_day",
        "last_decision_bucket_end",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def _terminal_seal_hash_valid(payload: Mapping[str, Any]) -> bool:
    from app.services.htdy_s6_10_remaining_window import canonical_hash

    return payload.get("seal_hash") == canonical_hash(
        {key: value for key, value in payload.items() if key != "seal_hash"}
    )


def _publish_create_only_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        if load_s610_terminal_seal(path) != dict(payload):
            raise ValueError("S610_TERMINAL_SEAL_ALREADY_EXISTS") from None
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
