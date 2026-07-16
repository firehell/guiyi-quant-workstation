from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

WORKSTATION_TESTS = Path(__file__).resolve().parents[1]
if str(WORKSTATION_TESTS) not in sys.path:
    sys.path.insert(0, str(WORKSTATION_TESTS))

from testkit import (  # noqa: E402
    DISPATCH_TASK_ID,
    make_dispatch_repo,
    read_json,
    run_dispatch,
    write_approval,
)


def _task_file(repo: Path, task_id: str = DISPATCH_TASK_ID) -> Path:
    return repo / "docs" / "tasks" / f"{task_id}.md"


def _task_text(repo: Path, task_id: str = DISPATCH_TASK_ID) -> str:
    return _task_file(repo, task_id).read_text(encoding="utf-8")


def _run_approve(repo: Path, task_id: str = DISPATCH_TASK_ID) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "approve_task.sh"), "--task", task_id],
        cwd=repo,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
    )


def _task_sha(repo: Path, task_id: str = DISPATCH_TASK_ID) -> str:
    return hashlib.sha256(_task_file(repo, task_id).read_bytes()).hexdigest()


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_plan_success_transitions_requirement_ready_to_plan_ready(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "plan", status="REQUIREMENT_READY")

    result = run_dispatch(repo, DISPATCH_TASK_ID, "plan", "--json", dry_run=False)

    assert result.returncode == 0, result.stderr
    assert "| Status | PLAN_READY |" in _task_text(repo)
    route = json.loads(result.stdout)
    assert route["status_before"] == "REQUIREMENT_READY"
    assert route["status_after"] == "PLAN_READY"
    record = read_json(repo / ".ai" / "results" / DISPATCH_TASK_ID / "status_transition.json")
    assert record["last_transition"]["to_status"] == "PLAN_READY"


def test_valid_approval_flow_binds_current_task_sha_and_transitions_to_approved(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "approve", status="PLAN_READY")
    _commit_all(repo)

    result = _run_approve(repo)

    assert result.returncode == 0, result.stderr
    assert "| Status | APPROVED |" in _task_text(repo)
    approval = read_json(repo / ".ai" / "approvals" / f"{DISPATCH_TASK_ID}.json")
    assert approval["approved_task_sha256"] != approval["current_task_sha256"]
    assert approval["current_task_sha256"] == _task_sha(repo)
    assert approval["approval_status_transition"]["new_status"] == "APPROVED"


def test_stale_approval_task_sha_is_rejected_after_task_changes(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "stale", status="APPROVED")
    _commit_all(repo)
    write_approval(repo)
    task_path = _task_file(repo)
    task_path.write_text(task_path.read_text(encoding="utf-8") + "\n\nManual change after approval.\n", encoding="utf-8")

    result = run_dispatch(repo, DISPATCH_TASK_ID, "dev", dry_run=False)

    assert result.returncode != 0
    assert "Approval invalid: TASK file changed since approval" in result.stderr


def test_dev_success_transitions_approved_to_testing(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "dev", status="PLAN_READY")
    _commit_all(repo)
    approve = _run_approve(repo)
    assert approve.returncode == 0, approve.stderr

    result = run_dispatch(repo, DISPATCH_TASK_ID, "dev", "--json", dry_run=False)

    assert result.returncode == 0, result.stderr
    assert "| Status | TESTING |" in _task_text(repo)
    route = json.loads(result.stdout)
    assert route["status_before"] == "APPROVED"
    assert route["status_after"] == "TESTING"


def test_dev_child_failure_does_not_advance_to_testing(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "dev_fail", status="PLAN_READY")
    _commit_all(repo)
    approve = _run_approve(repo)
    assert approve.returncode == 0, approve.stderr

    result = run_dispatch(
        repo,
        DISPATCH_TASK_ID,
        "dev",
        extra_env={"GUIYI_STUB_FAIL_STAGE": "codex_dev.sh"},
        dry_run=False,
    )

    assert result.returncode != 0
    assert "| Status | EXECUTING |" in _task_text(repo)
    assert "| Status | TESTING |" not in _task_text(repo)


def test_test_and_review_success_transitions(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path / "test_review", status="TESTING")

    test_result = run_dispatch(repo, DISPATCH_TASK_ID, "test", "--json", dry_run=False)
    assert test_result.returncode == 0, test_result.stderr
    assert "| Status | REVIEWING |" in _task_text(repo)

    review_result = run_dispatch(repo, DISPATCH_TASK_ID, "review", "--json", dry_run=False)
    assert review_result.returncode == 0, review_result.stderr
    assert "| Status | DELIVERY_READY |" in _task_text(repo)
