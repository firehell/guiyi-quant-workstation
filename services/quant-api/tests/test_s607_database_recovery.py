from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.s607_database_recovery import (
    S607DatabaseRecoveryError,
    apply_semantic_recovery,
    build_recovery_approval_packet,
    build_recovery_manifest,
    build_semantic_recovery_manifest,
    derive_semantic_recovery_rows,
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


def _semantic_bindings() -> list[dict[str, object]]:
    periods = ("15m", "1m", "5m", "15m", "1m", "5m", "1d")
    profiles = (
        "intraday_research_v1",
        "intraday_research_v1",
        "intraday_research_v1",
        "live_observation_v1",
        "live_observation_v1",
        "live_observation_v1",
        "long_horizon_daily_v1",
    )
    file_ids = (103981, 103980, 103984, 103981, 103980, 103984, 103982)
    return [
        {
            "id": 5240 + offset,
            "profile_id": profiles[offset],
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "contract_role": "actual_contract",
            "period": periods[offset],
            "data_version": f"version-{offset}",
            "market_data_file_id": file_ids[offset],
            "binding_status": "superseded",
            "activated_at": f"2026-07-22T09:00:53.{offset:06d}+00:00",
            "superseded_at": f"2026-07-23T09:02:49.{offset:06d}+00:00",
            "created_at": f"2026-07-22T09:00:53.{offset:06d}+00:00",
            "updated_at": f"2026-07-23T09:02:49.{offset:06d}+00:00",
        }
        for offset in range(7)
    ]


def _semantic_checkpoint() -> dict[str, object]:
    return {
        "product": "jm",
        "exchange_code": "DCE",
        "status": "idle",
        "authorization_hash": "c" * 64,
        "last_successful_trading_day": "2026-07-24",
        "current_trading_day": None,
        "last_attempt_at": "2026-07-24T10:25:18.071055+00:00",
        "last_success_at": "2026-07-24T10:25:18.071055+00:00",
        "next_retry_at": None,
        "retry_count": 0,
        "last_error_type": None,
        "last_error_at": None,
        "last_execution_packet_hash": "a" * 64,
        "last_receipt_path": "/evidence/completion_receipt.json",
        "last_result": {
            "status": "semantic_rebuild_from_s607_d2_completion",
            "semantic_reconstruction": True,
            "source_snapshot_sha256": "f" * 64,
        },
        "created_at": "2026-07-26T12:00:00.000000+00:00",
        "updated_at": "2026-07-26T12:00:00.000000+00:00",
    }


def _semantic_evidence() -> dict[str, object]:
    return {
        "profile_bindings_created": {
            "path": "/evidence/s607-20260722.json",
            "sha256": "d" * 64,
        },
        "profile_bindings_superseded": {
            "path": "/evidence/s607-20260723.json",
            "sha256": "e" * 64,
        },
        "scheduler_checkpoint": {
            "path": "/evidence/d2-completion.json",
            "sha256": "f" * 64,
        },
        "external_backtest_lineage": {
            "path": "/evidence/execution_input_snapshot.json",
            "sha256": "1" * 64,
        },
    }


def _backup_and_drill() -> tuple[dict[str, object], dict[str, object]]:
    return (
        {
            "path": "/backup/guiyi-s607-pre-recovery",
            "manifest_sha256": "2" * 64,
            "dump_sha256": "3" * 64,
            "mode": "database-only",
        },
        {
            "path": "/backup/guiyi-s607-pre-recovery/isolated_restore_receipt.json",
            "sha256": "4" * 64,
            "status": "passed",
            "cleanup_complete": True,
        },
    )


def test_semantic_manifest_freezes_synthesized_fields_and_report15_no_write() -> None:
    backup, drill = _backup_and_drill()
    manifest = build_semantic_recovery_manifest(
        current_facts=_current_facts(),
        profile_active_bindings=_semantic_bindings(),
        scheduler_checkpoint=_semantic_checkpoint(),
        evidence=_semantic_evidence(),
        backup=backup,
        isolated_restore_drill=drill,
        synthesized_fields={
            "profile_active_bindings[*].created_at": "activated_at",
            "profile_active_bindings[*].updated_at": "superseded_at",
            "after_market_scheduler_checkpoints.last_result": "semantic_provenance",
            "after_market_scheduler_checkpoints.created_at": "recovered_at",
            "after_market_scheduler_checkpoints.updated_at": "recovered_at",
        },
        external_lineage_exception={
            "task_id": 23,
            "report_id": 15,
            "database_write": False,
            "evidence_sha256": "1" * 64,
        },
    )

    assert manifest["schema_version"] == 2
    assert manifest["status"] == "ready"
    assert manifest["recovery_mode"] == "bounded_semantic_reconstruction"
    assert manifest["allowed_tables"] == [
        "profile_active_bindings",
        "after_market_scheduler_checkpoints",
    ]
    assert manifest["external_lineage_exception"]["report_id"] == 15
    assert manifest["external_lineage_exception"]["database_write"] is False
    assert manifest["forbidden_tables"] == [
        "backtest_tasks",
        "backtest_reports",
        "signal_events",
        "signal_notifications",
        "strategy_signals",
        "orders",
        "trades",
    ]


def test_semantic_packet_requires_verified_database_backup_and_drill() -> None:
    backup, drill = _backup_and_drill()
    drill["cleanup_complete"] = False
    with pytest.raises(
        S607DatabaseRecoveryError,
        match="recovery_isolated_drill_invalid",
    ):
        build_semantic_recovery_manifest(
            current_facts=_current_facts(),
            profile_active_bindings=_semantic_bindings(),
            scheduler_checkpoint=_semantic_checkpoint(),
            evidence=_semantic_evidence(),
            backup=backup,
            isolated_restore_drill=drill,
            synthesized_fields={"checkpoint.created_at": "recovered_at"},
            external_lineage_exception={
                "task_id": 23,
                "report_id": 15,
                "database_write": False,
                "evidence_sha256": "1" * 64,
            },
        )


def test_semantic_rows_are_derived_from_bound_immutable_evidence() -> None:
    created = {
        "profile_switches": [
            {
                "binding_id": row["id"],
                "profile_id": row["profile_id"],
                "instrument_symbol": "jm",
                "contract_code": "JM2609",
                "period": row["period"],
                "next_data_version": row["data_version"],
                "next_market_data_file_id": row["market_data_file_id"],
                "activated_at": row["activated_at"],
            }
            for row in _semantic_bindings()
        ]
    }
    superseded = {
        "profile_switches": [
            {
                "previous_binding_id": row["id"],
                "activated_at": row["superseded_at"],
            }
            for row in _semantic_bindings()
        ]
    }
    completion = {
        "authorization": {
            "service_enable_packet_hash": "c" * 64,
        },
        "checkpoint": {
            key: value
            for key, value in _semantic_checkpoint().items()
            if key
            not in {
                "exchange_code",
                "last_result",
                "created_at",
                "updated_at",
            }
        },
    }

    bindings, checkpoint = derive_semantic_recovery_rows(
        created_audit=created,
        superseded_audit=superseded,
        completion_snapshot=completion,
        completion_snapshot_sha256="f" * 64,
        recovered_at="2026-07-26T12:00:00.000000+00:00",
    )

    assert bindings == _semantic_bindings()
    assert checkpoint == _semantic_checkpoint()


def test_semantic_recovery_inserts_only_bound_rows_and_is_idempotent() -> None:
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.models.data_center import (
        AfterMarketSchedulerCheckpoint,
        MarketDataFile,
        ProfileActiveBinding,
    )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            MarketDataFile.__table__,
            ProfileActiveBinding.__table__,
            AfterMarketSchedulerCheckpoint.__table__,
        ],
    )
    backup, drill = _backup_and_drill()
    manifest = build_semantic_recovery_manifest(
        current_facts=_current_facts(),
        profile_active_bindings=_semantic_bindings(),
        scheduler_checkpoint=_semantic_checkpoint(),
        evidence=_semantic_evidence(),
        backup=backup,
        isolated_restore_drill=drill,
        synthesized_fields={"checkpoint.created_at": "recovered_at"},
        external_lineage_exception={
            "task_id": 23,
            "report_id": 15,
            "database_write": False,
            "evidence_sha256": "1" * 64,
        },
    )
    packet = build_recovery_approval_packet(
        manifest=manifest,
        source={"commit": "1" * 40, "tree": "2" * 40},
    )
    with Session(engine) as session:
        for file_id in {103980, 103981, 103982, 103984}:
            session.add(
                MarketDataFile(
                    id=file_id,
                    provider="rqdata",
                    data_type="bar",
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    period="15m",
                    start_time=datetime(2026, 6, 12, tzinfo=UTC),
                    end_time=datetime(2026, 7, 22, tzinfo=UTC),
                    data_version=f"file-{file_id}",
                    file_path=f"/data/{file_id}.parquet",
                    row_count=1,
                    file_size_bytes=1,
                    checksum=f"{file_id:064x}",
                    data_role="primary",
                    quality_status="passed",
                )
            )
        session.flush()

        first = apply_semantic_recovery(
            session,
            packet=packet,
            approval_hash=str(packet["packet_hash"]),
            current_facts=_current_facts(),
            current_source={"commit": "1" * 40, "tree": "2" * 40},
        )
        second = apply_semantic_recovery(
            session,
            packet=packet,
            approval_hash=str(packet["packet_hash"]),
            current_facts=_current_facts(),
            current_source={"commit": "1" * 40, "tree": "2" * 40},
        )

        assert first == {"created_bindings": 7, "created_checkpoints": 1, "unchanged": 0}
        assert second == {"created_bindings": 0, "created_checkpoints": 0, "unchanged": 8}
        assert session.query(ProfileActiveBinding).count() == 7
        assert session.query(AfterMarketSchedulerCheckpoint).count() == 1
