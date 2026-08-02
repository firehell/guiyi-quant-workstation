"""Behavior contracts for the modular Lean Matrix kernel."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"


def _charter() -> dict[str, object]:
    return {
        "schema_version": 1,
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "value": "Keep later orchestration deterministic.",
        "goal": "Render one execution plan.",
        "current_facts": ["The Charter contract is frozen."],
        "lane": 2,
        "domains": [],
        "allowed_paths": ["scripts/engineering/lean_matrix/"],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["Contracts serialize deterministically."],
        "external_gates": [],
    }


def test_modular_charter_renderer_preserves_the_public_payload() -> None:
    """Moving the renderer behind modules cannot change its consumer-visible JSON."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.charter import render_charter
    finally:
        sys.path.pop(0)

    rendered = render_charter(_charter())

    assert rendered["schema_version"] == 1
    assert rendered["status"] == "ok"
    assert rendered["task"] == {
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "branch": "feature/AI-TEAM-004-execution-contracts",
        "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-004-execution-contracts",
    }
    assert rendered["dispatch"] == {
        "model": "Terra",
        "reasoning_effort": "medium",
        "mode": "plan-then-execute",
        "session_count": 3,
        "roles": [
            "ai-project-lead",
            "technical-lead",
            "implementer",
            "independent-quality-reviewer",
        ],
        "specialists": [],
        "independence_requirements": [
            "implementer and independent-quality-reviewer use separate contexts",
        ],
    }
    assert rendered["charter_markdown"].startswith("# Task Charter\n")
