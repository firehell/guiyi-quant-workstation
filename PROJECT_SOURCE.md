# 归一量化项目事实源

更新时间：2026-07-21

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。当前重点是 V1 / V1-B 的可信研究闭环：

```text
数据更新 -> 数据质量检查 -> 标准化存储 -> K 线查看 -> 策略 / 信号
-> 回测 -> 报告 -> 单笔复盘 -> 人工观察 -> 前向验证
```

项目不是 SaaS，不是无人值守自动交易机器人，不连接实盘账户自动下单，不把预警或回测结论写成交易指令。

## 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL metadata / facts
-> FastAPI / vn.py / Vue Web
-> Market / Backtest / Signal / Review / Runtime
```

active 数据入口硬约束：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、回测和 Stage 9 前置 Gate 默认使用 `quality_status=passed`。`validation`、`legacy_reference`、`candidate`、旧 TqSdk / 天勤和交易练习者数据不得进入默认 active 链路。

## 当前总体状态

```text
V1_DATA_CONTRACT_FROZEN
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
POST_FREEZE_REAL_PILOT_PASSED
WORKSTATION_FINAL_CLEANUP_COMPLETE
STAGE6_CANONICAL_SYNCED
JM_HISTORICAL_CATCHUP_READY
JM_REFERENCE_METADATA_FRESH
JM_LIVE_TARGET_FRESHNESS_READY
JM_LIVE_CONTEXT_READY
T3_REAL_PASSED
```

业务 Gate 含义以 `STATUS.md` 与 `docs/DATA_CENTER.md` 为准；本文件不重复展开历史审计数字。

阶段 4/5 已完成工程闭环（`STAGE4_COMPLETED` / `STAGE5_COMPLETED`）；HTDY 研究终态为 `REJECTED_RESEARCH_CANDIDATE`。当前业务阶段为 Stage 6；S6-03 已完成 JM historical/reference/live-target freshness，S6-04 已完成 historical actual warm-up + latest live confirmed/passed 拼接（`JM_LIVE_CONTEXT_READY`），S6-05 已以 `2026-07-21 / JM2609` 的真实 receipt 通过 `T3_REAL_PASSED`。主线 `JM Data Continuity -> T3 -> T4 -> EOD Automation -> T5 -> T6 -> T7`；业务下一入口为 `S6-06` T4（代码完成、真实归档审批 pending）。上述状态不等于 `JM_ARCHIVE_PASSED`、SignalEvent、通知、runtime 或长稳 Ready。工具面正式模型见下节与 `docs/decisions/ADR-WS-002-simplified-github-codex-workstation.md`。

## Canonical 文件职责

| 文件 | 职责 |
|---|---|
| `PROJECT_SOURCE.md` | 长期目标、系统边界、主链路、不可突破范围 |
| `STATUS.md` | 当前阶段、已实现能力、未完成 Gate |
| `DECISIONS.md` | 已确认架构/数据/回测/运行/协作决策 |
| `docs/DEVELOPMENT.md` | 唯一开发流程（普通 vs 高风险） |
| `AGENTS.md` | 工程硬规则（精简版） |
| `TESTING.md` | 常用验证与 Gate 命令 |
| `docs/DATA_CENTER.md` | 数据层 deep canonical |
| `docs/ARCHITECTURE.md` | 系统架构 deep canonical |
| `docs/BACKTEST_ENGINE.md` | 回测口径 deep canonical |
| `docs/SIGNAL_EVENTS.md` | 信号事件和企业微信边界 |
| `docs/INDICATOR_KERNEL.md` | 指标内核 deep canonical |

旧任务池、GPT 双份摘要与工作站协议文档已从 active tree 删除；事实以本表与 GitHub Issue/PR 为准。

## AI 工作站模型（精简后）

```text
GitHub（Issue / PR / main canonical docs）
  + GPT（浏览器：需求、设计、审查）
  + Codex（编码）
  + 用户（批准 / merge / deploy）
```

关键边界：

- 项目状态唯一源：`STATUS.md`；任务生命周期：GitHub Issue / PR。
- 高风险任务可保留 `docs/tasks/<TASK_ID>.md`；普通任务不强制。
- GPT 默认在任务分支写文档/设计，不直接写 `main`。
- 工程入口目标：`scripts/engineering/*`；禁止把已退出的多入口控制面 / stage 调度作为正式架构。
- 用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。
- 不自动 push / merge / deploy；不静默降级数据源；不打印凭据。

当前迁移状态：

```text
WORKSTATION_SIMPLIFIED
WORKSTATION_MAINTENANCE_ONLY
ENGINEERING_GATES_HARDENED
WORKSTATION_REPOSITORY_CLEANED
POST_FREEZE_REAL_PILOT_PASSED
WORKSTATION_FINAL_CLEANUP_COMPLETE
```

精简盘点与过程报告已从 active tree 移除；结论保留在 `DECISIONS.md` / ADR-WS-002 / Git 历史。Step 6 Pilot（Issue #43 / PR #44，runtime observation adapter）已合入并标记 `POST_FREEZE_REAL_PILOT_PASSED` / `WORKSTATION_FINAL_CLEANUP_COMPLETE`。

## 不做事项

- 不自动交易，不自动生成或发送订单。
- 不把企业微信提醒写成买卖指令。
- 不把单次 smoke 写成长稳 Gate。
- 不把 `trust audit passed` 写成策略盈利、稳定或可实盘。
- 不把数据文件存在写成数据最终可信。
- 不把 historical replay smoke 写成 live-confirmed smoke。
- 不把 `.env`、webhook、token、password、cookie、license 或账号凭据写入仓库。

## 推荐阅读顺序

1. `STATUS.md`
2. `AGENTS.md`
3. `docs/DEVELOPMENT.md`
4. `PROJECT_SOURCE.md`（本文件）
5. `DECISIONS.md`
6. 任务相关 deep canonical（数据 / 架构 / 回测 / 信号）或 Issue/PR

若任何旁路摘要与 canonical 冲突，以 canonical 为准。
