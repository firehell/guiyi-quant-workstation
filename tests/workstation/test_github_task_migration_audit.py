from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap

from testkit import REPO_ROOT, init_git_repo


def write_task(path: Path, task_id: str, *, issue: str = "", branch: str = "", status: str = "PLAN_READY") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            # {task_id}

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {task_id} |
            | GitHub Issue | {issue} |
            | Branch | {branch} |
            | Status | {status} |
            """
        ),
        encoding="utf-8",
    )


def test_github_task_migration_audit_offline_classifies_matrix(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    write_task(repo / "docs/tasks/TASK-A.md", "TASK-A", issue="#1", branch="feature/a", status="PLAN_READY")
    write_task(repo / "docs/tasks/TASK-DONE.md", "TASK-DONE", issue="#2", branch="feature/done", status="DELIVERY_READY")
    write_task(repo / "docs/tasks/TASK-ORPHAN.md", "TASK-ORPHAN", status="REQUIREMENT_READY")
    write_task(repo / "docs/tasks/EXAMPLE-TASK.md", "TASK-EXAMPLE", issue="#99", status="PLAN_READY")

    issues = [
        {
            "number": 1,
            "title": "TASK-A: active",
            "body": "Branch: feature/a",
            "state": "OPEN",
            "labels": [{"name": "type/task"}],
            "url": "https://github.com/example/repo/issues/1",
        },
        {
            "number": 2,
            "title": "TASK-DONE: done",
            "body": "",
            "state": "OPEN",
            "labels": [{"name": "status/delivery-ready"}],
            "url": "https://github.com/example/repo/issues/2",
        },
        {
            "number": 3,
            "title": "Unlinked request",
            "body": "",
            "state": "OPEN",
            "labels": [],
            "url": "https://github.com/example/repo/issues/3",
        },
    ]
    issues_file = tmp_path / "issues.json"
    prs_file = tmp_path / "prs.json"
    issues_file.write_text(json.dumps(issues), encoding="utf-8")
    prs_file.write_text("[]", encoding="utf-8")

    result = subprocess.run(
        [
            "python3",
            str(REPO_ROOT / "scripts/ai/audit_github_task_links.py"),
            "--repo",
            "example/repo",
            "--issues-file",
            str(issues_file),
            "--prs-file",
            str(prs_file),
            "--output-dir",
            str(tmp_path / "out"),
            "--doc-report",
            str(tmp_path / "report.md"),
            "--json",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["classifications"]["Active"] == 1
    assert summary["classifications"]["Completed"] == 1
    assert summary["classifications"]["Orphan Issue"] == 1
    assert summary["classifications"]["Orphan TASK"] == 1

    matrix = json.loads((tmp_path / "out/migration_matrix.json").read_text(encoding="utf-8"))
    task_ids = {row["task_id"] for row in matrix["rows"]}
    assert "TASK-EXAMPLE" not in task_ids
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# GitHub TASK Migration Report")

