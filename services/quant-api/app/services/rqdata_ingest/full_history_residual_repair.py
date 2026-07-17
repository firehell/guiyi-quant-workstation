from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable


TASK_ID = "FULL-HISTORY-RESIDUAL-REPAIR-004B"
QUEUE_COLUMNS = (
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
BOOLEAN_COLUMNS = (
    "requires_code_change",
    "requires_manifest_change",
    "requires_db_write",
    "requires_parquet_write",
    "requires_rqdata",
)


class FrozenQueueError(ValueError):
    pass


class ApprovalRequiredError(PermissionError):
    pass


@dataclass(frozen=True)
class FrozenRepairAction:
    queue_action_id: str
    action_type: str
    target_scope: str
    source_residual_ids: tuple[str, ...]
    product: str
    contract_role: str
    contract: str
    period: str
    physical_path: str
    current_evidence: dict[str, object]
    recommended_action: str
    requires_code_change: bool
    requires_manifest_change: bool
    requires_db_write: bool
    requires_parquet_write: bool
    requires_rqdata: bool
    risk_level: str
    rollback_method: str


@dataclass(frozen=True)
class FrozenQueue:
    path: Path
    sha256: str
    actions: tuple[FrozenRepairAction, ...]


@dataclass(frozen=True)
class RepairPlan:
    task_id: str
    batch_id: str
    queue_path: str
    queue_sha256: str
    selected_action_ids: tuple[str, ...]
    actions: tuple[FrozenRepairAction, ...]
    ledger_sha256: str
    required_approval_statement: str
    requires_rqdata: bool


@dataclass(frozen=True)
class BatchApproval:
    task_id: str
    batch_id: str
    queue_sha256: str
    ledger_sha256: str
    approved_action_ids: tuple[str, ...]
    approval_statement: str
    rqdata_allowed: bool = False


def load_frozen_queue(
    path: Path,
    *,
    expected_sha256: str,
    allowed_action_types: set[str] | frozenset[str],
) -> FrozenQueue:
    path = path.resolve(strict=True)
    digest = _sha256(path)
    if digest != expected_sha256:
        raise FrozenQueueError(f"QUEUE_HASH_MISMATCH: expected={expected_sha256} actual={digest}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != QUEUE_COLUMNS:
            raise FrozenQueueError("QUEUE_SCHEMA_MISMATCH")
        actions = tuple(_parse_action(row) for row in reader)
    ids = [action.queue_action_id for action in actions]
    if not actions:
        raise FrozenQueueError("QUEUE_EMPTY")
    if len(ids) != len(set(ids)):
        raise FrozenQueueError("DUPLICATE_ACTION_ID")
    unexpected = sorted({action.action_type for action in actions} - set(allowed_action_types))
    if unexpected:
        raise FrozenQueueError(f"ACTION_TYPE_NOT_ALLOWED: {unexpected}")
    return FrozenQueue(path=path, sha256=digest, actions=actions)


def build_repair_plan(
    queue: FrozenQueue,
    *,
    batch_id: str,
    selected_action_ids: Iterable[str],
) -> RepairPlan:
    if not batch_id.strip():
        raise FrozenQueueError("BATCH_ID_REQUIRED")
    selected = tuple(sorted(set(selected_action_ids)))
    if not selected:
        raise FrozenQueueError("ACTION_SELECTION_REQUIRED")
    by_id = {action.queue_action_id: action for action in queue.actions}
    missing = sorted(set(selected) - set(by_id))
    if missing:
        raise FrozenQueueError(f"ACTION_NOT_IN_FROZEN_QUEUE: {missing}")
    actions = tuple(by_id[action_id] for action_id in selected)
    ledger_payload = {
        "task_id": TASK_ID,
        "batch_id": batch_id,
        "queue_sha256": queue.sha256,
        "actions": [_action_payload(action) for action in actions],
    }
    ledger_sha256 = hashlib.sha256(_canonical_json(ledger_payload).encode()).hexdigest()
    requires_rqdata = any(action.requires_rqdata for action in actions)
    prefix = "APPROVE RQDATA" if requires_rqdata else "APPROVE"
    statement = f"{prefix} {TASK_ID} {batch_id} {ledger_sha256}"
    return RepairPlan(
        task_id=TASK_ID,
        batch_id=batch_id,
        queue_path=str(queue.path),
        queue_sha256=queue.sha256,
        selected_action_ids=selected,
        actions=actions,
        ledger_sha256=ledger_sha256,
        required_approval_statement=statement,
        requires_rqdata=requires_rqdata,
    )


def validate_batch_approval(plan: RepairPlan, approval: BatchApproval) -> None:
    if approval.task_id != plan.task_id or approval.batch_id != plan.batch_id:
        raise ApprovalRequiredError("APPROVAL_BATCH_MISMATCH")
    if approval.queue_sha256 != plan.queue_sha256:
        raise ApprovalRequiredError("APPROVAL_QUEUE_MISMATCH")
    if approval.ledger_sha256 != plan.ledger_sha256:
        raise ApprovalRequiredError("APPROVAL_LEDGER_MISMATCH")
    if tuple(sorted(set(approval.approved_action_ids))) != plan.selected_action_ids:
        raise ApprovalRequiredError("APPROVAL_ACTION_SCOPE_MISMATCH")
    if approval.approval_statement != plan.required_approval_statement:
        raise ApprovalRequiredError("APPROVAL_STATEMENT_MISMATCH")
    if plan.requires_rqdata and not approval.rqdata_allowed:
        raise ApprovalRequiredError("RQDATA_NOT_EXPLICITLY_APPROVED")


def write_repair_plan(plan: RepairPlan, output_dir: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve(strict=False)
    if output_dir.exists():
        raise FileExistsError(f"OUTPUT_EXISTS: {output_dir}")
    output_dir.mkdir(parents=True)
    plan_path = output_dir / "repair_plan.json"
    payload = {
        "task_id": plan.task_id,
        "batch_id": plan.batch_id,
        "queue_path": plan.queue_path,
        "queue_sha256": plan.queue_sha256,
        "ledger_sha256": plan.ledger_sha256,
        "selected_action_ids": list(plan.selected_action_ids),
        "selected_action_count": len(plan.actions),
        "required_approval_statement": plan.required_approval_statement,
        "requires_rqdata": plan.requires_rqdata,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "status": "DRY_RUN_APPROVAL_REQUIRED",
    }
    plan_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ledger_path = output_dir / "selected_actions.json"
    ledger_path.write_text(
        json.dumps([_action_payload(action) for action in plan.actions], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"plan": plan_path, "ledger": ledger_path}


def _parse_action(row: dict[str, str]) -> FrozenRepairAction:
    if not row.get("queue_action_id", "").strip() or not row.get("action_type", "").strip():
        raise FrozenQueueError("ACTION_ID_AND_TYPE_REQUIRED")
    parsed_bools = {column: _parse_bool(row.get(column, ""), column) for column in BOOLEAN_COLUMNS}
    try:
        residual_ids = json.loads(row.get("source_residual_ids") or "[]")
        evidence = json.loads(row.get("current_evidence") or "{}")
    except json.JSONDecodeError as exc:
        raise FrozenQueueError(f"QUEUE_JSON_INVALID: {exc}") from exc
    if not isinstance(residual_ids, list) or not all(isinstance(item, str) for item in residual_ids):
        raise FrozenQueueError("SOURCE_RESIDUAL_IDS_INVALID")
    if not isinstance(evidence, dict):
        raise FrozenQueueError("CURRENT_EVIDENCE_INVALID")
    return FrozenRepairAction(
        queue_action_id=row["queue_action_id"].strip(),
        action_type=row["action_type"].strip(),
        target_scope=row.get("target_scope", "").strip(),
        source_residual_ids=tuple(sorted(set(residual_ids))),
        product=row.get("product", "").strip().lower(),
        contract_role=row.get("contract_role", "").strip(),
        contract=row.get("contract", "").strip(),
        period=row.get("period", "").strip(),
        physical_path=row.get("physical_path", "").strip(),
        current_evidence=evidence,
        recommended_action=row.get("recommended_action", "").strip(),
        risk_level=row.get("risk_level", "").strip(),
        rollback_method=row.get("rollback_method", "").strip(),
        **parsed_bools,
    )


def _parse_bool(value: str, column: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise FrozenQueueError(f"BOOLEAN_INVALID: {column}={value!r}")
    return normalized == "true"


def _action_payload(action: FrozenRepairAction) -> dict[str, object]:
    payload = asdict(action)
    payload["source_residual_ids"] = list(action.source_residual_ids)
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ApprovalRequiredError",
    "BatchApproval",
    "FrozenQueue",
    "FrozenQueueError",
    "FrozenRepairAction",
    "RepairPlan",
    "build_repair_plan",
    "load_frozen_queue",
    "validate_batch_approval",
    "write_repair_plan",
]
