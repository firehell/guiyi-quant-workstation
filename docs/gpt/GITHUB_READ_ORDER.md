# GPT GitHub Read Order

更新时间：2026-07-16

本文件定义浏览器 GPT 已授权读取 GitHub 仓库后的默认读取顺序。`docs/gpt/project_sources/` 不再是人工上传包的核心事实源，而是 GitHub 直读导航和兼容摘要包。

## 默认读取命令

```text
@GitHub 读取 docs/gpt/project_sources/00-INDEX.md、PROJECT_SOURCE.md、STATUS.md、CODEX_TASKS.md，并按任务需要读取相关 deep canonical 文件。
```

## 最小读取顺序

1. `docs/gpt/project_sources/00-INDEX.md`
2. `PROJECT_SOURCE.md`
3. `STATUS.md`
4. `DECISIONS.md`
5. `CODEX_TASKS.md`
6. `docs/gpt/PROJECT_SOURCE_MANIFEST.md`

## Deep Canonical 按需读取

| 主题 | 优先读取 |
|---|---|
| 数据中心 / active 数据入口 / 全历史重审 Gate | `docs/DATA_CENTER.md` |
| 系统架构 / 服务分层 / Web/API | `docs/ARCHITECTURE.md` |
| 回测 / trust audit / 报告口径 | `docs/BACKTEST_ENGINE.md` |
| 信号 / 企业微信 / 通知边界 | `docs/SIGNAL_EVENTS.md` |
| Codex 接手 / 当前本地执行状态 | `docs/CODEX_HANDOFF.md`、`tasks/current.md` |
| GitHub Native / WorkBuddy V3 工作站 | `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`、`docs/workstation/WORKBUDDY_UNIFIED_V3.md`、`docs/workstation/WORKSTATION_DOCUMENT_MAP.md`、`docs/workstation/WORKSTATION_UPGRADE_ACCEPTANCE.md` |
| WorkBuddy / 企业微信远程入口 | `docs/workstation/REMOTE_DEVELOPMENT.md`、`docs/AI_WECHAT_WORKFLOW.md`、`CODEBUDDY.md`（compatibility-only） |

## Project Sources 兼容包

`docs/gpt/project_sources/*.md` 只用于：

- 快速导航到 canonical 文件；
- 兼容仍需要上传 Markdown 的旧 GPT 工作流；
- 标记重复、过期、冲突或历史验收文档的读取边界。

如果 `project_sources/*.md` 与 canonical 文件冲突，以 canonical 文件为准。不要在 `project_sources/*.md` 中维护第二份事实结论。

## 不能假设 GitHub 已有的内容

以下内容仍需按任务需要单独上传或提供链接：

- 未提交的本地文件和工作区 diff；
- `.ai/results/<TASK_ID>/` 的本地 evidence 原文；
- 截图、录屏和浏览器可见 UI 状态；
- 外部 PDF、网页、聊天记录和 Review 页面；
- 本地数据报告中的大文件、CSV 明细、Parquet、DB dump 或样本数据。

本地数据报告只允许提交脱敏总结、manifest、索引或必要的小型统计，不提交巨量数据、敏感路径、凭据、原始样本或未脱敏异常堆栈。

## 引用审计与归档规则

- 删除或改写重复摘要前，先用 `rg` 审计引用方。
- 历史验收文档不删除；如事实已被新 canonical 取代，标记 `historical_acceptance` 或 `superseded`。
- 大型 deep canonical 保持原路径，不复制成第二份事实源。
- `PROJECT_SOURCE.md`、`STATUS.md`、`DECISIONS.md`、`CODEX_TASKS.md` 是根目录 summary layer；`docs/` 下 deep canonical 负责细节。
