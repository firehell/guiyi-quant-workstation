"""Static contracts for the lean-matrix repository skill."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "lean-matrix-ai-team"
CLI_PATH = ROOT / "scripts" / "engineering" / "lean_matrix_team.py"
CHARTER_HEADINGS = (
    "Identity",
    "Value",
    "Goal",
    "Current facts",
    "Lane and dispatch",
    "Dynamic team",
    "Allowed changes",
    "Forbidden changes",
    "Acceptance",
    "External Gates",
    "Completion flow",
)


def _read(relative_path: str) -> str:
    return (SKILL / relative_path).read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    body = markdown.split(f"## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def _parse_scalar_metadata(text: str) -> dict[str, str]:
    """Parse this skill's deliberately flat string metadata without a YAML dependency."""
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.endswith(":"):
            continue
        key, separator, raw_value = stripped.partition(": ")
        assert separator, f"invalid metadata line: {line!r}"
        metadata[key] = json.loads(raw_value) if raw_value.startswith('"') else raw_value
    return metadata


def test_required_resources_are_complete() -> None:
    """A usable skill ships every routing resource without scaffold placeholders."""
    required_paths = (
        "SKILL.md",
        "agents/openai.yaml",
        "references/roles.md",
        "references/routing.md",
        "assets/task-charter.md",
        "assets/stage-report.md",
    )

    for relative_path in required_paths:
        text = _read(relative_path)
        assert text.strip(), relative_path
        assert "TODO" not in text
        assert "TBD" not in text
        assert "[placeholder]" not in text.lower()


def test_frontmatter_and_agent_interface_are_exact() -> None:
    """Skill discovery and its user-facing invocation keep their frozen identifiers."""
    skill = _read("SKILL.md")
    frontmatter = _parse_scalar_metadata(skill.split("---", 2)[1])
    interface = _parse_scalar_metadata(_read("agents/openai.yaml"))

    assert frontmatter == {
        "name": "lean-matrix-ai-team",
        "description": (
            "Route Guiyi tasks into a minimal reviewed AI team. Use only when a user asks "
            "to use the lean matrix team, generate a Task Charter, select or route experts, "
            "coordinate implementation and independent review, or organize a Guiyi task through this model."
        ),
    }
    assert interface == {
        "display_name": "Lean Matrix AI Team",
        "short_description": "Route Guiyi tasks into a minimal reviewed AI team",
        "default_prompt": "Use $lean-matrix-ai-team to create a Task Charter and route the minimum team for this Guiyi task.",
    }


def test_roles_define_the_minimum_team_and_context_separation() -> None:
    """Removing a required independent role or combining its context must fail policy."""
    roles = _read("references/roles.md")

    for role in (
        "AI project lead",
        "Technical lead",
        "Implementer",
        "Independent quality reviewer",
        "Generic specialist overlay",
    ):
        assert role in roles
    assert "may combine with the technical lead" in roles
    assert "never final reviewer" in roles
    assert "always separate contexts" in roles
    assert "quant-research-specialist and backtest-audit-specialist use separate contexts" in roles


def test_role_prompts_preserve_required_outputs_and_boundaries() -> None:
    """Each executable role prompt must retain its design-baseline deliverables."""
    roles = _read("references/roles.md")
    requirements = {
        "AI project lead": (
            "STATUS.md", "PROJECT_SOURCE.md", "AGENTS.md", "docs/DEVELOPMENT.md",
            "task canonical", "Issue", "PR", "local-first", "single-user", "long-term maintenance",
            "Current judgment", "User value and whether to do it now", "Minimum task boundary",
            "Lane, model, Plan, sessions, and workspace", "Minimum expert team",
            "Prerequisites, risks, and acceptance", "Whether a human Gate is required",
            "Do not change the active target", "long-term goal", "formal strategy semantics",
        ),
        "Technical lead": (
            "Reuse", "Change", "Explicitly do not change", "Why no more complex architecture is needed",
            "Risks, tests, and rollback", "Lane 3 or a human Gate", "modular monolith",
            "single source of truth", "deterministic flow",
        ),
        "Implementer": (
            "independent task branch/worktree", "Task Charter", "active canonical", "allowed paths",
            "targeted tests", "TDD", "Change summary", "test commands and actual results",
            "PR and exact HEAD", "Risks and incomplete work", "external Gate",
            "Do not expand scope", "main", "Runtime", "unapproved real operation",
        ),
        "Independent quality reviewer": (
            "separate context", "exact task HEAD", "Goal and scope", "Canonical compliance",
            "Correctness and regression risk", "Test gaps", "Complexity and over-design",
            "Data, strategy, backtest, Runtime, and Gate boundaries", "Critical", "Important", "Minor",
            "Explicit verdict", "Do not lower the original acceptance criteria",
        ),
        "Generic specialist overlay": (
            "Domain constraints", "Recommended approach", "Main risks", "Required tests",
            "Forbidden scope", "Do not redefine the project", "expand the task",
            "replace the task lead's final decision",
        ),
    }

    for heading, required_phrases in requirements.items():
        section = _section(roles, heading)
        for phrase in required_phrases:
            assert phrase in section, f"{heading}: {phrase}"


def test_routing_matches_the_cli_and_limits_specialists() -> None:
    """The routing table rejects an oversized team rather than silently growing it."""
    routing = _read("references/routing.md")
    tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"), filename=str(CLI_PATH))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "DOMAIN_SPECIALISTS" for target in node.targets)
    )
    cli_mapping = ast.literal_eval(assignment.value)
    expected_mapping = {
        "product-interaction": "product-interaction-specialist",
        "frontend": "frontend-specialist",
        "data-database": "data-database-specialist",
        "quant-research": "quant-research-specialist",
        "backtest-audit": "backtest-audit-specialist",
        "research-ai": "research-ai-specialist",
        "runtime-sre": "runtime-sre-specialist",
        "security": "security-specialist",
    }

    assert cli_mapping == expected_mapping
    for domain, specialist in cli_mapping.items():
        assert f"| `{domain}` | {specialist} |" in routing
    for lane in ("Lane 1", "Lane 2", "Lane 3"):
        assert lane in routing
    assert "at most two specialists" in routing
    assert "three or more domains" in routing
    assert "split_required" in routing
    assert "Terra" in routing
    assert "Sol" in routing
    assert "plan-only-start" in routing


def test_workflow_preserves_read_only_charter_and_human_gates() -> None:
    """The skill must stop after three failed rounds and retain the human-only boundary."""
    skill = _read("SKILL.md")
    routing = _read("references/routing.md")
    combined = f"{skill}\n{routing}"

    assert "python3 scripts/engineering/lean_matrix_team.py charter --input - --format markdown" in skill
    assert "stdout-only" in skill
    assert "creates no worktree" in skill
    assert "three failed implementation-validation-review rounds" in skill
    for gate in (
        "real data/DB",
        "strategy/backtest semantics",
        "notifications",
        "live",
        "main/release/tag",
        "Runtime",
        "deletion",
        "candidate promotion",
        "GitHub rules",
    ):
        assert gate in combined


def test_templates_match_the_charter_and_stage_reporting_contracts() -> None:
    """A charter and report remain reviewable across code and external Gate states."""
    charter = _read("assets/task-charter.md")
    report = _read("assets/stage-report.md")

    assert tuple(line.removeprefix("## ") for line in charter.splitlines() if line.startswith("## ")) == CHARTER_HEADINGS
    for identity_field in (
        "Title:", "Issue:", "Task ID:", "Kind:", "Planned branch:", "Planned worktree:",
    ):
        assert identity_field in _section(charter, "Identity")

    cli_input = {
        "schema_version": 1,
        "issue_number": 97,
        "task_id": "AI-TEAM-001",
        "kind": "feature",
        "slug": "lean-matrix-team",
        "title": "Render a charter",
        "value": "Keep routing deterministic.",
        "goal": "Render one Task Charter.",
        "current_facts": ["Current policy exists."],
        "lane": 2,
        "domains": [],
        "allowed_paths": ["scripts/engineering/lean_matrix_team.py"],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["The Charter renders."],
        "external_gates": [],
    }
    rendered = subprocess.run(
        [sys.executable, str(CLI_PATH), "charter", "--input", "-", "--format", "markdown"],
        input=json.dumps(cli_input),
        text=True,
        capture_output=True,
        check=False,
    )

    assert rendered.returncode == 0, rendered.stderr
    assert tuple(
        line.removeprefix("## ") for line in rendered.stdout.splitlines() if line.startswith("## ")
    ) == CHARTER_HEADINGS[1:]
    for identity_field in (
        "Title:", "Issue:", "Task ID:", "Kind:", "Planned branch:", "Planned worktree:",
    ):
        assert identity_field in rendered.stdout.split("## Value", 1)[0]
    for section in (
        "Current status",
        "Completed",
        "Verification evidence",
        "Remaining risks",
        "User action required",
        "Automatic next step",
    ):
        assert f"## {section}" in report
    for distinction in ("Code", "Tests", "CI", "Independent review", "Real Gate", "Release", "Runtime"):
        assert distinction in report


def test_skill_does_not_claim_control_plane_or_gatekeeper_authority() -> None:
    """Skill guidance cannot replace repository canon or claim forbidden state changes."""
    combined = "\n".join(_read(path) for path in (
        "SKILL.md",
        "references/roles.md",
        "references/routing.md",
        "assets/task-charter.md",
        "assets/stage-report.md",
    ))

    assert "does not replace canonical sources or Gatekeepers" in combined
    for statement in (
        "does not merge main",
        "does not promote Runtime",
        "does not write real data",
        "does not send real notifications",
    ):
        assert statement in combined
