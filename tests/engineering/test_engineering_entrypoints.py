"""Engineering entrypoint tests for personal-development PowerShell contracts.

Bash preflight/test/secret/release and worktree/Lane orchestration are retired.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENG = REPO_ROOT / "scripts" / "engineering"


@pytest.mark.parametrize(
    "retired",
    [
        "preflight.sh",
        "test.sh",
        "check-secrets.sh",
        "release-flow.sh",
        "production-write-check.sh",
        "task-worktree.sh",
        "task_workflow.py",
        "worktree_flow.py",
        "runtime-promotion.sh",
        "runtime-health.sh",
    ],
)
def test_retired_bash_engineering_entrypoints_are_absent(retired: str) -> None:
    assert not (ENG / retired).exists()


@pytest.mark.parametrize(
    "active",
    [
        "preflight.ps1",
        "validate.ps1",
        "secret-scan.ps1",
        "release-tag.ps1",
        "personal_workflow.py",
        "repository_consistency.py",
    ],
)
def test_active_powershell_and_python_entrypoints_exist(active: str) -> None:
    path = ENG / active
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Invoke-Expression" not in text


def test_optional_ci_workflow_uses_pwsh() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "optional-ci.yml"
    assert workflow.is_file()
    assert not (REPO_ROOT / ".github" / "workflows" / "engineering-test.yml").exists()
    assert not (REPO_ROOT / ".github" / "workflows" / "lane-pr-gate.yml").exists()
    text = workflow.read_text(encoding="utf-8")
    assert "windows-latest" in text
    assert "preflight.ps1" in text
    assert "validate.ps1" in text
    assert "secret-scan.ps1" in text


def test_makefile_is_optional_non_canonical() -> None:
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "OPTIONAL" in text or "NON-CANONICAL" in text
    assert "preflight.ps1" in text


def test_production_write_check_deleted() -> None:
    assert not (ENG / "production-write-check.sh").exists()
