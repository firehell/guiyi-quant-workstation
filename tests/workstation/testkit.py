from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DISPATCH_TASK_ID = "TASK-DISPATCH"

AI_SCRIPT_NAMES = [
    "dispatch_task.sh",
    "bootstrap_github_task.sh",
    "record_external_review.sh",
    "route_task.sh",
    "writer_lock.sh",
    "_work_level_lib.sh",
    "_approve_lib.sh",
    "_dispatch_phase_lib.sh",
    "_external_disk_lib.sh",
    "_dirty_gate_lib.sh",
    "_scope_report_lib.sh",
]
ENV_SCRIPT_NAMES = [
    "check_task_env.sh",
    "bootstrap_worktree_env.sh",
]
LIB_NAMES = [
    "task_meta.py", "route_task.py", "writer_lock.py", "dispatch_control.py",
    "dispatch_phase.py", "approval_manager.py", "resource_lock.py",
    "status_machine.py", "risk_resolver.py", "schema_validator.py",
    "compat_reader.py", "epic_manager.py", "model_router.py",
    "task_runtime.py", "github_task_resolver.py", "result_bundler.py",
    "github_result_sync.py", "external_review_gate.py", "runtime_gate_ledger.py",
]
OPTIONAL_AI_SCRIPT_NAMES = [
    "collect_result.sh",
    "make_delivery_summary.sh",
    "comment_issue_result.sh",
    "update_pr_from_result.sh",
    "approval.sh",
    "resource_lock.sh",
    "codex_review.sh",
    "codex_plan.sh",
    "codex_dev.sh",
    "run_tests.sh",
]


def fixture_text(name: str, repo: Path, **replacements: str) -> str:
    text = (FIXTURES_DIR / f"{name}.md").read_text(encoding="utf-8")
    values = {"WORKTREE": str(repo), "MISSING_MOUNT": replacements.get("missing_mount", "/missing/external-disk")}
    values.update(replacements)
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def copy_workstation_scripts(repo: Path, *, include_collect: bool = False) -> None:
    scripts_dir = repo / "scripts" / "ai"
    env_scripts_dir = repo / "scripts" / "env"
    lib_dir = scripts_dir / "lib"
    schemas_dir = repo / "configs" / "ai" / "schemas"
    for directory in [scripts_dir, env_scripts_dir, lib_dir, schemas_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    for name in AI_SCRIPT_NAMES:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / name, scripts_dir / name)
    if include_collect:
        for name in OPTIONAL_AI_SCRIPT_NAMES:
            source = REPO_ROOT / "scripts" / "ai" / name
            if source.is_file():
                shutil.copy2(source, scripts_dir / name)
    for name in ENV_SCRIPT_NAMES:
        shutil.copy2(REPO_ROOT / "scripts" / "env" / name, env_scripts_dir / name)
    for name in LIB_NAMES:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / name, lib_dir / name)

    # Copy model routing config
    configs_ai_dir = repo / "configs" / "ai"
    configs_ai_dir.mkdir(parents=True, exist_ok=True)
    routing_config_src = REPO_ROOT / "configs" / "ai" / "model_routing.json"
    if routing_config_src.is_file():
        shutil.copy2(routing_config_src, configs_ai_dir / "model_routing.json")
    schema_src = REPO_ROOT / "configs" / "ai" / "schemas"
    if schema_src.is_dir():
        for schema_file in schema_src.glob("*.json"):
            shutil.copy2(schema_file, schemas_dir / schema_file.name)


def init_git_repo(repo: Path, *, branch: str = "feature/test") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo, check=True, capture_output=True, text=True)


def write_task_from_fixture(repo: Path, fixture_name: str, **replacements: str) -> Path:
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / f"{fixture_name}.md"
    task_path.write_text(fixture_text(fixture_name, repo, **replacements), encoding="utf-8")
    return task_path


def make_scenario_repo(
    path: Path,
    fixture_name: str,
    *,
    branch: str = "feature/test",
    include_collect: bool = False,
    git_commit: bool = False,
    **replacements: str,
) -> Path:
    repo = path
    init_git_repo(repo, branch=branch)
    copy_workstation_scripts(repo, include_collect=include_collect)
    write_task_from_fixture(repo, fixture_name, **replacements)
    write_stubs(repo, include_collect=include_collect)
    if git_commit:
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    return repo


def write_stubs(repo: Path, *, include_collect: bool = False) -> None:
    stubs = repo / "stubs"
    stubs.mkdir(exist_ok=True)
    collect_body = (
        'bash "$REPO_ROOT/scripts/ai/collect_result.sh" --task "$task_id"\n'
        if include_collect
        else 'echo \'{"ok": true}\' > ".ai/results/$task_id/result_bundle.json"\n'
    )
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        name="$(basename "$0")"
        echo "$name $*" >> "$GUIYI_STUB_CALLS"
        if [[ "${{GUIYI_STUB_SLEEP_STAGE:-}}" == "$name" ]]; then
          sleep 30
        fi
        if [[ "${{GUIYI_STUB_FAIL_STAGE:-}}" == "$name" ]]; then
          exit 9
        fi
        task_id=""
        while [[ $# -gt 0 ]]; do
          case "$1" in
            --task) task_id="${{2:-}}"; shift 2 ;;
            *) shift ;;
          esac
        done
        mkdir -p ".ai/results/$task_id"
        REPO_ROOT="$(git rev-parse --show-toplevel)"
        case "$name" in
          codex_plan.sh) echo "stub plan" > ".ai/results/$task_id/plan_result.md" ;;
          codex_dev.sh) echo "stub dev" > ".ai/results/$task_id/dev_child.log" ;;
          run_tests.sh)
            echo "stub tests" > ".ai/results/$task_id/test_child.log"
            echo "1\\tgit diff --check" > ".ai/results/$task_id/commands_executed.tsv"
            echo "1\\t0\\tPASS\\tgit diff --check" > ".ai/results/$task_id/test_results.tsv"
            echo "" > ".ai/results/$task_id/skipped_tests.txt"
            ;;
          collect_result.sh)
            {collect_body}
            ;;
          codex_review.sh) echo "stub review" > ".ai/results/$task_id/review.md" ;;
        esac
        """
    )
    names = ["codex_plan.sh", "codex_dev.sh", "run_tests.sh", "collect_result.sh", "codex_review.sh"]
    for name in names:
        path = stubs / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)


def dispatch_env(repo: Path, *, dry_run: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GUIYI_AI_SCRIPT_DIR": str(repo / "stubs"),
            "GUIYI_STUB_CALLS": str(repo / ".ai" / "stub_calls.log"),
            "GUIYI_SKIP_CODEX_ENV_CHECK": "1",
        }
    )
    if dry_run:
        env["GUIYI_AI_DRY_RUN"] = "1"
    return env


def run_dispatch(
    repo: Path,
    task_id: str,
    stage: str,
    *args: str,
    extra_env: dict[str, str] | None = None,
    dry_run: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dispatch_env(repo, dry_run=dry_run)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), task_id, stage, *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def run_route(repo: Path, task_id: str, stage: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), task_id, stage, *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def run_writer_lock(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "ai" / "writer_lock.sh"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def run_bootstrap(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"), "--worktree", str(repo), *args],
        cwd=repo,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
    )


def run_collect(repo: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GUIYI_SKIP_CODEX_ENV_CHECK"] = "1"
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "collect_result.sh"), "--task", task_id],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def write_plan(repo: Path, task_id: str = DISPATCH_TASK_ID) -> Path:
    out_dir = repo / ".ai" / "results" / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = out_dir / "plan_result.md"
    plan.write_text("approved plan\n", encoding="utf-8")
    return plan


def write_approval(repo: Path, task_id: str = DISPATCH_TASK_ID, *, production_write_approved: bool = False) -> None:
    plan = write_plan(repo, task_id)
    approval_dir = repo / ".ai" / "approvals"
    approval_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "task_id": task_id,
        "task_file": f"docs/tasks/{task_id}.md",
        "plan_file": f".ai/results/{task_id}/plan_result.md",
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "approved_branch": "feature/test",
        "head_commit": "0" * 40,
    }
    if production_write_approved:
        payload["production_write_approved"] = True
    (approval_dir / f"{task_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def write_test_result(repo: Path, task_id: str, *, exit_code: int = 0, status: str = "PASS", command: str = "git diff --check") -> None:
    out_dir = repo / ".ai" / "results" / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "commands_executed.tsv").write_text(f"1\t{command}\n", encoding="utf-8")
    (out_dir / "test_results.tsv").write_text(f"1\t{exit_code}\t{status}\t{command}\n", encoding="utf-8")
    (out_dir / "skipped_tests.txt").write_text("", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def route_payload(repo: Path, task_id: str, stage: str, *args: str) -> dict:
    result = run_route(repo, task_id, stage, "--json", *args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def make_dispatch_repo(
    path: Path,
    *,
    branch: str = "feature/test",
    expected_branch: str = "feature/test",
    status: str,
    task_id: str = DISPATCH_TASK_ID,
) -> Path:
    repo = path
    init_git_repo(repo, branch=branch)
    copy_workstation_scripts(repo, include_collect=False)
    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{task_id}.md").write_text(
        textwrap.dedent(
            f"""\
            # {task_id}: Dispatcher Fixture

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {task_id} |
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
    write_stubs(repo, include_collect=False)
    write_plan(repo, task_id)
    return repo


def update_task_status(repo: Path, status: str, *, task_id: str = DISPATCH_TASK_ID) -> None:
    path = repo / "docs" / "tasks" / f"{task_id}.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        next(line for line in text.splitlines() if line.startswith("| Status |")),
        f"| Status | {status} |",
    )
    path.write_text(text, encoding="utf-8")


def calls_file(repo: Path) -> Path:
    return repo / ".ai" / "stub_calls.log"


def lock_files(repo: Path) -> list[Path]:
    return list((repo / ".ai" / "locks" / "worktrees").glob("*.json"))
