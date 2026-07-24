from __future__ import annotations

from datetime import date, datetime, UTC
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import AfterMarketSchedulerCheckpoint


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(tmp_path: Path) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    receipt_path = tmp_path / "completion_receipt.json"
    outage_path = tmp_path / "outage.json"
    packet_path = tmp_path / "execution_packet.json"
    authorization_hash = "a" * 64
    receipt = {
        "status": "completed",
        "gate": "JM_EOD_ARCHIVE_DAY_PASSED",
        "trading_day": "2026-07-23",
        "actual_contract": "JM2609",
        "packet_hash": "b" * 64,
        "assets": [
            {
                "market_data_file_id": 101,
                "period": period,
                "data_version": f"version-{period}",
                "canonical_path": str(tmp_path / f"{period}.parquet"),
                "checksum": str(index) * 64,
                "quality_status": "passed",
            }
            for index, period in enumerate(("1m", "5m", "15m", "30m", "60m", "1d"), start=1)
        ],
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {
            "status": "passed",
            "verified_candidate_count": 7,
            "rows": [
                {
                    "profile_id": profile,
                    "contract": "JM2609",
                    "period": period,
                    "data_version": f"version-{period}",
                    "market_data_file_id": 101,
                    "quality_status": "passed",
                }
                for profile, period in (
                    ("intraday_research_v1", "1m"),
                    ("intraday_research_v1", "5m"),
                    ("intraday_research_v1", "15m"),
                    ("live_observation_v1", "1m"),
                    ("live_observation_v1", "5m"),
                    ("live_observation_v1", "15m"),
                    ("long_horizon_daily_v1", "1d"),
                )
            ],
        },
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    outage = {
        "status": "passed",
        "evidence_type": "d2_outage_pre_restart",
        "authorization": {"service_enable_packet_hash": authorization_hash},
        "d2": {
            "trading_day": "2026-07-24",
            "receipt_absent": True,
            "manifest_absent": True,
            "manual_trading_day_used": False,
        },
        "checkpoint": {
            "status": "idle",
            "authorization_hash": authorization_hash,
            "last_successful_trading_day": "2026-07-23",
            "current_trading_day": None,
            "retry_count": 0,
            "last_execution_packet_hash": "b" * 64,
            "last_receipt_path": str(receipt_path),
        },
        "forbidden_counts": {
            "signal_events": 3,
            "signal_notifications": 1,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
        },
        "assertions": {
            "eligible_day_discovered_by_calendar": True,
            "scheduler_label_unloaded": True,
            "watermark_not_advanced": True,
            "archive_lag_is_one": True,
            "d2_receipt_absent": True,
            "d2_not_manually_archived": True,
            "d1_and_previous_assets_immutable": True,
            "forbidden_counts_unchanged": True,
            "authorization_matches_checkpoint": True,
        },
        "immutable_evidence": {
            "previous_receipt_path": str(receipt_path),
            "previous_receipt_sha256": _sha256(receipt_path),
            "mismatch_count": 0,
        },
    }
    outage_path.write_text(json.dumps(outage), encoding="utf-8")
    packet = {
        "schema_version": 1,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DAY",
        "status": "approval_required",
        "writes_authorized": False,
        "bound_facts": {
            "trading_day": "2026-07-24",
            "actual_contract": "JM2609",
            "parent_automation_approval_hash": authorization_hash,
        },
    }
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    packet["packet_hash"] = canonical_packet_hash(packet)
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    return {
        "receipt": receipt,
        "receipt_path": receipt_path,
        "outage": outage,
        "outage_path": outage_path,
        "packet": packet,
        "packet_path": packet_path,
        "failed_task": {
            "task_no": f"archive:s607:jm:JM2609:2026-07-24:{packet['packet_hash'][:12]}",
            "status": "failed",
            "error_message": "unsupported aggregation period",
            "started_at": "2026-07-24T09:18:37+00:00",
            "finished_at": "2026-07-24T09:18:38+00:00",
            "result": {
                "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DAY",
                "packet_hash": packet["packet_hash"],
                "error_type": "ValueError",
                "active_binding_changed": False,
                "attempt_count": 1,
            },
        },
        "database_assets": receipt["assets"],
        "database_bindings": [
            {**row, "binding_status": "active"} for row in receipt["consumer_profile_smoke"]["rows"]
        ],
        "forbidden_counts": outage["forbidden_counts"],
    }


def test_recovery_facts_are_receipt_packet_task_and_database_bound(tmp_path) -> None:
    from app.services.after_market_checkpoint_recovery import build_checkpoint_recovery_bound_facts

    evidence = _evidence(tmp_path)
    facts = build_checkpoint_recovery_bound_facts(**evidence)

    assert facts["restore_state"]["status"] == "blocked"
    assert facts["restore_state"]["last_successful_trading_day"] == "2026-07-23"
    assert facts["restore_state"]["current_trading_day"] == "2026-07-24"
    assert facts["restore_state"]["retry_count"] == 1
    assert facts["restore_state"]["last_error_type"] == "ValueError"
    assert facts["restore_state"]["authorization_hash"] == "a" * 64
    assert facts["evidence"]["last_success_receipt"]["sha256"] == _sha256(evidence["receipt_path"])
    assert facts["evidence"]["failed_execution_packet"]["packet_hash"] == evidence["packet"]["packet_hash"]
    assert facts["database_verification"]["active_binding_count"] == 7


def test_recovery_facts_reject_forbidden_counter_or_packet_drift(tmp_path) -> None:
    from app.services.after_market_checkpoint_recovery import (
        CheckpointRecoveryError,
        build_checkpoint_recovery_bound_facts,
    )

    evidence = _evidence(tmp_path)
    evidence["forbidden_counts"] = {**evidence["forbidden_counts"], "signal_events": 4}
    with pytest.raises(CheckpointRecoveryError, match="recovery_forbidden_counter_drift"):
        build_checkpoint_recovery_bound_facts(**evidence)

    evidence = _evidence(tmp_path / "second")
    evidence["packet"]["bound_facts"]["trading_day"] = "2026-07-25"
    with pytest.raises(CheckpointRecoveryError, match="recovery_execution_packet_hash_invalid"):
        build_checkpoint_recovery_bound_facts(**evidence)


def test_recovery_restores_exact_blocked_checkpoint_once(tmp_path) -> None:
    from app.services.after_market_checkpoint_recovery import (
        build_checkpoint_recovery_bound_facts,
        restore_checkpoint_from_recovery,
    )

    facts = build_checkpoint_recovery_bound_facts(**_evidence(tmp_path))
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        checkpoint = restore_checkpoint_from_recovery(session, facts)
        session.commit()
        stored = session.scalar(select(AfterMarketSchedulerCheckpoint))

        assert checkpoint.id == stored.id
        assert stored.status == "blocked"
        assert stored.last_successful_trading_day == date(2026, 7, 23)
        assert stored.current_trading_day == date(2026, 7, 24)
        assert stored.last_attempt_at.replace(tzinfo=UTC) == datetime(
            2026, 7, 24, 9, 18, 37, tzinfo=UTC
        )
        assert stored.retry_count == 1
        assert stored.last_execution_packet_hash == "b" * 64

        assert restore_checkpoint_from_recovery(session, facts).id == stored.id
