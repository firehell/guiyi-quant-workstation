from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from testkit import (
    DISPATCH_TASK_ID,
    calls_file,
    dispatch_env,
    lock_files,
    make_dispatch_repo,
    run_dispatch,
    run_writer_lock,
    update_task_status,
    write_approval,
    write_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = DISPATCH_TASK_ID


def test_route_does_not_call_model(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="REQUIREMENT_READY")

    result = run_dispatch(repo, TASK_ID, "route", "--json")

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["stage"] == "route"
    assert route["calls_model"] is False
    assert route["sandbox"] == "none"
    assert not calls_file(repo).exists()


def test_test_and_result_do_not_call_model_in_dry_run(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="TESTING")

    test_result = run_dispatch(repo, TASK_ID, "test", "--dry-run", "--json")
    result_result = run_dispatch(repo, TASK_ID, "result", "--dry-run", "--json")

    assert test_result.returncode == 0, test_result.stderr
    assert result_result.returncode == 0, result_result.stderr
    assert json.loads(test_result.stdout)["calls_model"] is False
    assert json.loads(result_result.stdout)["calls_model"] is False
    assert not calls_file(repo).exists()


def test_plan_uses_read_only_and_dev_uses_workspace_write(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="REQUIREMENT_READY")

    plan = run_dispatch(repo, TASK_ID, "plan", "--dry-run", "--json")
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["sandbox"] == "read-only"

    update_task_status(repo, "APPROVED_DEV")
    write_approval(repo)
    dev = run_dispatch(repo, TASK_ID, "dev", "--json", dry_run=False)

    assert dev.returncode == 0, dev.stderr
    route = json.loads(dev.stdout)
    assert route["sandbox"] == "workspace-write"
    assert "codex_dev.sh --task TASK-DISPATCH" in calls_file(repo).read_text(encoding="utf-8")


def test_unapproved_dev_is_blocked(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="APPROVED_DEV")
    write_plan(repo)

    result = run_dispatch(repo, TASK_ID, "dev", "--json", dry_run=False)

    assert result.returncode != 0
    assert "Approval missing" in result.stderr
    assert not calls_file(repo).exists()


def test_wrong_branch_and_main_are_blocked(tmp_path: Path) -> None:
    wrong_branch_repo = make_dispatch_repo(tmp_path / "wrong", status="REQUIREMENT_READY", expected_branch="feature/other")
    wrong = run_dispatch(wrong_branch_repo, TASK_ID, "plan", "--dry-run")
    assert wrong.returncode != 0
    assert "Branch Gate failed" in wrong.stderr

    main_repo = make_dispatch_repo(tmp_path / "main", branch="main", expected_branch="main", status="REQUIREMENT_READY")
    main = run_dispatch(main_repo, TASK_ID, "plan", "--dry-run")
    assert main.returncode != 0
    assert "main/master" in main.stderr


def test_profile_downgrade_is_rejected_and_upgrade_is_recorded(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="APPROVED_DEV")
    write_approval(repo)

    downgrade = run_dispatch(repo, TASK_ID, "dev", "--profile", "read-only", "--dry-run")
    assert downgrade.returncode != 0
    assert "downgrade" in downgrade.stderr

    update_task_status(repo, "REQUIREMENT_READY")
    upgrade = run_dispatch(repo, TASK_ID, "plan", "--profile", "high-readonly", "--dry-run", "--json")
    assert upgrade.returncode == 0, upgrade.stderr
    route = json.loads(upgrade.stdout)
    assert route["resolved_profile"] == "high-readonly"
    assert route["override_reason"] == "requested_profile_upgrade:high-readonly"


def test_route_json_includes_routing_tier_fields(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="REQUIREMENT_READY")

    result = run_dispatch(repo, TASK_ID, "route", "--json")

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["routing_tier"] == "fast"
    assert "external_review_required" in route
    assert "production_write_requested" in route
    assert "recommended_profile" in route


def test_dry_run_writes_route_but_does_not_call_child(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="CODING")

    result = run_dispatch(repo, TASK_ID, "test", "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    assert not calls_file(repo).exists()
    route_path = repo / ".ai" / "results" / TASK_ID / "route.json"
    route = json.loads(route_path.read_text(encoding="utf-8"))
    assert route["dispatcher"]["dry_run"] is True


def test_stage_log_and_child_failure_exit_code(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="TESTING")

    ok = run_dispatch(repo, TASK_ID, "result", "--json", dry_run=False)
    assert ok.returncode == 0, ok.stderr
    assert (repo / ".ai" / "results" / TASK_ID / "result.log").exists()

    failed = run_dispatch(repo, TASK_ID, "result", "--json", extra_env={"GUIYI_STUB_FAIL_STAGE": "collect_result.sh"}, dry_run=False)
    assert failed.returncode == 9
    route = json.loads((repo / ".ai" / "results" / TASK_ID / "route.json").read_text(encoding="utf-8"))
    assert route["dispatcher"]["exit_code"] == 9


def test_review_uses_readonly_profile_and_stub(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="TESTING")

    result = run_dispatch(repo, TASK_ID, "review", "--json", dry_run=False)

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["stage"] == "review"
    assert route["sandbox"] == "read-only"
    assert route["calls_model"] is True
    assert route["review_target"]["supported"] == ["uncommitted", "base", "commit"]
    assert "codex_review.sh --task TASK-DISPATCH" in calls_file(repo).read_text(encoding="utf-8")
    assert (repo / ".ai" / "results" / TASK_ID / "review.md").exists()


def test_second_writer_is_blocked_and_wrong_owner_cannot_release(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="APPROVED_DEV")

    first = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        TASK_ID,
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codex",
        "--stage",
        "dev",
        "--pid",
        str(os.getpid()),
    )
    assert first.returncode == 0, first.stderr

    second = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        "TASK-OTHER",
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codebuddy",
        "--stage",
        "dev",
    )
    assert second.returncode == 3
    assert "Writer lock is held" in second.stderr

    wrong_release = run_writer_lock(
        repo,
        "release",
        "--task-id",
        TASK_ID,
        "--worktree",
        str(repo),
        "--writer",
        "cursor",
        "--pid",
        str(os.getpid()),
    )
    assert wrong_release.returncode != 0
    assert lock_files(repo)

    release = run_writer_lock(
        repo,
        "release",
        "--task-id",
        TASK_ID,
        "--worktree",
        str(repo),
        "--writer",
        "codex",
        "--pid",
        str(os.getpid()),
    )
    assert release.returncode == 0, release.stderr
    assert not lock_files(repo)


def test_review_is_blocked_by_active_writer(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="TESTING")
    held = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        "TASK-ACTIVE",
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "cursor",
        "--stage",
        "dev",
        "--pid",
        str(os.getpid()),
    )
    assert held.returncode == 0, held.stderr

    review = run_dispatch(repo, TASK_ID, "review", "--dry-run")
    assert review.returncode == 3


def test_reader_stage_is_blocked_by_active_writer(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="REQUIREMENT_READY")
    held = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        "TASK-ACTIVE",
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "cursor",
        "--stage",
        "dev",
        "--pid",
        str(os.getpid()),
    )
    assert held.returncode == 0, held.stderr

    plan = run_dispatch(repo, TASK_ID, "plan", "--dry-run")
    assert plan.returncode == 3


def test_stale_lock_requires_explicit_break_and_writes_audit(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="APPROVED_DEV")
    stale = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        TASK_ID,
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codex",
        "--stage",
        "dev",
        "--pid",
        "-1",
    )
    assert stale.returncode == 0, stale.stderr

    blocked = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        "TASK-OTHER",
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codebuddy",
        "--stage",
        "dev",
    )
    assert blocked.returncode == 3
    assert lock_files(repo)

    broken = run_writer_lock(
        repo,
        "break-stale",
        "--task-id",
        "TASK-OPERATOR",
        "--worktree",
        str(repo),
        "--writer",
        "cursor",
    )
    assert broken.returncode == 0, broken.stderr
    assert not lock_files(repo)
    audit = (repo / ".ai" / "locks" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"event": "break-stale"' in audit


def test_active_pid_is_not_misclassified_as_stale(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, status="APPROVED_DEV")
    active = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        TASK_ID,
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "codex",
        "--stage",
        "dev",
        "--pid",
        str(os.getpid()),
    )
    assert active.returncode == 0, active.stderr

    broken = run_writer_lock(
        repo,
        "break-stale",
        "--task-id",
        "TASK-OPERATOR",
        "--worktree",
        str(repo),
        "--writer",
        "cursor",
    )
    assert broken.returncode == 3
    assert "Refusing to break active writer lock" in broken.stderr
    assert lock_files(repo)


def test_dev_failure_and_interrupt_release_writer_lock(tmp_path: Path) -> None:
    failed_repo = make_dispatch_repo(tmp_path / "failed", status="APPROVED_DEV")
    write_approval(failed_repo)

    failed = run_dispatch(failed_repo, TASK_ID, "dev", "--json", extra_env={"GUIYI_STUB_FAIL_STAGE": "codex_dev.sh"}, dry_run=False)
    assert failed.returncode == 9
    assert not lock_files(failed_repo)

    interrupted_repo = make_dispatch_repo(tmp_path / "interrupted", status="APPROVED_DEV")
    write_approval(interrupted_repo)
    env = dispatch_env(interrupted_repo, dry_run=False)
    env["GUIYI_STUB_SLEEP_STAGE"] = "codex_dev.sh"
    proc = subprocess.Popen(
        [str(interrupted_repo / "scripts" / "ai" / "dispatch_task.sh"), TASK_ID, "dev"],
        cwd=interrupted_repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.time() + 5
    while time.time() < deadline and not lock_files(interrupted_repo):
        time.sleep(0.05)
    assert lock_files(interrupted_repo)

    os.killpg(proc.pid, signal.SIGTERM)
    proc.communicate(timeout=5)
    assert proc.returncode != 0
    assert not lock_files(interrupted_repo)


def test_main_branch_write_is_rejected_before_lock(tmp_path: Path) -> None:
    repo = make_dispatch_repo(tmp_path, branch="main", expected_branch="main", status="APPROVED_DEV")
    write_approval(repo)

    result = run_dispatch(repo, TASK_ID, "dev", "--json", dry_run=False)

    assert result.returncode != 0
    assert "main/master" in result.stderr
    assert not lock_files(repo)
