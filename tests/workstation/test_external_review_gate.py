from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

from testkit import REPO_ROOT, copy_workstation_scripts, init_git_repo


TASK_ID = "TASK-EXT-REVIEW"
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
import sys
sys.path.insert(0, str(LIB_DIR))

from dispatch_phase import Checkpoint, PhaseResult, validate_phase_gate  # noqa: E402


def _write_repo(repo: Path, *, risk_level: str = "R1", approval_scope: list[str] | None = None) -> None:
    init_git_repo(repo, branch="feature/test")
    copy_workstation_scripts(repo)
    scope = approval_scope if approval_scope is not None else ["plan", "code"]
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            kind: Task
            schema_version: "3.0"
            task_id: "{TASK_ID}"
            title: "External review gate test"
            status: REVIEWING
            risk_level: {risk_level}
            work_level: L1
            approval_scope: {json.dumps(scope)}
            allowed_paths: ["scripts/ai/**", "tests/workstation/**"]
            forbidden_paths: [".env"]
            required_tests: ["git diff --check"]
            branch: "feature/test"
            base_branch: "main"
            github_issue: "#9"
            github_pr: "#7"
            created_by: "test"
            source: "pytest"
            ---

            # {TASK_ID}
            """
        ),
        encoding="utf-8",
    )


def _write_gh_stub(bin_dir: Path, *, head_sha: str, reviews: list[dict]) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    pr_json = json.dumps(
        {
            "number": 7,
            "url": "https://github.com/firehell/guiyi-quant-workstation/pull/7",
            "headRefOid": head_sha,
        }
    )
    reviews_json = json.dumps(reviews)
    gh = bin_dir / "gh"
    gh.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$1 $2 $3" == "pr view 7" ]]; then
              cat <<'JSON'
            {pr_json}
            JSON
              exit 0
            fi
            if [[ "$1" == "api" && "$2" == "repos/firehell/guiyi-quant-workstation/pulls/7/reviews" ]]; then
              cat <<'JSON'
            {reviews_json}
            JSON
              exit 0
            fi
            echo "unexpected gh call: $*" >&2
            exit 9
            """
        ),
        encoding="utf-8",
    )
    gh.chmod(0o755)


def _run(repo: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "record_external_review.sh"), "--task", TASK_ID, "--json", *args],
        cwd=repo,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
    )


def _review(state: str, *, sha: str, body: str = "Looks good.", login: str = "gpt-reviewer") -> dict:
    return {
        "state": state,
        "commit_id": sha,
        "submitted_at": "2026-07-15T01:00:00Z",
        "body": body,
        "user": {"login": login},
    }


def test_r1_approved_review_at_current_head_passes_and_records(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R1")
    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, head_sha="abc123", reviews=[_review("APPROVED", sha="abc123")])

    result = _run(repo, bin_dir)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["gate_status"] == "passed"
    assert payload["review_action"] == "APPROVE"
    record = json.loads((repo / ".ai" / "external-reviews" / f"{TASK_ID}.json").read_text(encoding="utf-8"))
    assert record["head_sha"] == "abc123"
    assert record["reviewer_type"] == "gpt"


def test_request_changes_blocks_required_review(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R1")
    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, head_sha="abc123", reviews=[_review("CHANGES_REQUESTED", sha="abc123", body="blocking scope issue")])

    result = _run(repo, bin_dir)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["gate_status"] == "blocked"
    assert "review_action=REQUEST_CHANGES" in payload["blocking_findings"]


def test_new_pr_head_marks_previous_review_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R1")
    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, head_sha="oldsha", reviews=[_review("APPROVED", sha="oldsha")])
    first = _run(repo, bin_dir)
    assert first.returncode == 0, first.stderr

    _write_gh_stub(bin_dir, head_sha="newsha", reviews=[_review("APPROVED", sha="oldsha")])
    second = _run(repo, bin_dir, "--dry-run")

    assert second.returncode == 1
    payload = json.loads(second.stdout)
    assert payload["gate_status"] == "stale"
    assert payload["stale"] is True
    record = json.loads((repo / ".ai" / "external-reviews" / f"{TASK_ID}.json").read_text(encoding="utf-8"))
    assert record["head_sha"] == "oldsha"


def test_r2_requires_external_review_when_approval_scope_requests_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R2", approval_scope=["plan", "code", "external_review"])
    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, head_sha="abc123", reviews=[_review("COMMENTED", sha="abc123", body="Architecture OK.")])

    result = _run(repo, bin_dir)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["required"] is True
    assert payload["review_action"] == "COMMENT"
    assert payload["gate_status"] == "passed"


def test_r3_missing_review_is_optional(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R3", approval_scope=["plan", "code"])
    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, head_sha="abc123", reviews=[])

    result = _run(repo, bin_dir)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["required"] is False
    assert payload["gate_status"] == "not_required"


def test_docs_and_prompt_define_role_boundary() -> None:
    workflow = (REPO_ROOT / "docs" / "workflows" / "GPT_GITHUB_REVIEW_WORKFLOW.md").read_text(encoding="utf-8")
    prompt = (REPO_ROOT / "prompts" / "gpt-github-pr-review.md").read_text(encoding="utf-8")
    assert "Codex review" in workflow
    assert "GPT external review" in workflow
    assert "head SHA" in workflow
    assert "不允许脚本代替 GPT approve" in workflow
    assert "REQUEST_CHANGES" in prompt
    assert "不代表用户已批准 merge" in prompt


def test_close_phase_requires_passed_external_review_record_for_r1(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_repo(repo, risk_level="R1")
    cp = Checkpoint(task_id=TASK_ID, risk_level="R1")
    for phase in ["prepare", "plan", "audit", "dev", "test", "review", "result"]:
        cp.phases[phase] = PhaseResult(status="PASSED")

    missing = validate_phase_gate(
        "close",
        "R1",
        cp,
        approval_available=True,
        approval_operation="MERGE",
        repo_root=str(repo),
        task_id=TASK_ID,
    )
    assert missing["ok"] is False
    assert missing["code"] == "EXTERNAL_REVIEW_MISSING"

    record_dir = repo / ".ai" / "external-reviews"
    record_dir.mkdir(parents=True)
    (record_dir / f"{TASK_ID}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "pr_number": 7,
                "head_sha": "abc123",
                "review_action": "COMMENT",
                "review_timestamp": "2026-07-15T01:00:00Z",
                "reviewer_type": "gpt",
                "blocking_findings": [],
                "gate_status": "passed",
                "stale": False,
            }
        ),
        encoding="utf-8",
    )
    passed = validate_phase_gate(
        "close",
        "R1",
        cp,
        approval_available=True,
        approval_operation="MERGE",
        repo_root=str(repo),
        task_id=TASK_ID,
    )
    assert passed["ok"] is True
