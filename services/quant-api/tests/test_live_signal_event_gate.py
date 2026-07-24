from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import subprocess

import pytest

from app.live_signal_event_gate import main
from app.services.after_market_real_acceptance import FORBIDDEN_COUNTERS
from app.services.live_signal_event_gate import (
    BLOCKED_NO_ELIGIBLE_STRATEGY_GATE,
    ELIGIBILITY_GATE,
    FINAL_GATE,
    LiveSignalEventGateError,
    assess_live_strategy_eligibility,
    build_final_verification,
    build_service_approval_packet,
    canonical_packet_hash,
    publish_final_receipt,
    validate_s6_final_receipt,
    verify_service_approval_packet,
)
from app.services.live_signal_event_gate import _runtime_identity


def _s6_receipt() -> dict:
    forbidden_counts = {name: index for index, name in enumerate(FORBIDDEN_COUNTERS, start=1)}
    return {
        "schema_version": 2,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "gate": "JM_EOD_INCREMENTAL_AUTOMATION_READY",
        "status": "completed",
        "runtime_commit": "a" * 40,
        "database_revision": "20260721_0025",
        "authorization_hash": "b" * 64,
        "deployment_lineage": {
            "deployment_commit": "9" * 40,
            "runtime_commit": "a" * 40,
            "deployment_is_ancestor": True,
            "d1_runtime_commit": "8" * 40,
            "d1_runtime_is_ancestor": True,
            "d2_outage_runtime_commit": "7" * 40,
            "d2_outage_runtime_is_ancestor": True,
            "deployment_receipt": {"path": "/runtime/s6/deployment.json", "sha256": "1" * 64},
            "service_enable_packet": {"path": "/runtime/s6/enable.json", "sha256": "c" * 64},
            "d1_service_enable_packet": {"path": "/runtime/s6/d1-enable.json", "sha256": "d" * 64},
            "d2_outage_service_enable_packet": {
                "path": "/runtime/s6/d2-outage-enable.json",
                "sha256": "e" * 64,
            },
        },
        "d1": {
            "trading_day": "2026-07-22",
            "batch_id": "s607_20260722_aaaaaaaa",
            "execution_packet_hash": "5" * 64,
            "receipt_sha256": "6" * 64,
            "runtime_commit": "8" * 40,
            "authorization_hash": "3" * 64,
            "evidence": {"path": "/runtime/s6/d1.json", "sha256": "7" * 64},
        },
        "d2_outage": {
            "trading_day": "2026-07-24",
            "last_successful_before_outage": "2026-07-23",
            "archive_lag_trading_days": 1,
            "heartbeat": {"status": "degraded", "error_type": "heartbeat_missing"},
            "runtime_commit": "7" * 40,
            "authorization_hash": "4" * 64,
            "evidence": {"path": "/runtime/s6/d2-outage.json", "sha256": "8" * 64},
        },
        "d2": {
            "trading_day": "2026-07-24",
            "batch_id": "s607_20260724_aaaaaaaa",
            "execution_packet_hash": "9" * 64,
            "receipt_sha256": "a" * 64,
            "evidence": {"path": "/runtime/s6/d2.json", "sha256": "b" * 64},
        },
        "forbidden_write_counts": {
            "baseline": forbidden_counts,
            "final": dict(forbidden_counts),
        },
        "forbidden_write_deltas": {name: 0 for name in FORBIDDEN_COUNTERS},
        "scope_boundaries": {
            "jm_eod_incremental_automation_ready": True,
            "jm_runtime_ready": False,
            "long_running_ready": False,
            "signal_event_ready": False,
            "notification_ready": False,
            "automatic_trading_ready": False,
        },
    }


def _facts() -> dict:
    return {
        "runtime": {
            "commit": "c" * 40,
            "tracked_state_sha256": "d" * 64,
            "uv_lock_sha256": "e" * 64,
            "project_root": "/runtime/guiyi",
            "output_root": "/runtime/reports",
            "device_id": 123,
        },
        "database": {
            "driver": "postgresql+psycopg",
            "host": "127.0.0.1",
            "port": 5432,
            "database": "guiyi_quant",
            "revision": "20260721_0025",
        },
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-23",
        "profile_binding_sha256": "f" * 64,
        "strategy": {
            "code": "jm_v1b_daily_direction_fast_entry",
            "version": "v1b.0",
            "source_sha256": "1" * 64,
        },
        "indicator_policy": {"snapshot": {"schema_version": "strategy_indicator_policy_v1"}, "sha256": "2" * 64},
        "strategy_eligibility": _strategy_eligibility(),
        "quality_policy": {
            "quality_status": "passed",
            "warnings": "empty",
            "bar_status": "confirmed",
            "periods": ["5m", "15m"],
        },
        "feature_flags": {
            "GUIYI_LIVE_RUNTIME_ENABLED": True,
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
            "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED": False,
            "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": True,
        },
        "authorization_config": {
            "approval_packet_present": False,
            "approval_hash_present": False,
        },
        "live_table_baseline": {
            "minute_groups": [],
            "aggregate_groups": [],
            "minute_rows": [],
            "aggregate_rows": [],
            "ingest_checkpoints": [],
            "aggregation_checkpoints": [],
        },
        "allowed_table_baseline": {
            "strategy_signals": {"count": 10, "max_id": 10, "row_hashes": {"10": "old-signal"}},
            "signal_events": {"count": 20, "max_id": 20, "row_hashes": {"20": "old-event"}},
        },
        "forbidden_table_baseline": {
            "signal_notifications": 3,
            "signal_scan_tasks": 4,
            "backtest_tasks": 5,
            "backtest_reports": 6,
            "backtest_trades": 7,
            "backtest_orders": 8,
        },
    }


def _strategy_eligibility() -> dict:
    return {
        "schema_version": "live_signal_strategy_eligibility_v1",
        "status": "eligible",
        "gate": ELIGIBILITY_GATE,
        "strategy_code": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "profile_id": "live_observation_v1",
        "frozen_policy_id": "jm_v1b_report14_frozen_v1",
        "source_sha256": "1" * 64,
        "policy_sha256": "2" * 64,
        "frozen_legacy": True,
        "confirmed_only": True,
        "observation_only": True,
        "notification_ready": False,
        "trading_ready": False,
    }


def _packet() -> dict:
    return build_service_approval_packet(
        target_trading_day="2026-07-24",
        bound_facts=_facts(),
        s6_final_receipt={
            "path": "/runtime/reports/s6/final_receipt.json",
            "sha256": "3" * 64,
            "receipt": _s6_receipt(),
        },
    )


def _healthy_disabled_runtime(*, now: datetime | None = None) -> dict:
    current = now or datetime.now(UTC)
    return {
        "status": "ok",
        "generated_at": current.isoformat(),
        "components": {
            "scheduler": {
                "status": "ok",
                "enabled": True,
                "heartbeat_at": current.isoformat(),
                "heartbeat_age_seconds": 0,
                "signal_events_enabled": False,
                "signal_event_gate_status": "disabled",
                "signal_event_authorization_hash": None,
            }
        },
    }


def _authorized_execution_runtime(
    packet: dict,
    *,
    now: datetime | None = None,
    event_ids: list[int] | None = None,
) -> dict:
    current = now or datetime.now(UTC)
    return {
        "status": "ok",
        "generated_at": current.isoformat(),
        "components": {
            "scheduler": {
                "status": "ok",
                "enabled": True,
                "heartbeat_at": current.isoformat(),
                "heartbeat_age_seconds": 0,
                "signal_events_enabled": True,
                "signal_event_gate_status": "authorized",
                "signal_event_authorization_hash": packet["packet_hash"],
                "signal_event_target_trading_day": packet["target_trading_day"],
                "signal_event_result": {
                    "created": 0,
                    "changed": 0,
                    "unchanged": 1,
                    "blocked": 0,
                    "event_ids": event_ids or [21],
                },
            }
        },
    }


def _review_lineage(*, event_id: int = 21) -> dict:
    return {
        "schema_version": "review_source_lineage_v1",
        "source_type": "signal_event",
        "source_id": event_id,
        "source_snapshot_schema_version": "signal_review_lineage_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "signal_profile_v1",
        "quality_policy": "passed_only",
        "primary": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 101,
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "period": "15m",
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "data_version": "jm-live-context-v1",
        },
        "context_assets": [],
        "bar": {
            "bar_start": "2026-07-24T01:15:00+00:00",
            "bar_end": "2026-07-24T01:30:00+00:00",
            "confirmation_mode": "live_confirmed",
        },
    }


def _event(*, event_id: int = 21, event_key: str = "signal_created:live:key:created") -> dict:
    return {
        "id": event_id,
        "created_at": datetime.now(UTC).isoformat(),
        "event_key": event_key,
        "event_type": "signal_created",
        "source_mode": "live_confirmed",
        "strategy_name": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "symbol": "jm",
        "actual_contract": "JM2609",
        "period": "15m",
        "trading_day": "2026-07-24",
        "bar_end": "2026-07-24T01:30:00+00:00",
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": {"status": "passed"},
        "profile_id": "live_observation_v1",
        "payload": {
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v1",
                "resolver_name": "ProfileLineageResolver",
                "resolver_contract_version": "signal_profile_v1",
                "quality_policy": "passed_only",
                "source_mode": "live_confirmed",
                "primary": {
                    "profile_id": "live_observation_v1",
                    "market_data_file_id": 101,
                    "instrument_symbol": "jm",
                    "contract_code": "JM2609",
                    "period": "15m",
                    "provider": "rqdata",
                    "data_role": "primary",
                    "quality_status": "passed",
                    "data_version": "jm-live-context-v1",
                },
                "contract": {"actual_contract": "JM2609"},
                "bar": {
                    "bar_end": "2026-07-24T01:30:00+00:00",
                    "confirmation_mode": "live_confirmed",
                    "bar_status": "confirmed",
                    "live_bar_id": 101,
                    "live_bar_revision": 1,
                },
            }
        },
    }


def _signal() -> dict:
    return {
        "id": 11,
        "is_new": True,
        "dedupe_key": "live:dedupe",
        "strategy_name": "jm_v1b_daily_direction_fast_entry",
        "strategy_version": "v1b.0",
        "symbol": "jm",
        "actual_contract": "JM2609",
        "period": "15m",
        "provider": "rqdata",
        "source": "live_db_actual_contract",
        "data_role": "primary",
        "status": "entry_signal",
        "quality_status": {"status": "passed"},
        "profile_id": "live_observation_v1",
        "features": {
            "source_mode": "live_confirmed",
            "confirmed_bar": True,
            "observation_only": True,
            "auto_order": False,
            "formal_lineage": {"schema_version": "signal_review_lineage_v1"},
        },
    }


def test_s6_final_receipt_is_mandatory_and_hash_bound(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(LiveSignalEventGateError, match="s6_final_receipt_missing"):
        validate_s6_final_receipt(missing)

    path = tmp_path / "final.json"
    path.write_text(json.dumps(_s6_receipt()), encoding="utf-8")
    artifact = validate_s6_final_receipt(path)
    assert artifact["receipt"]["gate"] == "JM_EOD_INCREMENTAL_AUTOMATION_READY"
    assert len(artifact["sha256"]) == 64

    with pytest.raises(LiveSignalEventGateError, match="s6_final_receipt_hash_mismatch"):
        validate_s6_final_receipt(path, expected_sha256="0" * 64)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("gate", "REAL_ACCEPTANCE_IN_PROGRESS", "s6_final_receipt_gate_invalid"),
        ("status", "pending", "s6_final_receipt_status_invalid"),
        ("database_revision", "20260721_0024", "s6_final_receipt_database_revision_invalid"),
        ("runtime_commit", "z" * 40, "s6_final_receipt_runtime_commit_invalid"),
        ("authorization_hash", "z" * 64, "s6_final_receipt_authorization_hash_invalid"),
    ],
)
def test_invalid_s6_final_receipt_fails_closed(tmp_path, field, value, reason) -> None:
    receipt = {**_s6_receipt(), field: value}
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(LiveSignalEventGateError, match=reason):
        validate_s6_final_receipt(path)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda receipt: receipt["scope_boundaries"].update({"auto_trading_ready": False}),
            "s6_final_receipt_scope_boundaries_invalid",
        ),
        (
            lambda receipt: receipt["deployment_lineage"].update({"runtime_commit": "c" * 40}),
            "s6_final_receipt_deployment_lineage_invalid",
        ),
        (
            lambda receipt: receipt["d2"].update({"trading_day": "2026-07-22"}),
            "s6_final_receipt_d2_invalid",
        ),
        (
            lambda receipt: receipt["forbidden_write_deltas"].update({"signal_events": 1}),
            "s6_final_receipt_forbidden_write_deltas_invalid",
        ),
        (
            lambda receipt: receipt.update({"d1": "untrusted"}),
            "s6_final_receipt_d1_invalid",
        ),
    ],
)
def test_s6_final_receipt_rejects_schema_v2_contract_drift(tmp_path, mutate, reason) -> None:
    receipt = _s6_receipt()
    mutate(receipt)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(LiveSignalEventGateError, match=reason):
        validate_s6_final_receipt(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: receipt["d2_outage"].update({"archive_lag_trading_days": True}),
        lambda receipt: receipt["d2_outage"].update({"archive_lag_trading_days": "1"}),
        lambda receipt: receipt["d2_outage"].update({"archive_lag_trading_days": 0}),
        lambda receipt: receipt["d2_outage"].update({"heartbeat": []}),
        lambda receipt: receipt["d2_outage"]["heartbeat"].update({"status": "ok"}),
        lambda receipt: receipt["d2_outage"]["heartbeat"].update({"error_type": "scheduler_stopped"}),
    ],
)
def test_s6_final_receipt_rejects_invalid_d2_outage_contract(tmp_path, mutate) -> None:
    receipt = _s6_receipt()
    mutate(receipt)
    path = tmp_path / "invalid-outage.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(LiveSignalEventGateError, match="s6_final_receipt_d2_outage_invalid"):
        validate_s6_final_receipt(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: receipt.update(
            {
                "forbidden_write_counts": {
                    "baseline": {"unexpected": 0},
                    "final": {"unexpected": 0},
                },
                "forbidden_write_deltas": {"unexpected": 0},
            }
        ),
        lambda receipt: receipt["forbidden_write_counts"]["baseline"].pop("strategy_signals"),
        lambda receipt: receipt["forbidden_write_counts"]["final"].update({"unexpected": 0}),
        lambda receipt: receipt["forbidden_write_counts"]["baseline"].update({"signal_events": True}),
        lambda receipt: receipt["forbidden_write_counts"].update(
            {"baseline": {name: -1 for name in FORBIDDEN_COUNTERS}, "final": {name: -1 for name in FORBIDDEN_COUNTERS}}
        ),
        lambda receipt: receipt["forbidden_write_deltas"].update({"strategy_signals": True}),
        lambda receipt: receipt["forbidden_write_deltas"].update({"strategy_signals": 1}),
    ],
)
def test_s6_final_receipt_rejects_invalid_forbidden_counter_contract(tmp_path, mutate) -> None:
    receipt = _s6_receipt()
    mutate(receipt)
    path = tmp_path / "invalid-counters.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(LiveSignalEventGateError, match="s6_final_receipt_forbidden_write_deltas_invalid"):
        validate_s6_final_receipt(path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: receipt["d1"]["evidence"].update({"path": "   "}),
        lambda receipt: receipt["d1"].update({"evidence": {"path": ["/runtime/s6/d1.json"], "sha256": "7" * 64}}),
        lambda receipt: receipt["d1"]["evidence"].update({"sha256": "A" * 64}),
        lambda receipt: receipt["d1"]["evidence"].update({"sha256": ["7" * 64]}),
    ],
)
def test_s6_final_receipt_rejects_malformed_evidence_fields(tmp_path, mutate) -> None:
    receipt = _s6_receipt()
    mutate(receipt)
    path = tmp_path / "invalid-evidence.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(LiveSignalEventGateError, match="s6_final_receipt_d1_invalid"):
        validate_s6_final_receipt(path)


def test_packet_is_canonical_single_day_and_scope_bound() -> None:
    packet = _packet()

    assert FINAL_GATE == "LIVE_SIGNAL_EVENT_GATE_PASSED"
    assert packet["schema_version"] == 2
    assert packet["packet_hash"] == canonical_packet_hash(packet)
    assert packet["target_gate"] == FINAL_GATE
    assert packet["target_trading_day"] == "2026-07-24"
    assert packet["writes_authorized"] is False
    assert packet["allowed_writes"] == [
        "live_minute_bars",
        "live_ingest_checkpoints",
        "live_aggregated_bars",
        "live_aggregation_checkpoints",
        "runtime_scheduler_lock_and_heartbeat",
        "strategy_signals_scoped",
        "signal_events_scoped",
    ]
    assert "signal_notifications" in packet["forbidden_writes"]
    assert "orders_or_trades" in packet["forbidden_writes"]
    assert packet["strategy_eligibility"] == _strategy_eligibility()
    assert packet["revision_contract"] == {
        "state_key_fields": ["live_bar_id", "live_bar_revision"],
        "revision_change_event_type": "signal_changed",
        "proof": "commit_bound_integration_test",
        "production_bar_mutated": False,
    }


def test_strategy_eligibility_allows_only_frozen_jm_v1b_and_blocks_htdy() -> None:
    eligible = assess_live_strategy_eligibility(
        strategy={"code": "jm_v1b_daily_direction_fast_entry", "version": "v1b.0", "source_sha256": "1" * 64},
        indicator_policy={
            "snapshot": {
                "strategy_code": "jm_v1b_daily_direction_fast_entry",
                "strategy_version": "v1b.0",
                "profile_id": "live_observation_v1",
                "formal_policy_ids": [
                    "jm_v1b_report14_frozen_v1",
                    "ema_first_value_legacy_v1",
                    "quantcore_atr_ema_first_tr_v1",
                ],
                "confirmed_only": True,
                "frozen_legacy": True,
                "research_status": "frozen_legacy",
            },
            "sha256": "2" * 64,
        },
    )
    assert eligible == _strategy_eligibility()

    blocked = assess_live_strategy_eligibility(
        strategy={"code": "huotian_dayou_strict", "version": "v0.1.0-backtest-candidate", "source_sha256": "3" * 64},
        indicator_policy={"snapshot": {}, "sha256": "4" * 64},
    )
    assert blocked["status"] == "blocked"
    assert blocked["gate"] == BLOCKED_NO_ELIGIBLE_STRATEGY_GATE
    assert blocked["trading_ready"] is False
    assert "strategy_not_live_eligible" in blocked["blocked_reasons"]

    facts = deepcopy(_facts())
    facts["strategy_eligibility"] = blocked
    with pytest.raises(LiveSignalEventGateError, match=BLOCKED_NO_ELIGIBLE_STRATEGY_GATE):
        build_service_approval_packet(
            target_trading_day="2026-07-24",
            bound_facts=facts,
            s6_final_receipt={
                "path": "/runtime/reports/s6/final_receipt.json",
                "sha256": "3" * 64,
                "receipt": _s6_receipt(),
            },
        )


def test_packet_build_requires_safe_pre_enable_flags() -> None:
    facts = deepcopy(_facts())
    facts["feature_flags"]["GUIYI_WECHAT_AUTOSEND_ENABLED"] = True
    with pytest.raises(LiveSignalEventGateError, match="packet_pre_enable_flags_invalid"):
        build_service_approval_packet(
            target_trading_day="2026-07-24",
            bound_facts=facts,
            s6_final_receipt={
                "path": "/runtime/reports/s6/final_receipt.json",
                "sha256": "3" * 64,
                "receipt": _s6_receipt(),
            },
        )


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("runtime", "commit"), "9" * 40, "bound_fact_drift:runtime"),
        (("database", "revision"), "20260721_0026", "bound_fact_drift:database"),
        (("profile_binding_sha256",), "9" * 64, "bound_fact_drift:profile_binding_sha256"),
        (("strategy", "version"), "v1b.1", "bound_fact_drift:strategy"),
        (("indicator_policy", "sha256"), "9" * 64, "bound_fact_drift:indicator_policy"),
    ],
)
def test_packet_rejects_bound_fact_drift(path, value, reason) -> None:
    packet = _packet()
    current = deepcopy(_facts())
    target = current
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(LiveSignalEventGateError, match=reason):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
            current_trading_day="2026-07-24",
        )


def test_packet_rejects_wrong_day_flags_and_forbidden_delta() -> None:
    packet = _packet()
    with pytest.raises(LiveSignalEventGateError, match="target_trading_day_mismatch"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=_facts(),
            current_trading_day="2026-07-25",
        )

    invalid_flags = deepcopy(_facts())
    invalid_flags["feature_flags"]["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] = True
    invalid_flags["feature_flags"]["GUIYI_WECHAT_AUTOSEND_ENABLED"] = True
    invalid_flags["authorization_config"] = {
        "approval_packet_present": True,
        "approval_hash_present": True,
    }
    with pytest.raises(LiveSignalEventGateError, match="wechat_autosend_must_be_false"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=invalid_flags,
            current_trading_day="2026-07-24",
            execution_phase=True,
        )

    forbidden = deepcopy(_facts())
    forbidden["forbidden_table_baseline"]["signal_notifications"] += 1
    with pytest.raises(LiveSignalEventGateError, match="forbidden_table_delta"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=forbidden,
            current_trading_day="2026-07-24",
            execution_phase=True,
        )


def test_packet_allows_only_monotonic_scoped_signal_progress() -> None:
    packet = _packet()
    current = deepcopy(_facts())
    current["feature_flags"]["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] = True
    current["authorization_config"] = {
        "approval_packet_present": True,
        "approval_hash_present": True,
    }
    current["allowed_table_baseline"]["strategy_signals"] = {
        "count": 11,
        "max_id": 11,
        "row_hashes": {"10": "old-signal", "11": "new-signal"},
    }
    current["allowed_table_baseline"]["signal_events"] = {
        "count": 21,
        "max_id": 21,
        "row_hashes": {"20": "old-event", "21": "new-event"},
    }

    verify_service_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=current,
        current_trading_day="2026-07-24",
        execution_phase=True,
    )


def test_packet_rejects_unrelated_live_table_delta() -> None:
    packet = _packet()
    current = deepcopy(_facts())
    current["feature_flags"]["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] = True
    current["authorization_config"] = {
        "approval_packet_present": True,
        "approval_hash_present": True,
    }
    current["live_table_baseline"]["minute_groups"] = [
        {
            "provider": "rqdata",
            "instrument_symbol": "rb",
            "contract_code": "RB2610",
            "period": "1m",
            "trading_day": "2026-07-24",
            "bar_status": "confirmed",
            "quality_status": "passed",
            "count": 1,
            "max_id": 1,
        }
    ]

    with pytest.raises(LiveSignalEventGateError, match="live_table_scope_invalid"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
            current_trading_day="2026-07-24",
            execution_phase=True,
        )


def test_packet_rejects_existing_unrelated_live_row_content_mutation() -> None:
    facts = _facts()
    facts["live_table_baseline"]["minute_rows"] = [
        {
            "id": 9,
            "provider": "rqdata",
            "instrument_symbol": "rb",
            "contract_code": "RB2610",
            "period": "1m",
            "bar_datetime": "2026-07-24 01:30:00+00:00",
            "trading_day": "2026-07-24",
            "bar_status": "confirmed",
            "quality_status": "passed",
            "row_sha256": "before",
        }
    ]
    packet = build_service_approval_packet(
        target_trading_day="2026-07-24",
        bound_facts=facts,
        s6_final_receipt={
            "path": "/runtime/reports/s6/final_receipt.json",
            "sha256": "3" * 64,
            "receipt": _s6_receipt(),
        },
    )
    current = deepcopy(facts)
    current["feature_flags"]["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] = True
    current["authorization_config"] = {
        "approval_packet_present": True,
        "approval_hash_present": True,
    }
    current["live_table_baseline"]["minute_rows"][0]["row_sha256"] = "after"

    with pytest.raises(LiveSignalEventGateError, match="minute_rows_delta_out_of_scope"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
            current_trading_day="2026-07-24",
            execution_phase=True,
        )


def test_packet_requires_changed_checkpoint_to_reference_target_day_bar() -> None:
    facts = _facts()
    facts["live_table_baseline"]["ingest_checkpoints"] = [
        {
            "id": 7,
            "provider": "rqdata",
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "period": "1m",
            "source_mode": "poll_get_price_1m",
            "status": "success",
            "last_bar_at": "2026-07-23 01:30:00+00:00",
            "last_source_bar_at": "",
            "last_success_at": "2026-07-23 01:31:00+00:00",
            "consecutive_error_count": 0,
            "row_sha256": "before",
        }
    ]
    packet = build_service_approval_packet(
        target_trading_day="2026-07-24",
        bound_facts=facts,
        s6_final_receipt={
            "path": "/runtime/reports/s6/final_receipt.json",
            "sha256": "3" * 64,
            "receipt": _s6_receipt(),
        },
    )
    current = deepcopy(facts)
    current["feature_flags"]["GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"] = True
    current["authorization_config"] = {
        "approval_packet_present": True,
        "approval_hash_present": True,
    }
    current["live_table_baseline"]["ingest_checkpoints"][0].update(
        {
            "last_bar_at": "2026-07-24 01:30:00+00:00",
            "last_success_at": "2026-07-24 01:31:00+00:00",
            "row_sha256": "after",
        }
    )

    with pytest.raises(LiveSignalEventGateError, match="ingest_checkpoints_delta_out_of_scope"):
        verify_service_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
            current_trading_day="2026-07-24",
            execution_phase=True,
        )


def test_final_verifier_requires_event_scope_dedupe_forbidden_zero_and_restored_runtime() -> None:
    packet = _packet()
    current = deepcopy(_facts())
    current["allowed_table_baseline"]["strategy_signals"] = {
        "count": 11,
        "max_id": 11,
        "row_hashes": {"10": "old-signal", "11": "new-signal"},
    }
    current["allowed_table_baseline"]["signal_events"] = {
        "count": 21,
        "max_id": 21,
        "row_hashes": {"20": "old-event", "21": "new-event"},
    }
    flags = deepcopy(_facts()["feature_flags"])

    result = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[_review_lineage()],
    )

    assert result["status"] == "passed"
    assert result["gate"] == FINAL_GATE
    assert result["schema_version"] == 2
    assert result["event_count"] == 1
    assert result["idempotency_heartbeat"]["unchanged"] == 1
    assert result["review_lineage_event_ids"] == [21]
    assert result["review_deep_links"] == ["/review?source_type=signal_event&source_id=21&signal_event_id=21"]
    assert result["revision_contract"]["production_bar_mutated"] is False
    assert result["notification_ready"] is False
    assert result["auto_trading_ready"] is False

    missing_execution = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health={},
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[_review_lineage()],
    )
    assert missing_execution["status"] == "failed"
    assert "execution_runtime_not_authorized" in missing_execution["errors"]
    assert "idempotency_heartbeat_missing" in missing_execution["errors"]

    missing_review = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[],
    )
    assert missing_review["status"] == "failed"
    assert "review_lineage_event_set_invalid" in missing_review["errors"]

    pending = build_final_verification(
        packet=packet,
        current_facts=_facts(),
        new_signal_rows=[],
        new_event_rows=[],
        restored_flags=flags,
        execution_runtime_health={},
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[],
    )
    assert pending["status"] == "pending"
    assert pending["gate"] == "PENDING_ELIGIBLE_EVENT"

    duplicate = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event(), _event(event_id=22)],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[_review_lineage(), _review_lineage(event_id=22)],
    )
    assert duplicate["status"] == "failed"
    assert "event_dedupe_invalid" in duplicate["errors"]

    drifted = deepcopy(current)
    drifted["runtime"]["commit"] = "9" * 40
    drift = build_final_verification(
        packet=packet,
        current_facts=drifted,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[_review_lineage()],
    )
    assert drift["status"] == "failed"
    assert "bound_fact_drift:runtime" in drift["errors"]

    stale_authorized = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health={
            "status": "ok",
            "generated_at": datetime.now(UTC).isoformat(),
            "components": {
                "scheduler": {
                    "status": "ok",
                    "enabled": True,
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                    "heartbeat_age_seconds": 0,
                    "signal_events_enabled": True,
                    "signal_event_gate_status": "authorized",
                    "signal_event_authorization_hash": packet["packet_hash"],
                }
            },
        },
        review_lineages=[_review_lineage()],
    )
    assert stale_authorized["status"] == "failed"
    assert "runtime_signal_gate_not_disabled" in stale_authorized["errors"]

    unrelated_signal_update = deepcopy(current)
    unrelated_signal_update["allowed_table_baseline"]["strategy_signals"]["row_hashes"]["10"] = "mutated"
    unrelated = build_final_verification(
        packet=packet,
        current_facts=unrelated_signal_update,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(),
        review_lineages=[_review_lineage()],
    )
    assert unrelated["status"] == "failed"
    assert "strategy_signal_unscoped_mutation" in unrelated["errors"]

    verification_time = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    stale = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[_event()],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=_healthy_disabled_runtime(now=verification_time - timedelta(minutes=10)),
        review_lineages=[_review_lineage()],
        now=verification_time,
    )
    assert stale["status"] == "failed"
    assert "runtime_health_stale" in stale["errors"]

    event_time = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    pre_event_health = build_final_verification(
        packet=packet,
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[{**_event(), "created_at": event_time.isoformat()}],
        restored_flags=flags,
        execution_runtime_health=_authorized_execution_runtime(packet, now=event_time),
        runtime_health=_healthy_disabled_runtime(now=event_time - timedelta(seconds=1)),
        review_lineages=[_review_lineage()],
        now=event_time,
    )
    assert pre_event_health["status"] == "failed"
    assert "runtime_health_precedes_signal_event" in pre_event_health["errors"]


def test_final_receipt_is_create_only_and_redacted(tmp_path) -> None:
    packet = _packet()
    foundation_path = tmp_path / "s6-final.json"
    foundation_path.write_text(json.dumps(_s6_receipt()), encoding="utf-8")
    foundation = validate_s6_final_receipt(foundation_path)
    packet["foundation_receipt"] = {
        "path": foundation["path"],
        "sha256": foundation["sha256"],
        **foundation["receipt"],
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    current = deepcopy(_facts())
    current["allowed_table_baseline"]["strategy_signals"] = {
        "count": 11,
        "max_id": 11,
        "row_hashes": {"10": "old-signal", "11": "new-signal"},
    }
    current["allowed_table_baseline"]["signal_events"] = {
        "count": 21,
        "max_id": 21,
        "row_hashes": {"20": "old-event", "21": "new-event"},
    }
    event = _event()
    runtime_health = _healthy_disabled_runtime()
    path = tmp_path / "receipt.json"
    receipt = publish_final_receipt(
        path,
        packet=packet,
        approval_hash=packet["packet_hash"],
        current_facts=current,
        new_signal_rows=[_signal()],
        new_event_rows=[event],
        restored_flags=_facts()["feature_flags"],
        execution_runtime_health=_authorized_execution_runtime(packet),
        runtime_health=runtime_health,
        review_lineages=[_review_lineage()],
        confirm_final_gate=True,
    )
    text = path.read_text(encoding="utf-8")

    assert receipt["gate"] == FINAL_GATE
    assert receipt["schema_version"] == 2
    assert receipt["strategy_eligibility"] == _strategy_eligibility()
    assert receipt["idempotency_heartbeat"]["created"] == 0
    assert receipt["idempotency_heartbeat"]["changed"] == 0
    assert receipt["idempotency_heartbeat"]["unchanged"] == 1
    assert receipt["review_lineage_event_ids"] == [21]
    assert receipt["review_note_created"] is False
    assert receipt["revision_contract"]["revision_change_event_type"] == "signal_changed"
    assert "approval_packet" not in text
    assert "/runtime/" not in text
    with pytest.raises(FileExistsError):
        publish_final_receipt(
            path,
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_facts=current,
            new_signal_rows=[_signal()],
            new_event_rows=[event],
            restored_flags=_facts()["feature_flags"],
            execution_runtime_health=_authorized_execution_runtime(packet),
            runtime_health=runtime_health,
            review_lineages=[_review_lineage()],
            confirm_final_gate=True,
        )

    fake = tmp_path / "fake.json"
    with pytest.raises(LiveSignalEventGateError, match="approval_hash_mismatch"):
        publish_final_receipt(
            fake,
            packet=packet,
            approval_hash="0" * 64,
            current_facts=current,
            new_signal_rows=[_signal()],
            new_event_rows=[event],
            restored_flags=_facts()["feature_flags"],
            execution_runtime_health=_authorized_execution_runtime(packet),
            runtime_health=runtime_health,
            review_lineages=[_review_lineage()],
            confirm_final_gate=True,
        )


def test_gate_cli_dry_run_and_missing_foundation_open_no_database(capsys, tmp_path) -> None:
    def fail_session_factory():
        raise AssertionError("dry-run or missing foundation must not open database")

    assert main(["--dry-run"], session_factory=fail_session_factory) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["would_open_database"] is False
    assert dry_run["would_write_signal_event"] is False
    assert dry_run["would_publish_receipt"] is False

    exit_code = main(
        [
            "--prepare-packet",
            "--s6-final-receipt",
            str(tmp_path / "missing.json"),
            "--target-trading-day",
            "2026-07-24",
            "--packet-out",
            str(tmp_path / "packet.json"),
            "--output-root",
            str(tmp_path),
        ],
        session_factory=fail_session_factory,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "blocked"
    assert payload["error_type"] == "LiveSignalEventGateError"


def test_strategy_eligibility_cli_is_read_only_and_create_only(capsys, tmp_path) -> None:
    def fail_session_factory():
        raise AssertionError("strategy eligibility check must not open database")

    evidence = tmp_path / "strategy-eligibility.json"
    assert (
        main(
            ["--check-strategy-eligibility", "--eligibility-out", str(evidence)],
            session_factory=fail_session_factory,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "eligible"
    assert payload["gate"] == ELIGIBILITY_GATE
    assert json.loads(evidence.read_text(encoding="utf-8")) == payload

    assert (
        main(
            ["--check-strategy-eligibility", "--eligibility-out", str(evidence)],
            session_factory=fail_session_factory,
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error_type"] == "FileExistsError"


def test_prepare_packet_requires_explicit_lowercase_foundation_sha256(capsys, tmp_path) -> None:
    receipt = tmp_path / "s6-final.json"
    receipt.write_text(json.dumps(_s6_receipt()), encoding="utf-8")

    def fail_session_factory():
        raise AssertionError("prepare without a bound hash must not open database")

    args = [
        "--prepare-packet",
        "--s6-final-receipt",
        str(receipt),
        "--target-trading-day",
        "2026-07-24",
        "--packet-out",
        str(tmp_path / "packet.json"),
        "--output-root",
        str(tmp_path),
    ]
    exit_code = main(
        args,
        session_factory=fail_session_factory,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload == {"status": "blocked", "error_type": "LiveSignalEventGateError"}


def test_runtime_identity_requires_clean_tracked_and_untracked_state(tmp_path) -> None:
    root = tmp_path / "repo"
    output = tmp_path / "output"
    root.mkdir()
    output.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    lock_path = root / "services" / "quant-api" / "uv.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("lock\n", encoding="utf-8")
    (root / "tracked.py").write_text("one\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(root), "add", "services/quant-api/uv.lock", "tracked.py"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)

    identity = _runtime_identity(root, output)
    assert identity["uv_lock_relative_path"] == "services/quant-api/uv.lock"
    assert len(identity["tracked_state_sha256"]) == 64
    assert len(identity["tree_sha"]) == 40

    (root / "untracked.py").write_text("x\n", encoding="utf-8")
    with pytest.raises(LiveSignalEventGateError, match="runtime_worktree_not_clean"):
        _runtime_identity(root, output)
    (root / "untracked.py").unlink()
    (root / "tracked.py").write_text("two\n", encoding="utf-8")
    with pytest.raises(LiveSignalEventGateError, match="runtime_worktree_not_clean"):
        _runtime_identity(root, output)
