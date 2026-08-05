#!/usr/bin/env python3
"""Fail-closed local guard for destructive Git only.

Ordinary develop edit/test/commit/push is allowed. Collaboration metadata is
never consulted. Output reasons are bounded and non-secret.
"""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason[:240],
        }
    }


def decision(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("tool_name") != "Bash":
        return {}
    command = payload.get("tool_input", {}).get("command")
    if not isinstance(command, str) or not command.strip():
        return deny("Empty or malformed shell command blocked.")
    try:
        tokens = shlex.split(command)
    except ValueError:
        return deny("Unparseable shell command blocked.")
    if not tokens:
        return deny("Empty shell command blocked.")

    if tokens[0] != "git":
        return {}

    tail = tokens[1:]
    if "push" in tail and any(flag in tail for flag in ("--force", "--force-with-lease", "-f")):
        return deny("Force push is forbidden without a separate scoped execution intent.")
    if any(action in tail for action in ("filter-branch", "filter-repo")):
        return deny("History rewrite tooling is forbidden without a separate scoped execution intent.")
    if "rebase" in tail and any(flag in tail for flag in ("--onto",)):
        # Keep ordinary rebase available; block only clearly rewrite-oriented forms later if needed.
        return {}
    if len(tail) >= 2 and tail[0] == "reset" and "--hard" in tail and any(
        ref in {"main", "master", "origin/main", "origin/master"} for ref in tail
    ):
        return deny("Hard reset of protected release refs is forbidden.")
    # Direct push to develop/main is allowed in personal mode; not denied by branch alone.
    return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print(json.dumps(deny("Malformed Hook input blocked.")))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps(deny("Malformed Hook input blocked.")))
        return 0
    print(json.dumps(decision(payload)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
