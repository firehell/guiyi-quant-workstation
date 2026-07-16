# GPT Project Sources

更新时间：2026-07-16

本目录用于浏览器 GPT 读取当前项目事实。GPT 已可直接读取 GitHub 后，`docs/gpt/project_sources/` 是读取导航与兼容摘要包，不再是人工上传包的核心事实源；仓库 canonical 仍是根目录 summary 文件和 `docs/` deep canonical 文件。

## 推荐读取顺序

1. `project_sources/00-INDEX.md`
2. `../../PROJECT_SOURCE.md`
3. `../../STATUS.md`
4. `../../DECISIONS.md`
5. `../../CODEX_TASKS.md`
6. `PROJECT_SOURCE_MANIFEST.md`
7. `GITHUB_READ_ORDER.md`

## 当前结论

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

`FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只代表 manifest 层强支持物理历史数据已大规模下载；不代表 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 已通过。不要使用旧聊天或旧 `docs/gpt` 摘要覆盖当前事实。若本目录和 `PROJECT_SOURCE.md`、`STATUS.md`、`DECISIONS.md`、`CODEX_TASKS.md`、`docs/DATA_CENTER.md` 冲突，以 canonical 文件为准。

## 文件说明

- `CURRENT_STATE.md`：给 GPT 的当前状态速览。
- `NEXT_STEPS.md`：下一步任务和上传建议。
- `PROJECT_SNAPSHOT.md`：当前架构/功能快照。
- `DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`：数据阶段收口审查包。
- `GITHUB_READ_ORDER.md`：GPT GitHub 默认读取顺序。
- `project_sources/`：GitHub 读取导航与旧上传流程兼容摘要。
- `PROJECT_SOURCE_MANIFEST.md`：canonical 来源、兼容摘要、引用审计与敏感信息规则。

## 仍需按需提供的材料

- 截图、录屏、外部 PDF、外部网页和未提交本地文件。
- `.ai/results/<TASK_ID>/` 原始 evidence。
- 本地数据报告的大文件、CSV 明细、Parquet、DB dump 或数据样本。

这些材料不应默认假设 GitHub 已有；需要时只提交脱敏总结、manifest 或小型统计。

## 敏感信息规则

本目录不得包含真实 webhook、token、password、cookie、license、账号或连接串。允许出现环境变量名和安全规则说明。
