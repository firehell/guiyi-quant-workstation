"""Deterministic Markdown rendering for Lean Matrix contracts."""

from __future__ import annotations

import string
from collections.abc import Sequence
from typing import Any

from .routing import BASE_ROLES


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
