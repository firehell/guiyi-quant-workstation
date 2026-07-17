from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.services.rqdata_ingest.full_history_residual_repair import (
    ApprovalRequiredError,
    BatchApproval,
    FrozenQueueError,
    build_repair_plan,
    load_frozen_queue,
    validate_batch_approval,
    write_repair_plan,
)


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
