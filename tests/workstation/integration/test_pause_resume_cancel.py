from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSTATION_TESTS = Path(__file__).resolve().parents[1]
if str(WORKSTATION_TESTS) not in sys.path:
    sys.path.insert(0, str(WORKSTATION_TESTS))

from testkit import (
    make_scenario_repo,
    read_json,
    run_dispatch,
    run_writer_lock,
    write_approval,
)

TASK_ID = "LOCKED_WORKTREE"


def _acquire_lock(repo: Path, *, task_id: str = TASK_ID) -> None:
    result = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        task_id,
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codex",
        "--stage",
        "dev",
        "--pid",
        "424242",
    )
    assert result.returncode == 0, result.stderr


def _lock_files(repo: Path) -> list[Path]:
    return list((repo / ".ai" / "locks" / "worktrees").glob("*.json"))


def test_pause_releases_lock_and_sets_paused(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "pause", TASK_ID, git_commit=True)
    write_approval(repo, TASK_ID)
    _acquire_lock(repo)
    assert _lock_files(repo)

    pause = run_dispatch(repo, TASK_ID, "pause", "--json", dry_run=False)
    assert pause.returncode == 0, pause.stderr
    payload = json.loads(pause.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["previous_status"] == "APPROVED"

    task_text = (repo / "docs" / "tasks" / f"{TASK_ID}.md").read_text(encoding="utf-8")
    assert "| Status | BLOCKED |" in task_text
    pause_record = read_json(repo / ".ai" / "results" / TASK_ID / "pause_record.json")
    assert pause_record["previous_status"] == "APPROVED"
    assert pause_record["writer_released"] is True
    assert not _lock_files(repo)


def test_resume_restores_previous_status(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "resume", TASK_ID, git_commit=True)
    write_approval(repo, TASK_ID)
    _acquire_lock(repo)
    pause = run_dispatch(repo, TASK_ID, "pause", dry_run=False)
    assert pause.returncode == 0, pause.stderr

    resume = run_dispatch(repo, TASK_ID, "resume", "--json", dry_run=False)
    assert resume.returncode == 0, resume.stderr
    payload = json.loads(resume.stdout)
    assert payload["status"] == "APPROVED"

    task_text = (repo / "docs" / "tasks" / f"{TASK_ID}.md").read_text(encoding="utf-8")
    assert "| Status | APPROVED |" in task_text


def test_cancel_blocks_dev_and_resume(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "cancel", TASK_ID, git_commit=True)
    write_approval(repo, TASK_ID)

    cancel = run_dispatch(repo, TASK_ID, "cancel", dry_run=False)
    assert cancel.returncode == 0, cancel.stderr

    dev = run_dispatch(repo, TASK_ID, "dev", dry_run=False)
    assert dev.returncode != 0
    assert "已取消" in dev.stderr

    resume = run_dispatch(repo, TASK_ID, "resume", dry_run=False)
    assert resume.returncode != 0
    assert "已取消" in resume.stderr


def test_status_is_read_only(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "status", TASK_ID)
    write_approval(repo, TASK_ID)

    status = run_dispatch(repo, TASK_ID, "status", "--json", dry_run=False)
    assert status.returncode == 0, status.stderr
    payload = json.loads(status.stdout)
    assert payload["action"] == "status"
    assert payload["task_id"] == TASK_ID
    assert payload["status"] == "APPROVED"
    assert payload["approval_present"] is True


def test_duplicate_pause_returns_exit_5(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "dup_pause", TASK_ID)
    first = run_dispatch(repo, TASK_ID, "pause", dry_run=False)
    assert first.returncode == 0, first.stderr

    second = run_dispatch(repo, TASK_ID, "pause", dry_run=False)
    assert second.returncode == 5
    assert "already paused" in second.stderr.lower()
