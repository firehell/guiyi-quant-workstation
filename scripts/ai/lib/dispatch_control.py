"""Pause / resume / cancel / status control stages for the workstation dispatcher."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

from task_meta import parse_task_file, resolve_task_file


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def set_task_status(task_file: Path, status: str) -> None:
    text = task_file.read_text(encoding="utf-8")
    pattern = re.compile(r"(^\| Status \| ).*( \|$)", re.M)
    if not pattern.search(text):
        raise ValueError(f"Status field missing in {task_file}")
    task_file.write_text(pattern.sub(rf"\g<1>{status}\2", text, count=1), encoding="utf-8")


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pause_task(task_id: str, repo_root: Path, *, paused_by: str = "codex") -> dict:
    task_file = resolve_task_file(task_id, repo_root)
    meta = parse_task_file(task_file)
    if meta.status == "PAUSED":
        raise IdempotentError("already paused")
    if meta.status == "CANCELLED":
        raise ControlError("cannot pause cancelled task; replan or resume from cancel is not supported")

    out_dir = repo_root / ".ai" / "results" / meta.task_id
    record = {
        "schema_version": 1,
        "task_id": meta.task_id,
        "previous_status": meta.status or "UNKNOWN",
        "paused_at": utc_now(),
        "paused_by": paused_by,
        "writer_released": True,
    }
    write_json(out_dir / "pause_record.json", record)
    set_task_status(task_file, "PAUSED")
    return {"action": "pause", "task_id": meta.task_id, "status": "PAUSED", "previous_status": record["previous_status"]}


def resume_task(task_id: str, repo_root: Path) -> dict:
    task_file = resolve_task_file(task_id, repo_root)
    meta = parse_task_file(task_file)
    if meta.status == "CANCELLED":
        raise ControlError("已取消，需 resume 或 replan")
    if meta.status != "PAUSED":
        raise IdempotentError("not paused")

    out_dir = repo_root / ".ai" / "results" / meta.task_id
    record = read_json(out_dir / "pause_record.json")
    previous = record.get("previous_status") or "REQUIREMENT_READY"
    set_task_status(task_file, previous)
    write_json(
        out_dir / "resume_record.json",
        {"schema_version": 1, "task_id": meta.task_id, "restored_status": previous, "resumed_at": utc_now()},
    )
    return {"action": "resume", "task_id": meta.task_id, "status": previous}


def cancel_task(task_id: str, repo_root: Path, *, cancelled_by: str = "human") -> dict:
    task_file = resolve_task_file(task_id, repo_root)
    meta = parse_task_file(task_file)
    if meta.status == "CANCELLED":
        raise IdempotentError("already cancelled")

    out_dir = repo_root / ".ai" / "results" / meta.task_id
    write_json(
        out_dir / "cancel_record.json",
        {
            "schema_version": 1,
            "task_id": meta.task_id,
            "previous_status": meta.status,
            "cancelled_at": utc_now(),
            "cancelled_by": cancelled_by,
        },
    )
    set_task_status(task_file, "CANCELLED")
    return {"action": "cancel", "task_id": meta.task_id, "status": "CANCELLED"}


def status_task(task_id: str, repo_root: Path) -> dict:
    task_file = resolve_task_file(task_id, repo_root)
    meta = parse_task_file(task_file)
    out_dir = repo_root / ".ai" / "results" / meta.task_id
    approval = read_json(repo_root / ".ai" / "approvals" / f"{meta.task_id}.json")
    pause_record = read_json(out_dir / "pause_record.json")
    cancel_record = read_json(out_dir / "cancel_record.json")
    stage_logs = sorted(path.name for path in out_dir.glob("*.log")) if out_dir.is_dir() else []
    return {
        "action": "status",
        "task_id": meta.task_id,
        "status": meta.status,
        "work_level": meta.work_level,
        "branch": meta.branch,
        "worktree": meta.worktree,
        "approval_present": bool(approval),
        "pause_record": pause_record or None,
        "cancel_record": cancel_record or None,
        "stage_logs": stage_logs,
        "results_dir": str(out_dir.relative_to(repo_root)) if out_dir.is_dir() else "",
    }


class ControlError(ValueError):
    """Blocking control-plane error."""


class IdempotentError(ValueError):
    """Repeated pause/cancel/resume request."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run dispatcher control stages.")
    parser.add_argument("action", choices=["pause", "resume", "cancel", "status"])
    parser.add_argument("task")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    try:
        if args.action == "pause":
            payload = pause_task(args.task, root)
        elif args.action == "resume":
            payload = resume_task(args.task, root)
        elif args.action == "cancel":
            payload = cancel_task(args.task, root)
        else:
            payload = status_task(args.task, root)
    except IdempotentError as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except ControlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    text = json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
