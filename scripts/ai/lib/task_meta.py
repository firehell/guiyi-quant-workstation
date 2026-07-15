#!/usr/bin/env python3
"""Parse Guiyi TASK metadata with legacy Markdown compatibility."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


VALID_WORK_LEVELS = {"L0", "L1", "L2"}
VALID_TIERS = {"auto", "fast", "standard", "deep", "critical"}


def _strip_cell(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
        value = value[1:-1]
    return value.strip()


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _section(text: str, heading_pattern: str) -> str:
    match = re.search(heading_pattern, text, re.M)
    if not match:
        return ""
    start = match.end()
    end = re.search(r"^##\s+", text[start:], re.M)
    return text[start : start + end.start()] if end else text[start:]


def _parse_legacy_meta_table(text: str) -> dict[str, str]:
    meta_section = _section(text, r"^##\s+0\.\s*元信息\s*$")
    result: dict[str, str] = {}
    for line in meta_section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"字段", "------"}:
            continue
        result[cells[0]] = _strip_cell(cells[1])
    return result


def _parse_machine_json(text: str) -> dict[str, Any]:
    for match in re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.S):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (
            "task_id" in payload or "routing" in payload or "metadata" in payload
        ):
            return payload
    return {}


def _extract_backtick_paths(block: str) -> list[str]:
    paths: list[str] = []
    for value in re.findall(r"`([^`]+)`", block):
        value = value.strip()
        if value and value not in paths:
            paths.append(value)
    return paths


def _parse_paths(text: str) -> tuple[list[str], list[str]]:
    module_section = _section(text, r"^##\s+7\.\s*涉及模块\s*$")
    allowed = ""
    forbidden = ""
    allowed_match = re.search(r"\*\*允许修改[^*]*\*\*[:：]?(.*)", module_section, re.S)
    if allowed_match:
        allowed = allowed_match.group(1)
        forbidden_split = re.split(r"\*\*禁止修改[^*]*\*\*[:：]?", allowed, maxsplit=1)
        allowed = forbidden_split[0]
        if len(forbidden_split) > 1:
            forbidden = forbidden_split[1]
    else:
        allowed = module_section

    if not forbidden:
        forbidden_match = re.search(r"\*\*禁止修改[^*]*\*\*[:：]?(.*)", module_section, re.S)
        if forbidden_match:
            forbidden = forbidden_match.group(1)

    return _extract_backtick_paths(allowed), _extract_backtick_paths(forbidden)


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "允许", "是"}
    return bool(value)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def load_task_metadata(task_file: str | Path) -> dict[str, Any]:
    path = Path(task_file)
    text = path.read_text(encoding="utf-8")
    machine = _parse_machine_json(text)
    legacy_table = _parse_legacy_meta_table(text)
    legacy_allowed, legacy_forbidden = _parse_paths(text)

    metadata = machine.get("metadata", machine)
    routing = dict(machine.get("routing", {}))
    permissions = dict(machine.get("permissions", {}))

    task_id = str(metadata.get("task_id") or legacy_table.get("Task ID") or path.stem).strip()
    work_level = str(metadata.get("work_level") or legacy_table.get("Work Level") or "L2").strip().upper()
    if work_level not in VALID_WORK_LEVELS:
        work_level = "L2"

    requested_tier = str(routing.get("requested_tier", "auto")).strip().lower()
    if requested_tier not in VALID_TIERS:
        requested_tier = "auto"

    result = {
        "schema_version": int(machine.get("schema_version", 1)),
        "task_id": task_id,
        "work_level": work_level,
        "github_issue": str(metadata.get("github_issue") or legacy_table.get("GitHub Issue") or "").strip(),
        "branch": str(metadata.get("branch") or legacy_table.get("Branch") or "").strip(),
        "worktree": str(metadata.get("worktree") or legacy_table.get("Worktree") or "").strip(),
        "status": str(metadata.get("status") or legacy_table.get("Status") or "").strip(),
        "owner": str(metadata.get("owner") or legacy_table.get("Owner") or "").strip(),
        "allowed_paths": _list_value(machine.get("allowed_paths")) or legacy_allowed,
        "forbidden_paths": _list_value(machine.get("forbidden_paths")) or legacy_forbidden,
        "routing": {
            "requested_tier": requested_tier,
            "allow_auto_escalation": _bool_value(routing.get("allow_auto_escalation"), True),
            "max_auto_escalations": _int_value(routing.get("max_auto_escalations"), 1),
        },
        "permissions": {
            "production_access_allowed": _bool_value(
                permissions.get("production_access_allowed"), False
            ),
            "database_write_allowed": _bool_value(permissions.get("database_write_allowed"), False),
            "external_network_allowed": _bool_value(
                permissions.get("external_network_allowed"), False
            ),
            "push_allowed": _bool_value(permissions.get("push_allowed"), False),
            "merge_allowed": _bool_value(permissions.get("merge_allowed"), False),
            "deploy_allowed": _bool_value(permissions.get("deploy_allowed"), False),
            "trading_execution_allowed": _bool_value(
                permissions.get("trading_execution_allowed"), False
            ),
        },
        "source": {
            "path": str(path),
            "mode": "machine_json" if machine else "legacy_markdown",
        },
        "warnings": [],
    }

    if not machine:
        result["warnings"].append("legacy_markdown_metadata")
    if not task_id:
        result["warnings"].append("missing_task_id")
    if not result["allowed_paths"]:
        result["warnings"].append("missing_allowed_paths")
    return result


def validate_task_metadata(metadata: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not metadata.get("task_id"):
        errors.append("task_id is required")
    if metadata.get("work_level") not in VALID_WORK_LEVELS:
        errors.append("work_level must be L0, L1, or L2")
    routing = metadata.get("routing", {})
    if routing.get("requested_tier") not in VALID_TIERS:
        errors.append("routing.requested_tier must be auto, fast, standard, deep, or critical")
    return errors


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse and validate Guiyi TASK metadata.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "dump-json"):
        sub = subparsers.add_parser(command)
        sub.add_argument("task_file")
    args = parser.parse_args(argv)

    metadata = load_task_metadata(args.task_file)
    errors = validate_task_metadata(metadata)
    if args.command == "dump-json":
        _print_json(metadata)
        return 0 if not errors else 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"[OK] task metadata valid: {metadata['task_id']}")
    for warning in metadata["warnings"]:
        print(f"[WARN] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
