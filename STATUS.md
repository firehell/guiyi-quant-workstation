# 当前状态

更新时间：2026-07-29

本文件是项目当前状态的**仪表盘**：只列当前在做的事、仍未关闭的 Gate、少量仍然 active 的硬事实锚点，以及防过度宣称的红线。完整历史叙事、全部 flag 清单、旧审计口径与能力清单见 `STATUS_ARCHIVE.md`。

## 当前在做什么 / 下一步一件事

当前阶段：V1-B（JM 短持有研究闭环）+ 指标/策略可信验证主线，Stage 6 JM 主线。S6-00～S6-09 在各自限定范围内已收口；这些结论不等于策略盈利、长期 Runtime 或交易 Ready。S6-10 schema-v7 首个完整日链与 Approval D 长期 daily-child 消费链均为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`：`bar_end` 保留原始信号 K 线，`decision_bucket_end` 冻结本次确认收线；evaluator、Ledger 与 bounded dispatcher 统一按后者授权。长期 Runtime 在下一夜盘前四小时内，先要求相邻前日 S6-07 EOD 通过，再从 RQData 精确读取下一交易日 JM rank=1；事务内只创建或验证一条逻辑映射，DB commit 后才 create-only 发布 hash-bound `mapping_receipt.json`。首个完整日则由 exact signed C2 在 full deployment preflight 前授权同样的 mapping freeze，避免与部署后 Approval D 形成启动循环；activation receipt 只在 activate 后用于 23-close allowlist，不再被部署前阶段提前要求。开盘后再从 receipt、DB/交易日历/Session/Runtime、23 个 confirmed close、source facts 与代码身份构建每日 child；scheduler、observer、dispatcher 与 health 均消费已提交证据和 child hash，同日重启只允许恢复完全一致的文件，日切自动轮换。`8119dbba…8d64` 的已签 C2 已在零部署写入前因 `mapping_duplicate_or_missing` fail-closed 并保留为失败证据，不得重试或手工补 mapping。配置继续使用 `arm → activate`，global autosend 与 auto_order 始终为 false。仍需冻结修复后的干净 source checkpoint、生成 fresh 完整交易日 C2、签署 Approval D、执行真实 mapping/deployment、自然信号企微和 EOD 验收，因此禁止宣称 `LONG_RUNNING_READY`。

## 当前未关闭 / 阻塞 Gate

仅列仍需推进的 pending / blocking 项；已完成的 `*_READY` / `*_PASSED` flag 见 `STATUS_ARCHIVE.md`。

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | 阻塞 | XMA(6)/VAR23、直接内层与 provenance 仍缺失；保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，**不重开**公式审计 |
| Audit V2 residual triage | pending | 需解释 90 calendar gap、90 session historical-scope gap、252 physical partial、6 warning、21 failed，再决定后续受控任务 |
| 全历史 residual triage | pending | 按 Audit V2 独立处理；不得把消费者 Ready 扩写为“所有历史资产零 residual” |
| `LONG_RUNNING_READY` | external Gate pending | Approval D → 盘前权威 RQData mapping freeze → commit 后 mapping receipt → 每日 child → Runtime/scheduler/observer/dispatcher/health 消费与日切恢复已代码闭环；仍需新完整日 C2、签名 Approval D、干净 Runtime 身份及真实部署/运行证据 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达、FRP/Nginx 重启恢复 |
| S6-09 企业微信单条发送 | passed | event 4 only；notification 2；attempt=1；autosend=false |
| S6-10 15m 收线观察 | code fix verification in progress / exact external Gates held | `8119dbba` C2 的零写入失败证据保留；修复初始 C2 mapping 与 activation 前置循环后，只允许冻结新 commit/tree、生成 fresh parent/C2 并完成真实完整日；旧 C2/事件不得追发或复用 |

阶段 5 的 HTDY `REJECTED_RESEARCH_CANDIDATE` 不得通过实时例外、调参或重跑翻转。

## 关键事实锚点

仅保留少数仍然 active 的硬事实；完整证据链见 `STATUS_ARCHIVE.md` 的「当前事实依据」表。

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | 保持 `20260721_0025` | `docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` |
| Profile active bindings | `profile_active_bindings=5138` | HTDY S6-08 schema-v3 final receipt |
| S6-07 scheduler checkpoint | `checkpoint=1` | 同上 |
| 禁写 counter | 四类 / 十类禁写 counter 零漂移 | S6-07 recovery / deployment receipts |
| 回测可信审计 | `report_id=14 / trust audit passed`（不代表盈利或实盘准入） | `docs/BACKTEST_ENGINE.md`、`docs/STAGE13_BACKTEST_TRUST_AUDIT.md` |
| HTDY S6-08 / SignalEvent / autosend | S6-08 passed；事件 `id=4`；授权已关闭；autosend=false；after-market unloaded/disabled | `docs/tasks/V1-HTDY-05-S6-08-REAL-ACCEPTANCE.md` |

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
