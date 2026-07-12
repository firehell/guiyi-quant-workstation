"""Worktree-scoped writer lock for the local AI workstation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_STALE_SECONDS = 24 * 60 * 60
WRITERS = {"codex", "cursor", "codebuddy"}


class LockError(RuntimeError):
    """Raised when a lock operation cannot be completed."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class LockStatus:
    state: str
    lock_file: str
    lock: dict[str, Any] | None
    stale: bool
    reason: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_path(path: str | Path) -> str:
    raw = Path(path).expanduser()
    if raw.exists():
        return raw.resolve().as_posix()
    return raw.absolute().as_posix()


def lock_paths(repo_root: Path, worktree: str) -> tuple[Path, Path, str]:
    worktree_path = canonical_path(worktree)
    worktree_hash = hashlib.sha256(worktree_path.encode("utf-8")).hexdigest()
    lock_root = repo_root / ".ai" / "locks"
    return lock_root / "worktrees" / f"{worktree_hash[:16]}.json", lock_root / "audit.jsonl", worktree_hash


def current_branch(worktree: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", worktree, "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def current_command() -> str:
    return " ".join(sys.argv)


def pid_is_alive(pid: object) -> bool:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parse_started_at(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def stale_seconds() -> int:
    raw = os.getenv("GUIYI_WRITER_LOCK_STALE_SECONDS", str(DEFAULT_STALE_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_STALE_SECONDS
    return max(value, 1)


def read_lock(lock_file: Path) -> dict[str, Any] | None:
    if not lock_file.exists():
        return None
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockError(f"Lock file is not valid JSON: {lock_file}: {exc}", 3) from exc


def is_stale(lock: dict[str, Any]) -> tuple[bool, str]:
    lock_host = str(lock.get("hostname", ""))
    local_host = socket.gethostname()
    if lock_host == local_host:
        if not pid_is_alive(lock.get("pid")):
            return True, "pid_not_running"
        return False, "pid_alive"

    started_ts = parse_started_at(lock.get("started_at"))
    if started_ts is None:
        return False, "different_hostname_without_valid_started_at"
    age = time.time() - started_ts
    if age > stale_seconds():
        return True, "different_hostname_lock_expired"
    return False, "different_hostname_within_threshold"


def status(repo_root: Path, worktree: str) -> LockStatus:
    lock_file, _audit_file, _worktree_hash = lock_paths(repo_root, worktree)
    lock = read_lock(lock_file)
    if lock is None:
        return LockStatus("unlocked", lock_file.as_posix(), None, False, "no_lock")
    stale, reason = is_stale(lock)
    return LockStatus("stale" if stale else "locked", lock_file.as_posix(), lock, stale, reason)


def append_audit(repo_root: Path, event: str, lock: dict[str, Any] | None, *, actor: dict[str, Any]) -> None:
    _lock_file, audit_file, _worktree_hash = lock_paths(repo_root, actor.get("worktree", ""))
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "at": utc_now(),
        "actor": actor,
        "lock": lock,
    }
    with audit_file.open("a", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def acquire(
    repo_root: Path,
    *,
    task_id: str,
    worktree: str,
    branch: str,
    writer: str,
    stage: str,
    pid: int,
    command: str,
) -> dict[str, Any]:
    if writer not in WRITERS:
        raise LockError(f"Unsupported writer: {writer}", 2)

    lock_file, _audit_file, worktree_hash = lock_paths(repo_root, worktree)
    worktree_path = canonical_path(worktree)
    current = status(repo_root, worktree_path)
    if current.lock is not None:
        owner = current.lock.get("task_id", "unknown")
        reason = current.reason
        raise LockError(
            f"Writer lock is held for worktree={worktree_path} by task={owner} "
            f"writer={current.lock.get('writer', '')} pid={current.lock.get('pid', '')} "
            f"state={current.state} reason={reason}; use break-stale only after verification",
            3,
        )

    lock = {
        "schema_version": SCHEMA_VERSION,
        "lock_id": hashlib.sha256(f"{worktree_path}:{task_id}:{pid}:{utc_now()}".encode("utf-8")).hexdigest()[:16],
        "task_id": task_id,
        "worktree": worktree_path,
        "worktree_hash": worktree_hash,
        "branch": branch or current_branch(worktree_path),
        "writer": writer,
        "stage": stage,
        "pid": pid,
        "hostname": socket.gethostname(),
        "started_at": utc_now(),
        "command": command,
    }
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock_file.open("x", encoding="utf-8") as fh:
            json.dump(lock, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    except FileExistsError as exc:
        raise LockError(f"Writer lock appeared while acquiring: {lock_file}", 3) from exc

    append_audit(repo_root, "acquire", lock, actor=lock)
    return lock


def ensure_owner(lock: dict[str, Any], *, task_id: str, worktree: str, writer: str, pid: int | None) -> None:
    worktree_path = canonical_path(worktree)
    mismatches: list[str] = []
    if lock.get("task_id") != task_id:
        mismatches.append(f"task_id={lock.get('task_id')}")
    if canonical_path(str(lock.get("worktree", ""))) != worktree_path:
        mismatches.append(f"worktree={lock.get('worktree')}")
    if lock.get("writer") != writer:
        mismatches.append(f"writer={lock.get('writer')}")
    if pid is not None and int(lock.get("pid", -1)) != pid:
        mismatches.append(f"pid={lock.get('pid')}")
    if mismatches:
        raise LockError("Refusing to release lock owned by another writer: " + ", ".join(mismatches), 6)


def release(repo_root: Path, *, task_id: str, worktree: str, writer: str, pid: int | None) -> dict[str, Any] | None:
    lock_file, _audit_file, _worktree_hash = lock_paths(repo_root, worktree)
    lock = read_lock(lock_file)
    if lock is None:
        return None
    ensure_owner(lock, task_id=task_id, worktree=worktree, writer=writer, pid=pid)
    lock_file.unlink()
    append_audit(
        repo_root,
        "release",
        lock,
        actor={"task_id": task_id, "worktree": canonical_path(worktree), "writer": writer, "pid": pid},
    )
    return lock


def break_stale(repo_root: Path, *, worktree: str, actor_task_id: str, actor_writer: str) -> dict[str, Any]:
    lock_file, _audit_file, _worktree_hash = lock_paths(repo_root, worktree)
    lock = read_lock(lock_file)
    if lock is None:
        raise LockError(f"No lock to break for worktree={canonical_path(worktree)}", 4)
    stale, reason = is_stale(lock)
    if not stale:
        raise LockError(
            f"Refusing to break active writer lock task={lock.get('task_id')} pid={lock.get('pid')} reason={reason}",
            3,
        )
    lock_file.unlink()
    append_audit(
        repo_root,
        "break-stale",
        lock,
        actor={
            "task_id": actor_task_id,
            "worktree": canonical_path(worktree),
            "writer": actor_writer,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "reason": reason,
        },
    )
    return lock


def print_payload(payload: object, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(payload, LockStatus):
        if payload.lock is None:
            print(f"unlocked lock_file={payload.lock_file}")
        else:
            lock = payload.lock
            print(
                f"{payload.state} task={lock.get('task_id')} writer={lock.get('writer')} "
                f"pid={lock.get('pid')} worktree={lock.get('worktree')} reason={payload.reason}"
            )
        return
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage worktree-scoped writer locks.")
    parser.add_argument("--repo-root", default=".", help="Repository root that owns .ai/locks")
    subparsers = parser.add_subparsers(dest="action", required=True)

    status_parser = subparsers.add_parser("status", help="Show lock status")
    status_parser.add_argument("--worktree", default=".")
    status_parser.add_argument("--json", action="store_true")
    status_parser.add_argument("--fail-if-held", action="store_true")

    acquire_parser = subparsers.add_parser("acquire", help="Acquire an exclusive writer lock")
    acquire_parser.add_argument("--task-id", required=True)
    acquire_parser.add_argument("--worktree", required=True)
    acquire_parser.add_argument("--branch", default="")
    acquire_parser.add_argument("--writer", required=True, choices=sorted(WRITERS))
    acquire_parser.add_argument("--stage", required=True)
    acquire_parser.add_argument("--pid", type=int, default=os.getpid())
    acquire_parser.add_argument("--command", dest="lock_command", default=current_command())
    acquire_parser.add_argument("--json", action="store_true")

    release_parser = subparsers.add_parser("release", help="Release a lock owned by this writer")
    release_parser.add_argument("--task-id", required=True)
    release_parser.add_argument("--worktree", required=True)
    release_parser.add_argument("--writer", required=True, choices=sorted(WRITERS))
    release_parser.add_argument("--pid", type=int)
    release_parser.add_argument("--json", action="store_true")

    break_parser = subparsers.add_parser("break-stale", help="Explicitly remove a stale lock")
    break_parser.add_argument("--worktree", required=True)
    break_parser.add_argument("--task-id", required=True)
    break_parser.add_argument("--writer", required=True, choices=sorted(WRITERS))
    break_parser.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()

    try:
        if args.action == "status":
            payload = status(repo_root, args.worktree)
            print_payload(asdict(payload), as_json=args.json)
            if args.fail_if_held and payload.lock is not None and not payload.stale:
                lock = payload.lock
                print(
                    f"Writer lock is active for worktree={lock.get('worktree')} "
                    f"task={lock.get('task_id')} writer={lock.get('writer')} pid={lock.get('pid')}",
                    file=sys.stderr,
                )
                return 3
            return 0
        if args.action == "acquire":
            payload = acquire(
                repo_root,
                task_id=args.task_id,
                worktree=args.worktree,
                branch=args.branch,
                writer=args.writer,
                stage=args.stage,
                pid=args.pid,
                command=args.lock_command,
            )
            print_payload(payload, as_json=args.json)
            return 0
        if args.action == "release":
            payload = release(repo_root, task_id=args.task_id, worktree=args.worktree, writer=args.writer, pid=args.pid)
            print_payload({"released": payload is not None, "lock": payload}, as_json=args.json)
            return 0
        if args.action == "break-stale":
            payload = break_stale(repo_root, worktree=args.worktree, actor_task_id=args.task_id, actor_writer=args.writer)
            print_payload({"broken": True, "lock": payload}, as_json=args.json)
            return 0
    except LockError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code

    parser.error(f"unsupported command: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
