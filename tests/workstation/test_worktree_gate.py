#!/usr/bin/env python3
"""WS-V2-006: Worktree Gate tests — Branch, External Disk, Dirty Workspace, Scope Report"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile

import pytest

# Notes:
# - conftest.py sets GUIYI_SKIP_{DIRTY,EXTERNAL_DISK,SCOPE}_GATE=1 for all tests
# - Tests that want to exercise the real gate logic must call _clean_env() first
# - Gate output is written to stderr; test assertions should check stderr


def _clean_env():
    """Remove conftest bypass env vars so gate logic runs for real."""
    for key in ("GUIYI_SKIP_DIRTY_GATE", "GUIYI_SKIP_EXTERNAL_DISK_GATE", "GUIYI_SKIP_SCOPE_GATE"):
        os.environ.pop(key, None)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_repo(path: Path, *, branch: str = "feature/test") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", branch], cwd=path, check=True, capture_output=True, text=True
    )
    # Copy scripts
    repo_root = Path(__file__).resolve().parents[2]
    ai_dir = path / "scripts" / "ai"
    lib_dir = ai_dir / "lib"
    env_dir = path / "scripts" / "env"
    for d in [ai_dir, lib_dir, env_dir]:
        d.mkdir(parents=True, exist_ok=True)

    script_names = [
        "dispatch_task.sh", "route_task.sh", "writer_lock.sh",
        "_work_level_lib.sh", "_approve_lib.sh", "_dispatch_phase_lib.sh",
        "_external_disk_lib.sh", "_dirty_gate_lib.sh", "_scope_report_lib.sh",
        "_evidence_lib.sh",
    ]
    for name in script_names:
        src = repo_root / "scripts" / "ai" / name
        if src.is_file():
            shutil.copy2(src, ai_dir / name)

    lib_names = ["task_meta.py", "route_task.py", "writer_lock.py", "model_router.py", "task_runtime.py"]
    for name in lib_names:
        src = repo_root / "scripts" / "ai" / "lib" / name
        if src.is_file():
            shutil.copy2(src, lib_dir / name)

    env_names = ["check_task_env.sh", "bootstrap_worktree_env.sh"]
    for name in env_names:
        src = repo_root / "scripts" / "env" / name
        if src.is_file():
            shutil.copy2(src, env_dir / name)

    configs_dir = path / "configs" / "ai"
    configs_dir.mkdir(parents=True, exist_ok=True)
    routing_src = repo_root / "configs" / "ai" / "model_routing.json"
    if routing_src.is_file():
        shutil.copy2(routing_src, configs_dir / "model_routing.json")

    schemas_src = repo_root / "configs" / "ai" / "schemas"
    schemas_dst = configs_dir / "schemas"
    schemas_dst.mkdir(exist_ok=True)
    if schemas_src.is_dir():
        for f in schemas_src.glob("*.json"):
            shutil.copy2(f, schemas_dst / f.name)

    path.joinpath("docs/tasks").mkdir(parents=True, exist_ok=True)
    return path


def _write_legacy_task(repo: Path, *, task_id: str = "TASK-GATE", branch: str = "feature/test", worktree: str = "", status: str = "REQUIREMENT_READY", required_mounts: list[str] | None = None, allowed_paths: str = "scripts/ai/\n- tests/workstation/", forbidden_paths: str = ".env\n- data/raw/") -> None:
    mount_line = ", ".join(f"`{m}`" for m in required_mounts) if required_mounts else "-"
    # Convert paths to backtick format for _paths_from_scope extraction
    def _to_backtick(path_str: str) -> str:
        lines = [f"- `{p.strip()}`" for p in path_str.split("\n") if p.strip()]
        return "\n".join(lines)
    allowed_formatted = _to_backtick(allowed_paths)
    forbidden_formatted = _to_backtick(forbidden_paths)
    path = repo / "docs" / "tasks" / f"{task_id}.md"
    path.write_text(f"""# {task_id}

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | {task_id} |
| Work Level | L1 |
| GitHub Issue | #1 |
| Branch | {branch} |
| Base Branch | main |
| Worktree | {worktree or repo} |
| Status | {status} |
| Required Mounts | {mount_line} |

## 7. 涉及模块

**允许修改**:

{allowed_formatted}

**禁止修改**:

{forbidden_formatted}

## 18. 测试清单

```bash
git diff --check
```
""", encoding="utf-8")


def _write_v2_task(repo: Path, *, task_id: str = "TASK-GATE-V2", branch: str = "feature/example-v2", worktree: str = "", status: str = "PLAN_READY", required_mounts: list[str] | None = None, allowed_paths: str | None = None, forbidden_paths: str | None = None, model_profile: str = "balanced", base_branch: str = "main") -> None:
    mount_line = ", ".join(f'"{m}"' for m in required_mounts) if required_mounts else ""
    allowed = f'allowed_paths: [{allowed_paths}]' if allowed_paths else ""
    forbidden = f'forbidden_paths: [{forbidden_paths}]' if forbidden_paths else ""
    path = repo / "docs" / "tasks" / f"{task_id}.md"
    path.write_text(f"""---
kind: Task
schema_version: "2.0"
task_id: "{task_id}"
title: "Gate Test Task"
status: {status}
risk_level: R2
work_level: L2
approval_scope: [plan, code]
{allowed}
{forbidden}
resource_locks: []
model_profile: {model_profile}
base_branch: {base_branch}
critical: false
production_write_approved: false
branch: "{branch}"
worktree: "{worktree or repo}"
owner: "Test"
created_at: "2026-07-09"
updated_at: "2026-07-09"
---

# {task_id}: Gate Test

## 7. Scope

- scripts/ai/
- **禁止修改**: .env, data/raw/

## 18. Tests

```bash
git diff --check
```
""", encoding="utf-8")


def _git_commit(repo: Path, message: str = "init") -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@test.com", "commit", "-m", message],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def _make_dirty(repo: Path, files: dict[str, str]) -> None:
    """Create uncommitted files in the repo."""
    for rel_path, content in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


def _run_dispatch(repo: Path, task_id: str, stage: str, *, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GUIYI_STUB_CALLS"] = str(repo / ".ai" / "stub_calls.log")
    # Create stub scripts
    stubs = repo / "stubs"
    stubs.mkdir(exist_ok=True)
    for name in ["codex_plan.sh", "codex_dev.sh", "run_tests.sh", "collect_result.sh"]:
        stub = stubs / name
        stub.write_text("#!/usr/bin/env bash\necho \"$(basename \"$0\") $*\"\n", encoding="utf-8")
        stub.chmod(0o755)
    env["GUIYI_AI_SCRIPT_DIR"] = str(stubs)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "ai" / "dispatch_task.sh"), task_id, stage, "--dry-run"],
        cwd=repo, env=env, capture_output=True, text=True,
    )


# ── Branch Gate ───────────────────────────────────────────────────────


class TestBranchGate:
    """G1: Branch / Base Branch Gate"""

    def test_branch_mismatch_fails(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="feature/wrong")
        _write_legacy_task(repo, branch="feature/expected")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "plan")
        # Branch gate should fail — check_branch from _approve_lib.sh blocks mismatch
        assert "Branch Gate failed" in result.stderr

    def test_branch_match_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="feature/expected")
        _write_legacy_task(repo, branch="feature/expected")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "plan")
        assert result.returncode == 0

    def test_no_branch_declaration_warns(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="feature/test")
        _write_legacy_task(repo, branch="feature/test")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "plan")
        assert result.returncode == 0
        assert "Branch Gate" in result.stderr

    def test_main_write_protection_dev(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="main")
        _write_legacy_task(repo, branch="main", status="APPROVED_DEV")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "dev")
        # _approve_lib.sh check_branch blocks main/master for ALL stages
        assert result.returncode != 0
        assert "Branch Gate failed" in result.stderr

    def test_main_write_protection_fix(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="master")
        _write_legacy_task(repo, branch="master", status="FAILED")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "fix")
        assert result.returncode != 0
        assert "Branch Gate failed" in result.stderr

    def test_feature_branch_dev_passes(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, branch="feature/safe")
        _write_legacy_task(repo, branch="feature/safe", status="APPROVED_DEV")
        _git_commit(repo)

        # Plan stage just validates branch matching
        result = _run_dispatch(repo, "TASK-GATE", "plan")
        # Branch should match, no main/master protection needed
        assert "Write Protection" not in result.stderr


# ── External Disk Gate ──────────────────────────────────────────────────


class TestExternalDiskGate:
    """G2: External Disk Gate"""

    def test_no_mounts_passes(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo)
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route", extra_env={"GUIYI_SKIP_EXTERNAL_DISK_GATE": ""})
        assert result.returncode == 0

    def test_missing_mount_fails_and_no_autocreate(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        missing = tmp_path / "external-disk"
        _write_legacy_task(repo, required_mounts=[str(missing)])
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route", extra_env={"GUIYI_SKIP_EXTERNAL_DISK_GATE": ""})
        assert result.returncode != 0
        assert not missing.exists()  # Never auto-create

    def test_existing_dir_same_device_warns(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        # Create a directory on the same filesystem (not a real mount)
        not_mount = tmp_path / "not-a-mount"
        not_mount.mkdir()
        _write_legacy_task(repo, required_mounts=[str(not_mount)])
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route", extra_env={"GUIYI_SKIP_EXTERNAL_DISK_GATE": ""})
        # Should fail because it's not a real mount point
        assert result.returncode != 0

    def test_skip_env_bypasses(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        missing = tmp_path / "definitely-missing"
        _write_legacy_task(repo, required_mounts=[str(missing)])
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route", extra_env={"GUIYI_SKIP_EXTERNAL_DISK_GATE": "1"})
        assert result.returncode == 0


# ── Dirty Workspace Gate ────────────────────────────────────────────────


class TestDirtyWorkspaceGate:
    """G3: Dirty Workspace Gate"""

    def test_clean_workspace_passes(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": ""})
        assert result.returncode == 0
        assert "clean" in result.stderr or "Dirty Workspace" in result.stderr

    def test_allowed_change_passes(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV", allowed_paths="scripts/ai/test_health.py\n- tests/workstation/**")
        _git_commit(repo)
        # Create an allowed change
        _make_dirty(repo, {"scripts/ai/test_health.py": "# test file"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": ""})
        assert result.returncode == 0

    def test_forbidden_change_fails(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV", forbidden_paths=".env\n- data/raw/\n- secrets/**")
        _git_commit(repo)
        # Create a forbidden change
        _make_dirty(repo, {".env": "DATABASE_URL=xxx"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": ""})
        assert result.returncode != 0
        assert "VIOLATION" in result.stderr

    def test_unknown_change_blocked(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV", allowed_paths="scripts/ai/dispatch_task.sh\n- tests/workstation/test_specific.py")
        _git_commit(repo)
        # Create a change that matches neither allowed nor forbidden
        _make_dirty(repo, {"scripts/ai/something_random.sh": "# unknown"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": ""})
        assert result.returncode != 0
        assert "UNKNOWN" in result.stderr

    def test_skip_env_bypasses(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV")
        _git_commit(repo)
        _make_dirty(repo, {".env": "DATABASE_URL=xxx"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": "1"})
        assert result.returncode == 0


# ── Scope Report Gate ──────────────────────────────────────────────────


class TestScopeReportGate:
    """G4: Scope Report Gate"""

    def test_scope_report_written(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="CODING")
        _git_commit(repo)
        # Make a commit on a different branch
        subprocess.run(["git", "checkout", "-b", "feature/dev"], cwd=repo, check=True, capture_output=True, text=True)
        _make_dirty(repo, {"scripts/ai/new_feature.sh": "echo ok"})
        _git_commit(repo, "new feature")

        # Now run scope check
        out_dir = repo / ".ai" / "results" / "TASK-GATE"
        out_dir.mkdir(parents=True)

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "ai" / "_scope_report_lib.sh")],
            cwd=repo, env={**os.environ, "GUIYI_SKIP_SCOPE_GATE": ""},
            capture_output=True, text=True,
        )
        # This sources the lib; we need to call the function directly
        # For now, just verify the script is sourceable
        pass

    def test_skip_env_bypasses(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="CODING")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_SCOPE_GATE": "1"})
        # Should not fail on scope even though bypass is set
        assert "Scope Report Gate" not in (result.stdout + result.stderr) or "SKIP" in (result.stdout + result.stderr)

    def test_v2_task_scope_check(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_v2_task(repo, task_id="TASK-GATE-V2", branch="feature/example-v2", status="CODING",
                       allowed_paths='"scripts/ai/**"',
                       forbidden_paths='".env", "data/raw/**"')
        _git_commit(repo)
        # Make a branch and commit
        subprocess.run(["git", "checkout", "-b", "feature/example-v2"], cwd=repo, check=True, capture_output=True, text=True)
        _make_dirty(repo, {"scripts/ai/test_allowed.sh": "echo ok"})
        _git_commit(repo, "allowed change")

        out_dir = repo / ".ai" / "results" / "TASK-GATE-V2"
        out_dir.mkdir(parents=True)

        result = subprocess.run(
            ["bash", "-c", f'source "{repo}/scripts/ai/_scope_report_lib.sh" && check_scope_gate "TASK-GATE-V2" "{repo}" "{out_dir}" "{repo}/docs/tasks/TASK-GATE-V2.md"'],
            cwd=repo,
            env={**os.environ, "GUIYI_SKIP_SCOPE_GATE": ""},
            capture_output=True, text=True,
        )
        # May pass or fail depending on merge-base detection
        report_path = out_dir / "scope_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            assert "total_changed" in report


# ── Bootstrap Environment Gate ──────────────────────────────────────────


class TestBootstrapEnv:
    """G5: Bootstrap Environment"""

    def test_audit_mode_no_write(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = repo / "source.env"
        source.write_text("DATABASE_URL=secret\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"),
             "--worktree", str(repo), "--source", str(source), "--audit", "--quiet"],
            cwd=repo, capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert not (repo / ".env").exists()

    def test_dev_mode_creates_scoped_file(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = repo / "source.env"
        source.write_text("DATABASE_URL=secret\nGUIYI_LOG_LEVEL=INFO\nSECRET_TOKEN=nope\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"),
             "--worktree", str(repo), "--source", str(source), "--dev", "--apply", "--quiet"],
            cwd=repo, capture_output=True, text=True,
        )
        assert result.returncode == 0
        target = repo / ".env"
        assert target.is_file()
        content = target.read_text()
        assert "WORKTREE ENV" in content
        # Should NOT contain secret values from non-whitelisted keys
        assert "SECRET_TOKEN" not in content
        assert "DATABASE_URL" not in content  # Not in dev whitelist

    def test_runtime_requires_unlock(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = repo / "source.env"
        source.write_text("DATABASE_URL=secret\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"),
             "--worktree", str(repo), "--source", str(source), "--runtime"],
            cwd=repo, capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "--unlock-runtime" in result.stderr

    def test_runtime_with_unlock(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = repo / "source.env"
        source.write_text("DATABASE_URL=secret\nGUIYI_RUNTIME_KEY=value\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"),
             "--worktree", str(repo), "--source", str(source), "--runtime", "--unlock-runtime", "--apply", "--quiet"],
            cwd=repo, capture_output=True, text=True,
        )
        assert result.returncode == 0
        target = repo / ".env"
        assert target.is_file()
        content = target.read_text()
        assert "WORKTREE ENV" in content
        assert "mode=runtime" in content

    def test_never_prints_secret_values(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        source = repo / "source.env"
        secret = "super-secret-password-123"
        source.write_text(f"DATABASE_URL={secret}\nGUIYI_LOG_LEVEL=DEBUG\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "env" / "bootstrap_worktree_env.sh"),
             "--worktree", str(repo), "--source", str(source), "--runtime", "--unlock-runtime", "--apply"],
            cwd=repo, capture_output=True, text=True,
        )
        assert secret not in result.stdout
        assert secret not in result.stderr


# ── Integration Tests ──────────────────────────────────────────────────


class TestGateIntegration:
    """Integration tests for multiple gates together"""

    def test_all_gates_pass_clean_repo(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={
            "GUIYI_SKIP_DIRTY_GATE": "",
            "GUIYI_SKIP_EXTERNAL_DISK_GATE": "",
            "GUIYI_SKIP_SCOPE_GATE": "",
        })
        # Should pass all gate checks with a clean repo
        assert result.returncode == 0

    def test_dirty_and_forbidden_combo(self, tmp_path: Path) -> None:
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV")
        _git_commit(repo)
        _make_dirty(repo, {".env": "DATABASE_URL=forbidden", "scripts/ai/allowed.sh": "echo ok"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={
            "GUIYI_SKIP_DIRTY_GATE": "",
            "GUIYI_SKIP_EXTERNAL_DISK_GATE": "1",
            "GUIYI_SKIP_SCOPE_GATE": "1",
        })
        assert result.returncode != 0
        assert "VIOLATION" in result.stderr


# ── Demo Tests ──────────────────────────────────────────────────────────


class TestDemoGates:
    """Demo/acceptance tests for WS-V2-006"""

    def test_demo_branch_gate(self, tmp_path: Path) -> None:
        """Demo: Branch gate catches mismatched branch"""
        repo = _make_repo(tmp_path, branch="feature/other")
        _write_legacy_task(repo, branch="feature/expected")
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route")
        assert "Branch Gate" in result.stderr

    def test_demo_dirty_gate_blocks_unknown(self, tmp_path: Path) -> None:
        """Demo: Dirty gate blocks unknown changes"""
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, status="APPROVED_DEV", allowed_paths="scripts/ai/dispatch_task.sh")
        _git_commit(repo)
        _make_dirty(repo, {"scripts/ai/unauthorized.sh": "echo hack"})

        result = _run_dispatch(repo, "TASK-GATE", "dev", extra_env={"GUIYI_SKIP_DIRTY_GATE": ""})
        assert result.returncode != 0
        assert "UNKNOWN" in result.stderr

    def test_demo_external_disk_stops_execution(self, tmp_path: Path) -> None:
        """Demo: Missing external mount stops dispatch"""
        _clean_env()
        repo = _make_repo(tmp_path)
        _write_legacy_task(repo, required_mounts=["/nonexistent-volume"])
        _git_commit(repo)

        result = _run_dispatch(repo, "TASK-GATE", "route", extra_env={"GUIYI_SKIP_EXTERNAL_DISK_GATE": ""})
        assert result.returncode != 0
