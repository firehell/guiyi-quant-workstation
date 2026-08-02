"""Deterministic Markdown rendering for Lean Matrix contracts."""

from __future__ import annotations

import string
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .routing import BASE_ROLES

if TYPE_CHECKING:
    from .contracts import ExecutionPlanV1


MARKDOWN_ESCAPE_TABLE = str.maketrans({character: f"\\{character}" for character in string.punctuation})


def markdown_text(value: str) -> str:
    """Escape untrusted text so it cannot introduce Markdown structure."""
    return value.translate(MARKDOWN_ESCAPE_TABLE)


def bullets(items: Sequence[str]) -> str:
    return "\n".join(f"- {markdown_text(item)}" for item in items)


def render_charter_markdown(
    charter: dict[str, Any], task: dict[str, Any], dispatch: dict[str, Any],
) -> str:
    """Render the byte-for-byte schema-v1 Task Charter Markdown contract."""
    team = BASE_ROLES + charter["specialists"]
    gates = charter["external_gates"] or ["None; this Lane has no external Gate."]
    return "\n".join([
        "# Task Charter", "", "## Identity", "",
        f"- Title: {markdown_text(task['title'])}",
        f"- Issue: {task['issue_number']}",
        f"- Task ID: {task['task_id']}",
        f"- Kind: {task['kind']}",
        f"- Planned branch: {task['branch']}",
        f"- Planned worktree: {task['worktree']}",
        "", "## Value", markdown_text(charter["value"]),
        "", "## Goal", markdown_text(charter["goal"]),
        "", "## Current facts", bullets(charter["current_facts"]),
        "", "## Lane and dispatch",
        f"- Lane: {charter['lane']}",
        f"- Model: {dispatch['model']} ({dispatch['reasoning_effort']})",
        f"- Mode: {dispatch['mode']}",
        f"- Sessions: {dispatch['session_count']}",
        "", "## Dynamic team", bullets(team), bullets(dispatch["independence_requirements"]),
        "", "## Allowed changes", bullets(charter["allowed_paths"]),
        "", "## Forbidden changes", bullets(charter["forbidden_paths"]),
        "", "## Acceptance", bullets(charter["acceptance"]),
        "", "## External Gates", bullets(gates),
        "", "## Completion flow",
        f"- Planned branch: {task['branch']}",
        f"- Planned worktree: {task['worktree']}",
        "- This Charter only describes the plan; it performs no repository or external operation.",
        "",
    ])


def render_execution_plan_markdown(plan: "ExecutionPlanV1") -> str:
    """Render a deterministic human view without changing the canonical plan payload."""
    gates = plan.external_gates or ("None; this Lane has no external Gate.",)
    return "\n".join([
        "# Execution Plan", "", "## Identity", "",
        f"- Issue: {plan.task.issue_number}",
        f"- Task ID: {plan.task.task_id}",
        f"- Planned branch: {plan.task.branch}",
        f"- Planned worktree: {plan.task.worktree}",
        f"- Charter digest: {plan.charter_digest}",
        "", "## Base", "",
        f"- Ref: {plan.base.ref}",
        f"- Expected SHA: {plan.base.expected_sha}",
        "", "## Dispatch", "",
        f"- Model: {plan.dispatch.model} ({plan.dispatch.reasoning_effort})",
        "- Roles:", bullets(plan.dispatch.roles),
        "- Specialists:", bullets(plan.dispatch.specialists or ("None",)),
        "- Independence requirements:", bullets(plan.dispatch.independence_requirements),
        "", "## Scope", "", "- Allowed paths:", bullets(plan.scope.allowed_paths),
        "- Forbidden paths:", bullets(plan.scope.forbidden_paths),
        "", "## Validation", "",
        f"- Test profile: {plan.validation.test_profile}",
        "- Required checks:", bullets(plan.validation.required_checks),
        "", "## Transitions", "", bullets(plan.transitions),
        "", "## External Gates", "", bullets(gates),
        "", "This plan performs no transition or external operation.", "",
    ])
