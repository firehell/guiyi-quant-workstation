#!/usr/bin/env python3
"""Canonical TASK status mutation layer for workstation control-plane flows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Iterable

from status_machine import Status, is_valid_transition, map_legacy_status
from task_meta import parse_task_file, resolve_task_file


YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
MARKDOWN_STATUS_RE = re.compile(r"(^\|\s*Status\s*\|\s*).*(\s*\|$)", re.M)


class StatusTransitionError(ValueError):
    """Raised when a TASK status transition is invalid or cannot be persisted."""


@dataclass(frozen=True)
class StatusTransitionResult:
    task_id: str
    task_file: str
    previous_status: str
    new_status: str
    stage: str
    changed: bool
    idempotent: bool
    record_file: str

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_file": self.task_file,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "stage": self.stage,
            "changed": self.changed,
            "idempotent": self.idempotent,
            "record_file": self.record_file,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def transition_task_status(
    task_id_or_file: str | Path,
    to_status: str,
    *,
    repo_root: Path | str | None = None,
    stage: str = "",
    actor: str = "script",
    reason: str = "",
    exit_code: int | None = None,
    expected_from: Iterable[str] | None = None,
) -> StatusTransitionResult:
    """Transition a TASK status and persist YAML + legacy Markdown compatibility fields.

    This is the only canonical status mutation entrypoint. Callers must use this
    function or the CLI in this module instead of directly editing TASK files.
    """

    root = Path(repo_root or Path.cwd()).resolve()
    task_file = resolve_task_file(str(task_id_or_file), root)
    meta = parse_task_file(task_file, repo_root=root, include_runtime=False)
    previous_raw = meta.status or ""
    previous = _coerce_status(previous_raw)
    target = _coerce_status(to_status)

    if expected_from:
        expected = {_coerce_status(item) for item in expected_from}
        if previous not in expected and previous != target:
            allowed = ", ".join(sorted(status.value for status in expected))
            raise StatusTransitionError(
                f"Status precondition failed for {meta.task_id}: current={previous.value} expected={allowed}"
            )

    record_file = root / ".ai" / "results" / meta.task_id / "status_transition.json"
    if previous == target:
        _ensure_record(record_file, meta.task_id, task_file, previous.value, target.value)
        return StatusTransitionResult(
            task_id=meta.task_id,
            task_file=_repo_relative(task_file, root),
            previous_status=previous.value,
            new_status=target.value,
            stage=stage,
            changed=False,
            idempotent=True,
            record_file=_repo_relative(record_file, root),
        )

    if not is_valid_transition(previous, target):
        raise StatusTransitionError(f"Invalid status transition: {previous.value} -> {target.value}")

    text = task_file.read_text(encoding="utf-8")
    new_text = _replace_yaml_status(text, target.value)
    new_text = _replace_markdown_status(new_text, target.value)
    if new_text == text:
        raise StatusTransitionError(f"No status field found in TASK: {task_file}")
    task_file.write_text(new_text, encoding="utf-8")

    event = {
        "timestamp": utc_now(),
        "task_id": meta.task_id,
        "task_file": _repo_relative(task_file, root),
        "from_status": previous.value,
        "to_status": target.value,
        "stage": stage,
        "actor": actor,
        "reason": reason,
        "exit_code": exit_code,
        "idempotent": False,
    }
    _append_record(record_file, event)
    return StatusTransitionResult(
        task_id=meta.task_id,
        task_file=_repo_relative(task_file, root),
        previous_status=previous.value,
        new_status=target.value,
        stage=stage,
        changed=True,
        idempotent=False,
        record_file=_repo_relative(record_file, root),
    )


def _coerce_status(value: str) -> Status:
    try:
        return map_legacy_status(str(value or "").strip())
    except ValueError as exc:
        raise StatusTransitionError(str(exc)) from exc


def _replace_yaml_status(text: str, status: str) -> str:
    match = YAML_FRONTMATTER_RE.match(text)
    if not match:
        return text
    yaml_text = match.group(1)
    if not re.search(r"(?m)^status\s*:", yaml_text):
        raise StatusTransitionError("YAML frontmatter status field missing")
    updated_yaml = re.sub(r"(?m)^(status\s*:\s*).*$", rf"\g<1>{status}", yaml_text, count=1)
    return text[: match.start(1)] + updated_yaml + text[match.end(1) :]


def _replace_markdown_status(text: str, status: str) -> str:
    return MARKDOWN_STATUS_RE.sub(rf"\g<1>{status}\2", text, count=1)


def _append_record(record_file: Path, event: dict[str, object]) -> None:
    record_file.parent.mkdir(parents=True, exist_ok=True)
    if record_file.is_file():
        data = json.loads(record_file.read_text(encoding="utf-8"))
    else:
        data = {"schema_version": 1, "task_id": event["task_id"], "history": []}
    data["task_id"] = event["task_id"]
    data["last_transition"] = event
    data.setdefault("history", []).append(event)
    record_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ensure_record(record_file: Path, task_id: str, task_file: Path, previous: str, target: str) -> None:
    if record_file.is_file():
        return
    record_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "task_id": task_id,
        "last_transition": None,
        "history": [],
        "idempotent_observation": {
            "timestamp": utc_now(),
            "task_file": str(task_file),
            "from_status": previous,
            "to_status": target,
            "idempotent": True,
        },
    }
    record_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _repo_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transition canonical TASK status.")
    parser.add_argument("task")
    parser.add_argument("--to", required=True, dest="to_status")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="")
    parser.add_argument("--actor", default="script")
    parser.add_argument("--reason", default="")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--expected-from", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = transition_task_status(
            args.task,
            args.to_status,
            repo_root=args.repo_root,
            stage=args.stage,
            actor=args.actor,
            reason=args.reason,
            exit_code=args.exit_code,
            expected_from=args.expected_from or None,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = result.as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
