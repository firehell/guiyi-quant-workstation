from __future__ import annotations

import os
from pathlib import Path
import subprocess
import textwrap

import pytest

from testkit import REPO_ROOT, init_git_repo


yaml = pytest.importorskip("yaml")


def test_task_issue_template_is_remote_entry_not_full_task_copy() -> None:
    template = (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "task.md").read_text(encoding="utf-8")

    required_terms = [
        "Task ID",
        "Goal summary",
        "Risk level",
        "Work level",
        "Task branch",
        "TASK file path",
        "Draft PR",
        "Current status",
        "Key gates",
        "Non-goals",
        "Related Epic",
    ]
    for term in required_terms:
        assert term in template

    assert "Issue is the lifecycle and remote entry point" in template
    assert "## 7. 技术方案" not in template
    assert "## 10. 开发步骤" not in template


def test_bug_and_design_issue_forms_are_valid_yaml() -> None:
    for name in ["bug.yml", "design.yml", "config.yml"]:
        path = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    bug = yaml.safe_load((REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml").read_text(encoding="utf-8"))
    design = yaml.safe_load((REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "design.yml").read_text(encoding="utf-8"))
    assert "type/bug" in bug["labels"]
    assert "type/design" in design["labels"]
    assert any(item.get("id") == "risk_level" for item in bug["body"] if isinstance(item, dict))
    assert any(item.get("id") == "non_goals" for item in design["body"] if isinstance(item, dict))


def test_pull_request_template_contains_task_workspace_gates() -> None:
    template = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    required_terms = [
        "Related Issue",
        "Task ID",
        "TASK path",
        "Risk level",
        "Work level",
        "Scope",
        "Changed Files",
        "Tests",
        "Evidence Summary",
        "Security / Data Impact",
        "External GPT Review",
        "Merge Gate",
        "Unresolved Items",
    ]
    for term in required_terms:
        assert term in template
    assert "Auto-merge is not enabled" in template
    assert "Local evidence path: `.ai/results/<TASK_ID>/`" in template


def test_draft_pr_workflow_documents_lifecycle_and_no_auto_merge() -> None:
    workflow = (REPO_ROOT / "docs" / "workflows" / "GITHUB_DRAFT_PR_WORKFLOW.md").read_text(encoding="utf-8")
    required_terms = [
        "GPT creates Draft PR",
        "Plan complete",
        "User approval",
        "Codex implementation",
        "Ready for Review",
        "GPT external review",
        "User merge",
        "一个正式 TASK 对应",
        "Result Bundle 保持 local-first",
        "禁止启用 auto-merge",
    ]
    for term in required_terms:
        assert term in workflow
    assert "R0/R1 任务必须记录外部 GPT Review" in workflow
    assert "Issue 不取代 TASK" in workflow


def test_label_bootstrap_specs_are_unique_and_include_v3_and_legacy_labels() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "ai" / "bootstrap_github_labels.sh"), "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    labels = [line.split("|", 1)[0] for line in result.stdout.splitlines() if line.strip()]
    assert len(labels) == len(set(labels))
    for label in [
        "type/task",
        "type/bug",
        "type/design",
        "status/draft",
        "status/approved",
        "status/executing",
        "status/approved-dev",
        "risk/r0",
        "risk/r3",
        "ai/gpt-authored",
        "ai/codex-executed",
        "review/gpt-required",
    ]:
        assert label in labels


def test_label_bootstrap_dry_run_does_not_require_gh(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(REPO_ROOT / "scripts" / "ai" / "bootstrap_github_labels.sh")],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": "/bin:/usr/bin"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN]" in result.stdout
    assert "would ensure label: type/task" in result.stdout


def test_label_bootstrap_apply_uses_edit_for_existing_and_create_for_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.log"
    gh = bin_dir / "gh"
    gh.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$1 $2" == "auth status" ]]; then
              exit 0
            fi
            if [[ "$1 $2" == "label list" ]]; then
              printf 'type/task\\nstatus/draft\\n'
              exit 0
            fi
            echo "$*" >> "{calls}"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    gh.chmod(0o755)

    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "ai" / "bootstrap_github_labels.sh"), "--apply"],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="utf-8")
    assert "label edit type/task" in log
    assert "label edit status/draft" in log
    assert "label create type/bug" in log
    assert "label create review/gpt-required" in log


def test_update_issue_status_uses_v3_canonical_status_labels(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True)
    task_path = task_dir / "ISSUE-OPS.md"
    task_path.write_text(
        textwrap.dedent(
            """\
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

    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "ai" / "update_issue_status.sh"), "ISSUE-OPS", "APPROVED_DEV", "--dry-run"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "status/approved" in result.stdout
    assert "status/approved-dev" not in result.stdout
