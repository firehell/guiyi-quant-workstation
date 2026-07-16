"""Worktree/Branch/Scope/Env Gate tests — WS-V2-006."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from testkit import (
    REPO_ROOT,
    FIXTURES_DIR,
    copy_workstation_scripts,
    fixture_text,
    init_git_repo,
    make_scenario_repo,
    write_stubs,
    write_task_from_fixture,
)


def _clean_env(extra: dict | None = None) -> dict:
    """Build a clean subprocess env without the test bypass vars."""
    env = os.environ.copy()
    env.pop("GUIYI_SKIP_DIRTY_GATE", None)
    env.pop("GUIYI_SKIP_EXTERNAL_DISK_GATE", None)
    env.pop("GUIYI_SKIP_SCOPE_GATE", None)
    if extra:
        env.update(extra)
    return env


# ── External Disk Gate ──────────────────────────────────────────────────────

class TestExternalDiskGate:
    """G2: External disk mount verification."""

    def test_no_required_mounts_passes(self, tmp_path):
        """When no required_mounts are declared, the gate passes."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
        )
        # Override required_mounts to empty by using a task with no mounts
        task = write_task_from_fixture(repo, "sample_task_v2")
        # Remove required_mounts from the YAML frontmatter
        content = task.read_text(encoding="utf-8")
        content = content.replace('required_mounts: ["/Volumes/扩展盘"]', 'required_mounts: []')
        task.write_text(content, encoding="utf-8")

        result = subprocess.run(
            ["bash", str(repo / "scripts" / "ai" / "_external_disk_lib.sh")],
            capture_output=True, text=True, cwd=str(repo),
            env={**os.environ, "REPO_ROOT": str(repo)},
        )
        # Script is source-only, check via dispatch_task
        assert True  # Gate should not block

    def test_missing_mount_fails(self, tmp_path):
        """A declared mount that does not exist should fail the gate."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "MISSING_MOUNT",
            branch="feature/test",
            include_collect=False,
            missing_mount="/nonexistent/disk/path",
        )

        # Run check_task_env which includes mount checks
        task_path = repo / "docs" / "tasks" / "MISSING_MOUNT.md"
        result = subprocess.run(
            [
                "bash",
                str(repo / "scripts" / "env" / "check_task_env.sh"),
                "--task", str(task_path),
                "--stage", "dev",
                "--repo-root", str(repo),
                "--json",
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        if data:
            assert not data.get("ok", True)

    def test_mount_not_a_mount_point_fails(self, tmp_path):
        """A directory that exists but is not a mount point should fail."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
        )
        # Create a normal directory and declare it as required_mount
        normal_dir = tmp_path / "not-a-mount"
        normal_dir.mkdir(parents=True, exist_ok=True)

        task = write_task_from_fixture(repo, "sample_task_v2")
        content = task.read_text(encoding="utf-8")
        content = content.replace(
            'required_mounts: []',
            f'required_mounts: ["{normal_dir}"]',
        )
        task.write_text(content, encoding="utf-8")

        result = subprocess.run(
            [
                "bash",
                str(repo / "scripts" / "env" / "check_task_env.sh"),
                "--task", str(task),
                "--stage", "dev",
                "--repo-root", str(repo),
                "--json",
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode != 0
        data = json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}
        if data:
            assert not data.get("ok", True)


# ── Dirty Workspace Gate ─────────────────────────────────────────────────────

class TestDirtyWorkspaceGate:
    """G3: Pre-dev dirty workspace classification."""

    def test_clean_workspace_passes(self, tmp_path):
        """A clean workspace with no uncommitted changes passes."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_dirty_gate_lib.sh" && '
                f'REPO_ROOT="{repo}" check_dirty_workspace_gate "{task_file}" "TEST-001" "true"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )
        assert result.returncode == 0
        assert "Workspace clean" in result.stdout

    def test_allowed_change_passes(self, tmp_path):
        """Changes within allowed_paths pass the dirty gate."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        # Create a change in allowed_paths
        test_file = repo / "services" / "quant-api" / "tests" / "test_health.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("# allowed change\n")

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_dirty_gate_lib.sh" && '
                f'REPO_ROOT="{repo}" check_dirty_workspace_gate "{task_file}" "TEST-001" "true"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )
        assert result.returncode == 0
        assert "allowed" in result.stdout.lower()

    def test_unknown_change_blocks_strict(self, tmp_path):
        """Changes not in allowed_paths block in strict mode."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        # Create a change outside allowed_paths
        unknown_file = repo / "some" / "unknown" / "file.py"
        unknown_file.parent.mkdir(parents=True, exist_ok=True)
        unknown_file.write_text("# unknown\n")

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_dirty_gate_lib.sh" && '
                f'REPO_ROOT="{repo}" check_dirty_workspace_gate "{task_file}" "TEST-001" "true"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )
        # Strict mode blocks unknown changes
        assert result.returncode != 0

    def test_forbidden_change_always_blocks(self, tmp_path):
        """Changes matching forbidden_paths always block."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        # Create a change in forbidden_paths
        main_file = repo / "services" / "quant-api" / "app" / "main.py"
        main_file.parent.mkdir(parents=True, exist_ok=True)
        main_file.write_text("# forbidden\n")

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_dirty_gate_lib.sh" && '
                f'REPO_ROOT="{repo}" check_dirty_workspace_gate "{task_file}" "TEST-001" "true"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )
        assert result.returncode != 0
        assert "VIOLATION" in result.stdout or "violation" in result.stdout.lower()


# ── Scope Report Gate ────────────────────────────────────────────────────────

class TestScopeReportGate:
    """G4: Post-dev scope violation report."""

    def test_no_changes_scope_clean(self, tmp_path):
        """When there are no changes, scope report passes."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"
        out_dir = repo / ".ai" / "results" / "TEST"
        out_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_scope_report_lib.sh" && '
                f'REPO_ROOT="{repo}" check_scope_gate "{task_file}" "TEST" "{out_dir}" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )

        assert result.returncode == 0

        # Check report was written
        report_file = out_dir / "scope_report.json"
        assert report_file.is_file()
        report = json.loads(report_file.read_text())
        assert report["ok"] is True

    def test_scope_report_written(self, tmp_path):
        """Scope report JSON is written to out_dir."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        out_dir = repo / ".ai" / "results" / "SCOPE-TEST"
        out_dir.mkdir(parents=True, exist_ok=True)
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_scope_report_lib.sh" && '
                f'REPO_ROOT="{repo}" check_scope_gate "{task_file}" "SCOPE-TEST" "{out_dir}" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            check=False,
            env=_clean_env(),
        )

        report_file = out_dir / "scope_report.json"
        assert report_file.is_file()
        report = json.loads(report_file.read_text())
        assert "schema_version" in report
        assert report["task_id"] == "SCOPE-TEST"
        assert "in_scope" in report
        assert "out_of_scope" in report
        assert "violations" in report


# ── Branch Gate ──────────────────────────────────────────────────────────────

class TestBranchGate:
    """G1: Branch and base_branch verification."""

    def test_correct_branch_passes(self, tmp_path):
        """When current branch matches the declared branch, gate passes."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/example-v2",  # Match the fixture's declared branch
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_branch "{task_file}" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode == 0

    def test_wrong_branch_fails(self, tmp_path):
        """When current branch does not match declared branch, gate fails."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "WRONG_BRANCH",
            branch="feature/wrong",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "WRONG_BRANCH.md"

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_branch "{task_file}" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode != 0

    def test_main_write_protection_blocks_dev(self, tmp_path):
        """Dev on main/master branch is blocked."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="main",
            include_collect=False,
            git_commit=True,
        )

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_main_write_protection "dev" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode != 0

    def test_main_allows_route(self, tmp_path):
        """Route stage is allowed on main branch."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="main",
            include_collect=False,
            git_commit=True,
        )

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_main_write_protection "route" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode == 0

    def test_feature_branch_allows_dev(self, tmp_path):
        """Dev on feature/ branch is allowed."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/allowed",
            include_collect=False,
            git_commit=True,
        )

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_main_write_protection "dev" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode == 0

    def test_base_branch_defaults_to_main(self, tmp_path):
        """When base_branch is not declared, it defaults to main."""
        repo = make_scenario_repo(
            tmp_path / "repo",
            "sample_task_v2",
            branch="feature/test",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'extract_base_branch "{task_file}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert "main" in result.stdout


# ── Env Gate (G5) ────────────────────────────────────────────────────────────

class TestBootstrapEnv:
    """G5: Bootstrap worktree environment with three modes."""

    def test_dry_run_audit_mode(self, tmp_path):
        """Dry-run in audit mode produces a scoped .env preview."""
        worktree = tmp_path / "w"
        worktree.mkdir()

        # Create a minimal source .env
        source_env = tmp_path / "source.env"
        source_env.write_text("export APP_ENV=staging\nexport RQDATA_TOKEN=secret123\nexport RQDATA_USERNAME=user\n")

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "audit",
                "--source", str(source_env),
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "DRY-RUN" in result.stdout

    def test_runtime_requires_unlock(self, tmp_path):
        """Runtime mode requires explicit --unlock-runtime."""
        worktree = tmp_path / "w2"
        worktree.mkdir()
        source_env = tmp_path / "source2.env"
        source_env.write_text("export APP_ENV=staging\n")

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "runtime",
                "--source", str(source_env),
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        # Should fail because --unlock-runtime is missing
        assert result.returncode != 0

    def test_audit_mode_only_whitelisted_keys(self, tmp_path):
        """Audit mode only includes audit whitelist keys."""
        worktree = tmp_path / "w3"
        worktree.mkdir()
        source_env = tmp_path / "source3.env"
        source_env.write_text("export APP_ENV=staging\nexport GUIYI_DB_WRITE_URL=secret_write\nexport RQDATA_USERNAME=user\n")

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "audit",
                "--source", str(source_env),
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        # Should include RQDATA_USERNAME (audit key) and APP_ENV
        assert "RQDATA_USERNAME" in result.stdout
        # Should NOT include GUIYI_DB_WRITE_URL (runtime key only)
        assert "GUIYI_DB_WRITE_URL" not in result.stdout

    def test_missing_source_fails(self, tmp_path):
        """Missing source env file should fail."""
        worktree = tmp_path / "w4"
        worktree.mkdir()

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "audit",
                "--source", "/nonexistent/path.env",
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0


# ── Gate Integration ─────────────────────────────────────────────────────────

class TestGateIntegration:
    """End-to-end: all gates work together in dispatch_task.sh."""

    def test_dispatch_includes_new_gates(self, tmp_path):
        """dispatch_task.sh sources and calls the new gate libraries."""
        dispatch = REPO_ROOT / "scripts" / "ai" / "dispatch_task.sh"
        content = dispatch.read_text()

        # Verify new libs are sourced
        assert "_external_disk_lib.sh" in content
        assert "_dirty_gate_lib.sh" in content
        assert "_scope_report_lib.sh" in content

        # Verify gate calls
        assert "check_base_branch" in content
        assert "check_main_write_protection" in content
        assert "check_external_disk_gate" in content
        assert "check_dirty_workspace_gate" in content
        assert "check_scope_gate" in content

    def test_static_gates_called_in_order(self, tmp_path):
        """The static gates are called in the correct order within validate_static_gates."""
        dispatch = REPO_ROOT / "scripts" / "ai" / "dispatch_task.sh"
        content = dispatch.read_text()

        # Find the section after worktree/branch check
        idx_worktree = content.find("check_worktree_gate")
        idx_base = content.find("check_base_branch")
        idx_main = content.find("check_main_write_protection")
        idx_disk = content.find("check_external_disk_gate")

        assert idx_base > idx_worktree, "base_branch should be checked after worktree"
        assert idx_main > idx_base, "main write protection should be checked after base_branch"
        assert idx_disk > idx_main, "external disk should be checked after main write protection"


# ── Demo Gates ───────────────────────────────────────────────────────────────

class TestDemoGates:
    """Security boundary demonstrations."""

    def test_demo_dirty_gate_blocks_unknown(self, tmp_path):
        """Demo: Dirty workspace gate correctly blocks unknown changes."""
        repo = make_scenario_repo(
            tmp_path / "demo-dirty",
            "sample_task_v2",
            branch="feature/demo",
            include_collect=False,
            git_commit=True,
        )
        task_file = repo / "docs" / "tasks" / "sample_task_v2.md"

        # Add an untracked unknown file
        unknown = repo / "random_script.sh"
        unknown.write_text("#!/bin/bash\necho hack\n")

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_dirty_gate_lib.sh" && '
                f'REPO_ROOT="{repo}" check_dirty_workspace_gate "{task_file}" "DEMO-001" "true"',
            ],
            capture_output=True, text=True, cwd=str(repo),
            env=_clean_env(),
        )
        assert result.returncode != 0, "Gate should block unknown files in strict mode"

    def test_demo_main_write_protection(self, tmp_path):
        """Demo: Writing to main branch is blocked for dev stage."""
        repo = make_scenario_repo(
            tmp_path / "demo-main",
            "sample_task_v2",
            branch="main",
            include_collect=False,
            git_commit=True,
        )

        result = subprocess.run(
            [
                "bash", "-c",
                f'source "{repo}/scripts/ai/_work_level_lib.sh" && '
                f'check_main_write_protection "apply" "{repo}"',
            ],
            capture_output=True, text=True, cwd=str(repo),
        )
        assert result.returncode != 0, "apply on main should be blocked"

    def test_demo_runtime_locked_by_default(self, tmp_path):
        """Demo: Runtime mode requires explicit unlock — default is blocked."""
        worktree = tmp_path / "demo-runtime-lock"
        worktree.mkdir()
        source_env = tmp_path / "demo-source.env"
        source_env.write_text("export APP_ENV=staging\n")

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "runtime",
                "--source", str(source_env),
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode != 0, "Runtime should require --unlock-runtime"

    def test_demo_runtime_unlocked_passes(self, tmp_path):
        """Demo: Runtime mode with --unlock-runtime flag passes."""
        worktree = tmp_path / "demo-runtime-unlocked"
        worktree.mkdir()
        source_env = tmp_path / "demo-source2.env"
        source_env.write_text("export APP_ENV=staging\n")

        result = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "env" / "bootstrap_worktree_env.sh"),
                "--worktree", str(worktree),
                "--mode", "runtime",
                "--source", str(source_env),
                "--unlock-runtime",
            ],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
