# 当前状态

更新时间：2026-07-26（本次为结构重构：STATUS.md 改为仪表盘，历史叙事与完整 flag 清单迁入 `STATUS_ARCHIVE.md`，事实未改动。）

本文件是项目当前状态的**仪表盘**：只列当前在做的事、仍未关闭的 Gate、少量仍然 active 的硬事实锚点，以及防过度宣称的红线。完整历史叙事、全部 flag 清单、旧审计口径与能力清单见 `STATUS_ARCHIVE.md`。

## 当前在做什么 / 下一步一件事

当前阶段：V1-B（JM 短持有研究闭环）+ 指标/策略可信验证主线，Stage 6 JM 主线。HTDY exact realtime exception 的 Step 0–4 工程验收已闭合（合同冻结、production kernel/policy/Web golden、snapshot/evaluator、first-seen writer/lineage v2、schema-v3 code-only deployment/rebind/parent 零漂移验证均已完成，SignalEvent/autosend 仍关闭）。**下一步一件事**：独立授权的单日自然 first-seen event + 同 key 一次幂等探测；之后才可能进入 S6-10 五交易日长稳。当前不得宣称 Runtime、通知、交易或长稳 Ready。

## 当前未关闭 / 阻塞 Gate

仅列仍需推进的 pending / blocking 项；已完成的 `*_READY` / `*_PASSED` flag 见 `STATUS_ARCHIVE.md`。

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | 阻塞 | XMA(6)/VAR23、直接内层与 provenance 仍缺失；保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，**不重开**公式审计 |
| Audit V2 residual triage | pending | 需解释 90 calendar gap、90 session historical-scope gap、252 physical partial、6 warning、21 failed，再决定后续受控任务 |
| 全历史 residual triage | pending | 按 Audit V2 独立处理；不得把消费者 Ready 扩写为“所有历史资产零 residual” |
| `LONG_RUNNING_READY` | pending | 需至少 5 个真实交易日长稳和 kill/recovery |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复 |
| S6-08 自然事件 + 一次幂等探测 | pending | HTDY 下一入口；须独立授权 |
| S6-09 企业微信单条发送 | pending | 串行，须完成前置与精确批准 |
| S6-10 五交易日长稳 | pending | 串行，须完成前置与精确批准 |

阶段 5 的 HTDY `REJECTED_RESEARCH_CANDIDATE` 不得通过实时例外、调参或重跑翻转。

## 关键事实锚点

仅保留少数仍然 active 的硬事实；完整证据链见 `STATUS_ARCHIVE.md` 的「当前事实依据」表。

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | 保持 `20260721_0025` | `docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` |
| Profile active bindings | `profile_active_bindings=5131` | 同上 |
| S6-07 scheduler checkpoint | `checkpoint=1` | 同上 |
| 禁写 counter | 四类 / 十类禁写 counter 零漂移 | S6-07 recovery / deployment receipts |
| 回测可信审计 | `report_id=14 / trust audit passed`（不代表盈利或实盘准入） | `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| SignalEvent / autosend | 关闭；after-market scheduler unloaded/disabled | `docs/tasks/V1-HTDY-REALTIME-INTEGRATION-CLOSEOUT.md` |

## 不可宣称（红线，防过度宣称）

- 不可把 `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 写成全历史数据层验收完成。
- 不可把旧 Phase 3 的 `1853 / 34 / 45` 写成当前确定下载缺口（旧口径见 `STATUS_ARCHIVE.md`）。
- 不可把 `JM_ARCHIVE_PASSED` 扩写为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
- 不可把 `JM_EOD_INCREMENTAL_AUTOMATION_READY` 扩写为 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。
- 不可把 `HTDY_S6_08_SCHEMA_V3_GATE_READY` / code-only deployment 扩写为 HTDY Runtime、真实 SignalEvent、通知或自动交易 Ready；schema-v3 部署不授权 daily child、自然事件或收益声明。
- 不可把 `JM_ARCHIVE_PASSED` / `JM_EOD_INCREMENTAL_AUTOMATION_READY` 等消费者 Ready 扩写为“所有全历史资产零 residual”。
- 不可把 Stage 9-B2 historical replay single-send smoke 写成 live-confirmed 或长期发送验收。
- 不可把 `report_id=14` trust audit passed 写成策略盈利或实盘准入。
- 不可把 `REJECTED_RESEARCH_CANDIDATE` 写成阶段 5 工程失败；它表示可信验证管道成功淘汰了当前候选，不得通过实时例外翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；HTDY 公式审计已结束且不再重开，最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。

## 相关文档

- `STATUS_ARCHIVE.md`：历史叙事、完整 flag 清单、当前事实依据全表、旧 Phase 3 口径、已具备能力与工作站 backlog。
- canonical：`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`。
- 业务 deep canonical：`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/INDICATOR_KERNEL.md`。
