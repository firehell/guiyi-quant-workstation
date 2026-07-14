from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from testkit import REPO_ROOT, copy_workstation_scripts, init_git_repo


def _commit(repo: Path, message: str = "init") -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_v3_task(
    repo: Path,
    *,
    task_id: str = "TASK-V3-RUNTIME",
    branch: str = "feature/static",
    status: str = "REQUIREMENT_READY",
) -> Path:
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            kind: Task
            schema_version: "3.0"
            task_id: "{task_id}"
            title: "Runtime overlay test"
            status: {status}
            risk_level: R2
            work_level: L1
            approval_scope: [plan, code]
            allowed_paths: ["scripts/ai/**", "tests/workstation/**"]
            forbidden_paths: [".env", "data/**"]
            required_tests: ["git diff --check"]
            branch: "{branch}"
            base_branch: "main"
            github_issue: ""
            github_pr: ""
            created_by: "test"
            source: "pytest"
            ---

            # {task_id}

            ## 18. Tests

            ```bash
            git diff --check
            ```
            """
        ),
        encoding="utf-8",
    )
    return path


def _write_runtime(repo: Path, task_id: str, payload: dict) -> Path:
    path = repo / ".ai" / "task-runtime" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": "1.0", "task_id": task_id, **payload}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _make_repo(path: Path, *, branch: str = "feature/test") -> Path:
    repo = path
    init_git_repo(repo, branch=branch)
    copy_workstation_scripts(repo, include_collect=True)
    (repo / ".gitignore").write_text(".ai/\n", encoding="utf-8")
    return repo


def test_v3_task_uses_runtime_overlay_for_route_and_worktree_gate(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="feature/test")
    task_id = "TASK-V3-RUNTIME"
    _write_v3_task(repo, task_id=task_id, branch="feature/static")
    _write_runtime(
        repo,
        task_id,
        {
            "worktree": str(repo),
            "local_branch": "feature/test",
            "issue_number": 42,
            "pr_number": 7,
            "last_sync_at": "2026-07-14T00:00:00Z",
        },
    )
    _commit(repo)

    route = subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), task_id, "plan", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert route.returncode == 0, route.stderr
    payload = json.loads(route.stdout)
    assert payload["schema_version_task"] == "3.0"
    assert payload["worktree"] == str(repo)
    assert payload["branch"] == "feature/test"
    assert payload["github_issue"] == "#42"
    assert payload["github_pr"] == "#7"

    dispatch = subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), task_id, "plan", "--dry-run", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert dispatch.returncode == 0, dispatch.stderr
    runtime = json.loads((repo / ".ai" / "task-runtime" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert runtime["last_dispatch_stage"] == "plan"
    assert runtime["last_dispatch_exit_code"] == 0


def test_legacy_task_without_runtime_keeps_inline_worktree(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="feature/test")
    task_id = "TASK-LEGACY-RUNTIME"
    task_path = repo / "docs" / "tasks" / f"{task_id}.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        textwrap.dedent(
            f"""\
            # {task_id}

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {task_id} |
            | Work Level | L1 |
            | GitHub Issue | #1 |
            | Branch | feature/test |
            | Worktree | {repo} |
            | Status | REQUIREMENT_READY |
            """
        ),
        encoding="utf-8",
    )
    _commit(repo)

    route = subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), task_id, "plan", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert route.returncode == 0, route.stderr
    payload = json.loads(route.stdout)
    assert payload["worktree"] == str(repo)
    assert payload["branch"] == "feature/test"


def test_runtime_overlay_overrides_legacy_inline_worktree_for_shell_gate(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="feature/test")
    task_id = "TASK-LEGACY-OVERLAY"
    wrong_worktree = tmp_path / "wrong-worktree"
    task_path = repo / "docs" / "tasks" / f"{task_id}.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        textwrap.dedent(
            f"""\
            # {task_id}

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {task_id} |
            | Work Level | L1 |
            | GitHub Issue | #1 |
            | Branch | feature/wrong |
            | Worktree | {wrong_worktree} |
            | Status | REQUIREMENT_READY |
            """
        ),
        encoding="utf-8",
    )
    _write_runtime(
        repo,
        task_id,
        {
            "worktree": str(repo),
            "local_branch": "feature/test",
            "last_sync_at": "2026-07-14T00:00:00Z",
        },
    )
    _commit(repo)

    dispatch = subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), task_id, "plan", "--dry-run", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert dispatch.returncode == 0, dispatch.stderr
    payload = json.loads(dispatch.stdout)
    assert payload["worktree"] == str(repo)
    assert payload["branch"] == "feature/test"


def test_damaged_runtime_overlay_blocks_route(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="feature/test")
    task_id = "TASK-BAD-RUNTIME"
    _write_v3_task(repo, task_id=task_id, branch="feature/test")
    runtime_path = repo / ".ai" / "task-runtime" / f"{task_id}.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text("{not-json\n", encoding="utf-8")
    _commit(repo)

    route = subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), task_id, "plan", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert route.returncode != 0
    assert "invalid JSON" in route.stderr


def test_schema_invalid_runtime_overlay_blocks_route(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="feature/test")
    task_id = "TASK-SCHEMA-RUNTIME"
    _write_v3_task(repo, task_id=task_id, branch="feature/test")
    _write_runtime(repo, task_id, {"worktree": str(repo), "allowed_paths": ["must-not-overlay"]})
    _commit(repo)

    route = subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), task_id, "plan", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert route.returncode != 0
    assert "schema invalid" in route.stderr
    assert "allowed_paths" in route.stderr


def test_init_task_worktree_writes_runtime_without_mutating_tracked_task(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", branch="main")
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "init_task_worktree.sh", repo / "scripts" / "ai" / "init_task_worktree.sh")
    task_id = "TASK-INIT-RUNTIME"
    task_path = _write_v3_task(repo, task_id=task_id, branch="feature/init-runtime")
    original = task_path.read_text(encoding="utf-8")
    _commit(repo)

    result = subprocess.run(
        [str(repo / "scripts" / "ai" / "init_task_worktree.sh"), "--task", task_id, "--base", "HEAD", "--print-path"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    worktree_path = result.stdout.strip().splitlines()[-1]
    runtime = json.loads((repo / ".ai" / "task-runtime" / f"{task_id}.json").read_text(encoding="utf-8"))
    assert runtime["worktree"] == worktree_path
    assert runtime["local_branch"] == "feature/init-runtime"
    assert task_path.read_text(encoding="utf-8") == original
    diff = subprocess.run(["git", "diff", "--", str(task_path.relative_to(repo))], cwd=repo, capture_output=True, text=True)
    assert diff.stdout == ""
