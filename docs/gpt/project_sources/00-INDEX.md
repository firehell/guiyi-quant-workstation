# GPT GitHub Read Navigation

更新时间：2026-07-15

本文件是 GPT GitHub 直读导航。`docs/gpt/project_sources/` 不再承担人工上传包的核心事实源职责，而是 GitHub 读取导航与兼容摘要包：

- 指引 GPT 读取 canonical 文件；
- 为旧的 Markdown 上传流程保留兼容摘要；
- 标记重复、过期、冲突和历史验收文档的读取边界。

如果本目录摘要与 canonical 文件冲突，以 canonical 文件为准。

## 默认读取命令

```text
@GitHub 读取 docs/gpt/project_sources/00-INDEX.md、PROJECT_SOURCE.md、STATUS.md、CODEX_TASKS.md 和相关 deep canonical。
```

## 最小读取顺序

1. `PROJECT_SOURCE.md`
2. `STATUS.md`
3. `DECISIONS.md`
4. `CODEX_TASKS.md`
5. `docs/gpt/PROJECT_SOURCE_MANIFEST.md`
6. `docs/gpt/GITHUB_READ_ORDER.md`

## Deep Canonical 导航

| 主题 | canonical 来源 | 何时读取 |
|---|---|---|
| 数据层、active 数据入口、Phase 3 Gate | `docs/DATA_CENTER.md` | 任何数据、回测输入、信号输入、数据可信度判断 |
| 架构、服务分层、Web/API | `docs/ARCHITECTURE.md` | 任何跨模块设计或页面/API判断 |
| 回测、trust audit、报告口径 | `docs/BACKTEST_ENGINE.md` | 策略、回测、报告、trade/order/equity 判断 |
| 信号、企业微信、通知边界 | `docs/SIGNAL_EVENTS.md` | 任何提醒、发送、signal event、notification worker 判断 |
| Codex 接手与本地状态 | `docs/CODEX_HANDOFF.md`、`tasks/current.md` | 判断当前本地任务、未完成项和交接状态 |
| GitHub Native / WorkBuddy V3 工作站 | `docs/workstation/GITHUB_NATIVE_CONTROL_PLANE.md`、`docs/workstation/WORKBUDDY_UNIFIED_V3.md`、`docs/workstation/WORKSTATION_DOCUMENT_MAP.md`、`docs/workstation/WORKSTATION_UPGRADE_ACCEPTANCE.md` | 工作站、Issue-first、Draft PR、WorkBuddy 协调、CodeBuddy 兼容 |
| 企业微信远程入口 | `docs/workstation/REMOTE_DEVELOPMENT.md`、`docs/AI_WECHAT_WORKFLOW.md`、`CODEBUDDY.md`（compatibility-only） | `workbuddy_task.sh` 固定远程命令 |

## Project Sources 兼容摘要

| 文件 | canonical_source | 当前角色 |
|---|---|---|
| `01-PROJECT-SOURCE.md` | `PROJECT_SOURCE.md` | 兼容摘要，不维护第二份事实 |
| `02-CURRENT-STATUS.md` | `STATUS.md`、`tasks/current.md` | 兼容摘要，不维护第二份事实 |
| `03-ARCHITECTURE.md` | `docs/ARCHITECTURE.md` | 兼容摘要，不维护第二份事实 |
| `04-DATA-LAYER.md` | `docs/DATA_CENTER.md` | 兼容摘要，不维护第二份事实 |
| `05-INDICATOR-STRATEGY-KERNEL.md` | `packages/quant-core/README.md`、`docs/INDICATOR_KERNEL.md` | 兼容摘要，不维护第二份事实 |
| `06-WEB.md` | `docs/ARCHITECTURE.md`、`apps/quant-web/src/app/router.ts` | 兼容摘要，不维护第二份事实 |
| `07-BACKTEST.md` | `docs/BACKTEST_ENGINE.md` | 兼容摘要，不维护第二份事实 |
| `08-SIGNAL-NOTIFICATION.md` | `docs/SIGNAL_EVENTS.md` | 兼容摘要，不维护第二份事实 |
| `09-LIVE-RUNTIME-DEPLOYMENT.md` | `docs/ARCHITECTURE.md`、`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` | 兼容摘要，不维护第二份事实 |
| `10-WORKSTATION-WORKFLOW.md` | `docs/workstation/`、`docs/workflows/` | 兼容摘要，不维护第二份事实 |
| `11-DECISIONS.md` | `DECISIONS.md` | 兼容摘要，不维护第二份事实 |
| `12-TESTING-AND-GATES.md` | `TESTING.md` | 兼容摘要，不维护第二份事实 |
| `13-NEXT-STEPS.md` | `CODEX_TASKS.md`、`docs/gpt/NEXT_STEPS.md` | 兼容摘要，不维护第二份事实 |

## 当前总体状态

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口，不等于数据层最终封板完成。

## 引用审计结果

| 类别 | 发现 | 处理 |
|---|---|---|
| duplicate_summary | `01-*.md` 到 `13-*.md` 与 canonical 文件重复 | 保留为兼容摘要；事实冲突时以 canonical_source 为准 |
| superseded_upload_package | 旧口径把 `project_sources/` 当作人工投喂包 | 本文件和 manifest 改为 GitHub 读取导航 |
| historical_acceptance | `docs/tasks/*ACCEPTANCE*.md` 和旧任务记录 | 不删除；作为历史验收引用 |
| generated_evidence | `data/reports/**` 报告、CSV、manifest | 只引用脱敏 summary / manifest，不提交巨量数据 |
| local_only_evidence | `.ai/results/**`、截图、未提交文件、外部 PDF | GitHub 不保证可见；按任务需要单独提供 |

## 当前最重要阻塞项

- `metadata_gap=1853` manifest / DB 对齐。
- pre-2020 周线仍有 34 个品种缺口或需 N/A 口径确认。
- actual contract 缺口仍需专项处理。
- T3-real 单次 live 写入 Gate 未通过。
- `JM_RUNTIME_READY` / `LONG_RUNNING_READY` 未达成。
- 真实公网 TLS / Basic Auth / 端口封闭 / 重启恢复 smoke 未完成。
- OOS / walk-forward 未完成。
- 企业微信 historical replay smoke 不等于 live-confirmed 或长期发送验收。

## 不在 GitHub 中自动可见的材料

- 未提交本地文件、未推送分支和工作区 diff；
- 截图、录屏、浏览器状态、外部 PDF、外部网页；
- `.ai/results/<TASK_ID>/` 原始 evidence；
- 本地巨量数据、CSV 明细、Parquet、DB dump、敏感路径或未脱敏异常堆栈。
