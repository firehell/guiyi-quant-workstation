from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.htdy_s6_08_schema_v3 import final_receipt_hash


EVENT = {
    "id": 4,
    "signal_id": 6,
    "event_key": "signal_created:htdy-first-seen:observation:created",
    "event_type": "signal_created",
    "strategy_name": "htdy_original_realtime_first_seen",
    "strategy_version": "v1.0",
    "source_mode": "live_realtime_repainting",
    "product": "jm",
    "actual_contract": "JM2609",
    "period": "15m",
    "direction": "long",
    "profile_id": "live_observation_v1",
    "market_data_file_id": 104003,
    "payload": {
        "signal": {
            "spec_source": "htdy_original_xma_15m_first_seen_v1",
            "features": {
                "signal_policy": "htdy_original_xma_15m_first_seen_v1",
            },
        },
        "formal_lineage": {
            "schema_version": "signal_review_lineage_v2",
            "live_detection_snapshot": {
                "observation_key": "observation",
            },
        },
    },
}
COUNTS = {
    "strategy_signals": 6,
    "signal_events": 4,
    "signal_notifications": 1,
    "signal_scan_tasks": 5,
    "review_notes": 7,
    "canonical_assets": 103381,
    "profile_bindings": 5138,
    "backtest_tasks": 23,
    "orders": 4225,
    "trades": 4361,
}
HASHES = {
    "canonical_assets_sha256": "a" * 64,
    "profile_bindings_sha256": "b" * 64,
    "backtest_state_sha256": "c" * 64,
    "forbidden_tables_sha256": "d" * 64,
}
FACTS = {
    "source": {
        "branch": "codex/v1-htdy-s609-single-wecom",
        "commit": "1" * 40,
        "tree": "2" * 40,
        "tracked_clean": True,
    },
    "runtime": {
        "commit": "844b3f9beded6aae3375e25e34a7e5250f0a1ae2",
        "tree": "3" * 40,
        "tracked_clean": True,
    },
    "database_revision": "20260721_0025",
    "event": EVENT,
    "signal_sha256": "4" * 64,
    "event_notification_count": 0,
    "dedupe_key": "enterprise_wechat:signal_event:4",
    "counts": COUNTS,
    "hashes": HASHES,
    "feature_flags": {
        "GUIYI_LIVE_RUNTIME_ENABLED": True,
        "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
        "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
        "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
    },
    "webhook_present": True,
    "health": {"runtime": "ok", "live": "ok", "after_market": "ok"},
}
S608_RECEIPT = {
    "schema_version": 3,
    "status": "completed",
    "gate": "JM_LIVE_SIGNAL_EVENT_PASSED",
    "gate_alias": "LIVE_SIGNAL_EVENT_GATE_PASSED",
    "receipt_hash": "5" * 64,
}
S608_RECEIPT["receipt_hash"] = final_receipt_hash(S608_RECEIPT)
ACCEPTED_EVENT = {
    "status": "first_event_committed",
    "event_id": 4,
    "event_key": EVENT["event_key"],
    "observation_key": "observation",
    "child_packet_hash": "6" * 64,
}


def test_packet_is_deterministic_and_freezes_exact_event() -> None:
    from app.services.htdy_s6_09_wecom_gate import build_authorization_packet

    generated_at = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    first = build_authorization_packet(
        current_facts=FACTS,
        s6_08_receipt=S608_RECEIPT,
        s6_08_receipt_file_sha256="7" * 64,
        accepted_event=ACCEPTED_EVENT,
        accepted_event_file_sha256="8" * 64,
        rendered_message_sha256="9" * 64,
        generated_at=generated_at,
    )
    second = build_authorization_packet(
        current_facts=FACTS,
        s6_08_receipt=S608_RECEIPT,
        s6_08_receipt_file_sha256="7" * 64,
        accepted_event=ACCEPTED_EVENT,
        accepted_event_file_sha256="8" * 64,
        rendered_message_sha256="9" * 64,
        generated_at=generated_at,
    )

    assert first == second
    assert first["packet_hash"] == second["packet_hash"]
    assert first["scope"]["event_id"] == 4
    assert first["scope"]["signal_id"] == 6
    assert first["scope"]["max_attempts"] == 3
    assert first["scope"]["retry_window_seconds"] == 900
    assert first["scope"]["dedupe_key"] == "enterprise_wechat:signal_event:4"
    assert "webhook" not in str(first).lower()


def test_verify_returns_exact_authorization_and_rejects_event_drift() -> None:
    from app.services.htdy_s6_09_wecom_gate import (
        HtDyS609GateError,
        build_authorization_packet,
        verify_authorization_packet,
    )

    now = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    packet = build_authorization_packet(
        current_facts=FACTS,
        s6_08_receipt=S608_RECEIPT,
        s6_08_receipt_file_sha256="7" * 64,
        accepted_event=ACCEPTED_EVENT,
        accepted_event_file_sha256="8" * 64,
        rendered_message_sha256="9" * 64,
        generated_at=now,
    )

    authorization = verify_authorization_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=FACTS,
        now=now + timedelta(minutes=1),
        execution_started_at=now + timedelta(seconds=30),
    )
    assert authorization.event_id == 4
    assert authorization.signal_id == 6
    assert authorization.max_attempts == 3
    assert authorization.retry_deadline == now + timedelta(
        seconds=30 + 900
    )

    drifted = {**FACTS, "event": {**EVENT, "direction": "short"}}
    with pytest.raises(HtDyS609GateError, match="current_facts_drift"):
        verify_authorization_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=drifted,
            now=now + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (
            ("feature_flags", "GUIYI_WECHAT_AUTOSEND_ENABLED"),
            True,
            "feature_flags_invalid",
        ),
        (
            ("event_notification_count",),
            1,
            "notification_baseline_invalid",
        ),
        (("webhook_present",), False, "channel_not_configured"),
        (("health", "runtime"), "failed", "health_invalid"),
    ],
)
def test_verify_rejects_unsafe_current_facts(
    path: tuple[str, ...],
    value: object,
    reason: str,
) -> None:
    from app.services.htdy_s6_09_wecom_gate import (
        HtDyS609GateError,
        build_authorization_packet,
        verify_authorization_packet,
    )

    now = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    packet = build_authorization_packet(
        current_facts=FACTS,
        s6_08_receipt=S608_RECEIPT,
        s6_08_receipt_file_sha256="7" * 64,
        accepted_event=ACCEPTED_EVENT,
        accepted_event_file_sha256="8" * 64,
        rendered_message_sha256="9" * 64,
        generated_at=now,
    )
    drifted = dict(FACTS)
    if len(path) == 1:
        drifted[path[0]] = value
    else:
        drifted[path[0]] = {**FACTS[path[0]], path[1]: value}

    with pytest.raises(HtDyS609GateError, match=reason):
        verify_authorization_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=drifted,
            now=now,
        )


def test_final_verifier_allows_only_one_exact_sent_notification() -> None:
    from app.services.htdy_s6_09_wecom_gate import (
        HtDyS609GateError,
        build_authorization_packet,
        verify_final_facts,
    )

    packet = build_authorization_packet(
        current_facts=FACTS,
        s6_08_receipt=S608_RECEIPT,
        s6_08_receipt_file_sha256="7" * 64,
        accepted_event=ACCEPTED_EVENT,
        accepted_event_file_sha256="8" * 64,
        rendered_message_sha256="9" * 64,
        generated_at=datetime(2026, 7, 28, 1, 0, tzinfo=UTC),
    )
    final = {
        **FACTS,
        "event_notification_count": 1,
        "event_notification": {
            "id": 2,
            "event_id": 4,
            "signal_id": 6,
            "dedupe_key": "enterprise_wechat:signal_event:4",
            "channel": "enterprise_wechat",
            "status": "sent",
            "attempt_count": 1,
            "max_attempts": 3,
            "next_retry_at": None,
        },
        "counts": {
            **COUNTS,
            "signal_notifications": COUNTS["signal_notifications"] + 1,
        },
        "hashes": {
            **HASHES,
            "forbidden_tables_sha256": "e" * 64,
        },
    }
    verify_final_facts(packet, final)

    drifted = {
        **final,
        "counts": {**final["counts"], "review_notes": 8},
    }
    with pytest.raises(HtDyS609GateError, match="final_database_drift"):
        verify_final_facts(packet, drifted)
