"""Strict schema-v1 Task Charter validation and rendering."""

from __future__ import annotations

import re
from typing import Any

from task_workflow import WorkflowError, _validate_paths, classify_paths

from .errors import LeanMatrixError
from .rendering import render_charter_markdown
from .routing import DOMAIN_SPECIALISTS, LANE_DISPATCH, dispatch_charter


SCHEMA_VERSION = 1
REQUIRED_FIELDS = frozenset({
    "schema_version", "issue_number", "task_id", "kind", "slug", "title", "value", "goal",
    "current_facts", "lane", "domains", "allowed_paths", "forbidden_paths", "acceptance", "external_gates",
})
KINDS = frozenset({"feature", "fix", "docs", "research", "refactor"})
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
WORKTREE_ROOT = "/Volumes/扩展盘/GuiyiWorktrees/tasks"


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LeanMatrixError("invalid_string", f"{field} must be a non-blank string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise LeanMatrixError(
            "invalid_string_control_characters",
            f"{field} must be a single-line string without control characters",
        )
    return value.strip()


def require_string_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise LeanMatrixError(
            "invalid_string_list",
            f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} list",
        )
    return [require_string(item, f"{field} item") for item in value]


def require_token(value: object, field: str) -> str:
    token = require_string(value, field)
    if not TOKEN_RE.fullmatch(token) or "/" in token:
        raise LeanMatrixError("invalid_identifier", f"{field} must be a simple identifier")
    return token


def require_relative_paths(value: object, lane: int) -> list[str]:
    paths = require_string_list(value, "allowed_paths")
    if any(
        "\\" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path) or ".." in path.split("/")
        for path in paths
    ):
        raise LeanMatrixError(
            "invalid_allowed_path",
            "allowed_paths must be repository-relative slash-separated paths without traversal",
        )
    try:
        _validate_paths(paths)
        if lane in (1, 2):
            classify_paths(lane, paths)
    except WorkflowError as exc:
        error_type = "invalid_allowed_path" if exc.error_type == "invalid_changed_path" else exc.error_type
        raise LeanMatrixError(error_type, str(exc)) from exc
    return paths


def validate_charter(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LeanMatrixError("invalid_input", "input must be a JSON object")
    if set(raw) != REQUIRED_FIELDS:
        raise LeanMatrixError("invalid_schema_keys", "input keys must exactly match schema version 1")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != SCHEMA_VERSION:
        raise LeanMatrixError("invalid_schema_version", "schema_version must equal 1")
    issue_number = raw["issue_number"]
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
        raise LeanMatrixError("invalid_issue_number", "issue_number must be a positive integer")
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise LeanMatrixError("invalid_kind", "kind must be feature, fix, docs, research, or refactor")
    lane = raw["lane"]
    if type(lane) is not int or lane not in LANE_DISPATCH:
        raise LeanMatrixError("invalid_lane", "lane must be 1, 2, or 3")
    domains = require_string_list(raw["domains"], "domains", allow_empty=True)
    invalid_domains = [domain for domain in domains if domain not in DOMAIN_SPECIALISTS]
    if invalid_domains:
        raise LeanMatrixError("invalid_domain", f"unsupported domain: {invalid_domains[0]}")
    unique_domains = list(dict.fromkeys(domains))
    specialists = [DOMAIN_SPECIALISTS[domain] for domain in unique_domains]
    if len(specialists) > 2:
        raise LeanMatrixError("split_required", "more than two specialist domains require separate Task Charters")
    external_gates = require_string_list(raw["external_gates"], "external_gates", allow_empty=True)
    if lane in (1, 2) and external_gates:
        raise LeanMatrixError("external_gates_not_allowed", "external_gates must be empty for Lane 1 and Lane 2")
    if lane == 3 and not external_gates:
        raise LeanMatrixError("external_gates_required", "external_gates must be non-empty for Lane 3")
    return {
        "schema_version": SCHEMA_VERSION,
        "issue_number": issue_number,
        "task_id": require_token(raw["task_id"], "task_id"),
        "kind": kind,
        "slug": require_token(raw["slug"], "slug"),
        "title": require_string(raw["title"], "title"),
        "value": require_string(raw["value"], "value"),
        "goal": require_string(raw["goal"], "goal"),
        "current_facts": require_string_list(raw["current_facts"], "current_facts"),
        "lane": lane,
        "domains": unique_domains,
        "allowed_paths": require_relative_paths(raw["allowed_paths"], lane),
        "forbidden_paths": require_string_list(raw["forbidden_paths"], "forbidden_paths"),
        "acceptance": require_string_list(raw["acceptance"], "acceptance"),
        "external_gates": external_gates,
        "specialists": specialists,
    }


def task_identity(charter: dict[str, Any]) -> dict[str, Any]:
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


def render_charter(raw: object) -> dict[str, Any]:
    """Validate input and return the machine-readable Charter representation."""
    charter = validate_charter(raw)
    task = task_identity(charter)
    dispatch = dispatch_charter(charter)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "task": task,
        "dispatch": dispatch,
        "charter_markdown": render_charter_markdown(charter, task, dispatch),
    }
