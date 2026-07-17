from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import inspect
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport, MarketDataFile, ProfileActiveBinding
from app.services.rqdata_ingest.full_history_residual_repair import (
    ApprovalRequiredError,
    BatchApproval,
    FrozenQueueError,
    build_repair_plan,
    load_frozen_queue,
    validate_batch_approval,
    write_repair_plan,
)
from app.services.rqdata_ingest import full_history_residual_repair as repair_planning
from app.services.rqdata_ingest import full_history_residual_repair_apply as repair_apply
from app.services.rqdata_ingest.full_history_residual_repair_apply import classify_registration_reconcile, repair_manifest_checksum_rows
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality


HEADER = (
    "queue_action_id",
    "action_type",
    "target_scope",
    "source_residual_ids",
    "product",
    "contract_role",
    "contract",
    "period",
    "physical_path",
    "current_evidence",
    "recommended_action",
    "requires_code_change",
    "requires_manifest_change",
    "requires_db_write",
    "requires_parquet_write",
    "requires_rqdata",
    "risk_level",
    "rollback_method",
)


def _queue(tmp_path: Path, *, action_type: str = "repair_manifest_checksum") -> tuple[Path, str]:
    path = tmp_path / "metadata_repair_queue.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerow(
            {
                "queue_action_id": "ACT-001",
                "action_type": action_type,
                "target_scope": "manifest.csv#2",
                "source_residual_ids": '["RES-001"]',
                "current_evidence": '{"checksum":"old"}',
                "recommended_action": "repair one row",
                "requires_code_change": "false",
                "requires_manifest_change": "true",
                "requires_db_write": "false",
                "requires_parquet_write": "false",
                "requires_rqdata": "true" if action_type.startswith("download_") else "false",
                "risk_level": "medium",
                "rollback_method": "restore before copy",
            }
        )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_queue_requires_exact_hash_and_action_allowlist(tmp_path: Path) -> None:
    path, digest = _queue(tmp_path)

    queue = load_frozen_queue(path, expected_sha256=digest, allowed_action_types={"repair_manifest_checksum"})

    assert queue.sha256 == digest
    assert queue.actions[0].queue_action_id == "ACT-001"
    with pytest.raises(FrozenQueueError, match="QUEUE_HASH_MISMATCH"):
        load_frozen_queue(path, expected_sha256="0" * 64, allowed_action_types={"repair_manifest_checksum"})
    with pytest.raises(FrozenQueueError, match="ACTION_TYPE_NOT_ALLOWED"):
        load_frozen_queue(path, expected_sha256=digest, allowed_action_types={"reconcile_db_registration"})


def test_plan_requires_explicit_ids_and_refuses_scope_expansion(tmp_path: Path) -> None:
    path, digest = _queue(tmp_path)
    queue = load_frozen_queue(path, expected_sha256=digest, allowed_action_types={"repair_manifest_checksum"})

    with pytest.raises(FrozenQueueError, match="ACTION_SELECTION_REQUIRED"):
        build_repair_plan(queue, batch_id="manifest-001", selected_action_ids=())
    with pytest.raises(FrozenQueueError, match="ACTION_NOT_IN_FROZEN_QUEUE"):
        build_repair_plan(queue, batch_id="manifest-001", selected_action_ids=("ACT-999",))


def test_approval_must_match_batch_hash_ledger_and_exact_action_ids(tmp_path: Path) -> None:
    path, digest = _queue(tmp_path)
    queue = load_frozen_queue(path, expected_sha256=digest, allowed_action_types={"repair_manifest_checksum"})
    plan = build_repair_plan(queue, batch_id="manifest-001", selected_action_ids=("ACT-001",))
    approval = BatchApproval(
        task_id=plan.task_id,
        batch_id=plan.batch_id,
        queue_sha256=plan.queue_sha256,
        ledger_sha256=plan.ledger_sha256,
        approved_action_ids=("ACT-001",),
        approval_statement=plan.required_approval_statement,
        rqdata_allowed=False,
    )

    validate_batch_approval(plan, approval)
    with pytest.raises(ApprovalRequiredError, match="APPROVAL_LEDGER_MISMATCH"):
        validate_batch_approval(plan, BatchApproval(**{**approval.__dict__, "ledger_sha256": "0" * 64}))


def test_rqdata_plan_requires_additional_explicit_permission(tmp_path: Path) -> None:
    path, digest = _queue(tmp_path, action_type="download_missing_actual_rank1_interval")
    queue = load_frozen_queue(
        path,
        expected_sha256=digest,
        allowed_action_types={"download_missing_actual_rank1_interval"},
    )
    plan = build_repair_plan(queue, batch_id="rqdata-001", selected_action_ids=("ACT-001",))
    approval = BatchApproval(
        task_id=plan.task_id,
        batch_id=plan.batch_id,
        queue_sha256=plan.queue_sha256,
        ledger_sha256=plan.ledger_sha256,
        approved_action_ids=("ACT-001",),
        approval_statement=plan.required_approval_statement,
        rqdata_allowed=False,
    )

    with pytest.raises(ApprovalRequiredError, match="RQDATA_NOT_EXPLICITLY_APPROVED"):
        validate_batch_approval(plan, approval)


def test_plan_writer_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    path, digest = _queue(tmp_path)
    queue = load_frozen_queue(path, expected_sha256=digest, allowed_action_types={"repair_manifest_checksum"})
    plan = build_repair_plan(queue, batch_id="manifest-001", selected_action_ids=("ACT-001",))
    output = tmp_path / "plan"

    paths = write_repair_plan(plan, output)

    payload = json.loads(paths["plan"].read_text(encoding="utf-8"))
    assert payload["writes_database"] is False
    assert payload["writes_parquet"] is False
    assert payload["calls_rqdata"] is False
    with pytest.raises(FileExistsError, match="OUTPUT_EXISTS"):
        write_repair_plan(plan, output)


def test_closure_operation_plan_hashes_exact_operations_and_rqdata_permission() -> None:
    operations = [
        {"market_data_file_id": 2, "expected_checksum": "old-2"},
        {"market_data_file_id": 1, "expected_checksum": "old-1"},
    ]

    first = repair_planning.build_closure_operation_plan(
        batch_id="db-stale-retirement-002",
        operations=operations,
        requires_rqdata=False,
    )
    second = repair_planning.build_closure_operation_plan(
        batch_id="db-stale-retirement-002",
        operations=list(reversed(operations)),
        requires_rqdata=False,
    )
    rqdata = repair_planning.build_closure_operation_plan(
        batch_id="rqdata-missing-actual-002",
        operations=operations,
        requires_rqdata=True,
    )

    assert first["ledger_sha256"] == second["ledger_sha256"]
    assert first["required_approval_statement"].startswith("APPROVE FULL-HISTORY")
    assert rqdata["required_approval_statement"].startswith("APPROVE RQDATA FULL-HISTORY")


def test_closure_plan_writer_records_exact_operations_and_refuses_overwrite(tmp_path: Path) -> None:
    plan = repair_planning.build_closure_operation_plan(
        batch_id="db-stale-retirement-002",
        operations=[{"market_data_file_id": 1, "expected_checksum": "old"}],
        requires_rqdata=False,
    )
    output = tmp_path / "closure"

    paths = repair_planning.write_closure_operation_plan(plan, output)

    payload = json.loads(paths["plan"].read_text(encoding="utf-8"))
    operations = json.loads(paths["operations"].read_text(encoding="utf-8"))
    assert payload["operation_count"] == 1
    assert payload["writes_database"] is False
    assert operations == plan["operations"]
    with pytest.raises(FileExistsError, match="OUTPUT_EXISTS"):
        repair_planning.write_closure_operation_plan(plan, output)


def test_closure_apply_requires_exact_statement_and_unchanged_operations(tmp_path: Path) -> None:
    plan = repair_planning.build_closure_operation_plan(
        batch_id="db-stale-retirement-002",
        operations=[{"market_data_file_id": 1, "expected_checksum": "old"}],
        requires_rqdata=False,
    )
    output = tmp_path / "closure"
    repair_planning.write_closure_operation_plan(plan, output)

    loaded = repair_planning.load_approved_closure_operation_plan(
        output,
        approval_statement=plan["required_approval_statement"],
    )

    assert loaded["ledger_sha256"] == plan["ledger_sha256"]
    with pytest.raises(ApprovalRequiredError, match="APPROVAL_STATEMENT_MISMATCH"):
        repair_planning.load_approved_closure_operation_plan(output, approval_statement="APPROVE wrong")
    operations_path = output / "operations.json"
    operations_path.write_text('[{"market_data_file_id":2}]\n', encoding="utf-8")
    with pytest.raises(ApprovalRequiredError, match="APPROVAL_LEDGER_MISMATCH"):
        repair_planning.load_approved_closure_operation_plan(
            output,
            approval_statement=plan["required_approval_statement"],
        )


def test_closure_command_accepts_only_current_frozen_batch_ids() -> None:
    assert repair_planning.closure_command_accepts_batch("apply-rqdata", "rqdata-missing-actual-004") is True
    assert repair_planning.closure_command_accepts_batch("apply-rqdata", "rqdata-missing-actual-003") is False
    assert repair_planning.closure_command_accepts_batch("apply-db", "db-stale-retirement-002") is True


def test_manifest_checksum_repair_updates_only_frozen_line(tmp_path: Path) -> None:
    physical = tmp_path / "asset.parquet"
    physical.write_bytes(b"asset")
    digest = hashlib.sha256(b"asset").hexdigest()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "standard_path,period,checksum\n"
        f"{physical},1d,old\n"
        f"{tmp_path / 'other.parquet'},1d,keep\n",
        encoding="utf-8",
    )
    action = {
        "queue_action_id": "ACT-001",
        "physical_path": str(physical),
        "current_evidence": {
            "actual_checksums": [digest],
            "manifest_checksums": ["old"],
            "manifest_sources": ["manifest.csv#2"],
        },
    }

    result = repair_manifest_checksum_rows([action], project_root=tmp_path, backup_root=tmp_path / "backup")

    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    assert rows[0]["checksum"] == digest
    assert rows[1]["checksum"] == "keep"
    assert result[0]["updated_rows"] == 1


def test_registration_reconcile_preserves_superseded_and_flags_unmatched() -> None:
    verified = classify_registration_reconcile(
        {
            "actual_checksums": ["actual"],
            "db_checksums": ["old", "actual"],
            "db_data_roles": ["primary", "superseded"],
            "db_quality_statuses": ["passed"],
        }
    )
    blocked = classify_registration_reconcile(
        {
            "actual_checksums": ["actual"],
            "db_checksums": ["old"],
            "db_data_roles": ["superseded"],
            "db_quality_statuses": ["passed"],
        }
    )

    assert verified == "verified_existing_registration_no_write"
    assert blocked == "manual_review_checksum_not_registered"


def test_local_rebuild_registration_exposes_candidate_role_gate() -> None:
    parameter = inspect.signature(register_dominant_v2_quality).parameters["data_role"]

    assert parameter.default == "primary"


def test_rqdata_repair_registration_exposes_candidate_role_gate() -> None:
    from app.services.rqdata_ingest.actual_contract_bars_pilot import run_actual_contract_bars_pilot_write

    parameter = inspect.signature(run_actual_contract_bars_pilot_write).parameters["data_role"]

    assert parameter.default == "primary"


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _market_file(*, checksum: str, data_role: str, data_version: str) -> MarketDataFile:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    return MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1d",
        start_time=start,
        end_time=end,
        file_path="/data/JM2609_1d.parquet",
        row_count=2,
        file_size_bytes=100,
        checksum=checksum,
        data_version=data_version,
        data_role=data_role,
        quality_status="passed",
    )


def test_retire_stale_registration_deletes_only_exact_unbound_row_and_quality_report() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        current = _market_file(checksum="actual", data_role="primary", data_version="current")
        stale = _market_file(checksum="old", data_role="superseded", data_version="stale")
        session.add_all([current, stale])
        session.flush()
        session.add(
            DataQualityReport(
                file_id=stale.id,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1d",
                start_time=stale.start_time,
                end_time=stale.end_time,
                status="passed",
            )
        )
        session.flush()

        result = repair_apply.retire_stale_market_data_files(
            session,
            [
                {
                    "market_data_file_id": stale.id,
                    "expected_path": stale.file_path,
                    "expected_checksum": "old",
                    "expected_data_role": "superseded",
                    "replacement_market_data_file_id": current.id,
                    "replacement_checksum": "actual",
                }
            ],
        )
        session.commit()

        remaining = session.scalars(select(MarketDataFile)).all()
        reports = session.scalar(select(func.count()).select_from(DataQualityReport))

    assert [item.id for item in remaining] == [current.id]
    assert reports == 0
    assert result[0]["deleted_quality_report_count"] == 1


def test_retire_stale_registration_blocks_active_profile_binding() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        stale = _market_file(checksum="old", data_role="superseded", data_version="stale")
        session.add(stale)
        session.flush()
        session.add(
            ProfileActiveBinding(
                profile_id="research",
                instrument_symbol="jm",
                contract_code="JM2609",
                contract_role="actual_contract",
                period="1d",
                data_version="stale",
                market_data_file_id=stale.id,
                binding_status="active",
            )
        )
        session.flush()

        with pytest.raises(RuntimeError, match="PROFILE_BINDING_EXISTS"):
            repair_apply.retire_stale_market_data_files(
                session,
                [
                    {
                        "market_data_file_id": stale.id,
                        "expected_path": stale.file_path,
                        "expected_checksum": "old",
                        "expected_data_role": "superseded",
                    }
                ],
            )


def test_build_stale_retirement_ledger_selects_mismatching_row_and_exact_replacement() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        current = _market_file(checksum="actual", data_role="primary", data_version="current")
        stale = _market_file(checksum="old", data_role="superseded", data_version="stale")
        session.add_all([current, stale])
        session.flush()
        session.add(
            DataQualityReport(
                file_id=stale.id,
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1d",
                start_time=stale.start_time,
                end_time=stale.end_time,
                status="passed",
            )
        )
        session.flush()

        ledger = repair_apply.build_stale_retirement_ledger(
            session,
            [
                {
                    "physical_path": stale.file_path,
                    "physical_status": "readable",
                    "checksum_actual": "actual",
                    "checksum_status": "declared_conflict",
                    "market_data_file_ids": json.dumps([stale.id, current.id]),
                }
            ],
        )

    assert ledger == [
        {
            "market_data_file_id": stale.id,
            "expected_path": stale.file_path,
            "expected_checksum": "old",
            "expected_data_role": "superseded",
            "quality_report_ids": [1],
            "replacement_market_data_file_id": current.id,
            "replacement_checksum": "actual",
        }
    ]
