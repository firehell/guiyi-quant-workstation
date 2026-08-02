#!/usr/bin/env python3
"""Render a validated, read-only Task Charter from JSON input."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# The CLI's contract is stdout/stderr only. Prevent Python's import machinery
# from creating an ignored __pycache__ beside the shared repository policy.
sys.dont_write_bytecode = True

from task_workflow import WorkflowError, _validate_paths, classify_paths


SCHEMA_VERSION = 1
REQUIRED_FIELDS = frozenset({
    "schema_version", "issue_number", "task_id", "kind", "slug", "title", "value", "goal",
    "current_facts", "lane", "domains", "allowed_paths", "forbidden_paths", "acceptance", "external_gates",
})
KINDS = frozenset({"feature", "fix", "docs", "research", "refactor"})
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
DOMAIN_SPECIALISTS = {
    "product-interaction": "product-interaction-specialist",
    "frontend": "frontend-specialist",
    "data-database": "data-database-specialist",
    "quant-research": "quant-research-specialist",
    "backtest-audit": "backtest-audit-specialist",
    "research-ai": "research-ai-specialist",
    "runtime-sre": "runtime-sre-specialist",
    "security": "security-specialist",
}
BASE_ROLES = ["ai-project-lead", "technical-lead", "implementer", "independent-quality-reviewer"]
LANE_DISPATCH = {
    1: ("Terra", "medium", "direct-or-short-plan", 2),
    2: ("Terra", "medium", "plan-then-execute", 3),
    3: ("Sol", "high", "plan-only-start", 4),
}
WORKTREE_ROOT = "/Volumes/扩展盘/GuiyiWorktrees/tasks"


class CharterError(ValueError):
    """A stable reason why a Task Charter cannot be rendered."""

    def __init__(self, error_type: str, detail: str) -> None:
        self.error_type = error_type
        self.detail = detail
        super().__init__(detail)


class CharterArgumentParser(argparse.ArgumentParser):
    """Route invalid command syntax through the Charter JSON error contract."""

    def error(self, message: str) -> None:
        raise CharterError("invalid_cli_arguments", message)


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CharterError("invalid_string", f"{field} must be a non-blank string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CharterError(
            "invalid_string_control_characters",
            f"{field} must be a single-line string without control characters",
        )
    return value.strip()


def _require_string_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise CharterError("invalid_string_list", f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
    return [_require_string(item, f"{field} item") for item in value]


def _require_token(value: object, field: str) -> str:
    token = _require_string(value, field)
    if not TOKEN_RE.fullmatch(token) or "/" in token:
        raise CharterError("invalid_identifier", f"{field} must be a simple identifier")
    return token


def _require_relative_paths(value: object, lane: int) -> list[str]:
    paths = _require_string_list(value, "allowed_paths")
    if any(
        "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path) or ".." in path.split("/")
        for path in paths
    ):
        raise CharterError(
            "invalid_allowed_path",
            "allowed_paths must be repository-relative slash-separated paths without traversal",
        )
    try:
        # The shared validator provides the repository-relative baseline for all
        # lanes. Its public classifier intentionally supports only Lane 1/2;
        # Lane 3 remains plan-only and receives no automation classification.
        _validate_paths(paths)
        if lane in (1, 2):
            classify_paths(lane, paths)
    except WorkflowError as exc:
        error_type = "invalid_allowed_path" if exc.error_type == "invalid_changed_path" else exc.error_type
        raise CharterError(error_type, str(exc)) from exc
    return paths


def _read_input(input_name: str) -> object:
    try:
        if input_name == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            content = binary_stdin.read().decode("utf-8") if binary_stdin else sys.stdin.read()
        else:
            content = Path(input_name).read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CharterError("invalid_input_encoding", "input must be UTF-8 encoded JSON") from exc
    except OSError as exc:
        raise CharterError("input_file_unavailable", str(exc)) from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise CharterError("invalid_json", exc.msg) from exc


def _validate(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CharterError("invalid_input", "input must be a JSON object")
    if set(raw) != REQUIRED_FIELDS:
        raise CharterError("invalid_schema_keys", "input keys must exactly match schema version 1")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != SCHEMA_VERSION:
        raise CharterError("invalid_schema_version", "schema_version must equal 1")
    issue_number = raw["issue_number"]
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
        raise CharterError("invalid_issue_number", "issue_number must be a positive integer")
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise CharterError("invalid_kind", "kind must be feature, fix, docs, research, or refactor")
    lane = raw["lane"]
    if type(lane) is not int or lane not in LANE_DISPATCH:
        raise CharterError("invalid_lane", "lane must be 1, 2, or 3")
    domains = _require_string_list(raw["domains"], "domains", allow_empty=True)
    invalid_domains = [domain for domain in domains if domain not in DOMAIN_SPECIALISTS]
    if invalid_domains:
        raise CharterError("invalid_domain", f"unsupported domain: {invalid_domains[0]}")
    unique_domains = list(dict.fromkeys(domains))
    specialists = [DOMAIN_SPECIALISTS[domain] for domain in unique_domains]
    if len(specialists) > 2:
        raise CharterError("split_required", "more than two specialist domains require separate Task Charters")
    external_gates = _require_string_list(raw["external_gates"], "external_gates", allow_empty=True)
    if lane in (1, 2) and external_gates:
        raise CharterError("external_gates_not_allowed", "external_gates must be empty for Lane 1 and Lane 2")
    if lane == 3 and not external_gates:
        raise CharterError("external_gates_required", "external_gates must be non-empty for Lane 3")
    return {
        "schema_version": SCHEMA_VERSION,
        "issue_number": issue_number,
        "task_id": _require_token(raw["task_id"], "task_id"),
        "kind": kind,
        "slug": _require_token(raw["slug"], "slug"),
        "title": _require_string(raw["title"], "title"),
        "value": _require_string(raw["value"], "value"),
        "goal": _require_string(raw["goal"], "goal"),
        "current_facts": _require_string_list(raw["current_facts"], "current_facts"),
        "lane": lane,
        "domains": unique_domains,
        "allowed_paths": _require_relative_paths(raw["allowed_paths"], lane),
        "forbidden_paths": _require_string_list(raw["forbidden_paths"], "forbidden_paths"),
        "acceptance": _require_string_list(raw["acceptance"], "acceptance"),
        "external_gates": external_gates,
        "specialists": specialists,
    }


def _bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _dispatch(charter: dict[str, Any]) -> dict[str, Any]:
    model, reasoning_effort, mode, base_sessions = LANE_DISPATCH[charter["lane"]]
    independence = ["implementer and independent-quality-reviewer use separate contexts"]
    if {"quant-research", "backtest-audit"}.issubset(charter["domains"]):
        independence.append("quant-research-specialist and backtest-audit-specialist use separate contexts")
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "mode": mode,
        "session_count": base_sessions + len(charter["specialists"]),
        "roles": BASE_ROLES,
        "specialists": charter["specialists"],
        "independence_requirements": independence,
    }


def _task(charter: dict[str, Any]) -> dict[str, Any]:
    identity = f"{charter['task_id']}-{charter['slug']}"
    return {
        "issue_number": charter["issue_number"],
        "task_id": charter["task_id"],
        "kind": charter["kind"],
        "slug": charter["slug"],
        "title": charter["title"],
        "branch": f"{charter['kind']}/{identity}",
        "worktree": f"{WORKTREE_ROOT}/{identity}",
    }


def _markdown(charter: dict[str, Any], task: dict[str, Any], dispatch: dict[str, Any]) -> str:
    team = BASE_ROLES + charter["specialists"]
    gates = charter["external_gates"] or ["None; this Lane has no external Gate."]
    return "\n".join([
        "# Task Charter",
        "",
        "## Identity",
        "",
        f"- Title: {task['title']}",
        f"- Issue: {task['issue_number']}",
        f"- Task ID: {task['task_id']}",
        f"- Kind: {task['kind']}",
        f"- Planned branch: {task['branch']}",
        f"- Planned worktree: {task['worktree']}",
        "",
        "## Value",
        charter["value"],
        "",
        "## Goal",
        charter["goal"],
        "",
        "## Current facts",
        _bullets(charter["current_facts"]),
        "",
        "## Lane and dispatch",
        f"- Lane: {charter['lane']}",
        f"- Model: {dispatch['model']} ({dispatch['reasoning_effort']})",
        f"- Mode: {dispatch['mode']}",
        f"- Sessions: {dispatch['session_count']}",
        "",
        "## Dynamic team",
        _bullets(team),
        _bullets(dispatch["independence_requirements"]),
        "",
        "## Allowed changes",
        _bullets(charter["allowed_paths"]),
        "",
        "## Forbidden changes",
        _bullets(charter["forbidden_paths"]),
        "",
        "## Acceptance",
        _bullets(charter["acceptance"]),
        "",
        "## External Gates",
        _bullets(gates),
        "",
        "## Completion flow",
        f"- Planned branch: {task['branch']}",
        f"- Planned worktree: {task['worktree']}",
        "- This Charter only describes the plan; it performs no repository or external operation.",
        "",
    ])


def render(raw: object) -> dict[str, Any]:
    """Validate input and return the machine-readable Charter representation."""
    charter = _validate(raw)
    task = _task(charter)
    dispatch = _dispatch(charter)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "task": task,
        "dispatch": dispatch,
        "charter_markdown": _markdown(charter, task, dispatch),
    }


def _blocked(error: CharterError) -> int:
    print(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "error_type": error.error_type,
        "detail": error.detail,
    }), file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = CharterArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True, parser_class=CharterArgumentParser)
    charter = subcommands.add_parser("charter")
    charter.add_argument("--input", required=True)
    charter.add_argument("--format", required=True, choices=("markdown", "json"))
    try:
        args = parser.parse_args(argv)
        result = render(_read_input(args.input))
    except CharterError as exc:
        return _blocked(exc)
    if args.format == "markdown":
        print(result["charter_markdown"], end="")
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
