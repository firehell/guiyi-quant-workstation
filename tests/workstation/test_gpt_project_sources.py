from __future__ import annotations

import subprocess

from testkit import REPO_ROOT


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_github_read_order_exists_and_sets_default_order() -> None:
    text = read("docs/gpt/GITHUB_READ_ORDER.md")
    for term in [
        "@GitHub 读取",
        "PROJECT_SOURCE.md",
        "STATUS.md",
        "DECISIONS.md",
        "CODEX_TASKS.md",
        "docs/DATA_CENTER.md",
        "未提交的本地文件",
        "本地数据报告只允许提交脱敏总结",
    ]:
        assert term in text


def test_project_sources_index_is_navigation_not_canonical_copy() -> None:
    text = read("docs/gpt/project_sources/00-INDEX.md")
    assert "GitHub 读取导航" in text
    assert "兼容摘要包" in text
    assert "canonical 文件为准" in text
    assert "docs/gpt/GITHUB_READ_ORDER.md" in text
    assert "人工上传包的核心事实源" in text


def test_project_source_manifest_records_canonical_sources_and_audit_policy() -> None:
    text = read("docs/gpt/PROJECT_SOURCE_MANIFEST.md")
    for term in [
        "GitHub 直读模型",
        "canonical facts 只维护",
        "`docs/gpt/GITHUB_READ_ORDER.md`",
        "`PROJECT_SOURCE.md`",
        "`STATUS.md`",
        "`DECISIONS.md`",
        "`CODEX_TASKS.md`",
        "duplicate_summary",
        "local_only_evidence",
    ]:
        assert term in text


def test_project_source_index_script_check_passes() -> None:
    result = subprocess.run(
        ["python3", "scripts/docs/update_project_source_index.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "project source index check passed" in result.stdout

