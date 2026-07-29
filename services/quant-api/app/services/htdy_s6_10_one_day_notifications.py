"""Fail-closed selection and authorization for schema-v5 bounded WeCom."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class OneDayWechatAuthorization:
    event_id: int
    signal_id: int
    event_sha256: str
    packet_hash: str
    rendered_message_sha256: str
    dedupe_key: str
    authorized_at: datetime
    retry_deadline: datetime
    max_attempts: int = 3
    authorization_scope: str = "s6_10_one_day_bounded"


def select_bounded_delivery_events(
    events: Iterable[Any],
    *,
    trading_day: date,
    already_notified_event_ids: set[int],
    limit: int = 23,
    allowed_bucket_ends: set[datetime] | None = None,
    actual_contract: str | None = None,
) -> tuple[list[Any], list[Any], list[Any]]:
    if not 0 < limit <= 23:
        raise ValueError("S610_ONE_DAY_NOTIFICATION_LIMIT")
    eligible: list[Any] = []
    blocked: list[Any] = []
    for event in sorted(events, key=lambda item: item.id):
        decision_bucket_end = event_decision_bucket_end(event)
        if (
            not _exact_event(
                event,
                trading_day,
                actual_contract=actual_contract,
            )
            or (
                allowed_bucket_ends is not None
                and decision_bucket_end not in allowed_bucket_ends
            )
        ):
            blocked.append(event)
        elif event.id not in already_notified_event_ids:
            eligible.append(event)
    return eligible[:limit], eligible[limit:], blocked


def authorize_one_day_event(
    *,
    event: Any,
    event_sha256: str,
    rendered_message_sha256: str,
    dedupe_key: str,
    now: datetime,
    window_end: datetime,
    global_autosend_enabled: bool,
    packet_hash: str = "s6_10_schema_v5_bounded",
    actual_contract: str | None = None,
) -> OneDayWechatAuthorization:
    if (
        global_autosend_enabled
        or now.tzinfo is None
        or window_end.tzinfo is None
        or now >= window_end
        or not _sha256(event_sha256)
        or not _sha256(rendered_message_sha256)
        or dedupe_key != f"enterprise_wechat:signal_event:{event.id}"
        or not _exact_event(
            event,
            event.dominant_mapping_date,
            actual_contract=actual_contract,
        )
    ):
        raise ValueError("S610_ONE_DAY_NOTIFICATION_UNAUTHORIZED")
    return OneDayWechatAuthorization(
        event_id=event.id,
        signal_id=event.signal_id,
        event_sha256=event_sha256,
        packet_hash=packet_hash,
        rendered_message_sha256=rendered_message_sha256,
        dedupe_key=dedupe_key,
        authorized_at=now,
        retry_deadline=window_end,
    )


def dispatch_bounded_one_day(
    session: Any,
    *,
    delivery_service: Any,
    trading_day: date,
    window_end: datetime,
    parent_hash: str,
    global_autosend_enabled: bool,
    redis_ready: bool,
    allowed_bucket_ends: set[datetime] | None = None,
) -> dict[str, Any]:
    """Send eligible natural events; the caller owns commit and ledger sealing."""

    from sqlalchemy import select

    from app.models.signal import SignalEvent, SignalNotification
    from app.signal.events import signal_event_payload
    from app.signal.stage9_wechat import build_stage9_wechat_payload_from_basis
    from app.signal.stage9_gate import evaluate_stage9_signal_event_gate
    from app.services.htdy_s6_09_wecom_gate import canonical_hash
    from app.services.htdy_s6_10_runtime_support import _mapping_contracts

    if (
        global_autosend_enabled
        or not redis_ready
        or not _sha256(parent_hash)
        or delivery_service.now >= window_end
    ):
        raise ValueError("S610_ONE_DAY_DISPATCH_FAIL_CLOSED")
    actual_contract = _mapping_contracts(session, (trading_day,))[trading_day]
    events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))
    notifications = list(
        session.scalars(
            select(SignalNotification).where(
                SignalNotification.channel == "enterprise_wechat"
            )
        )
    )
    eligible_event_ids = {
        event.id
        for event in events
        if _exact_event(
            event,
            trading_day,
            actual_contract=actual_contract,
        )
        and (
            allowed_bucket_ends is None
            or event_decision_bucket_end(event) in allowed_bucket_ends
        )
    }
    allocated = {
        item.event_id
        for item in notifications
        if (
            item.event_id in eligible_event_ids
            and not _is_capped_notification(item)
        )
    }
    terminal = {
        item.event_id
        for item in notifications
        if (
            item.event_id in eligible_event_ids
            and item.status in {"sent", "skipped", "failed"}
        )
    }
    selected, capped, blocked = select_bounded_delivery_events(
        events,
        trading_day=trading_day,
        already_notified_event_ids=terminal,
        allowed_bucket_ends=allowed_bucket_ends,
        actual_contract=actual_contract,
    )
    remaining_new = max(0, 23 - len(allocated))
    retrying = [item for item in selected if item.id in allocated]
    new = [item for item in selected if item.id not in allocated]
    capped = [*new[remaining_new:], *capped]
    selected = [*retrying, *new[:remaining_new]]
    for event in capped:
        if event.id in {item.event_id for item in notifications}:
            continue
        session.add(
            SignalNotification(
                event_id=event.id,
                signal_id=event.signal_id,
                task_no=event.task_no,
                dedupe_key=f"enterprise_wechat:signal_event:{event.id}",
                event_type=event.event_type,
                channel="enterprise_wechat",
                status="skipped",
                payload={
                    "s6_10_bounded": {
                        "status": "capped",
                        "reason": "daily_23_event_send_cap",
                        "parent_hash": parent_hash,
                    }
                },
                attempt_count=0,
                max_attempts=3,
                last_error_type="s6_10_daily_cap",
                error_message="S6-10 one-day delivery cap reached",
            )
        )
    results = []
    for event in selected:
        gate = evaluate_stage9_signal_event_gate(event)
        if not gate["allowed"]:
            blocked.append(event)
            continue
        message = build_stage9_wechat_payload_from_basis(gate["payload_basis"])
        authorization = authorize_one_day_event(
            event=event,
            event_sha256=canonical_hash(signal_event_payload(event)),
            rendered_message_sha256=canonical_hash(message),
            dedupe_key=f"enterprise_wechat:signal_event:{event.id}",
            now=delivery_service.now,
            window_end=window_end,
            global_autosend_enabled=False,
            packet_hash=parent_hash,
            actual_contract=actual_contract,
        )
        results.append(
            delivery_service.send_event(event.id, authorization=authorization)
        )
    return {
        "selected_event_ids": [item.event_id for item in results],
        "capped_event_ids": [item.id for item in capped],
        "blocked_event_ids": sorted({item.id for item in blocked}),
        "results": [item.to_public_dict() for item in results],
    }


def _exact_event(
    event: Any,
    trading_day: date,
    *,
    actual_contract: str | None = None,
) -> bool:
    lineage = (
        (getattr(event, "payload", None) or {}).get("formal_lineage") or {}
    )
    indicator = lineage.get("indicator") or {}
    return (
        getattr(event, "event_type", None) == "signal_created"
        and getattr(event, "source_mode", None) == "live_realtime_repainting"
        and getattr(event, "strategy_name", None)
        == "htdy_original_realtime_first_seen"
        and getattr(event, "strategy_version", None) == "v1.1"
        and getattr(event, "product", None) == "jm"
        and getattr(event, "period", None) == "15m"
        and getattr(event, "dominant_mapping_date", None) == trading_day
        and (
            actual_contract is None
            or getattr(event, "actual_contract", None) == actual_contract
        )
        and indicator.get("signal_policy")
        == "htdy_original_xma_15m_close_first_seen_v1"
        and indicator.get("partial_allowed") is False
        and indicator.get("live_confirmed_required") is True
        and indicator.get("decision_trigger") == "confirmed_15m_close"
        and event_decision_bucket_end(event) is not None
    )


def event_decision_bucket_end(event: Any) -> datetime | None:
    """Return the confirmed close that made an observation first visible.

    ``event.bar_end`` remains the original (possibly older) signal bar.  S6-10
    delivery authority is scoped to this explicit decision close instead.
    Missing or malformed lineage is deliberately ineligible.
    """

    lineage = (
        (getattr(event, "payload", None) or {}).get("formal_lineage") or {}
    )
    detection = lineage.get("live_detection_snapshot") or {}
    raw = detection.get("decision_bucket_end")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def _sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _is_capped_notification(notification: Any) -> bool:
    return (
        ((getattr(notification, "payload", None) or {}).get("s6_10_bounded") or {})
        .get("status")
        == "capped"
    )
