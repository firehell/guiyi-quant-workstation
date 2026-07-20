from __future__ import annotations

from app.services.live_t3_gate import (
    LiveT3ApprovalError,
    build_approval_packet,
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
