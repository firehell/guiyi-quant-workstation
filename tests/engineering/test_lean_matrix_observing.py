"""Behavior tests for reconstructing Lean Matrix state from local Git facts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"
TASK_PATH = Path("/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-005-local-orchestrator")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "develop")
    _git(repo, "config", "user.name", "Lean Matrix tests")
    _git(repo, "config", "user.email", "lean-matrix@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", sha)
    return repo, sha


def _plan(base_sha: str, *, external_gates: list[str] | None = None):
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import ExecutionPlanV1
    finally:
        sys.path.pop(0)
    return ExecutionPlanV1.from_mapping({
        "schema_version": 1,
        "status": "ok",
        "charter_digest": "sha256:" + "1" * 64,
        "task": {
            "issue_number": 109,
            "task_id": "AI-TEAM-005",
            "branch": "feature/AI-TEAM-005-local-orchestrator",
            "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-005-local-orchestrator",
        },
        "base": {"ref": "origin/develop", "expected_sha": base_sha},
        "dispatch": {
            "model": "Terra",
            "reasoning_effort": "medium",
            "roles": ["ai-project-lead"],
            "specialists": [],
            "independence_requirements": ["independent review"],
        },
        "scope": {
            "allowed_paths": ["scripts/engineering/lean_matrix/observing.py"],
            "forbidden_paths": ["Runtime"],
        },
        "validation": {"test_profile": "engineering", "required_checks": ["diff-check"]},
        "transitions": ["task-create", "draft-pr", "cleanup"],
        "external_gates": external_gates or [],
    })


class _FakeGit:
    """Complete fake at the Git executable boundary; orchestration logic stays real."""

    def __init__(
        self,
        repo: Path,
        *,
        branch: str,
        dirty: bool,
        merged: bool,
        protected_dirty: bool = False,
        content_marker: str = "first",
    ) -> None:
        self.repo = repo.resolve()
        self.branch = branch
        self.dirty = dirty
        self.merged = merged
        self.protected_dirty = protected_dirty
        self.content_marker = content_marker
        self.base_sha = "a" * 40
        self.task_sha = "b" * 40

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["git", "-c", "core.fsmonitor=false"]
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        args = tuple(command[3:])
        cwd = Path(kwargs["cwd"]).resolve()
        stdout = ""
        returncode = 0
        if args == ("rev-parse", "--show-toplevel"):
            stdout = f"{self.repo}\n"
        elif args == ("rev-parse", "--verify", "origin/develop^{commit}"):
            stdout = f"{self.base_sha}\n"
        elif args == ("rev-parse", "--verify", "--quiet", "refs/heads/feature/AI-TEAM-005-local-orchestrator^{commit}"):
            stdout = f"{self.task_sha}\n"
        elif args == ("rev-parse", "--verify", "--quiet", "refs/remotes/origin/feature/AI-TEAM-005-local-orchestrator^{commit}"):
            returncode = 1
        elif args == ("rev-parse", "--verify", "--quiet", "refs/heads/develop^{commit}"):
            stdout = f"{self.base_sha}\n"
        elif args == ("worktree", "list", "--porcelain"):
            stdout = (
                f"worktree {self.repo}\nHEAD {self.base_sha}\nbranch refs/heads/develop\n\n"
                f"worktree {TASK_PATH}\nHEAD {self.task_sha}\nbranch refs/heads/{self.branch}\n\n"
            )
        elif cwd == self.repo and args == ("status", "--porcelain=v1", "-z"):
            stdout = " M protected.txt\0" if self.protected_dirty else ""
        elif cwd == TASK_PATH and args == ("branch", "--show-current"):
            stdout = f"{self.branch}\n"
        elif cwd == TASK_PATH and args == ("rev-parse", "HEAD"):
            stdout = f"{self.task_sha}\n"
        elif cwd == TASK_PATH and args == ("status", "--porcelain=v1", "-z"):
            stdout = " M scripts/engineering/lean_matrix/observing.py\0" if self.dirty else ""
        elif cwd == TASK_PATH and args == ("diff", "--name-only", "-z", f"{self.base_sha}...HEAD"):
            stdout = "tests/engineering/test_lean_matrix_observing.py\0"
        elif cwd == TASK_PATH and args in {
            ("diff", "--cached", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        }:
            stdout = ""
        elif cwd == TASK_PATH and args == ("diff", "--name-only", "-z"):
            stdout = "scripts/engineering/lean_matrix/observing.py\0" if self.dirty else ""
        elif cwd == TASK_PATH and args == ("ls-files", "--stage", "-z"):
            stdout = self.content_marker if self.dirty else ""
        elif args in {
            ("merge-base", "--is-ancestor", self.task_sha, "refs/heads/develop"),
            ("merge-base", "--is-ancestor", self.task_sha, "origin/develop"),
        }:
            returncode = 0 if self.merged else 1
        else:
            raise AssertionError(f"unexpected Git call cwd={cwd} args={args}")
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def test_absent_task_branch_reconstructs_deterministic_planned_state(tmp_path: Path) -> None:
    """Removing state files must not change a planned observation reconstructed from Git."""
    repo, base_sha = _repository(tmp_path)
    plan = _plan(base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    first = observe_execution_plan(plan, repo)
    second = observe_execution_plan(plan, repo)

    assert first.state.to_dict() == {
        "state_digest": first.state.state_digest,
        "branch": None,
        "worktree": None,
        "base_sha": base_sha,
        "dirty": False,
        "changed_paths": [],
        "pr_number": None,
        "pr_head_sha": None,
        "ci_state": "NOT_RUN",
        "review_state": "NOT_RUN",
        "merge_state": "NOT_RUN",
        "cleanup_safe": False,
    }
    assert first.state.state_digest == second.state.state_digest
    assert first.phase == "planned"
    assert not (repo / ".ai").exists()


def test_observation_reports_base_drift_without_falling_back(tmp_path: Path) -> None:
    """Advancing origin/develop must remain visible instead of silently using the planned SHA."""
    repo, base_sha = _repository(tmp_path)
    plan = _plan(base_sha)
    (repo / "README.md").write_text("advanced\n", encoding="utf-8")
    _git(repo, "commit", "-am", "advance")
    advanced_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", advanced_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    observed = observe_execution_plan(plan, repo)

    assert observed.state.base_sha == advanced_sha
    assert observed.base_matches_plan is False
    assert observed.phase == "planned"


def test_state_digest_changes_when_a_material_git_fact_changes(tmp_path: Path) -> None:
    """A stale expected-state guard must fail when the observed base ref moves."""
    repo, base_sha = _repository(tmp_path)
    plan = _plan(base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)
    before = observe_execution_plan(plan, repo).state.state_digest
    (repo / "README.md").write_text("advanced\n", encoding="utf-8")
    _git(repo, "commit", "-am", "advance")
    _git(repo, "update-ref", "refs/remotes/origin/develop", _git(repo, "rev-parse", "HEAD"))

    after = observe_execution_plan(plan, repo).state.state_digest

    assert after != before


def test_state_digest_binds_task_head_even_when_changed_path_names_are_unchanged(tmp_path: Path) -> None:
    """Amending task content under the same filenames must invalidate an expected-state guard."""
    repo = tmp_path / "repo"
    repo.mkdir()
    first_git = _FakeGit(
        repo,
        branch="feature/AI-TEAM-005-local-orchestrator",
        dirty=True,
        merged=False,
    )
    second_git = _FakeGit(
        repo,
        branch="feature/AI-TEAM-005-local-orchestrator",
        dirty=True,
        merged=False,
    )
    second_git.task_sha = "c" * 40
    plan = _plan(first_git.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    first = observe_execution_plan(plan, repo, runner=first_git)
    second = observe_execution_plan(plan, repo, runner=second_git)

    assert first.state.changed_paths == second.state.changed_paths
    assert first.state.state_digest != second.state.state_digest


def test_state_digest_binds_dirty_content_when_path_names_and_head_are_unchanged(tmp_path: Path) -> None:
    """Editing an already-dirty file must invalidate the previously approved state digest."""
    repo = tmp_path / "repo"
    repo.mkdir()
    first_git = _FakeGit(
        repo,
        branch="feature/AI-TEAM-005-local-orchestrator",
        dirty=True,
        merged=False,
        content_marker="first patch content",
    )
    second_git = _FakeGit(
        repo,
        branch="feature/AI-TEAM-005-local-orchestrator",
        dirty=True,
        merged=False,
        content_marker="different patch content",
    )
    plan = _plan(first_git.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    first = observe_execution_plan(plan, repo, runner=first_git)
    second = observe_execution_plan(plan, repo, runner=second_git)

    assert first.state.changed_paths == second.state.changed_paths
    assert first.task_head == second.task_head
    assert first.state.state_digest != second.state.state_digest


def test_registered_task_worktree_collects_identity_dirty_state_and_changed_paths(tmp_path: Path) -> None:
    """Dropping any staged, unstaged, committed, or untracked path would bypass scope validation."""
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = _FakeGit(repo, branch="feature/AI-TEAM-005-local-orchestrator", dirty=True, merged=False)
    plan = _plan(fake.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    observed = observe_execution_plan(plan, repo, runner=fake)

    assert observed.phase == "implementation-ready"
    assert observed.state.branch == plan.task.branch
    assert observed.state.worktree == str(TASK_PATH)
    assert observed.state.dirty is True
    assert observed.state.changed_paths == (
        "scripts/engineering/lean_matrix/observing.py",
        "tests/engineering/test_lean_matrix_observing.py",
    )
    assert observed.state.cleanup_safe is False
    assert observed.state.merge_state == "FAIL"


def test_registered_worktree_with_wrong_branch_fails_closed(tmp_path: Path) -> None:
    """A path collision must not let an unrelated task branch inherit this plan."""
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = _FakeGit(repo, branch="feature/unrelated-task", dirty=False, merged=False)
    plan = _plan(fake.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    try:
        observe_execution_plan(plan, repo, runner=fake)
    except LeanMatrixError as exc:
        assert exc.error_type == "worktree_identity_mismatch"
    else:
        raise AssertionError("wrong task branch was accepted")


def test_clean_task_head_reachable_from_both_develop_refs_is_cleanup_safe(tmp_path: Path) -> None:
    """Cleanup must remain blocked unless both local and remote-tracking develop contain task HEAD."""
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = _FakeGit(repo, branch="feature/AI-TEAM-005-local-orchestrator", dirty=False, merged=True)
    plan = _plan(fake.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    observed = observe_execution_plan(plan, repo, runner=fake)

    assert observed.phase == "merged-develop-observed"
    assert observed.state.merge_state == "PASS"
    assert observed.state.cleanup_safe is True


def test_clean_new_worktree_at_base_is_not_cleanup_safe(tmp_path: Path) -> None:
    """A newly created task branch equals develop but has not delivered any task change."""
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = _FakeGit(repo, branch="feature/AI-TEAM-005-local-orchestrator", dirty=False, merged=True)
    fake.task_sha = fake.base_sha
    plan = _plan(fake.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    observed = observe_execution_plan(plan, repo, runner=fake)

    assert observed.phase == "implementation-ready"
    assert observed.state.cleanup_safe is False


def test_dirty_develop_checkout_blocks_observation_before_any_transition(tmp_path: Path) -> None:
    """Creating a task from an unreviewed protected checkout risks mixing unrelated local work."""
    repo = tmp_path / "repo"
    repo.mkdir()
    fake = _FakeGit(
        repo,
        branch="feature/AI-TEAM-005-local-orchestrator",
        dirty=False,
        merged=False,
        protected_dirty=True,
    )
    plan = _plan(fake.base_sha)
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        observe_execution_plan(plan, repo, runner=fake)
    assert raised.value.error_type == "protected_checkout_dirty"


def test_non_develop_base_ref_is_rejected_even_when_it_resolves(tmp_path: Path) -> None:
    """An untrusted plan must not redirect local orchestration to main or another moving ref."""
    repo, base_sha = _repository(tmp_path)
    payload = _plan(base_sha).to_dict()
    payload["base"] = {"ref": "refs/heads/develop", "expected_sha": base_sha}
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import ExecutionPlanV1
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.observing import observe_execution_plan
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        observe_execution_plan(ExecutionPlanV1.from_mapping(payload), repo)
    assert raised.value.error_type == "unsupported_base_ref"
