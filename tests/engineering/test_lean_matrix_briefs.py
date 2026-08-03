"""Document-intake scoped role briefs, handoffs, and workspace boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"
CLI = ENGINEERING / "lean_matrix_team.py"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(tmp_path: Path, *, copy_cli: bool = False) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    if copy_cli:
        target = repo / "scripts" / "engineering"
        target.mkdir(parents=True)
        shutil.copy2(CLI, target / CLI.name)
        shutil.copy2(ENGINEERING / "task_workflow.py", target / "task_workflow.py")
        shutil.copytree(
            ENGINEERING / "lean_matrix",
            target / "lean_matrix",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    _write(repo / ".gitignore", ".ai/\n__pycache__/\n")
    _write(repo / "docs/design.md", "approved design\nFULL_HISTORICAL_PLAN_SENTINEL\n")
    _write(repo / "docs/plan.md", "approved implementation plan\nUNRELATED_WORK_ITEM_SENTINEL\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "briefs@example.invalid")
    _git(repo, "config", "user.name", "Brief Tests")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", base_sha)
    return repo, base_sha


def _execution_payload(base_sha: str, *, specialists: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "ok",
        "charter_digest": "sha256:" + "0" * 64,
        "task": {
            "issue_number": 111,
            "task_id": "AI-TEAM-006-BRIEFS",
            "branch": "feature/AI-TEAM-006-briefs",
            "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-006-briefs",
        },
        "base": {"ref": "origin/develop", "expected_sha": base_sha},
        "dispatch": {
            "model": "Sol",
            "reasoning_effort": "high",
            "roles": ["implementer", "reviewer"],
            "specialists": specialists or [],
            "independence_requirements": ["FULL_CHAT_SENTINEL", "separate contexts"],
        },
        "scope": {
            "allowed_paths": ["scripts/engineering/lean_matrix/**"],
            "forbidden_paths": ["data/**", "services/**"],
        },
        "validation": {
            "test_profile": "engineering",
            "required_checks": ["pytest focused", "git diff --check"],
        },
        "transitions": ["FULL_HISTORICAL_PLAN_SENTINEL"],
        "external_gates": ["UNRELATED_WORK_ITEM_SENTINEL"],
    }


def _intake(repo: Path, base_sha: str, *, specialists: list[str] | None = None):
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import DocumentIntakeV1, ExecutionPlanV1
    finally:
        sys.path.pop(0)
    execution = ExecutionPlanV1.from_mapping(_execution_payload(base_sha, specialists=specialists))
    payload = {
        "schema_version": 1,
        "design_path": "docs/design.md",
        "design_digest": "sha256:" + hashlib.sha256((repo / "docs/design.md").read_bytes()).hexdigest(),
        "implementation_plan_path": "docs/plan.md",
        "implementation_plan_digest": "sha256:" + hashlib.sha256((repo / "docs/plan.md").read_bytes()).hexdigest(),
        "execution_plan_digest": _digest(execution.to_dict()),
        "execution_plan": execution.to_dict(),
        "delivery_mode": "team_path",
        "task_id": execution.task.task_id,
        "develop_ref": "origin/develop",
        "develop_sha": base_sha,
    }
    intake = DocumentIntakeV1.from_mapping(
        payload, repo_root=repo, approved_execution_plan=execution,
    )
    return intake, payload, execution


def _imports():
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.briefs import build_role_brief
        from lean_matrix.contracts import HandoffReportV1, RoleBriefV1
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.workspace import intake_workspace, write_role_brief_files
    finally:
        sys.path.pop(0)
    return build_role_brief, HandoffReportV1, RoleBriefV1, LeanMatrixError, intake_workspace, write_role_brief_files


def _brief(
    intake,
    *,
    role: str = "implementer",
    context_id: str = "implementer-alpha",
    specialist_domain: str | None = None,
    specialist_contexts: dict[str, str] | None = None,
    round_number: int = 0,
    original_implementer_context_id: str = "implementer-alpha",
    predecessor_decision_digest: str | None = None,
    round_zero_brief=None,
):
    build_role_brief, *_ = _imports()
    if round_number and round_zero_brief is None:
        round_zero_brief = _brief(
            intake,
            specialist_contexts=specialist_contexts or {},
        )
    return build_role_brief(
        intake,
        role=role,
        context_id=context_id,
        implementer_context_id=(
            context_id if role == "implementer" else "implementer-alpha"
        ),
        reviewer_context_id="reviewer-alpha",
        specialist_domain=specialist_domain,
        specialist_contexts=specialist_contexts or {},
        round_number=round_number,
        original_implementer_context_id=original_implementer_context_id,
        predecessor_decision_digest=predecessor_decision_digest,
        round_zero_brief=round_zero_brief,
    )


def test_brief_exposes_only_role_minimum_and_trusted_task_contract(tmp_path: Path) -> None:
    """Copying full dispatch/history/document prose into an implementer brief is a leak."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    brief = _brief(intake)
    serialized = json.dumps(brief.to_dict(), ensure_ascii=False, sort_keys=True)

    assert brief.role == "implementer"
    assert brief.trusted_allowed_paths == ("scripts/engineering/lean_matrix/**",)
    assert brief.trusted_forbidden_paths == ("data/**", "services/**")
    assert brief.acceptance_criteria == ("pytest focused", "git diff --check")
    assert intake.task_id in serialized
    for sentinel in (
        "FULL_CHAT_SENTINEL",
        "FULL_HISTORICAL_PLAN_SENTINEL",
        "UNRELATED_WORK_ITEM_SENTINEL",
        "approved design",
        "approved implementation plan",
    ):
        assert sentinel not in serialized


def test_role_brief_trusted_scope_requires_the_bound_intake(tmp_path: Path) -> None:
    """A self-described scope must not become trusted without its intake provenance anchor."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    brief = _brief(intake)
    _, _, RoleBriefV1, LeanMatrixError, *_ = _imports()
    payload = brief.to_dict()
    payload["trusted_allowed_paths"] = ["services/**"]

    with pytest.raises(TypeError):
        RoleBriefV1.from_mapping(payload)
    with pytest.raises(LeanMatrixError) as raised:
        RoleBriefV1.from_mapping(payload, document_intake=intake)
    assert raised.value.error_type == "brief_intake_mismatch"
    with pytest.raises(TypeError):
        RoleBriefV1(**brief.to_dict())


@pytest.mark.parametrize("mutation", ["same_context", "same_report_path"])
def test_implementer_and_reviewer_identity_and_report_provenance_are_separate(
    tmp_path: Path, mutation: str,
) -> None:
    """Sharing either identity or output provenance destroys independent review."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    build_role_brief, _, RoleBriefV1, LeanMatrixError, *_ = _imports()

    if mutation == "same_context":
        with pytest.raises(LeanMatrixError, match="implementer and reviewer") as raised:
            build_role_brief(
                intake,
                role="implementer",
                context_id="shared-context",
                implementer_context_id="shared-context",
                reviewer_context_id="shared-context",
                specialist_contexts={},
                round_number=0,
                original_implementer_context_id="shared-context",
            )
        assert raised.value.error_type == "role_identity_collision"
    else:
        implementer = _brief(intake)
        reviewer = _brief(intake, role="reviewer", context_id="reviewer-alpha")
        payload = reviewer.to_dict()
        payload["report_path"] = implementer.report_path
        with pytest.raises(LeanMatrixError) as raised:
            RoleBriefV1.from_mapping(payload, document_intake=intake)
        assert raised.value.error_type == "brief_report_path_mismatch"


def test_specialist_identity_context_and_report_are_digest_bound(tmp_path: Path) -> None:
    """A specialist report must not be reusable under another domain or context."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha, specialists=["testing"])
    contexts = {"testing": "testing-specialist"}
    brief = _brief(
        intake,
        role="specialist",
        context_id="testing-specialist",
        specialist_domain="testing",
        specialist_contexts=contexts,
    )
    _, HandoffReportV1, _, LeanMatrixError, *_ = _imports()
    payload = {
        "schema_version": 1,
        "report_kind": "specialist",
        "specialist_domain": "testing",
        "intake_digest": brief.intake_digest,
        "brief_digest": _digest(brief.to_dict()),
        "context_id": brief.context_id,
        "round": 0,
        "report_path": brief.report_path,
        "exact_head_sha": base_sha,
        "changed_paths": [],
        "test_evidence": ["advisory inspection complete"],
        "advisory_evidence_digests": [],
        "status": "DONE_WITH_CONCERNS",
        "concerns": ["advisory only"],
        "predecessor_decision_digest": None,
    }
    report = HandoffReportV1.from_mapping(payload, role_brief=brief)
    assert report.specialist_domain == "testing"

    payload["context_id"] = "another-specialist"
    with pytest.raises(LeanMatrixError) as raised:
        HandoffReportV1.from_mapping(payload, role_brief=brief)
    assert raised.value.error_type == "handoff_brief_mismatch"


@pytest.mark.parametrize("specialists", [[], ["testing"], ["testing", "security"]])
def test_zero_to_two_specialists_are_supported(tmp_path: Path, specialists: list[str]) -> None:
    """The declared specialist cardinality from the trusted plan must be honored exactly."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha, specialists=specialists)
    contexts = {domain: f"{domain}-context" for domain in specialists}
    implementer = _brief(intake, specialist_contexts=contexts)
    assert implementer.specialist_context_ids == tuple(contexts.values())


def test_third_distinct_specialist_domain_requires_split(tmp_path: Path) -> None:
    """Allowing three domains would silently exceed the frozen team shape."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha, specialists=["testing", "security", "docs"])
    _, _, _, LeanMatrixError, *_ = _imports()
    with pytest.raises(LeanMatrixError) as raised:
        _brief(
            intake,
            specialist_contexts={
                "testing": "testing-context",
                "security": "security-context",
                "docs": "docs-context",
            },
        )
    assert raised.value.error_type == "split_required"


def test_quant_research_and_backtest_audit_never_share_context_or_report(tmp_path: Path) -> None:
    """Collapsing research and audit into one specialist defeats their independent evidence."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha, specialists=["quant-research", "backtest-audit"])
    _, _, _, LeanMatrixError, *_ = _imports()
    with pytest.raises(LeanMatrixError) as raised:
        _brief(
            intake,
            specialist_contexts={
                "quant-research": "shared-specialist",
                "backtest-audit": "shared-specialist",
            },
        )
    assert raised.value.error_type == "specialist_identity_collision"

    contexts = {
        "quant-research": "quant-context",
        "backtest-audit": "audit-context",
    }
    quant = _brief(
        intake,
        role="specialist",
        context_id="quant-context",
        specialist_domain="quant-research",
        specialist_contexts=contexts,
    )
    audit = _brief(
        intake,
        role="specialist",
        context_id="audit-context",
        specialist_domain="backtest-audit",
        specialist_contexts=contexts,
    )
    assert quant.context_id != audit.context_id
    assert quant.report_path != audit.report_path


def test_quant_research_context_cannot_be_cross_swapped_to_audit(tmp_path: Path) -> None:
    """A domain must remain bound to its exact context, not merely any roster member."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha, specialists=["quant-research", "backtest-audit"])
    contexts = {
        "quant-research": "quant-context",
        "backtest-audit": "audit-context",
    }
    quant = _brief(
        intake,
        role="specialist",
        context_id="quant-context",
        specialist_domain="quant-research",
        specialist_contexts=contexts,
    )
    _, _, RoleBriefV1, LeanMatrixError, *_ = _imports()
    payload = quant.to_dict()
    payload["context_id"] = "audit-context"
    payload["report_path"] = payload["report_path"].replace("quant-context", "audit-context")

    with pytest.raises(LeanMatrixError) as raised:
        RoleBriefV1.from_mapping(payload, document_intake=intake)
    assert raised.value.error_type == "specialist_context_mismatch"


def test_handoff_status_is_fixed_and_repair_reuses_original_implementer(tmp_path: Path) -> None:
    """A repair must not swap implementers or invent a fifth success status."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    _, HandoffReportV1, _, LeanMatrixError, *_ = _imports()
    predecessor = "sha256:" + "9" * 64
    repair = _brief(
        intake,
        round_number=1,
        predecessor_decision_digest=predecessor,
    )
    payload = {
        "schema_version": 1,
        "report_kind": "implementer",
        "specialist_domain": None,
        "intake_digest": repair.intake_digest,
        "brief_digest": _digest(repair.to_dict()),
        "context_id": repair.context_id,
        "round": 1,
        "report_path": repair.report_path,
        "exact_head_sha": base_sha,
        "changed_paths": ["scripts/engineering/lean_matrix/briefs.py"],
        "test_evidence": ["pytest focused: passed"],
        "advisory_evidence_digests": [],
        "status": "DONE",
        "concerns": [],
        "predecessor_decision_digest": predecessor,
    }
    assert HandoffReportV1.from_mapping(payload, role_brief=repair).status == "DONE"

    payload["status"] = "COMPLETE"
    with pytest.raises(LeanMatrixError) as raised:
        HandoffReportV1.from_mapping(payload, role_brief=repair)
    assert raised.value.error_type == "invalid_status"

    with pytest.raises(LeanMatrixError) as raised:
        _brief(
            intake,
            context_id="replacement-implementer",
            round_number=1,
            original_implementer_context_id="implementer-alpha",
            predecessor_decision_digest=predecessor,
        )
    assert raised.value.error_type == "implementer_context_changed"


def test_repair_rejects_consistent_replacement_against_round_zero_anchor(tmp_path: Path) -> None:
    """Self-consistent current fields cannot replace the independently frozen implementer."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    original = _brief(intake)
    build_role_brief, _, _, LeanMatrixError, *_ = _imports()

    with pytest.raises(LeanMatrixError) as raised:
        build_role_brief(
            intake,
            role="implementer",
            context_id="replacement-context",
            implementer_context_id="replacement-context",
            reviewer_context_id="reviewer-alpha",
            specialist_contexts={},
            round_number=1,
            original_implementer_context_id="replacement-context",
            predecessor_decision_digest="sha256:" + "8" * 64,
            round_zero_brief=original,
        )
    assert raised.value.error_type == "implementer_context_changed"


def test_handoff_direct_constructor_and_unanchored_loader_are_closed(tmp_path: Path) -> None:
    """Every handoff instance must have passed fixed-status and trusted-brief validation."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    brief = _brief(intake)
    _, HandoffReportV1, _, _, *_ = _imports()
    invalid = {
        "schema_version": 1,
        "report_kind": "bogus",
        "specialist_domain": None,
        "intake_digest": brief.intake_digest,
        "brief_digest": "sha256:" + "7" * 64,
        "context_id": brief.context_id,
        "round": 99,
        "report_path": "../canonical.json",
        "exact_head_sha": base_sha,
        "changed_paths": [],
        "test_evidence": [],
        "advisory_evidence_digests": [],
        "status": "COMPLETE",
        "concerns": [],
        "predecessor_decision_digest": None,
    }
    with pytest.raises(TypeError):
        HandoffReportV1(**invalid)
    with pytest.raises(TypeError):
        HandoffReportV1.from_mapping(invalid)


@pytest.mark.parametrize("mutation", ["wrong_output", "traversal", "symlink", "tracked_workspace"])
def test_workspace_is_exact_ignored_noncanonical_and_symlink_safe(
    tmp_path: Path, mutation: str,
) -> None:
    """Brief writes outside the exact ignored intake workspace must fail closed."""
    repo, base_sha = _repo(tmp_path)
    intake, _, _ = _intake(repo, base_sha)
    brief = _brief(intake)
    _, _, _, LeanMatrixError, intake_workspace, write_role_brief_files = _imports()
    workspace = intake_workspace(repo, intake)
    output = workspace
    if mutation == "wrong_output":
        output = repo / "docs"
    elif mutation == "traversal":
        output = workspace / ".." / workspace.name
    elif mutation == "symlink":
        (repo / ".ai").mkdir()
        target = repo / "ignored-target"
        target.mkdir()
        (repo / ".ai" / "lean-matrix").symlink_to(target, target_is_directory=True)
    else:
        workspace.mkdir(parents=True)
        _write(workspace / "canonical.txt", "tracked canonical\n")
        _git(repo, "add", "-f", workspace.relative_to(repo).as_posix())

    with pytest.raises(LeanMatrixError) as raised:
        write_role_brief_files(repo, intake, brief, output)
    assert raised.value.error_type in {
        "brief_output_mismatch",
        "invalid_workspace_path",
        "workspace_symlink_forbidden",
        "canonical_workspace_conflict",
    }


def test_intake_and_brief_cli_use_new_public_contracts(tmp_path: Path) -> None:
    """The CLI must not require retired coordination/work-item vocabulary."""
    repo, base_sha = _repo(tmp_path, copy_cli=True)
    _, intake_payload, execution = _intake(repo, base_sha)
    intake_path = tmp_path / "intake.json"
    plan_path = tmp_path / "approved-plan.json"
    _write(intake_path, json.dumps(intake_payload))
    _write(plan_path, json.dumps(execution.to_dict()))

    intake_result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/engineering/lean_matrix_team.py"),
            "intake",
            "--input", str(intake_path),
            "--approved-plan", str(plan_path),
            "--format", "json",
        ],
        cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert intake_result.returncode == 0, intake_result.stderr
    assert json.loads(intake_result.stdout)["task_id"] == execution.task.task_id

    plan_digest = _digest(execution.to_dict()).removeprefix("sha256:")
    intake_digest = _digest(intake_payload).removeprefix("sha256:")
    workspace = repo / ".ai" / "lean-matrix" / plan_digest / intake_digest
    brief_result = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/engineering/lean_matrix_team.py"),
            "brief",
            "--intake", str(intake_path),
            "--approved-plan", str(plan_path),
            "--role", "implementer",
            "--context-id", "implementer-alpha",
            "--implementer-context-id", "implementer-alpha",
            "--reviewer-context-id", "reviewer-alpha",
            "--original-implementer-context-id", "implementer-alpha",
            "--output", str(workspace),
        ],
        cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert brief_result.returncode == 0, brief_result.stderr
    output = json.loads(brief_result.stdout)
    role_brief = json.loads((repo / output["json_path"]).read_text(encoding="utf-8"))
    assert role_brief["intake_digest"] == "sha256:" + intake_digest
    assert "coordination_digest" not in role_brief
    assert "work_item_id" not in role_brief


def test_repair_cli_uses_fixed_round_zero_anchor_not_original_id_argument(tmp_path: Path) -> None:
    """A valid repair loads the frozen identity; a consistently replaced identity is blocked."""
    repo, base_sha = _repo(tmp_path, copy_cli=True)
    _, intake_payload, execution = _intake(repo, base_sha)
    intake_path = tmp_path / "intake.json"
    plan_path = tmp_path / "approved-plan.json"
    _write(intake_path, json.dumps(intake_payload))
    _write(plan_path, json.dumps(execution.to_dict()))
    workspace = (
        repo
        / ".ai"
        / "lean-matrix"
        / _digest(execution.to_dict()).removeprefix("sha256:")
        / _digest(intake_payload).removeprefix("sha256:")
    )

    def run_brief(*extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(repo / "scripts/engineering/lean_matrix_team.py"),
                "brief",
                "--intake", str(intake_path),
                "--approved-plan", str(plan_path),
                "--role", "implementer",
                "--reviewer-context-id", "reviewer-alpha",
                "--output", str(workspace),
                *extra,
            ],
            cwd=repo,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=False,
        )

    initial = run_brief(
        "--context-id", "implementer-alpha",
        "--implementer-context-id", "implementer-alpha",
        "--original-implementer-context-id", "implementer-alpha",
    )
    assert initial.returncode == 0, initial.stderr

    repaired = run_brief(
        "--context-id", "implementer-alpha",
        "--implementer-context-id", "implementer-alpha",
        "--round", "1",
        "--predecessor-decision-digest", "sha256:" + "6" * 64,
    )
    assert repaired.returncode == 0, repaired.stderr

    replacement = run_brief(
        "--context-id", "replacement-context",
        "--implementer-context-id", "replacement-context",
        "--round", "1",
        "--predecessor-decision-digest", "sha256:" + "6" * 64,
    )
    assert replacement.returncode == 2
    assert json.loads(replacement.stderr)["error_type"] == "implementer_context_changed"


def test_retired_task2_report_name_is_not_public() -> None:
    """Leaving WorkReportV1 public would preserve a second active V1 vocabulary."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        import lean_matrix.contracts as contracts
    finally:
        sys.path.pop(0)
    assert hasattr(contracts, "HandoffReportV1")
    assert not hasattr(contracts, "WorkReportV1")
