"""
GUIYI Approval Manager V3.0 — atomic operation-level approval.

Core capabilities:
- create:  generate V3 approval record with secret scanning
- verify:  12-step gate check (task/plan/hash/expiry/consumed/scope)
- consume: mark one_time approval as consumed (append-only log)
- status:  VALID | EXPIRED | CONSUMED with remaining time
"""

from __future__ import annotations

import hashlib
import json
import re
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────────────

VALID_OPERATIONS = frozenset({
    "AUDIT", "DEV", "DATA_WRITE", "RUNTIME",
    "EXTERNAL_SEND", "MERGE", "DOC_DELETE",
})

# Secret patterns — any match in the payload body → create rejected
_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r'(api[_-]?key|apikey|secret|token|password|passwd|credential)\W*[:=]\s*.{0,12}\S{8,}',
        r'Bearer\s+[A-Za-z0-9_\-\.]+=',
        r'ghp_[A-Za-z0-9_]{36}',
        r'(sk|rk)-[A-Za-z0-9_\-]{32,}',
        r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+',  # JWT
    ]
]

# ── Helper ──────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    """Compute SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        raise ApprovalError("INVALID_JSON", f"Cannot parse approval file: {path}")
    if not isinstance(data, dict):
        raise ApprovalError("INVALID_JSON", f"Approval file is not a JSON object: {path}")
    return data


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file, returning list of objects."""
    if not path.is_file():
        return []
    entries: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _append_jsonl(path: Path, entry: Dict[str, Any]) -> None:
    """Append one entry to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _scan_secrets(payload: Dict[str, Any]) -> Optional[str]:
    """Scan the full JSON payload for secrets. Returns the first hit or None."""
    payload_str = json.dumps(payload, ensure_ascii=False)
    for pattern in _SECRET_PATTERNS:
        m = pattern.search(payload_str)
        if m:
            return f"Secret pattern matched: {m.group(0)[:60]}..."
    return None


def _is_expired(record: Dict[str, Any]) -> bool:
    """Check if an approval has expired."""
    expires_at = record.get("expires_at")
    if not expires_at:
        return False
    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return _utc_now_dt() > expires_dt
    except (ValueError, TypeError):
        return True  # unparseable dates are treated as expired


def _is_consumed(record: Dict[str, Any], consumed_log: Path) -> bool:
    """Check if a one_time approval has been consumed."""
    if not record.get("one_time"):
        return False
    entries = _load_jsonl(consumed_log)
    task_id = record.get("task_id", "")
    approval_sha = hashlib.sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    for entry in entries:
        if entry.get("task_id") == task_id and entry.get("approval_sha256") == approval_sha:
            return True
    return False


# ── Error ───────────────────────────────────────────────────────────────────


class ApprovalError(Exception):
    """Structured approval error with a code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"[{code}] {detail}")
        self.code = code
        self.detail = detail


# ── Create ──────────────────────────────────────────────────────────────────


def create(
    *,
    task_id: str,
    epic_id: str,
    plan_file: str,
    task_file: str,
    approved_operations: List[str],
    approval_file: str,
    repo_root: str = ".",
    approver: str = "local-user",
    expires_at: Optional[str] = None,
    one_time: bool = False,
    approval_scope: Optional[List[str]] = None,
    forbidden_operations: Optional[List[str]] = None,
    branch: Optional[str] = None,
    head_commit: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a V3 approval record with full validation and secret scanning.

    Args:
        task_id: Unique task identifier (e.g. WS-V2-003)
        epic_id: Parent epic identifier
        plan_file: Relative path to the approved plan
        task_file: Relative path to the task markdown
        approved_operations: List of operation enums
        approval_file: Where to write the approval JSON
        repo_root: Repository root for resolving relative paths
        approver: Human identifier of the approver
        expires_at: ISO 8601 expiry (optional, not allowed with one_time)
        one_time: Single-use approval
        approval_scope: Legacy coarse-grained scope (optional)
        forbidden_operations: Explicitly denied operations
        branch: Git branch at approval time
        head_commit: Git commit SHA at approval time
    """
    root = Path(repo_root).resolve()
    plan_path = (root / plan_file).resolve()
    task_path = (root / task_file).resolve()

    # Validate file existence
    if not plan_path.is_file():
        raise ApprovalError("MISSING_PLAN", f"Plan file not found: {plan_path}")
    if not task_path.is_file():
        raise ApprovalError("MISSING_TASK", f"Task file not found: {task_path}")

    # Validate operations
    for op in approved_operations:
        if op not in VALID_OPERATIONS:
            raise ApprovalError("INVALID_OP", f"Unknown operation: {op} (valid: {sorted(VALID_OPERATIONS)})")

    if forbidden_operations:
        overlap = set(approved_operations) & set(forbidden_operations)
        if overlap:
            raise ApprovalError("OP_CONFLICT", f"Operations in both approved and forbidden: {overlap}")

    # one_time + expires_at mutual exclusion
    if one_time and expires_at:
        raise ApprovalError("MUTUAL_EXCLUSION", "one_time=true and expires_at are mutually exclusive")

    # Compute hashes
    plan_hash = _sha256(plan_path)
    task_hash = _sha256(task_path)

    # Resolve branch and commit
    if not branch:
        branch = _git_branch(root)
    if not head_commit:
        head_commit = _git_head(root)

    # Build payload
    payload: Dict[str, Any] = {
        "schema_version": 3,
        "task_id": task_id,
        "epic_id": epic_id,
        "plan_hash": plan_hash,
        "task_hash": task_hash,
        "approved_operations": sorted(approved_operations),
        "approver": approver,
        "approved_at": _utc_now(),
        "one_time": one_time,
        "branch": branch,
        "head_commit": head_commit,
        "task_file": task_file,
        "plan_file": plan_file,
    }

    if approval_scope:
        payload["approval_scope"] = approval_scope
    if forbidden_operations:
        payload["forbidden_operations"] = sorted(forbidden_operations)
    if expires_at:
        payload["expires_at"] = expires_at

    # ── Secret scan ──
    secret_hit = _scan_secrets(payload)
    if secret_hit:
        raise ApprovalError("SECRET_LEAK", f"Approval payload contains potential secret: {secret_hit}")

    # Write
    out_path = Path(approval_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return payload


def _git_branch(repo_root: Path) -> str:
    """Get current git branch."""
    import subprocess
    r = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    return r.stdout.strip()


def _git_head(repo_root: Path) -> str:
    """Get current git HEAD commit SHA."""
    import subprocess
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    return r.stdout.strip()


# ── Verify ──────────────────────────────────────────────────────────────────


def verify(
    *,
    approval_file: str,
    task_id: str,
    task_file: str,
    plan_file: str,
    operation: str,
    repo_root: str = ".",
    strict_head: bool = False,
) -> Dict[str, Any]:
    """
    12-step V3 approval verification.

    Returns the approval record on success.
    Raises ApprovalError with a structured code on failure.

    Gate order:
        1.  File exists
        2.  Schema version check
        3.  task_id match
        4.  plan_hash match
        5.  task_hash match
        6.  branch match
        7.  head_commit match (if strict)
        8.  expired?
        9.  consumed? (one_time)
        10. operation in approved_operations?
        11. operation in forbidden_operations?
        12. ALL PASS → return record
    """
    root = Path(repo_root).resolve()
    approval_path = Path(approval_file)
    plan_path = (root / plan_file).resolve()
    task_path = (root / task_file).resolve()

    # ── 1. File exists ──
    if not approval_path.is_file():
        raise ApprovalError("APPROVAL_MISSING", f"Approval file not found: {approval_path}")

    # ── 2. Schema version ──
    record = _load_json(approval_path)
    schema_ver = record.get("schema_version")
    if schema_ver != 3:
        raise ApprovalError(
            "SCHEMA_UNSUPPORTED",
            f"Expected schema_version=3, got {schema_ver}",
        )

    # ── 3. task_id match ──
    if record.get("task_id") != task_id:
        raise ApprovalError(
            "CROSS_TASK",
            f"Approval task_id={record.get('task_id')} does not match requested={task_id}",
        )

    # ── 4. plan_hash match ──
    current_plan_hash = _sha256(plan_path) if plan_path.is_file() else ""
    approved_plan_hash = record.get("plan_hash", "")
    if current_plan_hash != approved_plan_hash:
        raise ApprovalError(
            "PLAN_CHANGED",
            f"Plan hash mismatch: approved={approved_plan_hash[:12]}... current={current_plan_hash[:12]}...",
        )

    # ── 5. task_hash match ──
    current_task_hash = _sha256(task_path)
    approved_task_hash = record.get("task_hash", "")
    if approved_task_hash and current_task_hash != approved_task_hash:
        raise ApprovalError(
            "TASK_CHANGED",
            f"Task hash mismatch: approved={approved_task_hash[:12]}... current={current_task_hash[:12]}...",
        )

    # ── 6. branch match ──
    current_branch = _git_branch(root)
    approved_branch = record.get("branch", "")
    if approved_branch and current_branch != approved_branch:
        raise ApprovalError(
            "BRANCH_MISMATCH",
            f"Branch mismatch: approved={approved_branch} current={current_branch}",
        )

    # ── 7. head_commit match (strict) ──
    if strict_head:
        current_head = _git_head(root)
        approved_head = record.get("head_commit", "")
        if approved_head and current_head != approved_head:
            raise ApprovalError(
                "HEAD_MOVED",
                f"HEAD moved since approval: approved={approved_head[:12]} current={current_head[:12]}",
            )

    # ── 8. expired? ──
    if _is_expired(record):
        raise ApprovalError(
            "EXPIRED",
            f"Approval expired at {record.get('expires_at')}",
        )

    # ── 9. consumed? (one_time) ──
    consumed_log = root / ".ai" / "results" / task_id / "consumed_approvals.jsonl"
    if _is_consumed(record, consumed_log):
        raise ApprovalError(
            "CONSUMED",
            f"One-time approval for {task_id} has already been consumed",
        )

    # ── 10. operation in approved_operations? ──
    approved_ops = set(record.get("approved_operations", []))
    if operation not in approved_ops:
        raise ApprovalError(
            "SCOPE_MISMATCH",
            f"Operation '{operation}' is not in approved_operations: {sorted(approved_ops)}",
        )

    # ── 11. operation in forbidden_operations? ──
    forbidden_ops = set(record.get("forbidden_operations", []))
    if operation in forbidden_ops:
        raise ApprovalError(
            "FORBIDDEN_OP",
            f"Operation '{operation}' is explicitly forbidden",
        )

    # ── 12. ALL PASS ──
    return record


# ── Consume ─────────────────────────────────────────────────────────────────


def consume(
    *,
    approval_file: str,
    task_id: str,
    repo_root: str = ".",
    success: bool = True,
    task_file: str = "",
    plan_file: str = "",
) -> Dict[str, Any]:
    """
    Consume a one-time approval.

    Writes a consumption entry to .ai/results/<task_id>/consumed_approvals.jsonl.
    Returns the consumption entry.

    Raises ApprovalError if:
    - The approval is not one_time
    - The approval has already been consumed
    """
    root = Path(repo_root).resolve()
    approval_path = Path(approval_file)

    # Load and validate
    if not approval_path.is_file():
        raise ApprovalError("APPROVAL_MISSING", f"Approval file not found: {approval_path}")

    record = _load_json(approval_path)

    if not record.get("one_time"):
        raise ApprovalError("NOT_ONE_TIME", f"Approval {task_id} is not marked as one_time")

    consumed_log = root / ".ai" / "results" / task_id / "consumed_approvals.jsonl"

    # Check already consumed
    approval_sha = hashlib.sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    if _is_consumed(record, consumed_log):
        raise ApprovalError("ALREADY_CONSUMED", f"One-time approval for {task_id} already consumed")

    # Build consumption entry
    entry: Dict[str, Any] = {
        "task_id": task_id,
        "approval_sha256": approval_sha,
        "consumed_at": _utc_now(),
        "success": success,
        "approved_operations": record.get("approved_operations", []),
    }
    if task_file:
        entry["task_file"] = task_file
    if plan_file:
        entry["plan_file"] = plan_file

    _append_jsonl(consumed_log, entry)
    return entry


# ── Status ──────────────────────────────────────────────────────────────────


def status(
    *,
    approval_file: str,
    task_id: str,
    repo_root: str = ".",
) -> Dict[str, Any]:
    """
    Report approval status: VALID | EXPIRED | CONSUMED, plus remaining time.

    Returns a status dict with keys:
        task_id, status, expires_at, remaining_seconds, one_time, consumed,
        approved_operations, schema_version
    """
    root = Path(repo_root).resolve()
    approval_path = Path(approval_file)

    result: Dict[str, Any] = {
        "task_id": task_id,
        "status": "MISSING",
        "schema_version": None,
        "approved_operations": [],
        "one_time": False,
        "consumed": False,
    }

    if not approval_path.is_file():
        return result

    record = _load_json(approval_path)
    result["schema_version"] = record.get("schema_version")
    result["approved_operations"] = record.get("approved_operations", [])
    result["one_time"] = record.get("one_time", False)
    result["expires_at"] = record.get("expires_at")

    # Check expiry
    if _is_expired(record):
        result["status"] = "EXPIRED"
        return result

    # Check consumed
    if record.get("one_time"):
        consumed_log = root / ".ai" / "results" / task_id / "consumed_approvals.jsonl"
        if _is_consumed(record, consumed_log):
            result["status"] = "CONSUMED"
            result["consumed"] = True
            return result

    # Compute remaining time
    if record.get("expires_at"):
        try:
            expires_dt = datetime.fromisoformat(
                record["expires_at"].replace("Z", "+00:00")
            )
            remaining = (expires_dt - _utc_now_dt()).total_seconds()
            result["remaining_seconds"] = int(remaining)
            if remaining <= 0:
                result["status"] = "EXPIRED"
                return result
        except (ValueError, TypeError):
            result["status"] = "EXPIRED"
            return result

    result["status"] = "VALID"
    return result


# ── CLI Entry ───────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    """CLI dispatcher: approval.sh create|verify|consume|status [opts]."""
    import argparse

    parser = argparse.ArgumentParser(
        description="GUIYI Approval Manager V3 — create / verify / consume / status",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Generate a V3 approval record")
    p_create.add_argument("--task-id", required=True)
    p_create.add_argument("--epic-id", required=True)
    p_create.add_argument("--plan-file", required=True)
    p_create.add_argument("--task-file", required=True)
    p_create.add_argument("--approved-ops", required=True, help="Comma-separated operations")
    p_create.add_argument("--approval-file", required=True)
    p_create.add_argument("--repo-root", default=".")
    p_create.add_argument("--approver", default="local-user")
    p_create.add_argument("--expires-at", default=None)
    p_create.add_argument("--one-time", action="store_true")
    p_create.add_argument("--approval-scope", default=None)
    p_create.add_argument("--forbidden-ops", default=None)
    p_create.add_argument("--branch", default=None)
    p_create.add_argument("--head-commit", default=None)
    p_create.add_argument("--json", action="store_true")

    # verify
    p_verify = sub.add_parser("verify", help="12-step gate check")
    p_verify.add_argument("--approval-file", required=True)
    p_verify.add_argument("--task-id", required=True)
    p_verify.add_argument("--task-file", required=True)
    p_verify.add_argument("--plan-file", required=True)
    p_verify.add_argument("--operation", required=True)
    p_verify.add_argument("--repo-root", default=".")
    p_verify.add_argument("--strict-head", action="store_true")
    p_verify.add_argument("--json", action="store_true")

    # consume
    p_consume = sub.add_parser("consume", help="Consume a one-time approval")
    p_consume.add_argument("--approval-file", required=True)
    p_consume.add_argument("--task-id", required=True)
    p_consume.add_argument("--repo-root", default=".")
    p_consume.add_argument("--success", action="store_true", default=True)
    p_consume.add_argument("--failed", dest="consume_success", action="store_false")
    p_consume.add_argument("--task-file", default="")
    p_consume.add_argument("--plan-file", default="")
    p_consume.add_argument("--json", action="store_true")

    # status
    p_status = sub.add_parser("status", help="Report approval status")
    p_status.add_argument("--approval-file", required=True)
    p_status.add_argument("--task-id", required=True)
    p_status.add_argument("--repo-root", default=".")
    p_status.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            result = create(
                task_id=args.task_id,
                epic_id=args.epic_id,
                plan_file=args.plan_file,
                task_file=args.task_file,
                approved_operations=[op.strip() for op in args.approved_ops.split(",") if op.strip()],
                approval_file=args.approval_file,
                repo_root=args.repo_root,
                approver=args.approver,
                expires_at=args.expires_at,
                one_time=args.one_time,
                approval_scope=(
                    [s.strip() for s in args.approval_scope.split(",") if s.strip()]
                    if args.approval_scope else None
                ),
                forbidden_operations=(
                    [op.strip() for op in args.forbidden_ops.split(",") if op.strip()]
                    if args.forbidden_ops else None
                ),
                branch=args.branch,
                head_commit=args.head_commit,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"[OK] Approval V3 created: {args.approval_file}")
                print(f"     task={args.task_id} ops={result['approved_operations']}")

        elif args.command == "verify":
            result = verify(
                approval_file=args.approval_file,
                task_id=args.task_id,
                task_file=args.task_file,
                plan_file=args.plan_file,
                operation=args.operation,
                repo_root=args.repo_root,
                strict_head=args.strict_head,
            )
            if args.json:
                print(json.dumps({"status": "ACCEPT", **result}, ensure_ascii=False, indent=2))
            else:
                print(f"[ACCEPT] operation={args.operation} task={args.task_id}")

        elif args.command == "consume":
            success_flag = getattr(args, "consume_success", True)
            result = consume(
                approval_file=args.approval_file,
                task_id=args.task_id,
                repo_root=args.repo_root,
                success=success_flag,
                task_file=args.task_file,
                plan_file=args.plan_file,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"[CONSUMED] task={args.task_id}")

        elif args.command == "status":
            result = status(
                approval_file=args.approval_file,
                task_id=args.task_id,
                repo_root=args.repo_root,
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"[{result['status']}] task={args.task_id} ops={result['approved_operations']}")
                if result.get("remaining_seconds"):
                    print(f"     remaining={result['remaining_seconds']}s")

    except ApprovalError as e:
        if hasattr(args, "json") and args.json:
            print(json.dumps({"status": "REJECT", "code": e.code, "detail": e.detail}, ensure_ascii=False, indent=2))
        else:
            print(f"[REJECT] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
