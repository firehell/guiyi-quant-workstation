from __future__ import annotations

from app.services.live_t3_gate import (
    LiveT3ApprovalError,
    build_approval_packet,
    build_gate_audit,
    canonical_packet_hash,
    verify_approval_packet,
)


def test_packet_hash_and_bound_facts_verify() -> None:
    facts = {"git": {"commit": "abc"}, "actual_contract": "JM2609"}
    packet = build_approval_packet(facts)

    assert packet["packet_hash"] == canonical_packet_hash(packet)
    verify_approval_packet(packet, approval_hash=packet["packet_hash"], current_facts=facts)


def test_packet_drift_and_wrong_approval_fail_closed() -> None:
    facts = {"git": {"commit": "abc"}, "actual_contract": "JM2609"}
    packet = build_approval_packet(facts)

    for approval_hash, current, reason in (
        ("wrong", facts, "approval_hash_mismatch"),
        (packet["packet_hash"], {**facts, "actual_contract": "JM2701"}, "bound_fact_drift:actual_contract"),
    ):
        try:
            verify_approval_packet(packet, approval_hash=approval_hash, current_facts=current)
        except LiveT3ApprovalError as exc:
            assert str(exc) == reason
        else:
            raise AssertionError("approval mismatch must fail closed")


def test_packet_allows_only_monotonic_live_baseline_progress() -> None:
    facts = {
        "actual_contract": "JM2609",
        "live_baseline": {
            "live_minute_bars": 0,
            "live_aggregated_bars": 0,
            "ingest_checkpoints": [],
            "aggregation_checkpoints": [],
        },
    }
    packet = build_approval_packet(facts)
    advanced = {
        **facts,
        "live_baseline": {
            "live_minute_bars": 2,
            "live_aggregated_bars": 1,
            "ingest_checkpoints": [{"id": 1, "contract_code": "JM2609", "period": "1m"}],
            "aggregation_checkpoints": [{"id": 2, "contract_code": "JM2609", "period": "5m"}],
        },
    }
    verify_approval_packet(packet, approval_hash=packet["packet_hash"], current_facts=advanced)

    regressed = {**advanced, "live_baseline": {**advanced["live_baseline"], "live_minute_bars": -1}}
    try:
        verify_approval_packet(packet, approval_hash=packet["packet_hash"], current_facts=regressed)
    except LiveT3ApprovalError as exc:
        assert str(exc) == "bound_fact_drift:live_baseline"
    else:
        raise AssertionError("live baseline regression must fail closed")


def test_gate_audit_requires_two_successful_runs_and_zero_forbidden_delta() -> None:
    baseline = {
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-20",
        "active_binding_sha256": "binding",
        "live_baseline": {
            "live_minute_bars": 0,
            "live_aggregated_bars": 0,
            "ingest_checkpoints": [],
            "aggregation_checkpoints": [],
        },
        "forbidden_table_baseline": {"signal_events": 3, "market_data_files": 10},
    }
    packet = build_approval_packet(baseline)
    periods = ["5m", "15m", "30m", "60m", "1d", "1w"]
    current = {
        **baseline,
        "live_baseline": {
            "live_minute_bars": 2,
            "live_aggregated_bars": 1,
            "ingest_checkpoints": [{"contract_code": "JM2609", "period": "1m", "status": "success"}],
            "aggregation_checkpoints": [
                {"contract_code": "JM2609", "period": period, "status": "success"}
                for period in periods
            ],
        },
    }
    common = {
        "status": "success",
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-20",
        "trading_day": "2026-07-21",
        "writes_historical_active": False,
        "writes_signal_event": False,
        "sends_notification": False,
    }
    runs = [
        {**common, "ingest": {"confirmed_candidates": 2, "unchanged_count": 0, "max_trading_day": "2026-07-21"}},
        {**common, "ingest": {"confirmed_candidates": 2, "unchanged_count": 2, "max_trading_day": "2026-07-21"}},
    ]

    audit = build_gate_audit(
        packet=packet,
        current_facts=current,
        run_results=runs,
        project_flags={name: False for name in (
            "GUIYI_LIVE_RUNTIME_ENABLED",
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
            "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
            "GUIYI_WECHAT_AUTOSEND_ENABLED",
        )},
    )

    assert audit["status"] == "passed"
    assert audit["gate"] == "T3_REAL_PASSED"
    assert audit["live_minute_bar_delta"] == 2
    assert audit["forbidden_table_delta"] is False


def test_gate_audit_rejects_provider_trading_day_mismatch() -> None:
    baseline = {
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-20",
        "active_binding_sha256": "binding",
        "live_baseline": {
            "live_minute_bars": 0,
            "live_aggregated_bars": 0,
            "ingest_checkpoints": [],
            "aggregation_checkpoints": [],
        },
        "forbidden_table_baseline": {},
    }
    packet = build_approval_packet(baseline)
    current = {
        **baseline,
        "live_baseline": {
            "live_minute_bars": 1,
            "live_aggregated_bars": 1,
            "ingest_checkpoints": [{"contract_code": "JM2609", "period": "1m", "status": "success"}],
            "aggregation_checkpoints": [
                {"contract_code": "JM2609", "period": period, "status": "success"}
                for period in ("5m", "15m", "30m", "60m", "1d", "1w")
            ],
        },
    }
    common = {
        "status": "success",
        "actual_contract": "JM2609",
        "dominant_mapping_date": "2026-07-20",
        "trading_day": "2026-07-21",
        "writes_historical_active": False,
        "writes_signal_event": False,
        "sends_notification": False,
    }
    audit = build_gate_audit(
        packet=packet,
        current_facts=current,
        run_results=[
            {**common, "ingest": {"confirmed_candidates": 1, "max_trading_day": "2026-07-20"}},
            {**common, "ingest": {"unchanged_count": 1, "max_trading_day": "2026-07-20"}},
        ],
        project_flags={
            name: False
            for name in (
                "GUIYI_LIVE_RUNTIME_ENABLED",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
                "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
                "GUIYI_WECHAT_AUTOSEND_ENABLED",
            )
        },
    )

    assert audit["status"] == "failed"
    assert "confirmed_1m_trading_day_mismatch" in audit["errors"]
    assert "idempotent_1m_trading_day_mismatch" in audit["errors"]
