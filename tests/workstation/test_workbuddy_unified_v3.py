from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

from testkit import REPO_ROOT, init_git_repo


SCRIPT = REPO_ROOT / "scripts" / "ai" / "workbuddy_task.sh"


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    scripts = repo / "scripts" / "ai"
    scripts.mkdir(parents=True)
    (scripts / "workbuddy_task.sh").write_bytes(SCRIPT.read_bytes())
    (scripts / "workbuddy_task.sh").chmod(0o755)
    for name in [
        "bootstrap_github_task.sh",
        "route_task.sh",
        "dispatch_task.sh",
        "approve_task.sh",
        "make_delivery_summary.sh",
        "update_pr_from_result.sh",
        "record_external_review.sh",
    ]:
        (scripts / name).write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                echo "{name} $*" >> "$PWD/calls.log"
                case "{name}" in
                  bootstrap_github_task.sh)
                    printf '{{"ok":true,"task_id":"TASK-123","issue_number":123}}\\n'
                    ;;
                  route_task.sh)
                    printf '{{"ok":true,"command":"route"}}\\n'
                    ;;
                  dispatch_task.sh)
                    printf '{{"ok":true,"command":"dispatch","stage":"%s"}}\\n' "${{2:-}}"
                    ;;
                  update_pr_from_result.sh)
                    printf '{{"ok":true,"command":"sync-pr"}}\\n'
                    ;;
                  record_external_review.sh)
                    printf '{{"ok":true,"command":"record-external-review"}}\\n'
                    ;;
                  *)
                    exit 0
                    ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        (scripts / name).chmod(0o755)
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "ai" / "workbuddy_task.sh"), *args],
        cwd=repo,
        env={**os.environ, "HOME": str(repo)},
        capture_output=True,
        text=True,
    )


def test_facade_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_facade_has_fixed_commands_and_rejects_unknown(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    help_result = _run(repo, "--help")
    for command in [
        "analyze",
        "bootstrap",
        "plan",
        "approve",
        "dev",
        "test",
        "review",
        "result",
        "delivery",
        "status",
        "cancel",
        "sync-pr",
        "record-external-review",
    ]:
        assert command in help_result.stdout

    result = _run(repo, "shell", "--task", "TASK-123")
    assert result.returncode == 2
    assert "unknown_command" in result.stderr


def test_issue_and_pr_must_be_numeric(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    issue_result = _run(repo, "status", "--issue", "abc")
    pr_result = _run(repo, "record-external-review", "--task", "TASK-123", "--pr", "x12")

    assert issue_result.returncode == 2
    assert "invalid_issue" in issue_result.stderr
    assert pr_result.returncode == 2
    assert "invalid_pr" in pr_result.stderr


def test_approve_requires_explicit_user_confirmation(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    blocked = _run(repo, "approve", "--task", "TASK-123")
    allowed = _run(repo, "approve", "--task", "TASK-123", "--confirm-user-approval")

    assert blocked.returncode == 6
    assert "user_approval_required" in blocked.stderr
    assert allowed.returncode == 0
    assert "approve_task.sh --task TASK-123" in (repo / "calls.log").read_text(encoding="utf-8")


def test_sync_pr_requires_explicit_github_write_confirmation(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    blocked = _run(repo, "sync-pr", "--task", "TASK-123", "--pr", "12")
    allowed = _run(repo, "sync-pr", "--task", "TASK-123", "--pr", "12", "--confirm-github-write")

    assert blocked.returncode == 6
    assert "github_write_confirmation_required" in blocked.stderr
    assert allowed.returncode == 0
    assert "--confirm-issue-ops" in (repo / "calls.log").read_text(encoding="utf-8")


def test_no_direct_codex_or_free_shell_and_no_stage_chaining() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "eval" not in text
    assert "codex " not in text
    assert "codex_plan.sh" not in text
    assert "codex_dev.sh" not in text
    assert "dispatch_task.sh" in text
    assert "dev --json" not in text
    assert "test --json" not in text
    assert "review --json" not in text
    assert "result --json" not in text


def test_plan_calls_only_one_dispatch_stage(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = _run(repo, "plan", "--task", "TASK-123")

    assert result.returncode == 0
    calls = (repo / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls == ["dispatch_task.sh TASK-123 plan --json"]


def test_skill_and_canonical_docs_define_v3_boundaries() -> None:
    skill = (REPO_ROOT / ".agents" / "skills" / "guiyi-workstation-orchestrator" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    control = (REPO_ROOT / "docs" / "workstation" / "GITHUB_NATIVE_CONTROL_PLANE.md").read_text(encoding="utf-8")
    codebuddy = (REPO_ROOT / "CODEBUDDY.md").read_text(encoding="utf-8")

    for term in [
        "GitHub Issue",
        "docs/tasks/<TASK_ID>.md",
        "not state sources",
        "ARCHITECTURE_REQUIRED",
        "EXPLICIT_APPROVAL_REQUIRED",
        "ESCALATE_TO_CODEX",
    ]:
        assert term in skill
    assert "CodeBuddy is compatibility-only" in codebuddy
    assert "WorkBuddy Unified V3" in control
    assert "second task state" in control
