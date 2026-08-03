"""Static contracts for the lean-matrix repository skill."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents" / "skills" / "lean-matrix-ai-team"
ENGINEERING = ROOT / "scripts" / "engineering"
PROTOCOL_RESOURCES = (
    "assets/role-brief.md",
    "assets/handoff-report.md",
    "assets/review-package.md",
    "assets/final-decision.md",
    "references/execution.md",
    "references/review.md",
    "references/recovery.md",
)
PROTOCOL_TEMPLATE_FIELDS = {
    "assets/role-brief.md": (
        "schema_version", "intake_digest", "execution_plan_digest", "role",
        "specialist_domain", "context_id", "implementer_context_id",
        "reviewer_context_id", "original_implementer_context_id", "specialist_contexts",
        "round", "selected_context", "trusted_allowed_paths", "trusted_forbidden_paths",
        "acceptance_criteria", "report_path", "predecessor_decision_digest",
    ),
    "assets/handoff-report.md": (
        "schema_version", "report_kind", "specialist_domain", "intake_digest",
        "brief_digest", "context_id", "round", "report_path", "exact_head_sha",
        "changed_paths", "test_evidence", "advisory_evidence_digests", "status",
        "concerns", "predecessor_decision_digest",
    ),
    "assets/review-package.md": None,
    "assets/final-decision.md": (
        "schema_version", "review_package_digest", "exact_head_sha", "implementer_context_id",
        "reviewer_context_id", "round", "spec_verdict", "quality_verdict", "findings", "decision",
    ),
}
INTAKE_WORKSPACE_PATH = ".ai/lean-matrix/<execution-plan-digest>/<intake-digest>/"
REVIEW_LEDGER_PATH = f"{INTAKE_WORKSPACE_PATH}review-ledger.json"


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
        *PROTOCOL_RESOURCES,
    )

    for relative_path in required_paths:
        text = _read(relative_path)
        assert text.strip(), relative_path
        assert "TODO" not in text
        assert "TBD" not in text
        assert "[placeholder]" not in text.lower()

    assert {path.name for path in (SKILL / "assets").glob("*.md")} == {
        "role-brief.md", "handoff-report.md", "review-package.md", "final-decision.md",
    }


def test_frontmatter_and_agent_interface_are_exact() -> None:
    """Skill discovery and its user-facing invocation keep their frozen identifiers."""
    skill = _read("SKILL.md")
    frontmatter = _parse_scalar_metadata(skill.split("---", 2)[1])
    interface = _parse_scalar_metadata(_read("agents/openai.yaml"))

    assert frontmatter == {
        "name": "lean-matrix-ai-team",
        "description": (
            "Lead user-started Guiyi AI delivery from approved design and implementation plans "
            "through minimal implementation, independent exact-head review, and evidence handoff. "
            "Use only when the user explicitly asks to start or continue Lean Matrix AI delivery."
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
        "AI delivery lead",
        "Implementer",
        "Independent reviewer",
        "Specialist",
    ):
        assert role in roles
    assert "AI project lead" not in roles
    assert "Technical lead" not in roles
    assert "sole global delivery role" in roles
    assert "globally disjoint" in roles
    assert "quant-research and backtest-audit use separate contexts" in roles


def test_role_prompts_preserve_required_outputs_and_boundaries() -> None:
    """Each executable role prompt must retain its design-baseline deliverables."""
    roles = _read("references/roles.md")
    requirements = {
        "AI delivery lead": (
            "approved design spec", "approved implementation plan", "trusted ExecutionPlanV1",
            "minimum team", "Lane 1/2", "Lane 3", "product-direction change",
            "active-canonical conflict", "scope expansion", "Owner Gate",
            "does not implement code", "does not review its own implementation",
        ),
        "Implementer": (
            "RoleBriefV1", "HandoffReportV1", "TDD", "exact HEAD", "test receipts",
            "trusted allowed paths", "trusted forbidden paths", "original round-zero context",
            "does not widen scope", "Runtime", "real operation",
        ),
        "Independent reviewer": (
            "separate context", "ReviewPackageV1", "exact HEAD", "Spec", "Quality",
            "Critical", "Important", "Minor", "read-only", "do not fix code",
            "do not lower acceptance",
        ),
        "Specialist": (
            "RoleBriefV1", "advisory", "specialist domain", "test receipts",
            "does not implement task code", "does not replace the independent reviewer",
        ),
    }

    for heading, required_phrases in requirements.items():
        section = _section(roles, heading)
        for phrase in required_phrases:
            assert phrase in section, f"{heading}: {phrase}"


def test_routing_matches_the_cli_and_limits_specialists() -> None:
    """The routing table rejects an oversized team rather than silently growing it."""
    routing = _read("references/routing.md")
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.routing import DOMAIN_SPECIALISTS as cli_mapping
    finally:
        sys.path.pop(0)
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
    assert "AI delivery lead" in routing
    assert "implementer" in routing
    assert "independent reviewer" in routing
    assert "four base roles" not in routing


def test_workflow_preserves_existing_flow_and_v06_owner_gate_boundaries() -> None:
    """V06 starts from approved documents and cannot widen product or runtime authority."""
    skill = _read("SKILL.md")
    routing = _read("references/routing.md")
    combined = f"{skill}\n{routing}"

    assert "python3 scripts/engineering/lean_matrix_team.py charter --input - --format markdown" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py plan --charter - --format markdown" in skill
    assert "stdout-only" in skill
    assert "creates no worktree" in skill
    assert "git -c core.fsmonitor=false rev-parse --verify origin/develop^{commit}" in skill
    assert "GIT_OPTIONAL_LOCKS=0" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py observe --plan" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py next --plan" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py apply" in skill
    assert "--expected-transition" in skill
    assert "--expected-state-digest" in skill
    assert "explicit `--apply`" in skill
    assert ".ai/lean-matrix/<plan-digest>/" in skill
    assert "Lane 3" in skill
    assert "AI-TEAM-007" in skill
    assert "one transition" in skill
    assert "does not fetch" in skill
    assert "does not call GitHub" in skill
    assert "three failed implementation-validation-review rounds" in skill
    for phrase in (
        "user explicitly starts AI delivery",
        "AI delivery lead",
        "approved design spec",
        "approved implementation plan",
        "Lane 1/2 Charter freezes automatically",
        "Lane 3",
        "product-direction change",
        "active-canonical conflict",
        "scope expansion",
        "exact-head decision",
        "existing Codex/GitHub flow",
        "merge commit",
        "V06 performs no network, PR, CI polling, merge, or Runtime operation",
    ):
        assert phrase in combined
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


def test_subagent_templates_match_the_strict_json_contract_fields() -> None:
    """Removing or inventing a template field must fail before an agent writes invalid evidence."""
    for relative_path, expected_fields in PROTOCOL_TEMPLATE_FIELDS.items():
        headings = tuple(
            line.removeprefix("## ")
            for line in _read(relative_path).splitlines()
            if line.startswith("## ")
        )
        if expected_fields is None:
            sys.path.insert(0, str(ENGINEERING))
            try:
                from lean_matrix.contracts import ReviewPackageV1
            finally:
                sys.path.pop(0)
            assert len(headings) == len(ReviewPackageV1.KEYS), relative_path
            assert set(headings) == ReviewPackageV1.KEYS, relative_path
        else:
            assert headings == expected_fields, relative_path


def test_subagent_protocol_links_execution_review_recovery_and_frozen_boundaries() -> None:
    """The Skill must expose the executable protocol without claiming new controller authority."""
    skill = _read("SKILL.md")
    execution = _read("references/execution.md")
    review = _read("references/review.md")
    recovery = _read("references/recovery.md")
    combined = "\n".join((skill, execution, review, recovery))

    for resource in PROTOCOL_RESOURCES:
        assert resource in skill
    assert "python3 scripts/engineering/lean_matrix_team.py intake" in skill
    assert "--approved-plan" in skill
    assert "--intake" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py brief" in skill
    assert "--role implementer" in skill
    assert "--context-id" in skill
    assert "--implementer-context-id" in skill
    assert "--reviewer-context-id" in skill
    assert "--round 0" in skill
    assert "--output" in skill
    assert "--role specialist" in skill
    assert "--specialist-domain" in skill
    assert "--specialist-context" in skill
    assert "--context-id <specialist-context>" in skill
    assert "Use this complete specialist command; do not append specialist flags" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py review-package" in skill
    assert "--implementer-brief" in skill
    assert "--implementer-handoff" in skill
    assert "--reviewer-brief" in skill
    assert "python3 scripts/engineering/lean_matrix_team.py decision" in skill
    assert "direct-written" in combined
    assert "read-only" in combined
    assert "round 0" in combined
    assert "rounds 1, 2, and 3" in combined
    assert "No fourth round" in combined
    assert "at most two specialists" in combined
    assert "Spec `PASS/FAIL`" in combined
    assert "Quality `APPROVED/CHANGES_REQUIRED`" in combined
    for severity in ("Critical", "Important", "Minor"):
        assert severity in review
    assert "never selects evidence by modification time" in recovery
    assert "reconstructed from Git/PR facts" in recovery
    for boundary in (
        "no daemon",
        "no Codex App API wrapper",
        "no GitHub integration",
        "no V06 network or merge implementation",
        "no Runtime authority",
        "no data/DB write authority",
        "no notification authority",
        "no release authority",
        "no trading authority",
    ):
        assert boundary in combined


def test_subagent_protocol_documents_brief_bound_roles_and_full_ledger_recovery() -> None:
    """The written protocol must not permit role swaps or advisory/implementer ambiguity."""
    skill = _read("SKILL.md")
    execution = _read("references/execution.md")
    review = _read("references/review.md")
    recovery = _read("references/recovery.md")
    role_brief = _read("assets/role-brief.md")
    handoff_report = _read("assets/handoff-report.md")
    review_package = _read("assets/review-package.md")
    combined = " ".join(
        "\n".join(
            (skill, execution, review, recovery, role_brief, handoff_report, review_package)
        ).split()
    )

    for phrase in (
        "round-zero implementer context",
        "globally disjoint",
        "handoffs/specialists/<domain>/<context-id>/round-0/handoff-report.json",
        "exactly one brief-bound implementer handoff per round",
        "specialist domain, context, brief digest, and test receipts",
        "specialist evidence digests",
        "recomputes Git facts and artifact bindings",
    ):
        assert phrase in combined


def test_review_protocol_documents_the_executable_ledger_contract() -> None:
    """A controller following the public protocol must write exactly where the loader reads."""
    skill = _read("SKILL.md")
    execution = _read("references/execution.md")
    review = _read("references/review.md")
    recovery = _read("references/recovery.md")
    package_template = _read("assets/review-package.md")
    decision_template = _read("assets/final-decision.md")

    for protocol in (skill, execution, review, recovery):
        assert INTAKE_WORKSPACE_PATH in protocol
    assert REVIEW_LEDGER_PATH in recovery
    assert "review-package.json" in package_template
    assert "final-decision.json" in decision_template
    combined = "\n".join(
        (skill, execution, review, recovery, package_template, decision_template)
    )
    assert "validates package digest, exact HEAD, and implementer/reviewer contexts" in combined
    assert "fixed derived paths" in combined
    assert "never uses a caller-supplied recovery path" in combined
    for phrase in (
        '"schema_version": 1',
        '"intake_digest": "sha256:..."',
        '"rounds"',
        '"implementer_brief"',
        '"implementer_handoff"',
        '"reviewer_brief"',
        '"review_package"',
        '"final_decision"',
        '"specialist_evidence"',
        '"path": "<repo-relative-path>"',
        '"digest": "sha256:..."',
        "AI delivery lead writes",
        "after each final decision",
        "recover_review_ledger(repo_root, intake, ledger_path, round_zero_brief=round_zero_brief)",
        "conversation_memory",
    ):
        assert phrase in recovery


def test_skill_does_not_claim_control_plane_or_gatekeeper_authority() -> None:
    """Skill guidance cannot replace repository canon or claim forbidden state changes."""
    combined = "\n".join(_read(path) for path in (
        "SKILL.md",
        "references/roles.md",
        "references/routing.md",
        "references/execution.md",
        "references/review.md",
        "references/recovery.md",
    ))
    lowered = combined.lower()

    assert "does not replace canonical sources or Gatekeepers" in combined
    for statement in (
        "does not merge main",
        "does not promote Runtime",
        "does not write real data",
        "does not send real notifications",
    ):
        assert statement in combined
    for forbidden_affirmative in (
        "merges main",
        "promotes runtime",
        "writes real data",
        "sends real notifications",
        "this report can satisfy",
        "this report authorizes",
        "this report drives a gate",
        "this report can drive a gate",
        "this report replaces a gate",
        "this report can replace a gate",
    ):
        assert forbidden_affirmative not in lowered


def test_v07_skill_exposes_only_the_pure_three_stage_develop_gate() -> None:
    """Removing one staged re-evaluation or adding controller authority must fail policy."""
    skill = _read("SKILL.md")
    execution = _read("references/execution.md")
    review = _read("references/review.md")
    recovery = _read("references/recovery.md")
    combined = "\n".join((skill, execution, review, recovery))

    assert "## V07 develop Gate evaluator" in skill
    assert (
        "python3 scripts/engineering/lean_matrix_team.py develop-gate "
        "--plan <approved-execution-plan.json> --facts <github-gate-facts.json> --format json"
    ) in skill
    for contract in (
        "GitHubCheckV1",
        "GitHubReviewEvidenceV1",
        "GitHubGateFactsV1",
        "DevelopGateDecisionV1",
    ):
        assert contract in combined
    for stage in ("pre_merge", "merge_readback", "cleanup"):
        assert f"`{stage}`" in combined
    for category in ("code", "test", "dry_run", "disabled_feature", "isolated_migration"):
        assert f"`{category}`" in combined
    assert "exactly five minutes" in combined
    assert "strict base drift" in combined
    assert "change_categories=()" in combined
    assert "four positional arguments" in combined
    assert "pure evaluator" in combined


def test_v07_skill_keeps_connector_mutations_receipt_and_cleanup_outside_harness() -> None:
    """An operator must re-read exact-head facts and never infer a timed-out merge result."""
    skill = _read("SKILL.md")
    execution = _read("references/execution.md")
    review = _read("references/review.md")
    recovery = _read("references/recovery.md")
    combined = "\n".join((skill, execution, review, recovery))

    for phrase in (
        "Connector/Codex owns",
        "ready transition",
        "re-read",
        "expected head SHA",
        "must not retry",
        "digest-bound merge receipt",
        "separate cleanup transition",
        "no repository GitHub client",
        "no `gh`",
        "no token",
        "no poller",
        "no merge daemon",
        "AI-TEAM-007 self-bootstrap",
        "existing Connector/Codex flow",
    ):
        assert phrase in combined
    for manual_gate in (
        "main/release/tag",
        "Runtime",
        "real data/DB",
        "strategy/backtest semantics",
        "notifications",
        "live",
        "deletion",
        "candidate promotion",
        "GitHub rules",
    ):
        assert manual_gate in combined
