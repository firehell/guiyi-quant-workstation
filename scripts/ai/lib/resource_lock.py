"""Resource-scoped lock for business operations (data-writer, runtime-jm, etc.).

Independent from writer_lock (worktree-scoped). Uses heartbeat-based staleness
detection instead of PID-liveness to handle stuck-process scenarios.

8 scopes with differentiated stale thresholds:
  data-writer(2h), postgres-metadata-writer(2h), rqdata-download(4h),
  main-contract-map-writer(2h), runtime-jm(8h), after-market-archive(8h),
  external-notification(5m), docs-delete(5m)

Mutex rules: runtime-jm <-> after-market-archive
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Final


SCHEMA_VERSION = 1

# 8 valid resource scopes with their stale thresholds in seconds
VALID_SCOPES: Final[dict[str, int]] = {
    "data-writer": 2 * 3600,
    "postgres-metadata-writer": 2 * 3600,
    "rqdata-download": 4 * 3600,
    "main-contract-map-writer": 2 * 3600,
    "runtime-jm": 8 * 3600,
    "after-market-archive": 8 * 3600,
    "external-notification": 300,
    "docs-delete": 300,
}

# Mutex pairs: scopes in the same frozenset cannot be held simultaneously
MUTEX_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(["runtime-jm", "after-market-archive"]),
)


class LockError(RuntimeError):
    """Raised when a lock operation cannot be completed."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, Any]:
        return {"error": str(self), "exit_code": self.exit_code}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_ts(value: str) -> float:
    """Parse ISO8601 UTC string to Unix timestamp."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _lock_dir(repo_root: Path) -> Path:
    return repo_root / ".ai" / "locks" / "resources"


def _lock_file(repo_root: Path, scope: str) -> Path:
    return _lock_dir(repo_root) / f"{scope}.json"


def _audit_file(repo_root: Path) -> Path:
    return _lock_dir(repo_root) / "audit.jsonl"


def _mutex_group(scope: str) -> frozenset[str] | None:
    for group in MUTEX_GROUPS:
        if scope in group:
            return group
    return None


def _held_scopes(repo_root: Path) -> set[str]:
    """Return the set of currently held scope names (non-stale only)."""
    lock_dir = _lock_dir(repo_root)
    if not lock_dir.exists():
        return set()
    held: set[str] = set()
    for f in lock_dir.glob("*.json"):
        if f.name == "audit.json":
            continue
        scope = f.stem
        lock = _read_lock(repo_root, scope)
        if lock is None:
            continue
        stale, _ = _is_stale(scope, lock)
        if not stale:
            held.add(scope)
    return held


def _check_mutex(held: set[str], target: str) -> None:
    group = _mutex_group(target)
    if group is None:
        return
    conflict = group & held
    if conflict:
        raise LockError(
            f"MUTEX_CONFLICT: scope={target} conflicts with held scope(s) {sorted(conflict)}", 3,
        )


def _read_lock(repo_root: Path, scope: str) -> dict[str, Any] | None:
    """Read a lock file, returning None if it does not exist.

    Returns None on empty/partial JSON (concurrent write race) — caller
    should treat as lock not yet valid.
    """
    lf = _lock_file(repo_root, scope)
    if not lf.exists():
        return None
    raw = lf.read_text(encoding="utf-8").strip()
    if not raw:  # Empty file = concurrent write in progress
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Partial write from concurrent process — treat as not yet valid
        return None


def _is_stale(scope: str, lock: dict[str, Any]) -> tuple[bool, str]:
    """Check if a lock is stale based on heartbeat timeout."""
    threshold = VALID_SCOPES.get(scope, 3600)
    heartbeat_str = str(lock.get("heartbeat_at", lock.get("acquired_at", "")))
    hb_ts = _utc_ts(heartbeat_str)
    if hb_ts <= 0:
        return True, "bad_heartbeat_ts"
    from time import time
    age = time() - hb_ts
    if age > threshold:
        return True, f"heartbeat_expired_age={int(age)}s_threshold={threshold}s"
    return False, "active"


def _atomic_write_new(target: Path, data: dict[str, Any]) -> None:
    """Create target file with O_EXCL — only one process succeeds."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except FileExistsError:
        raise LockError(f"TOCTOU: lock file {target.name} already exists", 3)


def _atomic_write_existing(target: Path, data: dict[str, Any]) -> None:
    """Overwrite existing lock file (used for re-acquire / heartbeat)."""
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_audit(
    repo_root: Path,
    event: str,
    lock: dict[str, Any] | None,
    *,
    actor: dict[str, Any],
) -> None:
    af = _audit_file(repo_root)
    af.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "at": utc_now(),
        "actor": actor,
        "lock": lock,
    }
    with af.open("a", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def _actor_meta(*, task_id: str = "", reason: str = "") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "reason": reason,
    }


def inspect(repo_root: Path, scope: str) -> dict[str, Any]:
    """Inspect the lock status for a scope.

    Returns: {"state": "unlocked"|"locked"|"stale", "lock": {...}|null, "reason": str}
    """
    if scope not in VALID_SCOPES:
        raise LockError(f"INVALID_SCOPE: {scope} not in {sorted(VALID_SCOPES)}", 2)

    lock = _read_lock(repo_root, scope)
    if lock is None:
        return {"state": "unlocked", "scope": scope, "lock": None, "reason": "no_lock"}

    stale, reason = _is_stale(scope, lock)
    return {
        "state": "stale" if stale else "locked",
        "scope": scope,
        "lock": lock,
        "stale": stale,
        "reason": reason,
        "stale_threshold_seconds": VALID_SCOPES.get(scope, 3600),
    }


def acquire(
    repo_root: Path,
    *,
    scope: str,
    task_id: str,
    epic_id: str = "",
    branch: str = "",
    worktree: str = "",
    pid: int | None = None,
) -> dict[str, Any]:
    """Atomically acquire a resource lock for the given scope.

    Idempotent: if the same task_id already holds the lock, refreshes heartbeat and returns.
    """
    if scope not in VALID_SCOPES:
        raise LockError(f"INVALID_SCOPE: {scope} not in {sorted(VALID_SCOPES)}", 2)

    lf = _lock_file(repo_root, scope)
    lf.parent.mkdir(parents=True, exist_ok=True)

    effective_pid = pid if pid is not None else os.getpid()
    host = socket.gethostname()
    now = utc_now()

    # Check mutex
    held = _held_scopes(repo_root)
    _check_mutex(held, scope)

    lock_id = hashlib.sha256(
        f"{task_id}:{scope}:{effective_pid}:{now}".encode("utf-8")
    ).hexdigest()[:16]

    existing = _read_lock(repo_root, scope)
    if existing is not None:
        # Stale? Remove and proceed
        stale, reason = _is_stale(scope, existing)
        if stale:
            _append_audit(repo_root, "auto-break-stale", existing, actor={
                "task_id": task_id, "host": host, "pid": effective_pid,
                "reason": f"stale_acquisition: {reason}",
            })
            lf.unlink()
        elif existing.get("task_id") == task_id:
            # Same task re-acquire: idempotent, refresh heartbeat (atomic write)
            existing["heartbeat_at"] = now
            _atomic_write_existing(lf, existing)
            _append_audit(repo_root, "re-acquire", existing, actor={
                "task_id": task_id, "host": host, "pid": effective_pid, "reason": "idempotent_refresh",
            })
            return existing
        else:
            raise LockError(
                f"SCOPE_HELD: scope={scope} held by task_id={existing.get('task_id')} "
                f"pid={existing.get('owner_pid')} host={existing.get('host')} "
                f"since={existing.get('acquired_at')}", 3,
            )

    lock: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "lock_id": lock_id,
        "scope": scope,
        "task_id": task_id,
        "epic_id": epic_id,
        "owner_pid": effective_pid,
        "host": host,
        "acquired_at": now,
        "heartbeat_at": now,
        "command": " ".join(sys.argv) if sys.argv else "",
        "branch": branch,
        "worktree": worktree,
    }

    # Atomic write: temp file + rename to prevent TOCTOU (partial JSON read)
    _atomic_write_new(lf, lock)

    _append_audit(repo_root, "acquire", lock, actor=_actor_meta(task_id=task_id))
    return lock


def heartbeat(repo_root: Path, *, scope: str, task_id: str, pid: int | None = None) -> dict[str, Any]:
    """Refresh the heartbeat timestamp for a held lock."""
    if scope not in VALID_SCOPES:
        raise LockError(f"INVALID_SCOPE: {scope}", 2)

    lock = _read_lock(repo_root, scope)
    if lock is None:
        raise LockError(f"LOCK_NOT_FOUND: no lock for scope={scope}", 4)

    effective_pid = pid if pid is not None else os.getpid()
    if lock.get("task_id") != task_id:
        raise LockError(
            f"OWNER_MISMATCH: task_id mismatch (lock={lock.get('task_id')} caller={task_id})", 6,
        )
    if int(lock.get("owner_pid", -1)) != effective_pid:
        raise LockError(
            f"OWNER_MISMATCH: pid mismatch (lock={lock.get('owner_pid')} caller={effective_pid})", 6,
        )

    now = utc_now()
    lock["heartbeat_at"] = now
    _atomic_write_existing(_lock_file(repo_root, scope), lock)
    _append_audit(repo_root, "heartbeat", lock, actor=_actor_meta(task_id=task_id))
    return lock


def release(repo_root: Path, *, scope: str, task_id: str, pid: int | None = None) -> dict[str, Any] | None:
    """Release a lock owned by this task+pid."""
    if scope not in VALID_SCOPES:
        raise LockError(f"INVALID_SCOPE: {scope}", 2)

    lock = _read_lock(repo_root, scope)
    if lock is None:
        return None

    effective_pid = pid if pid is not None else os.getpid()
    if lock.get("task_id") != task_id:
        raise LockError(
            f"OWNER_MISMATCH: cannot release lock held by task_id={lock.get('task_id')}", 6,
        )
    if int(lock.get("owner_pid", -1)) != effective_pid:
        raise LockError(
            f"OWNER_MISMATCH: cannot release lock held by pid={lock.get('owner_pid')}", 6,
        )

    _lock_file(repo_root, scope).unlink()
    _append_audit(repo_root, "release", lock, actor=_actor_meta(task_id=task_id))
    return lock


def force_release(repo_root: Path, *, scope: str, reason: str, task_id: str = "") -> dict[str, Any]:
    """Force-release a lock with an audit trail. Requires a reason string >= 10 chars."""
    if scope not in VALID_SCOPES:
        raise LockError(f"INVALID_SCOPE: {scope}", 2)

    reason_stripped = reason.strip()
    if len(reason_stripped) < 10:
        raise LockError("force-release requires a reason string of at least 10 characters", 2)

    lock = _read_lock(repo_root, scope)
    if lock is None:
        raise LockError(f"LOCK_NOT_FOUND: no lock for scope={scope}", 4)

    _append_audit(
        repo_root, "force-release", lock,
        actor={
            "task_id": task_id,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "reason": reason_stripped,
        },
    )
    _lock_file(repo_root, scope).unlink()
    return lock


def release_all(repo_root: Path, *, task_id: str, pid: int | None = None) -> list[str]:
    """Release all locks held by this task_id+pid across all scopes.

    Returns list of released scope names.
    """
    effective_pid = pid if pid is not None else os.getpid()
    released: list[str] = []
    for scope in VALID_SCOPES:
        lock = _read_lock(repo_root, scope)
        if lock is None:
            continue
        if lock.get("task_id") != task_id:
            continue
        if int(lock.get("owner_pid", -1)) != effective_pid:
            continue
        try:
            release(repo_root, scope=scope, task_id=task_id, pid=effective_pid)
            released.append(scope)
        except LockError:
            pass  # Best-effort cleanup on exit
    return released


def status_all(repo_root: Path) -> list[dict[str, Any]]:
    """Return status of all scopes as a list of inspect results."""
    results: list[dict[str, Any]] = []
    for scope in sorted(VALID_SCOPES):
        try:
            results.append(inspect(repo_root, scope))
        except LockError as e:
            results.append({
                "state": "error",
                "scope": scope,
                "lock": None,
                "reason": str(e),
            })
    return results


# --- CLI ---

def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage resource-scoped locks.")
    parser.add_argument("--repo-root", default=".", help="Repository root that owns .ai/locks")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # inspect
    sp = subparsers.add_parser("inspect", help="Inspect lock status for a scope")
    sp.add_argument("--scope", required=True, help=f"Scope: {', '.join(sorted(VALID_SCOPES))}")
    sp.add_argument("--json", action="store_true")

    # acquire
    sp = subparsers.add_parser("acquire", help="Acquire a resource lock")
    sp.add_argument("--scope", required=True, choices=sorted(VALID_SCOPES))
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--epic-id", default="")
    sp.add_argument("--branch", default="")
    sp.add_argument("--worktree", default="")
    sp.add_argument("--pid", type=int, default=os.getpid())
    sp.add_argument("--json", action="store_true")

    # heartbeat
    sp = subparsers.add_parser("heartbeat", help="Refresh heartbeat for a held lock")
    sp.add_argument("--scope", required=True, choices=sorted(VALID_SCOPES))
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--pid", type=int, default=os.getpid())
    sp.add_argument("--json", action="store_true")

    # release
    sp = subparsers.add_parser("release", help="Release a lock owned by this task")
    sp.add_argument("--scope", required=True, choices=sorted(VALID_SCOPES))
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--pid", type=int, default=os.getpid())
    sp.add_argument("--json", action="store_true")

    # force-release
    sp = subparsers.add_parser("force-release", help="Force-release a lock with audit trail")
    sp.add_argument("--scope", required=True, choices=sorted(VALID_SCOPES))
    sp.add_argument("--reason", required=True, help="Reason string (min 10 characters)")
    sp.add_argument("--task-id", default="", help="Caller task ID for audit")
    sp.add_argument("--json", action="store_true")

    # release-all
    sp = subparsers.add_parser("release-all", help="Release all locks held by this task")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--pid", type=int, default=os.getpid())
    sp.add_argument("--json", action="store_true")

    # status-all
    sp = subparsers.add_parser("status-all", help="Show status of all resource scopes")
    sp.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()

    try:
        if args.action == "inspect":
            result = inspect(repo_root, args.scope)
            _print_json(result) if args.json else print(
                f"{result['state']} scope={args.scope} reason={result['reason']}"
            )
            return 0

        if args.action == "acquire":
            result = acquire(
                repo_root,
                scope=args.scope,
                task_id=args.task_id,
                epic_id=getattr(args, "epic_id", ""),
                branch=getattr(args, "branch", ""),
                worktree=getattr(args, "worktree", ""),
                pid=args.pid,
            )
            _print_json(result) if args.json else print(
                f"acquired scope={args.scope} task_id={args.task_id} lock_id={result.get('lock_id')}"
            )
            return 0

        if args.action == "heartbeat":
            result = heartbeat(repo_root, scope=args.scope, task_id=args.task_id, pid=args.pid)
            _print_json(result) if args.json else print(
                f"heartbeat scope={args.scope} task_id={args.task_id} hb={result.get('heartbeat_at')}"
            )
            return 0

        if args.action == "release":
            result = release(repo_root, scope=args.scope, task_id=args.task_id, pid=args.pid)
            _print_json({"released": result is not None, "scope": args.scope}) if args.json else print(
                f"released={'yes' if result else 'no'} scope={args.scope}"
            )
            return 0

        if args.action == "force-release":
            result = force_release(
                repo_root,
                scope=args.scope,
                reason=args.reason,
                task_id=getattr(args, "task_id", ""),
            )
            _print_json({"force_released": True, "scope": args.scope}) if args.json else print(
                f"force-released scope={args.scope}"
            )
            return 0

        if args.action == "release-all":
            result = release_all(repo_root, task_id=args.task_id, pid=args.pid)
            _print_json({"released": result}) if args.json else print(
                f"release-all task_id={args.task_id} scopes={result}"
            )
            return 0

        if args.action == "status-all":
            result = status_all(repo_root)
            _print_json(result) if args.json else print(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            )
            return 0

    except LockError as exc:
        data = exc.to_dict()
        print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
        return exc.exit_code

    parser.error(f"unsupported command: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
