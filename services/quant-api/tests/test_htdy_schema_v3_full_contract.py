from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime

import pytest


SHA = "a" * 64
COUNTS = {
    "strategy_signals": 10,
    "signal_events": 20,
    "signal_notifications": 30,
    "signal_scan_tasks": 40,
    "review_notes": 50,
    "backtest_tasks": 60,
    "profile_bindings": 70,
    "canonical_assets": 80,
    "orders": 0,
    "trades": 0,
}
HASHES = {
    "backtest_state_sha256": "1" * 64,
    "profile_bindings_sha256": "2" * 64,
    "canonical_assets_sha256": "3" * 64,
    "forbidden_tables_sha256": "4" * 64,
}
PARENT_BINDINGS = {
    "deployment_packet_sha256": "1" * 64,
    "s6_07_rebind_packet_sha256": "2" * 64,
    "s6_07_final_receipt": {
        "path": "data/reports/jm_eod_incremental_automation_s6_07/final/completion_receipt.json",
        "sha256": "3" * 64,
    },
    "database_recovery_receipt": {
        "path": "/Volumes/GuiyiRecoverySafe/s607-recovery-evidence/recovery_receipt.json",
        "sha256": "f" * 64,
        "receipt_hash": "0" * 64,
    },
    "parent_mapping": {
        "trade_date": "2026-07-24",
        "contract_code": "JM2609",
        "sha256": "1" * 64,
    },
    "service_bundle_sha256": "4" * 64,
    "runtime": {
        "root": "/Volumes/扩展盘/GuiyiRuntime/guiyi-quant-workstation-runtime",
        "commit": "5" * 40,
        "tree_sha256": "6" * 64,
        "tracked_clean": True,
    },
    "database_revision": "20260721_0025",
    "actual_contract_resolver_sha256": "7" * 64,
    "profile": {
        "profile_id": "live_observation_v1",
        "market_data_file_id": 42,
        "data_version": "rqdata-jm-15m-v1",
        "checksum": "8" * 64,
    },
    "source_sha256": "9" * 64,
    "policy_sha256": "a" * 64,
    "writer_sha256": "b" * 64,
    "web": {
        "bundle_sha256": "c" * 64,
        "source_sha256": "d" * 64,
    },
    "feature_flags": {
        "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
        "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
    },
    "baseline": {"counts": COUNTS, "hashes": HASHES},
    "output": {
        "root": "/Volumes/扩展盘/guiyi-quant-workstation/data/reports/jm_live_signal_event_s6_08",
        "device": 42,
        "mount": "/Volumes/扩展盘",
    },
    "launchd": {
        "label": "com.guiyi.quant-runtime-scheduler",
        "plist_sha256": "e" * 64,
    },
    "no_migration": True,
}
SOURCE_FACTS = {
    "profile_sha256": "1" * 64,
    "source_sha256": "9" * 64,
    "policy_sha256": "a" * 64,
    "runtime_heartbeat_sha256": "2" * 64,
    "autosend_enabled": False,
}


def _parent():
    from app.services.htdy_s6_08_schema_v3 import (
        FROZEN_TRADING_DAYS,
        build_parent_authorization,
    )

    return build_parent_authorization(
        trading_days=FROZEN_TRADING_DAYS,
        bindings=PARENT_BINDINGS,
    )


def _child():
    from app.services.htdy_s6_08_schema_v3 import (
        build_daily_child_authorization,
    )

    parent = _parent()
    child = build_daily_child_authorization(
        parent_packet=parent,
        parent_approval_hash=parent["packet_hash"],
        current_parent_bindings=PARENT_BINDINGS,
        trading_day=date(2026, 7, 28),
        actual_contract="JM2609",
        mapping_sha256="f" * 64,
        source_facts=SOURCE_FACTS,
        baseline_counts=COUNTS,
        baseline_hashes=HASHES,
    )
    return parent, child


def _event() -> dict:
    return {
        "event_key": f"signal_created:htdy-first-seen:{SHA}:created",
        "event_type": "signal_created",
        "source_mode": "live_realtime_repainting",
        "strategy_name": "htdy_original_realtime_first_seen",
        "strategy_version": "v1.0",
        "product": "jm",
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-28",
        "period": "15m",
        "direction": "long",
        "payload": {
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v2",
                "indicator": {
                    "indicator_code": "huotian_dayou_original_v0",
                    "indicator_version": "original-v0",
                    "signal_policy": "htdy_original_xma_15m_first_seen_v1",
                    "future_looking": True,
                    "repainting_accepted": True,
                    "first_seen_no_retraction": True,
                    "live_confirmed_required": False,
                    "partial_allowed": True,
                    "confirmed_allowed": True,
                    "historical_backtest_allowed": False,
                    "notification_ready": False,
                    "auto_order": False,
                },
            },
        },
    }


def test_parent_binds_full_runtime_profile_web_output_launchd_and_baseline() -> None:
    from app.services.htdy_s6_08_schema_v3 import verify_parent_authorization

    parent = _parent()

    assert parent["bindings"] == PARENT_BINDINGS
    assert parent["strategy"]["confirmed_allowed"] is True
    assert parent["strategy"]["live_confirmed_required"] is False
    verify_parent_authorization(
        parent,
        approval_hash=parent["packet_hash"],
        current_bindings=PARENT_BINDINGS,
    )

    drift = deepcopy(PARENT_BINDINGS)
    drift["profile"]["market_data_file_id"] = 99
    with pytest.raises(RuntimeError, match="binding_drift"):
        verify_parent_authorization(
            parent,
            approval_hash=parent["packet_hash"],
            current_bindings=drift,
        )


def test_parent_rejects_superseded_window_even_when_other_bindings_match() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        build_parent_authorization,
        verify_parent_authorization,
    )

    old_parent = build_parent_authorization(
        trading_days=[date(2026, 7, day) for day in range(27, 32)],
        bindings=PARENT_BINDINGS,
    )

    with pytest.raises(RuntimeError, match="parent_window_invalid"):
        verify_parent_authorization(
            old_parent,
            approval_hash=old_parent["packet_hash"],
            current_bindings=PARENT_BINDINGS,
        )


def test_parent_accepts_only_exact_recovery_lineage_rebind_identity() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        FROZEN_TRADING_DAYS,
        build_parent_authorization,
        verify_parent_authorization,
    )
    from app.services.s607_recovery_lineage_rebind import (
        ORIGINAL_RECOVERY_RECEIPT_HASH,
        ORIGINAL_RECOVERY_RECEIPT_SHA256,
    )

    bindings = deepcopy(PARENT_BINDINGS)
    bindings["database_recovery_receipt"] = {
        "path": "/safe/recovery_lineage_rebind_receipt.json",
        "sha256": "e" * 64,
        "receipt_hash": "f" * 64,
        "evidence_mode": "tracked_read_only_lineage_rebind_v1",
        "source_commit": "1" * 40,
        "original_receipt_hash": ORIGINAL_RECOVERY_RECEIPT_HASH,
        "original_receipt_sha256": ORIGINAL_RECOVERY_RECEIPT_SHA256,
    }
    parent = build_parent_authorization(
        trading_days=FROZEN_TRADING_DAYS,
        bindings=bindings,
    )
    verify_parent_authorization(
        parent,
        approval_hash=parent["packet_hash"],
        current_bindings=bindings,
    )


def test_daily_child_rechecks_external_parent_and_current_source_facts() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        verify_daily_child_authorization,
    )

    parent, child = _child()
    verify_daily_child_authorization(
        child,
        approval_hash=child["packet_hash"],
        parent_packet=parent,
        parent_approval_hash=parent["packet_hash"],
        current_parent_bindings=PARENT_BINDINGS,
        current_trading_day=date(2026, 7, 28),
        current_actual_contract="JM2609",
        current_mapping_sha256="f" * 64,
        current_source_facts=SOURCE_FACTS,
        current_counts=COUNTS,
        current_hashes=HASHES,
    )

    drift = deepcopy(PARENT_BINDINGS)
    drift["runtime"]["tracked_clean"] = False
    with pytest.raises(RuntimeError, match="binding_drift"):
        verify_daily_child_authorization(
            child,
            approval_hash=child["packet_hash"],
            parent_packet=parent,
            parent_approval_hash=parent["packet_hash"],
            current_parent_bindings=drift,
            current_trading_day=date(2026, 7, 28),
            current_actual_contract="JM2609",
            current_mapping_sha256="f" * 64,
            current_source_facts=SOURCE_FACTS,
            current_counts=COUNTS,
            current_hashes=HASHES,
        )

    autosend = {**SOURCE_FACTS, "autosend_enabled": True}
    with pytest.raises(RuntimeError, match="source_facts_drift"):
        verify_daily_child_authorization(
            child,
            approval_hash=child["packet_hash"],
            parent_packet=parent,
            parent_approval_hash=parent["packet_hash"],
            current_parent_bindings=PARENT_BINDINGS,
            current_trading_day=date(2026, 7, 28),
            current_actual_contract="JM2609",
            current_mapping_sha256="f" * 64,
            current_source_facts=autosend,
            current_counts=COUNTS,
            current_hashes=HASHES,
        )


def test_final_verifier_requires_idempotency_health_cleared_flags_and_zero_drift() -> None:
    from app.services.htdy_s6_08_schema_v3 import verify_daily_execution

    _, child = _child()
    final_counts = {
        **COUNTS,
        "strategy_signals": 11,
        "signal_events": 21,
    }
    result = verify_daily_execution(
        child,
        approval_hash=child["packet_hash"],
        events=[_event()],
        final_counts=final_counts,
        final_hashes=HASHES,
        idempotency_result={
            "created": 0,
            "changed": 0,
            "unchanged": 1,
        },
        final_flags={
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        health={
            "runtime": "ok",
            "live": "ok",
            "after_market": "ok",
        },
        review_deep_links=[{"event_id": 21, "readable": True}],
    )

    assert result["canonical_gate"] == "JM_LIVE_SIGNAL_EVENT_PASSED"
    assert result["gate_alias"] == "LIVE_SIGNAL_EVENT_GATE_PASSED"
    assert result["historical_validation"] is False
    assert result["trading_ready"] is False
    assert result["notification_ready"] is False
    assert result["long_running_ready"] is False


def test_final_verifier_rejects_forbidden_hash_or_idempotency_drift() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        HtDySchemaV3GateError,
        verify_daily_execution,
    )

    _, child = _child()
    final_counts = {
        **COUNTS,
        "strategy_signals": 11,
        "signal_events": 21,
    }
    with pytest.raises(
        HtDySchemaV3GateError,
        match="idempotency_probe_invalid",
    ):
        verify_daily_execution(
            child,
            approval_hash=child["packet_hash"],
            events=[_event()],
            final_counts=final_counts,
            final_hashes=HASHES,
            idempotency_result={
                "created": 1,
                "changed": 0,
                "unchanged": 0,
            },
            final_flags={},
            health={},
            review_deep_links=[],
        )


def test_runtime_delta_accepts_one_natural_event_then_only_same_event_probe() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        verify_runtime_first_event,
        verify_runtime_idempotency_probe,
    )

    _, child = _child()
    event = _event()
    event["id"] = 31
    event["payload"]["formal_lineage"]["live_detection_snapshot"] = {
        "observation_key": "observation-key-1"
    }
    after_counts = {
        **COUNTS,
        "strategy_signals": 11,
        "signal_events": 21,
    }

    accepted = verify_runtime_first_event(
        child,
        approval_hash=child["packet_hash"],
        events=[event],
        final_counts=after_counts,
        final_hashes=HASHES,
    )
    assert accepted == {
        "event_id": 31,
        "event_key": event["event_key"],
        "observation_key": "observation-key-1",
    }

    verify_runtime_idempotency_probe(
        child,
        approval_hash=child["packet_hash"],
        accepted_event=accepted,
        events=[event],
        current_counts=after_counts,
        current_hashes=HASHES,
        runtime_result={
            "created": 0,
            "changed": 0,
            "unchanged": 1,
            "blocked": 0,
            "event_ids": [31],
        },
    )

    with pytest.raises(RuntimeError, match="idempotency_probe_invalid"):
        verify_runtime_idempotency_probe(
            child,
            approval_hash=child["packet_hash"],
            accepted_event=accepted,
            events=[{**event, "event_key": "signal_created:htdy:new"}],
            current_counts=after_counts,
            current_hashes=HASHES,
            runtime_result={
                "created": 1,
                "changed": 0,
                "unchanged": 0,
                "blocked": 0,
                "event_ids": [32],
            },
        )


def test_real_parent_window_is_exact_and_must_be_frozen_before_it_starts() -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        FROZEN_TRADING_DAYS,
        validate_frozen_parent_window,
    )

    assert [item.isoformat() for item in FROZEN_TRADING_DAYS] == [
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
    ]
    validate_frozen_parent_window(
        generated_on=date(2026, 7, 27),
        verified_trading_days=FROZEN_TRADING_DAYS,
    )
    with pytest.raises(RuntimeError, match="frozen_window_already_started"):
        validate_frozen_parent_window(
            generated_on=date(2026, 7, 28),
            verified_trading_days=FROZEN_TRADING_DAYS,
        )
    validate_frozen_parent_window(
        generated_at=datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
        verified_trading_days=FROZEN_TRADING_DAYS,
        first_day_htdy_event_count=0,
        first_day_child_present=False,
    )
    with pytest.raises(
        RuntimeError,
        match="frozen_window_preopen_deadline_passed",
    ):
        validate_frozen_parent_window(
            generated_at=datetime(2026, 7, 28, 0, 30, tzinfo=UTC),
            verified_trading_days=FROZEN_TRADING_DAYS,
            first_day_htdy_event_count=0,
            first_day_child_present=False,
        )
    with pytest.raises(
        RuntimeError,
        match="frozen_window_first_day_state_not_clean",
    ):
        validate_frozen_parent_window(
            generated_at=datetime(2026, 7, 28, 0, 15, tzinfo=UTC),
            verified_trading_days=FROZEN_TRADING_DAYS,
            first_day_htdy_event_count=1,
            first_day_child_present=False,
        )
    with pytest.raises(RuntimeError, match="frozen_window_calendar_incomplete"):
        validate_frozen_parent_window(
            generated_on=date(2026, 7, 26),
            verified_trading_days=FROZEN_TRADING_DAYS[:-1],
        )
    with pytest.raises(RuntimeError, match="frozen_window_calendar_incomplete"):
        validate_frozen_parent_window(
            generated_on=date(2026, 7, 27),
            verified_trading_days=(
                *FROZEN_TRADING_DAYS,
                date(2026, 8, 3),
            ),
        )


def test_final_receipt_is_create_only_and_keeps_non_trading_boundaries(
    tmp_path,
) -> None:
    from app.services.htdy_s6_08_schema_v3 import (
        build_final_receipt,
        final_receipt_hash,
        publish_final_receipt_create_only,
    )

    _, child = _child()
    receipt = build_final_receipt(
        child_packet=child,
        verification={
            "status": "passed",
            "canonical_gate": "JM_LIVE_SIGNAL_EVENT_PASSED",
            "gate_alias": "LIVE_SIGNAL_EVENT_GATE_PASSED",
            "trading_ready": False,
            "notification_ready": False,
            "long_running_ready": False,
        },
        service_parent_packet_sha256="1" * 64,
        deployment_receipt_sha256="2" * 64,
        s6_07_rebind_receipt_sha256="3" * 64,
    )
    path = tmp_path / "完成证据" / "completion_receipt.json"
    publish_final_receipt_create_only(path, receipt)

    assert receipt["receipt_hash"] == final_receipt_hash(receipt)
    assert receipt["trading_ready"] is False
    assert receipt["notification_ready"] is False
    assert receipt["long_running_ready"] is False
    with pytest.raises(RuntimeError, match="create_only_path_exists"):
        publish_final_receipt_create_only(path, receipt)
