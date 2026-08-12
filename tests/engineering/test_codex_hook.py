"""Minimal tests for the project-local destructive Git guard."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".codex" / "hooks" / "pre_tool_use_policy.py"


def _decision(command: str) -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("pre_tool_use_policy", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decision(
        {"tool_name": "Bash", "tool_input": {"command": command}}
    )


def test_ordinary_develop_push_is_allowed() -> None:
    assert _decision("git push origin develop") == {}


def test_force_push_is_denied() -> None:
    result = _decision("git push --force origin develop")
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_non_git_shell_command_is_ignored() -> None:
    assert _decision("uv run pytest -q") == {}
