# GPT Project Source Manifest

更新时间：2026-07-15

生成 commit：`e1ec97f1`

## GitHub 直读模型

`docs/gpt/project_sources/` 现在是 GitHub 读取导航与兼容摘要包，不再是人工上传包的核心事实源。canonical facts 只维护在根目录 summary layer 和 deep canonical 原路径中。

## 推荐读取列表

### GitHub 默认最小集合

- `docs/gpt/project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `DECISIONS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`

### 任务相关 deep canonical

- 数据：`docs/DATA_CENTER.md`
- 架构/Web/API：`docs/ARCHITECTURE.md`
- 回测：`docs/BACKTEST_ENGINE.md`
- 信号/企业微信：`docs/SIGNAL_EVENTS.md`
- 工作站：`docs/workstation/`、`docs/workflows/`
- 当前本地执行：`docs/CODEX_HANDOFF.md`、`tasks/current.md`

### 仍需按需上传或提供链接

- 未提交本地文件、工作区 diff、截图、录屏、外部 PDF、外部网页。
- `.ai/results/<TASK_ID>/` 原始 evidence、巨量 CSV、Parquet、DB dump、数据样本。
- 本地数据报告只提交脱敏总结和 manifest，不提交巨量数据或敏感内容。

## Manifest

| path | category | canonical_source | updated_at | git_commit | state | recommended_for_gpt | notes |
|---|---|---|---|---|---|---|---|
| `docs/gpt/project_sources/00-INDEX.md` | navigation | `PROJECT_SOURCE.md; STATUS.md; CODEX_TASKS.md` | 2026-07-15 | `e1ec97f1` | current_navigation | yes | GitHub read navigation |
| `docs/gpt/GITHUB_READ_ORDER.md` | navigation | `PROJECT_SOURCE.md; STATUS.md; DECISIONS.md; CODEX_TASKS.md` | 2026-07-15 | `e1ec97f1` | current_navigation | yes | Default GPT GitHub read order |
| `PROJECT_SOURCE.md` | project | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | yes | Project boundary and source-of-truth map |
| `STATUS.md` | status | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | yes | Current state and unfinished gates |
| `DECISIONS.md` | decisions | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | yes | Accepted decisions and pending decisions |
| `CODEX_TASKS.md` | tasks | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | yes | Current task pool and next steps |
| `docs/gpt/PROJECT_SOURCE_MANIFEST.md` | manifest | `self` | 2026-07-15 | `e1ec97f1` | current_navigation | yes | Source inventory and policy |
| `docs/DATA_CENTER.md` | deep_canonical | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | topic | Data-layer canonical details |
| `docs/ARCHITECTURE.md` | deep_canonical | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | topic | Architecture canonical details |
| `docs/BACKTEST_ENGINE.md` | deep_canonical | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | topic | Backtest canonical details |
| `docs/SIGNAL_EVENTS.md` | deep_canonical | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | topic | Signal and WeCom canonical details |
| `docs/CODEX_HANDOFF.md` | deep_canonical | `self` | 2026-07-15 | `e1ec97f1` | canonical_current | topic | Codex handoff state |
| `tasks/current.md` | task_state | `self` | 2026-07-15 | `e1ec97f1` | current_task | topic | Current local task state |
| `docs/gpt/project_sources/01-PROJECT-SOURCE.md` | compat_summary | `PROJECT_SOURCE.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/02-CURRENT-STATUS.md` | compat_summary | `STATUS.md; tasks/current.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/03-ARCHITECTURE.md` | compat_summary | `docs/ARCHITECTURE.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/04-DATA-LAYER.md` | compat_summary | `docs/DATA_CENTER.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/05-INDICATOR-STRATEGY-KERNEL.md` | compat_summary | `packages/quant-core/README.md; docs/INDICATOR_KERNEL.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/06-WEB.md` | compat_summary | `docs/ARCHITECTURE.md; apps/quant-web/src/app/router.ts` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/07-BACKTEST.md` | compat_summary | `docs/BACKTEST_ENGINE.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/08-SIGNAL-NOTIFICATION.md` | compat_summary | `docs/SIGNAL_EVENTS.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/09-LIVE-RUNTIME-DEPLOYMENT.md` | compat_summary | `docs/ARCHITECTURE.md; docs/tasks/JM-LIVE-GATE-EVIDENCE.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/10-WORKSTATION-WORKFLOW.md` | compat_summary | `docs/workstation/; docs/workflows/` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/11-DECISIONS.md` | compat_summary | `DECISIONS.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/12-TESTING-AND-GATES.md` | compat_summary | `TESTING.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |
| `docs/gpt/project_sources/13-NEXT-STEPS.md` | compat_summary | `CODEX_TASKS.md; docs/gpt/NEXT_STEPS.md` | 2026-07-15 | `e1ec97f1` | compat_summary | compat | Do not treat as canonical |

## 重复 / 过期 / 冲突审计

| 类别 | 文件 | 处理 |
|---|---|---|
| duplicate_summary | `docs/gpt/project_sources/01-*.md` 到 `13-*.md` | 保留为兼容摘要；事实冲突时以 canonical_source 为准 |
| superseded_upload_package | 旧的人工上传包口径 | 在 `00-INDEX.md` 和本 manifest 中标记为 GitHub 直读导航 |
| historical_acceptance | `docs/tasks/*ACCEPTANCE*.md`、旧任务记录 | 不删除；按历史验收引用 |
| generated_evidence | `data/reports/**` | 引用脱敏 summary / manifest；不提交巨量数据 |
| local_only_evidence | `.ai/results/**`、截图、未提交文件 | GitHub 不一定可见，按任务需要单独提供 |

## 敏感信息说明

Manifest 和 Project Sources 只允许出现环境变量名与安全规则说明，不允许出现真实 webhook、token、password、cookie、license、账号或连接串。
