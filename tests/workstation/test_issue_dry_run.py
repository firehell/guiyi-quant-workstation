from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

from testkit import REPO_ROOT, init_git_repo


def _write_issue_task(repo: Path) -> Path:
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / "ISSUE-OPS.md"
    task_path.write_text(
        textwrap.dedent(
            f"""\
            # ISSUE-OPS

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | ISSUE-OPS |
            | GitHub Issue | #99 |
            | Status | REQUIREMENT_READY |
            """
        ),
        encoding="utf-8",
    )
    (repo / ".ai" / "results" / "ISSUE-OPS").mkdir(parents=True, exist_ok=True)
    (repo / ".ai" / "results" / "ISSUE-OPS" / "plan_result.md").write_text("plan\n", encoding="utf-8")
    (repo / ".ai" / "results" / "ISSUE-OPS" / "result_bundle.json").write_text(
        json.dumps(
            {
                "task_id": "ISSUE-OPS",
                "task_status": "REQUIREMENT_READY",
                "execution_status": "ready_for_manual_review",
                "work_level": "L1",
                "changed_files": [],
                "test_results": [],
                "scope_check": "passed",
                "forbidden_path_check": "passed",
                "sensitive_data_check": "passed",
                "issue_gate": "passed",
                "review_status": "missing",
                "external_review_required": False,
                "warnings": [],
                "incomplete_items": [],
                "next_action": "manual review",
            }
        ),
        encoding="utf-8",
    )
    return task_path


def _run_issue_script(repo: Path, script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "ai" / script), *args],
        cwd=repo,
        env=run_env,
        capture_output=True,
        text=True,
    )


def test_update_issue_status_blocks_without_confirm(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _write_issue_task(repo)

    result = _run_issue_script(repo, "update_issue_status.sh", "ISSUE-OPS", "PLAN_READY")

    assert result.returncode == 6
    assert "--confirm-issue-ops" in result.stderr
    assert "PLAN" in result.stdout
    assert "| Status | PLAN_READY |" not in (repo / "docs" / "tasks" / "ISSUE-OPS.md").read_text(encoding="utf-8")


def test_update_issue_status_dry_run_exits_zero(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _write_issue_task(repo)

    result = _run_issue_script(repo, "update_issue_status.sh", "ISSUE-OPS", "PLAN_READY", "--dry-run")

    assert result.returncode == 0
    assert "[DRY-RUN]" in result.stdout


def test_comment_issue_result_blocks_without_confirm(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _write_issue_task(repo)

    result = _run_issue_script(repo, "comment_issue_result.sh", "ISSUE-OPS", "plan")

    assert result.returncode == 6
    assert "gh issue comment" in result.stdout


def test_comment_issue_result_confirm_uses_stub_gh(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    _write_issue_task(repo)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "gh").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            if [[ "$1" == "auth" && "$2" == "status" ]]; then
              exit 0
            fi
            if [[ "$1" == "api" ]]; then
              printf '[]'
              exit 0
            fi
            echo "stub-gh $*"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    (stub_bin / "gh").chmod(0o755)

    result = _run_issue_script(
        repo,
        "comment_issue_result.sh",
        "ISSUE-OPS",
        "plan",
        "--confirm-issue-ops",
        env={"PATH": f"{stub_bin}:{os.environ.get('PATH', '')}", "HOME": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "[OK] github result sync" in result.stdout


def test_approve_task_writes_production_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    scripts = repo / "scripts" / "ai"
    scripts.mkdir(parents=True)
    for name in ["approve_task.sh", "_approve_lib.sh", "_work_level_lib.sh"]:
        (scripts / name).write_bytes((REPO_ROOT / "scripts" / "ai" / name).read_bytes())
    lib_dir = scripts / "lib"
    lib_dir.mkdir(parents=True)
    for name in [
        "task_status_transition.py",
        "task_meta.py",
        "task_runtime.py",
        "status_machine.py",
        "compat_reader.py",
        "risk_resolver.py",
    ]:
        (lib_dir / name).write_bytes((REPO_ROOT / "scripts" / "ai" / "lib" / name).read_bytes())
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True)
    task_path = task_dir / "PROD-APPROVE.md"
    task_path.write_text(
        textwrap.dedent(
            f"""\
            # PROD-APPROVE

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | PROD-APPROVE |
            | Work Level | L1 |
            | GitHub Issue | #1 |
            | Branch | feature/test |
            | Worktree | {repo} |
            | Status | PLAN_READY |
            """
        ),
        encoding="utf-8",
    )
    plan_dir = repo / ".ai" / "results" / "PROD-APPROVE"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan_result.md").write_text("plan\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        ["bash", str(scripts / "approve_task.sh"), "--task", "PROD-APPROVE", "--confirm-production-write"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    approval = json.loads((repo / ".ai" / "approvals" / "PROD-APPROVE.json").read_text(encoding="utf-8"))
    assert approval["production_write_approved"] is True
