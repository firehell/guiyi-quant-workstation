from __future__ import annotations

from pathlib import Path

from testkit import REPO_ROOT


SETUP = REPO_ROOT / "docs" / "workstation" / "WORKBUDDY_ASSISTANT_SETUP.md"
CARD = REPO_ROOT / "docs" / "workstation" / "WORKBUDDY_REMOTE_COMMAND_CARD.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workbuddy_assistant_setup_defines_fixed_repo_and_permissions() -> None:
    text = _read(SETUP)
    required = [
        "Mac mini 已开机",
        "WorkBuddy Assistant 已运行",
        "默认权限",
        "助理固定目录只是 WorkBuddy 的运行/会话目录，不是项目 worktree",
        "/Volumes/扩展盘/guiyi-quant-workstation",
        "git rev-parse --show-toplevel",
        "scripts/ai/workbuddy_task.sh bootstrap --issue N --json",
        "TASK 专用 worktree",
        "main 只能只读定位",
        "data/**",
        ".env",
        "生产目录",
        "手机 / 企业微信只发送",
        "不上传完整 TASK、完整 diff、完整 log、数据文件或凭据",
        "失败立即停止",
    ]
    for phrase in required:
        assert phrase in text


def test_remote_command_card_allows_only_readonly_smoke_and_bootstrap() -> None:
    text = _read(CARD)
    required = [
        "STATUS #<DEMO_ISSUE>",
        "ANALYZE #<DEMO_ISSUE>",
        "scripts/ai/workbuddy_task.sh bootstrap --issue N --json",
        "/Volumes/扩展盘/guiyi-quant-workstation",
        "N 必须是数字 Issue 编号",
        "只在 TASK worktree 中进行",
        "任一失败立即停止",
    ]
    for phrase in required:
        assert phrase in text

    forbidden = [
        "codex exec",
        "codex_plan.sh",
        "codex_dev.sh",
        "CodeBuddy",
        "git push",
        "git merge",
    ]
    for phrase in forbidden:
        assert phrase not in text


def test_remote_smoke_expected_response_fields_are_documented() -> None:
    combined = _read(SETUP) + "\n" + _read(CARD)
    for field in [
        "repo root",
        "current branch",
        "Issue",
        "TASK",
        "PR",
        "worktree",
        "current Gate",
        "result/log path",
        "file changes",
    ]:
        assert field in combined
    assert "只返回路径，不粘贴完整日志" in combined
    assert "不粘贴完整 diff" in combined


def test_remote_docs_block_sensitive_and_wrong_directory_usage() -> None:
    combined = _read(SETUP) + "\n" + _read(CARD)
    boundaries = [
        "不在 `main` 修改",
        "不写 WorkBuddy Assistant 固定目录",
        "不读取或上传 `data/**`",
        "`.env*`",
        "凭据",
        "生产目录",
        "任意 shell",
        "自动 retry",
    ]
    for phrase in boundaries:
        assert phrase in combined


def test_remote_docs_do_not_claim_demo_passed_or_perform_execution() -> None:
    combined = _read(SETUP) + "\n" + _read(CARD)
    assert "WORKBUDDY_V3_DEMO_PASSED" not in combined
    assert "自动 merge" not in combined
    assert "自动交易" in combined
