from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from testkit import copy_workstation_scripts, init_git_repo


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
sys.path.insert(0, str(LIB_DIR))

from github_result_sync import (  # noqa: E402
    PR_BLOCK_START,
    build_context,
    merge_pr_body,
    render_issue_comment,
    render_pr_summary_block,
)


TASK_ID = "TASK-SYNC-001"


def _write_repo(repo: Path) -> None:
    init_git_repo(repo, branch="feature/test")
    copy_workstation_scripts(repo, include_collect=True)
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            # {TASK_ID}

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {TASK_ID} |
            | Work Level | L1 |
            | GitHub Issue | #99 |
            | GitHub PR | #7 |
            | Branch | feature/test |
            | Worktree | {repo} |
            | Status | TESTING |
            """
        ),
        encoding="utf-8",
    )
    out = repo / ".ai" / "results" / TASK_ID
    out.mkdir(parents=True, exist_ok=True)
    (out / "plan_result.md").write_text("Plan says token=abcdef1234567890 should be hidden.\n", encoding="utf-8")
    (out / "review.md").write_text("No blocking findings.\n", encoding="utf-8")
    (out / "delivery_summary.md").write_text("Delivery password: verysecretvalue12345\n", encoding="utf-8")
    (out / "evidence_index.json").write_text(
        json.dumps({"schema_version": 1, "total_files": 3, "entries": [{"path": "execution.json"}]}),
        encoding="utf-8",
    )
    bundle = {
        "task_id": TASK_ID,
        "task_status": "TESTING",
        "execution_status": "ready_for_manual_review",
        "work_level": "L1",
        "changed_files": ["scripts/ai/comment_issue_result.sh", "tests/workstation/test_github_result_sync.py"],
        "git_diff_stat": "scripts/ai/comment_issue_result.sh | 10 +++++",
        "test_results": [{"index": 1, "exit_code": 0, "status": "PASS", "command": "git diff --check"}],
        "scope_check": "passed",
        "forbidden_path_check": "passed",
        "sensitive_data_check": "passed",
        "issue_gate": "passed",
        "review_status": "completed",
        "external_review_required": False,
        "warnings": [],
        "incomplete_items": [],
        "next_action": "manual review",
        "evidence_index": {"total_files": 3, "entries": [{"path": "execution.json"}]},
    }
    (out / "result_bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(repo: Path, script: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [str(repo / "scripts" / "ai" / script), *args],
        cwd=repo,
        env=run_env,
        capture_output=True,
        text=True,
    )


def test_issue_comment_summary_is_redacted_and_does_not_upload_full_logs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)
    ctx = build_context(repo, TASK_ID)

    body = render_issue_comment(ctx, "delivery")

    assert f"guiyi-result-sync:issue:{TASK_ID}:delivery" in body
    assert ".ai/results/TASK-SYNC-001/" in body
    assert "verysecretvalue12345" not in body
    assert "abcdef1234567890" not in body
    assert "[REDACTED]" in body
    assert "完整日志" in body


def test_pr_body_merge_preserves_human_content_and_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)
    ctx = build_context(repo, TASK_ID)
    block = render_pr_summary_block(ctx)
    human = "## Human Notes\n\nKeep this paragraph."

    once = merge_pr_body(human, block)
    twice = merge_pr_body(once, block)

    assert "Keep this paragraph." in twice
    assert twice.count(PR_BLOCK_START) == 1
    assert "scripts/ai/comment_issue_result.sh" in twice
    assert ".ai/results/TASK-SYNC-001/" in twice


def test_comment_issue_result_dry_run_json_is_safe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)

    result = _run(repo, "comment_issue_result.sh", TASK_ID, "plan", "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["issue_number"] == 99
    assert payload["action"] == "dry_run"
    assert "abcdef1234567890" not in payload["body"]


def test_issue_comment_confirm_updates_existing_marker_instead_of_creating_duplicate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.log"
    marker = f"guiyi-result-sync:issue:{TASK_ID}:test"
    (bin_dir / "gh").write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$1 $2" == "auth status" ]]; then
              exit 0
            fi
            echo "$*" >> "{calls}"
            if [[ "$1" == "api" && "$2" == "repos/firehell/guiyi-quant-workstation/issues/99/comments" ]]; then
              printf '[{{"id":123,"body":"<!-- {marker} --> old"}}]'
              exit 0
            fi
            if [[ "$1" == "api" && "$2" == "-X" && "$3" == "PATCH" ]]; then
              exit 0
            fi
            echo "unexpected gh call: $*" >&2
            exit 9
            """
        ),
        encoding="utf-8",
    )
    (bin_dir / "gh").chmod(0o755)

    result = _run(
        repo,
        "comment_issue_result.sh",
        TASK_ID,
        "test",
        "--confirm-issue-ops",
        "--json",
        env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "update"
    log = calls.read_text(encoding="utf-8")
    assert "PATCH repos/firehell/guiyi-quant-workstation/issues/comments/123" in log
    assert "issue comment" not in log


def test_update_pr_from_result_dry_run_json_preserves_marker(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)

    result = _run(repo, "update_pr_from_result.sh", "--task", TASK_ID, "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["pr_number"] == 7
    assert payload["body"].count(PR_BLOCK_START) == 1
    assert "Auto-merge" not in payload["body"]


def test_make_delivery_summary_uses_safe_result_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo)

    result = _run(repo, "make_delivery_summary.sh", "--task", TASK_ID)

    assert result.returncode == 0, result.stderr
    summary = (repo / ".ai" / "results" / TASK_ID / "delivery_summary.md").read_text(encoding="utf-8")
    assert "verysecretvalue12345" not in summary
    assert str(repo) not in summary
    assert ".ai/results/TASK-SYNC-001/" in summary
