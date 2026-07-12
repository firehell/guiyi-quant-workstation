from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import textwrap
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "TASK-DISPATCH"


def test_route_does_not_call_model(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="REQUIREMENT_READY")

    result = run_dispatch(repo, TASK_ID, "route", "--json")

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["stage"] == "route"
    assert route["calls_model"] is False
    assert route["sandbox"] == "none"
    assert not calls_file(repo).exists()


def test_test_and_result_do_not_call_model_in_dry_run(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="TESTING")

    test_result = run_dispatch(repo, TASK_ID, "test", "--dry-run", "--json")
    result_result = run_dispatch(repo, TASK_ID, "result", "--dry-run", "--json")

    assert test_result.returncode == 0, test_result.stderr
    assert result_result.returncode == 0, result_result.stderr
    assert json.loads(test_result.stdout)["calls_model"] is False
    assert json.loads(result_result.stdout)["calls_model"] is False
    assert not calls_file(repo).exists()


def test_plan_uses_read_only_and_dev_uses_workspace_write(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="REQUIREMENT_READY")

    plan = run_dispatch(repo, TASK_ID, "plan", "--dry-run", "--json")
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["sandbox"] == "read-only"

    update_task_status(repo, "APPROVED_DEV")
    write_approval(repo)
    dev = run_dispatch(repo, TASK_ID, "dev", "--json")

    assert dev.returncode == 0, dev.stderr
    route = json.loads(dev.stdout)
    assert route["sandbox"] == "workspace-write"
    assert "codex_dev.sh --task TASK-DISPATCH" in calls_file(repo).read_text(encoding="utf-8")


def test_unapproved_dev_is_blocked(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="APPROVED_DEV")
    write_plan(repo)

    result = run_dispatch(repo, TASK_ID, "dev", "--json")

    assert result.returncode != 0
    assert "Approval missing" in result.stderr
    assert not calls_file(repo).exists()


def test_wrong_branch_and_main_are_blocked(tmp_path: Path) -> None:
    wrong_branch_repo = make_repo(tmp_path / "wrong", status="REQUIREMENT_READY", expected_branch="feature/other")
    wrong = run_dispatch(wrong_branch_repo, TASK_ID, "plan", "--dry-run")
    assert wrong.returncode != 0
    assert "Branch Gate failed" in wrong.stderr

    main_repo = make_repo(tmp_path / "main", branch="main", expected_branch="main", status="REQUIREMENT_READY")
    main = run_dispatch(main_repo, TASK_ID, "plan", "--dry-run")
    assert main.returncode != 0
    assert "main/master" in main.stderr


def test_profile_downgrade_is_rejected_and_upgrade_is_recorded(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="APPROVED_DEV")
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


def test_dry_run_writes_route_but_does_not_call_child(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="CODING")

    result = run_dispatch(repo, TASK_ID, "test", "--dry-run", "--json")

    assert result.returncode == 0, result.stderr
    assert not calls_file(repo).exists()
    route_path = repo / ".ai" / "results" / TASK_ID / "route.json"
    route = json.loads(route_path.read_text(encoding="utf-8"))
    assert route["dispatcher"]["dry_run"] is True


def test_stage_log_and_child_failure_exit_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="TESTING")

    ok = run_dispatch(repo, TASK_ID, "result", "--json")
    assert ok.returncode == 0, ok.stderr
    assert (repo / ".ai" / "results" / TASK_ID / "result.log").exists()

    failed = run_dispatch(repo, TASK_ID, "result", "--json", extra_env={"GUIYI_STUB_FAIL_STAGE": "collect_result.sh"})
    assert failed.returncode == 9
    route = json.loads((repo / ".ai" / "results" / TASK_ID / "route.json").read_text(encoding="utf-8"))
    assert route["dispatcher"]["exit_code"] == 9


def test_second_writer_is_blocked_and_wrong_owner_cannot_release(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="APPROVED_DEV")

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


def test_reader_stage_is_blocked_by_active_writer(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="REQUIREMENT_READY")
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
    repo = make_repo(tmp_path, status="APPROVED_DEV")
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
    repo = make_repo(tmp_path, status="APPROVED_DEV")
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
    failed_repo = make_repo(tmp_path / "failed", status="APPROVED_DEV")
    write_approval(failed_repo)

    failed = run_dispatch(failed_repo, TASK_ID, "dev", "--json", extra_env={"GUIYI_STUB_FAIL_STAGE": "codex_dev.sh"})
    assert failed.returncode == 9
    assert not lock_files(failed_repo)

    interrupted_repo = make_repo(tmp_path / "interrupted", status="APPROVED_DEV")
    write_approval(interrupted_repo)
    env = dispatch_env(interrupted_repo)
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
    repo = make_repo(tmp_path, branch="main", expected_branch="main", status="APPROVED_DEV")
    write_approval(repo)

    result = run_dispatch(repo, TASK_ID, "dev", "--json")

    assert result.returncode != 0
    assert "main/master" in result.stderr
    assert not lock_files(repo)


def make_repo(
    path: Path,
    *,
    branch: str = "feature/test",
    expected_branch: str = "feature/test",
    status: str,
) -> Path:
    repo = path
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True, text=True)

    scripts_dir = repo / "scripts" / "ai"
    env_scripts_dir = repo / "scripts" / "env"
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True)
    env_scripts_dir.mkdir(parents=True)
    for name in ["dispatch_task.sh", "route_task.sh", "writer_lock.sh", "_work_level_lib.sh", "_approve_lib.sh"]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / name, scripts_dir / name)
    for name in ["check_task_env.sh"]:
        shutil.copy2(REPO_ROOT / "scripts" / "env" / name, env_scripts_dir / name)
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / "task_meta.py", lib_dir / "task_meta.py")
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / "route_task.py", lib_dir / "route_task.py")
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / "writer_lock.py", lib_dir / "writer_lock.py")

    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True)
    write_task(repo, status=status, expected_branch=expected_branch)
    write_stubs(repo)
    write_plan(repo)
    return repo


def write_task(repo: Path, *, status: str, expected_branch: str) -> None:
    (repo / "docs" / "tasks" / f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            # {TASK_ID}: Dispatcher Fixture

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {TASK_ID} |
            | Work Level | L1 |
            | GitHub Issue | #1 |
            | Branch | {expected_branch} |
            | Worktree | {repo} |
            | Status | {status} |
            | Created At | 2026-07-12 |
            | Owner | test |

            ## 7. 涉及模块

            **允许修改**：

            - `scripts/ai/`
            - `tests/workstation/`

            **禁止修改**：

            - `.env`
            - `data/raw/`

            ## 18. 测试清单

            ### 18.0 自动化测试命令

            ```bash
            bash -n scripts/ai/*.sh
            git diff --check
            ```
            """
        ),
        encoding="utf-8",
    )


def update_task_status(repo: Path, status: str) -> None:
    path = repo / "docs" / "tasks" / f"{TASK_ID}.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(next(line for line in text.splitlines() if line.startswith("| Status |")), f"| Status | {status} |")
    path.write_text(text, encoding="utf-8")


def write_plan(repo: Path) -> Path:
    out_dir = repo / ".ai" / "results" / TASK_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = out_dir / "plan_result.md"
    plan.write_text("approved plan\n", encoding="utf-8")
    return plan


def write_approval(repo: Path) -> None:
    plan = write_plan(repo)
    approval_dir = repo / ".ai" / "approvals"
    approval_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "task_file": f"docs/tasks/{TASK_ID}.md",
        "plan_file": f".ai/results/{TASK_ID}/plan_result.md",
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "approved_branch": "feature/test",
        "head_commit": "0" * 40,
    }
    (approval_dir / f"{TASK_ID}.json").write_text(json.dumps(payload), encoding="utf-8")


def write_stubs(repo: Path) -> None:
    stubs = repo / "stubs"
    stubs.mkdir()
    script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        name="$(basename "$0")"
        echo "$name $*" >> "$GUIYI_STUB_CALLS"
        if [[ "${GUIYI_STUB_SLEEP_STAGE:-}" == "$name" ]]; then
          sleep 30
        fi
        if [[ "${GUIYI_STUB_FAIL_STAGE:-}" == "$name" ]]; then
          exit 9
        fi
        task_id=""
        while [[ $# -gt 0 ]]; do
          case "$1" in
            --task) task_id="${2:-}"; shift 2 ;;
            *) shift ;;
          esac
        done
        mkdir -p ".ai/results/$task_id"
        case "$name" in
          codex_plan.sh) echo "stub plan" > ".ai/results/$task_id/plan_result.md" ;;
          codex_dev.sh) echo "stub dev" > ".ai/results/$task_id/dev_child.log" ;;
          run_tests.sh) echo "stub tests" > ".ai/results/$task_id/test_child.log" ;;
          collect_result.sh) echo '{"ok": true}' > ".ai/results/$task_id/result_bundle.json" ;;
        esac
        """
    )
    for name in ["codex_plan.sh", "codex_dev.sh", "run_tests.sh", "collect_result.sh"]:
        path = stubs / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)


def run_dispatch(repo: Path, task: str, stage: str, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dispatch_env(repo)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), task, stage, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def calls_file(repo: Path) -> Path:
    return repo / ".ai" / "stub_calls.log"


def dispatch_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GUIYI_AI_SCRIPT_DIR": str(repo / "stubs"),
            "GUIYI_STUB_CALLS": str(calls_file(repo)),
            "GUIYI_SKIP_CODEX_ENV_CHECK": "1",
        }
    )
    return env


def run_writer_lock(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "ai" / "writer_lock.sh"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def lock_files(repo: Path) -> list[Path]:
    return list((repo / ".ai" / "locks" / "worktrees").glob("*.json"))
