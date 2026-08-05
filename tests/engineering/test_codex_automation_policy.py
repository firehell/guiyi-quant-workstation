"""Personal-development Codex hook and policy contracts.

Lane/Issue/worktree/PR Gate automation is retired. These tests prove ordinary
``git push origin develop`` is not denied by branch metadata, while force push
and narrow history-rewrite forms remain blocked.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / ".codex" / "hooks" / "pre_tool_use_policy.py"
WORKFLOW_RULES = ROOT / ".codex" / "rules" / "workflow.rules"
CONFIG_TOML = ROOT / ".codex" / "config.toml"
DEVELOPMENT_DOC = ROOT / "docs" / "DEVELOPMENT.md"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _decision(command: str) -> dict:
    hook = _module(HOOK_PATH, "pre_tool_use_policy_personal")
    return hook.decision(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


def test_retired_collaboration_assets_are_absent() -> None:
    retired = [
        ROOT / "scripts" / "engineering" / "task-worktree.sh",
        ROOT / "scripts" / "engineering" / "task_workflow.py",
        ROOT / "scripts" / "engineering" / "worktree_flow.py",
        ROOT / "scripts" / "engineering" / "runtime-promotion.sh",
        ROOT / "scripts" / "engineering" / "runtime-health.sh",
        ROOT / ".github" / "workflows" / "lane-pr-gate.yml",
    ]
    present = [path.as_posix() for path in retired if path.exists()]
    assert not present, present


def test_ordinary_develop_push_is_not_denied() -> None:
    result = _decision("git push origin develop")
    assert result == {}


def test_ordinary_feature_push_is_not_denied() -> None:
    result = _decision("git push -u origin feature/example")
    assert result == {}


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin develop",
        "git push --force-with-lease origin main",
        "git push -f origin HEAD:main",
    ],
)
def test_force_push_remains_denied(command: str) -> None:
    result = _decision(command)
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Force" in result["hookSpecificOutput"]["permissionDecisionReason"] or "force" in result[
        "hookSpecificOutput"
    ]["permissionDecisionReason"].lower()


def test_history_rewrite_filter_branch_denied() -> None:
    result = _decision("git filter-branch -- --all")
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_workflow_rules_no_longer_forbid_develop_push() -> None:
    text = WORKFLOW_RULES.read_text(encoding="utf-8")
    assert "task-worktree.sh" not in text
    assert "release-flow.sh" not in text
    assert 'pattern = ["git", "push", "origin", "develop"]' not in text
    assert "force" in text.lower()
    assert "forbidden" in text


def test_codex_hook_uses_windows_available_python() -> None:
    text = CONFIG_TOML.read_text(encoding="utf-8")
    assert "/usr/bin/python3" not in text
    assert "pre_tool_use_policy.py" in text
    assert 'command = \'python "' in text or 'command = "python ' in text or "python " in text


def test_development_doc_allows_direct_develop() -> None:
    text = DEVELOPMENT_DOC.read_text(encoding="utf-8")
    assert "develop" in text
    assert "PERSONAL_DEVELOPMENT_WORKFLOW" in text or "个人" in text
    assert "exact-head" not in text.lower() or "不再" in text or "不要求" in text


def test_hook_ignores_non_bash_tools() -> None:
    hook = _module(HOOK_PATH, "pre_tool_use_policy_non_bash")
    assert hook.decision({"tool_name": "Edit", "tool_input": {}}) == {}


def test_hook_denies_empty_command() -> None:
    hook = _module(HOOK_PATH, "pre_tool_use_policy_empty")
    result = hook.decision({"tool_name": "Bash", "tool_input": {"command": "   "}})
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
