from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap


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
    lib_dir = scripts_dir / "lib"
    lib_dir.mkdir(parents=True)
    for name in ["dispatch_task.sh", "route_task.sh", "_work_level_lib.sh", "_approve_lib.sh"]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / name, scripts_dir / name)
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / "task_meta.py", lib_dir / "task_meta.py")
    shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / "route_task.py", lib_dir / "route_task.py")

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
    env = os.environ.copy()
    env.update(
        {
            "GUIYI_AI_SCRIPT_DIR": str(repo / "stubs"),
            "GUIYI_STUB_CALLS": str(calls_file(repo)),
        }
    )
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
