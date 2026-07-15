#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "docs" / "gpt" / "project_sources" / "00-INDEX.md"
MANIFEST_PATH = ROOT / "docs" / "gpt" / "PROJECT_SOURCE_MANIFEST.md"
READ_ORDER_PATH = ROOT / "docs" / "gpt" / "GITHUB_READ_ORDER.md"


@dataclass(frozen=True)
class SourceEntry:
    path: str
    category: str
    canonical_source: str
    state: str
    recommended: str
    notes: str


ENTRIES: tuple[SourceEntry, ...] = (
    SourceEntry("docs/gpt/project_sources/00-INDEX.md", "navigation", "PROJECT_SOURCE.md; STATUS.md; CODEX_TASKS.md", "current_navigation", "yes", "GitHub read navigation"),
    SourceEntry("docs/gpt/GITHUB_READ_ORDER.md", "navigation", "PROJECT_SOURCE.md; STATUS.md; DECISIONS.md; CODEX_TASKS.md", "current_navigation", "yes", "Default GPT GitHub read order"),
    SourceEntry("PROJECT_SOURCE.md", "project", "self", "canonical_current", "yes", "Project boundary and source-of-truth map"),
    SourceEntry("STATUS.md", "status", "self", "canonical_current", "yes", "Current state and unfinished gates"),
    SourceEntry("DECISIONS.md", "decisions", "self", "canonical_current", "yes", "Accepted decisions and pending decisions"),
    SourceEntry("CODEX_TASKS.md", "tasks", "self", "canonical_current", "yes", "Current task pool and next steps"),
    SourceEntry("docs/gpt/PROJECT_SOURCE_MANIFEST.md", "manifest", "self", "current_navigation", "yes", "Source inventory and policy"),
    SourceEntry("docs/DATA_CENTER.md", "deep_canonical", "self", "canonical_current", "topic", "Data-layer canonical details"),
    SourceEntry("docs/ARCHITECTURE.md", "deep_canonical", "self", "canonical_current", "topic", "Architecture canonical details"),
    SourceEntry("docs/BACKTEST_ENGINE.md", "deep_canonical", "self", "canonical_current", "topic", "Backtest canonical details"),
    SourceEntry("docs/SIGNAL_EVENTS.md", "deep_canonical", "self", "canonical_current", "topic", "Signal and WeCom canonical details"),
    SourceEntry("docs/CODEX_HANDOFF.md", "deep_canonical", "self", "canonical_current", "topic", "Codex handoff state"),
    SourceEntry("tasks/current.md", "task_state", "self", "current_task", "topic", "Current local task state"),
    SourceEntry("docs/gpt/project_sources/01-PROJECT-SOURCE.md", "compat_summary", "PROJECT_SOURCE.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/02-CURRENT-STATUS.md", "compat_summary", "STATUS.md; tasks/current.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/03-ARCHITECTURE.md", "compat_summary", "docs/ARCHITECTURE.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/04-DATA-LAYER.md", "compat_summary", "docs/DATA_CENTER.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/05-INDICATOR-STRATEGY-KERNEL.md", "compat_summary", "packages/quant-core/README.md; docs/INDICATOR_KERNEL.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/06-WEB.md", "compat_summary", "docs/ARCHITECTURE.md; apps/quant-web/src/app/router.ts", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/07-BACKTEST.md", "compat_summary", "docs/BACKTEST_ENGINE.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/08-SIGNAL-NOTIFICATION.md", "compat_summary", "docs/SIGNAL_EVENTS.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/09-LIVE-RUNTIME-DEPLOYMENT.md", "compat_summary", "docs/ARCHITECTURE.md; docs/tasks/JM-LIVE-GATE-EVIDENCE.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/10-WORKSTATION-WORKFLOW.md", "compat_summary", "docs/workstation/; docs/workflows/", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/11-DECISIONS.md", "compat_summary", "DECISIONS.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/12-TESTING-AND-GATES.md", "compat_summary", "TESTING.md", "compat_summary", "compat", "Do not treat as canonical"),
    SourceEntry("docs/gpt/project_sources/13-NEXT-STEPS.md", "compat_summary", "CODEX_TASKS.md; docs/gpt/NEXT_STEPS.md", "compat_summary", "compat", "Do not treat as canonical"),
)


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def today() -> str:
    return dt.date.today().isoformat()


def existing_path(entry_path: str) -> bool:
    path = ROOT / entry_path
    if entry_path.endswith("/"):
        return path.is_dir()
    return path.exists()


def generate_manifest() -> str:
    current_date = today()
    commit = git_commit()
    lines = [
        "# GPT Project Source Manifest",
        "",
        f"更新时间：{current_date}",
        "",
        f"生成 commit：`{commit}`",
        "",
        "## GitHub 直读模型",
        "",
        "`docs/gpt/project_sources/` 现在是 GitHub 读取导航与兼容摘要包，不再是人工上传包的核心事实源。canonical facts 只维护在根目录 summary layer 和 deep canonical 原路径中。",
        "",
        "## 推荐读取列表",
        "",
        "### GitHub 默认最小集合",
        "",
        "- `docs/gpt/project_sources/00-INDEX.md`",
        "- `PROJECT_SOURCE.md`",
        "- `STATUS.md`",
        "- `DECISIONS.md`",
        "- `CODEX_TASKS.md`",
        "- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`",
        "",
        "### 任务相关 deep canonical",
        "",
        "- 数据：`docs/DATA_CENTER.md`",
        "- 架构/Web/API：`docs/ARCHITECTURE.md`",
        "- 回测：`docs/BACKTEST_ENGINE.md`",
        "- 信号/企业微信：`docs/SIGNAL_EVENTS.md`",
        "- 工作站：`docs/workstation/`、`docs/workflows/`",
        "- 当前本地执行：`docs/CODEX_HANDOFF.md`、`tasks/current.md`",
        "",
        "### 仍需按需上传或提供链接",
        "",
        "- 未提交本地文件、工作区 diff、截图、录屏、外部 PDF、外部网页。",
        "- `.ai/results/<TASK_ID>/` 原始 evidence、巨量 CSV、Parquet、DB dump、数据样本。",
        "- 本地数据报告只提交脱敏总结和 manifest，不提交巨量数据或敏感内容。",
        "",
        "## Manifest",
        "",
        "| path | category | canonical_source | updated_at | git_commit | state | recommended_for_gpt | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in ENTRIES:
        lines.append(
            f"| `{entry.path}` | {entry.category} | `{entry.canonical_source}` | {current_date} | `{commit}` | {entry.state} | {entry.recommended} | {entry.notes} |"
        )
    lines.extend(
        [
            "",
            "## 重复 / 过期 / 冲突审计",
            "",
            "| 类别 | 文件 | 处理 |",
            "|---|---|---|",
            "| duplicate_summary | `docs/gpt/project_sources/01-*.md` 到 `13-*.md` | 保留为兼容摘要；事实冲突时以 canonical_source 为准 |",
            "| superseded_upload_package | 旧的人工上传包口径 | 在 `00-INDEX.md` 和本 manifest 中标记为 GitHub 直读导航 |",
            "| historical_acceptance | `docs/tasks/*ACCEPTANCE*.md`、旧任务记录 | 不删除；按历史验收引用 |",
            "| generated_evidence | `data/reports/**` | 引用脱敏 summary / manifest；不提交巨量数据 |",
            "| local_only_evidence | `.ai/results/**`、截图、未提交文件 | GitHub 不一定可见，按任务需要单独提供 |",
            "",
            "## 敏感信息说明",
            "",
            "Manifest 和 Project Sources 只允许出现环境变量名与安全规则说明，不允许出现真实 webhook、token、password、cookie、license、账号或连接串。",
            "",
        ]
    )
    return "\n".join(lines)


def check_files(manifest_text: str, index_text: str) -> list[str]:
    errors: list[str] = []
    for entry in ENTRIES:
        if not existing_path(entry.path):
            errors.append(f"missing path: {entry.path}")
        if f"`{entry.path}`" not in manifest_text:
            errors.append(f"manifest missing entry: {entry.path}")
    required_index_terms = [
        "GitHub 读取导航",
        "canonical 文件为准",
        "PROJECT_SOURCE.md",
        "STATUS.md",
        "CODEX_TASKS.md",
        "docs/gpt/GITHUB_READ_ORDER.md",
    ]
    for term in required_index_terms:
        if term not in index_text:
            errors.append(f"index missing term: {term}")
    if "人工上传包的核心事实源" not in manifest_text:
        errors.append("manifest missing GitHub direct-read policy")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or validate GPT project source navigation files.")
    parser.add_argument("--check", action="store_true", help="validate required source entries")
    parser.add_argument("--write", action="store_true", help="rewrite docs/gpt/PROJECT_SOURCE_MANIFEST.md")
    args = parser.parse_args(argv)

    if args.write:
        MANIFEST_PATH.write_text(generate_manifest(), encoding="utf-8")
        print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")

    if args.check or not args.write:
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        index_text = INDEX_PATH.read_text(encoding="utf-8")
        errors = check_files(manifest_text, index_text)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("project source index check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

