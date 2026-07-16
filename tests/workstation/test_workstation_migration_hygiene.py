from __future__ import annotations

import subprocess
from pathlib import Path

from testkit import REPO_ROOT


def _git_ls_files(*patterns: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_runtime_artifacts_are_not_tracked() -> None:
    tracked = _git_ls_files(".ai/**", ".workbuddy/**")
    assert tracked == [".ai/schema/task.schema.json"]


def test_generated_migration_outputs_are_not_tracked() -> None:
    assert _git_ls_files("outputs/workstation-github-migration/**") == []


def test_gitignore_contract_covers_runtime_and_generated_paths() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [
        ".ai/approvals/",
        ".ai/results/",
        ".ai/runtime-gates/",
        ".ai/task-runtime/",
        ".ai/tasks/",
        ".workbuddy/memory/",
        "outputs/workstation-github-migration/",
    ]:
        assert pattern in gitignore
    assert "!.ai/schema/task.schema.json" in gitignore


def test_archive_docs_are_not_current_canonical_links() -> None:
    checked = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "PROJECT_SOURCE.md",
        REPO_ROOT / "STATUS.md",
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "workstation" / "ARCHITECTURE.md",
        REPO_ROOT / "docs" / "workstation" / "GITHUB_NATIVE_CONTROL_PLANE.md",
        REPO_ROOT / "docs" / "workstation" / "WORKBUDDY_UNIFIED_V3.md",
        REPO_ROOT / "docs" / "AGENT_WORKFLOW.md",
        REPO_ROOT / "docs" / "AI_WECHAT_WORKFLOW.md",
    ]
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert "archive/pre-workbuddy-v3" not in text
        assert "docs/tasks/archive/workstation-legacy" not in text


def test_no_old_independent_state_machine_as_active_contract() -> None:
    template = (REPO_ROOT / "docs" / "tasks" / "TASK_TEMPLATE.md").read_text(encoding="utf-8")
    for old_contract in ["STATE_MACHINE_TICKET.md", "TASK_MATRIX.md", "ROLE_SPEC.md"]:
        assert old_contract not in template
    assert "WORKBUDDY_UNIFIED_V3.md" in template
    assert "GITHUB_NATIVE_CONTROL_PLANE.md" in template


def test_codebuddy_is_compatibility_only() -> None:
    codebuddy = (REPO_ROOT / "CODEBUDDY.md").read_text(encoding="utf-8")
    assert "compatibility-only" in codebuddy
    assert "不再新增功能" in codebuddy


def test_legacy_paths_no_longer_tracked_in_active_locations() -> None:
    active_files = set(
        _git_ls_files(
            "workstation/**",
            "docs/tasks/examples/V1.1-ACCEPTANCE.md",
            "docs/tasks/examples/V1.2-ACCEPTANCE.md",
            "docs/tasks/examples/V1.5-ACCEPTANCE.md",
        )
    )
    assert active_files == set()

    archive_files = set(
        _git_ls_files(
            "docs/workstation/archive/pre-workbuddy-v3/**",
            "docs/tasks/archive/workstation-legacy/**",
        )
    )
    assert "docs/workstation/archive/pre-workbuddy-v3/team/STATE_MACHINE_TICKET.md" in archive_files
    assert "docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md" in archive_files


def test_workbuddy_v3_final_status_is_demo_pending_not_frozen() -> None:
    checked = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "PROJECT_SOURCE.md",
        REPO_ROOT / "STATUS.md",
        REPO_ROOT / "docs" / "workstation" / "WORKSTATION_UPGRADE_ACCEPTANCE.md",
    ]
    for path in checked:
        text = path.read_text(encoding="utf-8")
        assert "WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING" in text
        assert "WORKBUDDY_V3_FROZEN" not in text


def test_no_invalid_active_codebuddy_flow_phrases() -> None:
    active_docs = [
        REPO_ROOT / "docs" / "AI_WECHAT_WORKFLOW.md",
        REPO_ROOT / "docs" / "AGENT_WORKFLOW.md",
        REPO_ROOT / "docs" / "workflows" / "README.md",
        REPO_ROOT / "docs" / "workflows" / "status_machine.md",
        REPO_ROOT / "docs" / "workflows" / "work_levels.md",
        REPO_ROOT / "prompts" / "workbuddy-delivery-team.md",
        REPO_ROOT / ".agents" / "skills" / "local-workstation" / "SKILL.md",
    ]
    forbidden_phrases = [
        "V1.1 主流程",
        "WorkBuddy 维护状态机",
        "用户将批准的 `PLAN #N` 发送给 CodeBuddy",
        "CodeBuddy 先 bootstrap Issue",
        "CodeBuddy 返回 Issue",
        "ChatGPT（外部）：架构和量化逻辑审查，人工粘贴 diff",
    ]
    for path in active_docs:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden_phrases:
            assert phrase not in text, f"{phrase!r} remains in {path}"


def test_github_lifecycle_cleanup_is_manual_only() -> None:
    text = (
        REPO_ROOT
        / "docs"
        / "workstation"
        / "WORKSTATION_GITHUB_LIFECYCLE_CLEANUP.md"
    ).read_text(encoding="utf-8")
    assert "本轮不执行 close、merge、mark ready、label 或 deploy" in text
    assert "需要用户确认后才能执行的命令" in text
    assert "gh issue close" in text
    assert "gh pr close" in text
