"""Black-box CLI and adapter policy tests for AI-TEAM-005 orchestration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"
CLI = ROOT / "scripts" / "engineering" / "lean_matrix_team.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _isolated_cli(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    engineering = repo / "scripts" / "engineering"
    engineering.mkdir(parents=True)
    shutil.copy2(CLI, engineering / CLI.name)
    shutil.copy2(ENGINEERING / "task_workflow.py", engineering / "task_workflow.py")
    shutil.copytree(ENGINEERING / "lean_matrix", engineering / "lean_matrix")
    (engineering / "task-worktree.sh").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' 'SECRET-SHOULD-NOT-PERSIST'\n",
        encoding="utf-8",
    )
    (engineering / "task-worktree.sh").chmod(0o755)
    (repo / ".gitignore").write_text(".ai/\n", encoding="utf-8")
    _git(repo, "init", "-b", "develop")
    _git(repo, "config", "user.name", "Lean Matrix tests")
    _git(repo, "config", "user.email", "lean-matrix@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", base_sha)
    return repo, engineering / CLI.name, base_sha


def _plan(base_sha: str, *, external_gates: list[str] | None = None) -> dict[str, object]:
    gates = external_gates or []
    return {
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
            "model": "Sol" if gates else "Terra",
            "reasoning_effort": "high" if gates else "medium",
            "roles": ["ai-project-lead"],
            "specialists": [],
            "independence_requirements": ["independent review"],
        },
        "scope": {"allowed_paths": ["tests/example.py"], "forbidden_paths": ["Runtime"]},
        "validation": {"test_profile": "engineering", "required_checks": ["diff-check"]},
        "transitions": ["task-create", "draft-pr", "cleanup"],
        "external_gates": gates,
    }


def _invoke(cli: Path, repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(cli), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_observe_next_and_apply_dry_run_are_read_only_and_consistent(tmp_path: Path) -> None:
    """Dry-run commands must not create the ignored runtime workspace or diverging proposals."""
    repo, cli, base_sha = _isolated_cli(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(base_sha)), encoding="utf-8")

    observe = _invoke(cli, repo, "observe", "--plan", str(plan_path), "--format", "json")
    next_result = _invoke(cli, repo, "next", "--plan", str(plan_path), "--format", "json")
    assert observe.returncode == 0, observe.stderr
    assert next_result.returncode == 0, next_result.stderr
    state = json.loads(observe.stdout)
    proposal = json.loads(next_result.stdout)
    apply_dry = _invoke(
        cli,
        repo,
        "apply",
        "--plan", str(plan_path),
        "--expected-transition", proposal["transition_id"],
        "--expected-state-digest", state["state_digest"],
        "--format", "json",
    )

    assert apply_dry.returncode == 0, apply_dry.stderr
    assert json.loads(apply_dry.stdout) == proposal
    assert state["branch"] is None
    assert proposal["action"] == "task-create"
    assert not (repo / ".ai").exists()


def test_apply_rechecks_expected_transition_and_state_digest(tmp_path: Path) -> None:
    """A caller must not apply a proposal observed from different local facts."""
    repo, cli, base_sha = _isolated_cli(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(base_sha)), encoding="utf-8")
    result = _invoke(
        cli,
        repo,
        "apply",
        "--plan", str(plan_path),
        "--expected-transition", "tr-" + "9" * 64,
        "--expected-state-digest", "sha256:" + "8" * 64,
        "--format", "json",
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error_type"] == "expected_state_mismatch"
    assert not (repo / ".ai").exists()


def test_lane_three_explicit_apply_is_always_rejected(tmp_path: Path) -> None:
    """Even a matching await-human proposal cannot become a generic Lane 3 side effect."""
    repo, cli, base_sha = _isolated_cli(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(_plan(base_sha, external_gates=["Owner approval required."])),
        encoding="utf-8",
    )
    state = json.loads(_invoke(cli, repo, "observe", "--plan", str(plan_path), "--format", "json").stdout)
    proposal = json.loads(_invoke(cli, repo, "next", "--plan", str(plan_path), "--format", "json").stdout)
    result = _invoke(
        cli,
        repo,
        "apply",
        "--plan", str(plan_path),
        "--expected-transition", proposal["transition_id"],
        "--expected-state-digest", state["state_digest"],
        "--format", "json",
        "--apply",
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["error_type"] == "lane_three_apply_forbidden"
    assert not (repo / ".ai").exists()


def test_adapter_executes_exactly_one_existing_entrypoint_with_fixed_cwd() -> None:
    """Direct Git or multiple subprocess calls would duplicate the controlled workflow."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.adapters import execute_action
        from lean_matrix.contracts import ExecutionPlanV1
    finally:
        sys.path.pop(0)
    plan = ExecutionPlanV1.from_mapping(_plan("a" * 40))
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}\n', stderr="")

    result = execute_action(plan, "local-integrate-to-draft-pr", ROOT, runner=runner)

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:3] == ["bash", "scripts/engineering/task-worktree.sh", "integrate"]
    assert command[-1] == "--apply"
    assert kwargs["cwd"] == Path(plan.task.worktree)
    assert kwargs["shell"] is False
    assert result.exit_code == 0
    assert result.error_type is None
    assert result.command_digest.startswith("sha256:")


def test_lane_one_scope_is_delegated_with_least_privilege() -> None:
    """A research-only plan must not be widened to Lane 2 by the adapter."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.adapters import command_for_action
        from lean_matrix.contracts import ExecutionPlanV1
    finally:
        sys.path.pop(0)
    payload = _plan("a" * 40)
    payload["scope"] = {"allowed_paths": ["tests/**", "docs/research/**"], "forbidden_paths": []}
    plan = ExecutionPlanV1.from_mapping(payload)

    command = command_for_action(plan, "task-create")

    assert command[command.index("--lane") + 1] == "1"


def test_sol_dispatch_cannot_be_downgraded_by_removing_external_gates(tmp_path: Path) -> None:
    """Editing only external_gates must not turn a Lane 3 plan into a local apply plan."""
    repo, cli, base_sha = _isolated_cli(tmp_path)
    payload = _plan(base_sha)
    payload["dispatch"] = {
        **payload["dispatch"],
        "model": "Sol",
        "reasoning_effort": "high",
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    result = _invoke(cli, repo, "next", "--plan", str(plan_path), "--format", "json")

    assert result.returncode == 2
    assert json.loads(result.stderr)["error_type"] == "lane_three_plan_invalid"


def test_cleanup_cannot_remove_the_checkout_running_the_controller() -> None:
    """Cleanup must be launched from a surviving repository checkout, never its own target cwd."""
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.adapters import execute_action
        from lean_matrix.contracts import ExecutionPlanV1
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)
    plan = ExecutionPlanV1.from_mapping(_plan("a" * 40))

    with pytest.raises(LeanMatrixError) as raised:
        execute_action(
            plan,
            "local-cleanup-after-merge-observed",
            Path(plan.task.worktree),
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
        )
    assert raised.value.error_type == "cleanup_invocation_from_target"


def test_success_exit_without_state_change_is_recorded_failed_and_cannot_retry(tmp_path: Path) -> None:
    """Exit zero alone must not claim a transition happened or permit a blind second attempt."""
    repo, cli, base_sha = _isolated_cli(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(base_sha)), encoding="utf-8")
    state = json.loads(_invoke(cli, repo, "observe", "--plan", str(plan_path), "--format", "json").stdout)
    proposal = json.loads(_invoke(cli, repo, "next", "--plan", str(plan_path), "--format", "json").stdout)

    applied = _invoke(
        cli,
        repo,
        "apply",
        "--plan", str(plan_path),
        "--expected-transition", proposal["transition_id"],
        "--expected-state-digest", state["state_digest"],
        "--format", "json",
        "--apply",
    )

    assert applied.returncode == 2
    assert json.loads(applied.stderr)["error_type"] == "transition_state_unchanged"
    workspace_files = [path for path in (repo / ".ai").rglob("*") if path.is_file()]
    assert workspace_files
    assert all("SECRET-SHOULD-NOT-PERSIST" not in path.read_text(encoding="utf-8") for path in workspace_files)
    retried = _invoke(cli, repo, "next", "--plan", str(plan_path), "--format", "json")
    assert retried.returncode == 2
    assert json.loads(retried.stderr)["error_type"] == "transition_already_attempted"
