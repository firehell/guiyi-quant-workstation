from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.s607_database_recovery import (
    S607DatabaseRecoveryError,
    build_recovery_approval_packet,
    build_recovery_manifest,
    verify_recovery_approval_packet,
)


def _current_facts() -> dict[str, object]:
    return {
        "database": {
            "database": "guiyi_quant",
            "oid": 16384,
            "revision": "20260721_0025",
        },
        "row_counts": {
            "profile_active_bindings": 5124,
            "after_market_scheduler_checkpoints": 0,
            "backtest_tasks": 23,
            "backtest_reports": 15,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "signal_events": 3,
            "signal_notifications": 1,
        },
        "runtime": {
            "commit": "a" * 40,
            "tracked_status_sha256": "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
        },
    }


def _recovery_rows() -> dict[str, object]:
    return {
        "profile_active_bindings": [
            {
                "id": 5240,
                "profile_id": "intraday_research_v1",
                "instrument_symbol": "jm",
                "contract_code": "JM2609",
                "period": "15m",
                "binding_status": "superseded",
            }
        ],
        "backtest_lineage": [
            {
                "table": "backtest_tasks",
                "id": 23,
                "profile_id": "intraday_research_v1",
                "market_data_file_id": 71338,
                "binding_snapshot": {"snapshot_hash": "b" * 64},
            }
        ],
        "scheduler_checkpoint": {
            "product": "jm",
            "status": "idle",
            "authorization_hash": "c" * 64,
        },
    }


def _evidence() -> dict[str, object]:
    return {
        "profile_bindings": {
            "path": "/evidence/s607-20260722.json",
            "sha256": "d" * 64,
        },
        "backtest_lineage": {
            "path": "/evidence/htdy-input.json",
            "sha256": "e" * 64,
        },
        "scheduler_checkpoint": {
            "path": "/evidence/d2-completion.json",
            "sha256": "f" * 64,
        },
    }


def test_manifest_is_blocked_when_any_original_field_is_unproven() -> None:
    manifest = build_recovery_manifest(
        current_facts=_current_facts(),
        recovery_rows=_recovery_rows(),
        evidence=_evidence(),
        unproven_fields=[
            "profile_active_bindings[5240].created_at",
            "scheduler_checkpoint.last_result",
        ],
    )

    assert manifest["status"] == "blocked"
    assert manifest["migration_allowed"] is False
    assert manifest["unproven_fields"] == [
        "profile_active_bindings[5240].created_at",
        "scheduler_checkpoint.last_result",
    ]
    assert len(str(manifest["manifest_hash"])) == 64


def test_approval_packet_rejects_blocked_manifest() -> None:
    manifest = build_recovery_manifest(
        current_facts=_current_facts(),
        recovery_rows=_recovery_rows(),
        evidence=_evidence(),
        unproven_fields=["scheduler_checkpoint.last_result"],
    )

    with pytest.raises(S607DatabaseRecoveryError, match="recovery_manifest_incomplete"):
        build_recovery_approval_packet(
            manifest=manifest,
            source={"commit": "1" * 40, "tree": "2" * 40},
        )


def test_complete_manifest_builds_deterministic_data_only_packet() -> None:
    manifest = build_recovery_manifest(
        current_facts=_current_facts(),
        recovery_rows=_recovery_rows(),
        evidence=_evidence(),
        unproven_fields=[],
    )
    source = {"commit": "1" * 40, "tree": "2" * 40}

    first = build_recovery_approval_packet(manifest=manifest, source=source)
    second = build_recovery_approval_packet(manifest=manifest, source=source)

    assert first == second
    assert first["status"] == "approval_required"
    assert first["writes_authorized"] is False
    assert first["allowed_operations"] == ["restore_exact_bound_database_rows"]
    assert first["forbidden_operations"] == [
        "database_migration",
        "runtime_deployment",
        "signal_event_write",
        "notification_write",
        "order_or_trade_write",
    ]


def test_packet_verifier_rejects_current_fact_drift() -> None:
    manifest = build_recovery_manifest(
        current_facts=_current_facts(),
        recovery_rows=_recovery_rows(),
        evidence=_evidence(),
        unproven_fields=[],
    )
    packet = build_recovery_approval_packet(
        manifest=manifest,
        source={"commit": "1" * 40, "tree": "2" * 40},
    )
    drifted = deepcopy(_current_facts())
    drifted["row_counts"]["signal_events"] = 4  # type: ignore[index]

    with pytest.raises(S607DatabaseRecoveryError, match="recovery_current_fact_drift"):
        verify_recovery_approval_packet(
            packet,
            approval_hash=str(packet["packet_hash"]),
            current_facts=drifted,
            current_source={"commit": "1" * 40, "tree": "2" * 40},
        )
