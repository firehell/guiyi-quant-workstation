"""Local-only TASK runtime overlay helpers.

Runtime overlays live under `.ai/task-runtime/<TASK_ID>.json` and carry
machine-local state such as absolute worktree paths. They are intentionally
separate from tracked TASK contracts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in stripped envs
    Draft202012Validator = None  # type: ignore[assignment]


RUNTIME_SCHEMA_VERSION = "1.0"
RUNTIME_DIR = Path(".ai") / "task-runtime"
SCHEMA_RELATIVE_PATH = Path("configs") / "ai" / "schemas" / "task-runtime-v1.0.schema.json"
RUNTIME_META_FIELDS = {
    "worktree",
    "local_branch",
    "issue_number",
    "pr_number",
    "last_dispatch_stage",
    "last_dispatch_exit_code",
    "last_sync_at",
    "updated_by",
    "notes",
}


class TaskRuntimeError(ValueError):
    """Raised when a runtime overlay is unreadable, invalid, or unsafe."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def runtime_path(repo_root: Path | str, task_id: str) -> Path:
    return Path(repo_root).resolve() / RUNTIME_DIR / f"{task_id}.json"


def load_runtime_schema(repo_root: Path | str) -> dict[str, Any]:
    schema_path = Path(repo_root).resolve() / SCHEMA_RELATIVE_PATH
    if not schema_path.is_file():
        raise TaskRuntimeError(f"Task runtime schema not found: {schema_path}")
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskRuntimeError(f"Task runtime schema is invalid JSON: {schema_path}: {exc}") from exc


def validate_runtime_payload(repo_root: Path | str, task_id: str, payload: dict[str, Any]) -> None:
    if Draft202012Validator is None:
        raise TaskRuntimeError("jsonschema is required to validate task runtime overlays")
    schema = load_runtime_schema(repo_root)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "(root)"
        raise TaskRuntimeError(f"Task runtime overlay schema invalid for {task_id}: {location}: {first.message}")
    if payload.get("task_id") != task_id:
        raise TaskRuntimeError(
            f"Task runtime overlay task_id mismatch: expected={task_id} actual={payload.get('task_id')}"
        )


def load_task_runtime(repo_root: Path | str, task_id: str, *, required: bool = False) -> dict[str, Any]:
    path = runtime_path(repo_root, task_id)
    if not path.is_file():
        if required:
            raise TaskRuntimeError(f"Task runtime overlay missing: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskRuntimeError(f"Task runtime overlay is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TaskRuntimeError(f"Task runtime overlay must be a JSON object: {path}")
    validate_runtime_payload(repo_root, task_id, payload)
    return payload


def save_task_runtime(repo_root: Path | str, task_id: str, payload: dict[str, Any]) -> Path:
    clean: dict[str, Any] = {
        "schema_version": RUNTIME_SCHEMA_VERSION,
        "task_id": task_id,
    }
    for key, value in payload.items():
        if key in {"schema_version", "task_id"}:
            continue
        if key in RUNTIME_META_FIELDS and value not in (None, ""):
            clean[key] = value
    clean.setdefault("last_sync_at", utc_now())
    validate_runtime_payload(repo_root, task_id, clean)

    target = runtime_path(repo_root, task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def update_task_runtime(repo_root: Path | str, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    current = load_task_runtime(repo_root, task_id, required=False)
    merged = {**current, **updates}
    save_task_runtime(repo_root, task_id, merged)
    return load_task_runtime(repo_root, task_id, required=True)


def runtime_field(payload: dict[str, Any], field: str) -> Any:
    if field == "branch":
        return payload.get("local_branch", "")
    if field == "github_issue":
        issue_number = payload.get("issue_number", 0)
        return f"#{issue_number}" if issue_number else ""
    if field == "github_pr":
        pr_number = payload.get("pr_number", 0)
        return f"#{pr_number}" if pr_number else ""
    return payload.get(field, "")


def _coerce_updates(args: argparse.Namespace) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    for key in (
        "worktree",
        "local_branch",
        "last_dispatch_stage",
        "last_sync_at",
        "updated_by",
        "notes",
    ):
        value = getattr(args, key, None)
        if value not in (None, ""):
            updates[key] = value
    for key in ("issue_number", "pr_number", "last_dispatch_exit_code"):
        value = getattr(args, key, None)
        if value is not None:
            updates[key] = value
    if "last_sync_at" not in updates:
        updates["last_sync_at"] = utc_now()
    return updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read or write local TASK runtime overlays.")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    get_p = sub.add_parser("get")
    get_p.add_argument("--task", required=True)
    get_p.add_argument("--field", required=True)

    validate_p = sub.add_parser("validate")
    validate_p.add_argument("--task", required=True)

    set_p = sub.add_parser("set")
    set_p.add_argument("--task", required=True)
    set_p.add_argument("--worktree")
    set_p.add_argument("--local-branch")
    set_p.add_argument("--issue-number", type=int)
    set_p.add_argument("--pr-number", type=int)
    set_p.add_argument("--last-dispatch-stage")
    set_p.add_argument("--last-dispatch-exit-code", type=int)
    set_p.add_argument("--last-sync-at")
    set_p.add_argument("--updated-by", default="script")
    set_p.add_argument("--notes")
    set_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    try:
        if args.command == "get":
            payload = load_task_runtime(root, args.task, required=False)
            value = runtime_field(payload, args.field) if payload else ""
            if value in (None, ""):
                return 1
            print(value)
            return 0
        if args.command == "validate":
            load_task_runtime(root, args.task, required=True)
            print(f"[OK] task runtime valid: {args.task}")
            return 0
        if args.command == "set":
            payload = update_task_runtime(root, args.task, _coerce_updates(args))
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(runtime_path(root, args.task))
            return 0
    except TaskRuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
