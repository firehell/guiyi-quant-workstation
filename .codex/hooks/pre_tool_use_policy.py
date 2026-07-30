#!/usr/bin/env python3
"""Fail-closed local guard for commands that bypass the workflow entrypoints."""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any


PROTECTED_REFS = {"main", "master", "develop"}
CONTROLLED_ACTIONS = {"create", "integrate", "cleanup"}


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _is_controlled_entrypoint(tokens: list[str]) -> bool:
    if len(tokens) < 3:
        return False
    return (
        tokens[0] in {"bash", "/bin/bash"}
        and tokens[1] == "scripts/engineering/task-worktree.sh"
        and tokens[2] in CONTROLLED_ACTIONS
    )


def decision(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("tool_name") != "Bash":
        return {}
    command = payload.get("tool_input", {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return deny("Empty or malformed shell command blocked by workflow policy.")
    try:
        tokens = shlex.split(command)
    except ValueError:
        return deny("Unparseable shell command blocked by workflow policy.")
    if _is_controlled_entrypoint(tokens):
        return {}
    if not tokens:
        return deny("Empty shell command blocked by workflow policy.")
    if tokens[0] == "git":
        tail = tokens[1:]
        if "push" in tail:
            if any(flag in tail for flag in ("--force", "--force-with-lease", "-f")):
                return deny("Force push is forbidden; use the controlled task workflow.")
            if any(ref in {"main", "master", "develop"} or ref.endswith(":main") or ref.endswith(":master") or ref.endswith(":develop") for ref in tail):
                return deny("Direct protected-branch push is forbidden; use the controlled task workflow.")
        if any(action in tail for action in ("merge", "rebase", "tag")):
            return deny("Direct merge, rebase, and tag operations are forbidden by workflow policy.")
        if "worktree" in tail and "remove" in tail:
            return deny("Direct worktree removal is forbidden; use task-worktree.sh cleanup.")
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps(deny("Malformed Hook input blocked by workflow policy.")))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps(deny("Malformed Hook input blocked by workflow policy.")))
        return 0
    print(json.dumps(decision(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
