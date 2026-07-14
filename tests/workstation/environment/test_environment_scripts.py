from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "TASK-ENV"


def test_missing_env_fails_without_leaking_values(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=["DATABASE_URL"], required_mounts=["/"])
    secret = "postgresql+psycopg://guiyi:secret-password@127.0.0.1:5432/guiyi_quant"

    result = run_check(repo, env={**os.environ, "DATABASE_URL": "", "GUIYI_ENV_SOURCE": ""})

    assert result.returncode == 1
    assert "missing_env:DATABASE_URL" in result.stderr
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_env_file_key_satisfies_required_env_without_value_output(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=["DATABASE_URL"], required_mounts=["/"])
    env_source = repo / "safe.env"
    secret = "postgresql+psycopg://guiyi:secret-password@127.0.0.1:5432/guiyi_quant"
    env_source.write_text(f"DATABASE_URL={secret}\n", encoding="utf-8")

    result = run_check(repo, "--json", env={**os.environ, "GUIYI_ENV_SOURCE": str(env_source)})

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["checks"]["env"] == [{"name": "DATABASE_URL", "present": True, "source": "env_file"}]
    assert secret not in result.stdout


def test_missing_mount_fails_and_does_not_create_directory(tmp_path: Path) -> None:
    missing_mount = tmp_path / "external-disk"
    repo = make_repo(tmp_path / "repo", required_env=[], required_mounts=[str(missing_mount)])

    result = run_check(repo)

    assert result.returncode == 1
    assert f"missing_mount:{missing_mount}" in result.stderr
    assert not missing_mount.exists()


def test_bootstrap_dry_run_does_not_write_env(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=[], required_mounts=[])
    source = repo / "source.env"
    source.write_text("DATABASE_URL=secret\n", encoding="utf-8")

    result = run_bootstrap(repo, "--source", str(source), "--dev")

    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN]" in result.stdout
    assert not (repo / ".env").exists()
    assert "secret" not in result.stdout


def test_bootstrap_dev_mode_creates_scoped_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=[], required_mounts=[])
    source = repo / "source.env"
    source.write_text("DATABASE_URL=secret\nGUIYI_LOG_LEVEL=INFO\n", encoding="utf-8")

    result = run_bootstrap(repo, "--source", str(source), "--dev", "--apply")

    assert result.returncode == 0, result.stderr
    target = repo / ".env"
    assert target.is_file()
    assert not target.is_symlink()
    content = target.read_text(encoding="utf-8")
    assert "WORKTREE ENV" in content
    assert "mode=dev" in content
    assert "secret" not in result.stdout


def test_bootstrap_refuses_to_overwrite_regular_env(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=[], required_mounts=[])
    source = repo / "source.env"
    source.write_text("DATABASE_URL=secret\n", encoding="utf-8")
    (repo / ".env").write_text("DATABASE_URL=local\n", encoding="utf-8")

    result = run_bootstrap(repo, "--source", str(source), "--dev", "--apply")

    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert not (repo / ".env").is_symlink()


def test_dispatch_blocks_before_child_when_env_missing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, required_env=["DATABASE_URL"], required_mounts=["/"], status="TESTING")
    write_stubs(repo)

    result = subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), TASK_ID, "result"],
        cwd=repo,
        env={
            **os.environ,
            "GUIYI_AI_SCRIPT_DIR": str(repo / "stubs"),
            "GUIYI_STUB_CALLS": str(repo / ".ai" / "stub_calls.log"),
            "DATABASE_URL": "",
            "GUIYI_ENV_SOURCE": "",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "missing_env:DATABASE_URL" in result.stderr
    assert not (repo / ".ai" / "stub_calls.log").exists()
    env_check = json.loads((repo / ".ai" / "results" / TASK_ID / "env_check.json").read_text(encoding="utf-8"))
    assert env_check["ok"] is False


def make_repo(
    path: Path,
    *,
    required_env: list[str],
    required_mounts: list[str],
    status: str = "REQUIREMENT_READY",
) -> Path:
    repo = path
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "feature/test"], cwd=repo, check=True, capture_output=True, text=True)

    ai_dir = repo / "scripts" / "ai"
    env_dir = repo / "scripts" / "env"
    lib_dir = ai_dir / "lib"
    lib_dir.mkdir(parents=True)
    env_dir.mkdir(parents=True)
    for name in ["dispatch_task.sh", "route_task.sh", "writer_lock.sh", "_work_level_lib.sh", "_approve_lib.sh", "_dispatch_phase_lib.sh", "_external_disk_lib.sh", "_dirty_gate_lib.sh", "_scope_report_lib.sh", "_evidence_lib.sh"]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / name, ai_dir / name)
    for name in ["task_meta.py", "route_task.py", "writer_lock.py", "model_router.py", "task_runtime.py"]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / name, lib_dir / name)
    for name in ["check_task_env.sh", "bootstrap_worktree_env.sh"]:
        shutil.copy2(REPO_ROOT / "scripts" / "env" / name, env_dir / name)
    # Copy routing config
    routing_config = REPO_ROOT / "configs" / "ai" / "model_routing.json"
    configs_dir = repo / "configs" / "ai"
    configs_dir.mkdir(parents=True, exist_ok=True)
    if routing_config.is_file():
        shutil.copy2(routing_config, configs_dir / "model_routing.json")
    # Copy schemas
    schemas_src = REPO_ROOT / "configs" / "ai" / "schemas"
    schemas_dst = configs_dir / "schemas"
    schemas_dst.mkdir(exist_ok=True)
    if schemas_src.is_dir():
        for schema_file in schemas_src.glob("*.json"):
            shutil.copy2(schema_file, schemas_dst / schema_file.name)

    task_dir = repo / "docs" / "tasks"
    task_dir.mkdir(parents=True)
    task_dir.joinpath(f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            # {TASK_ID}

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {TASK_ID} |
            | Work Level | L1 |
            | GitHub Issue | 待创建 |
            | Branch | feature/test |
            | Worktree | {repo} |
            | Status | {status} |
            | Required Env | {', '.join(required_env) if required_env else '-'} |
            | Required Mounts | {', '.join(required_mounts) if required_mounts else '-'} |
            | Created At | 2026-07-12 |
            | Owner | test |

            ## 18. 测试清单

            ### 18.0 自动化测试命令

            ```bash
            git diff --check
            ```
            """
        ),
        encoding="utf-8",
    )
    return repo


def run_check(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "env" / "check_task_env.sh"), "--task", TASK_ID, "--stage", "test", *args],
        cwd=repo,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
    )


def run_bootstrap(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"), "--worktree", str(repo), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def write_stubs(repo: Path) -> None:
    stubs = repo / "stubs"
    stubs.mkdir()
    script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        echo "$(basename "$0") $*" >> "$GUIYI_STUB_CALLS"
        """
    )
    for name in ["codex_plan.sh", "codex_dev.sh", "run_tests.sh", "collect_result.sh"]:
        path = stubs / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
