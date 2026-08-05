# 当前状态

更新时间：2026-08-05

本文件是项目当前状态仪表盘；历史过程由 Git、任务合同与既有
receipt/report/evidence 追溯。

## 当前执行线

Task 07 Stage A/B 的最新仓库证据记录 release/main/tag 已收口，且生产
PostgreSQL revision 曾回读为 `20260803_0032`。本任务未重新连接生产环境，
因此该 revision 仍需在后续生产只读验收中再次精确回读。

Task 07 Stage C 已收窄为“JM 目标 Canonical 验收与精确缺口计划”。当前
Lane 3 candidate 基于 `develop@364753e72458641e226280e326841919539c1354`，仅从
`config/data_core_v2_targets.yaml`、Catalog 和 MainContractMap 生成 JM 显式目标，
再通过既有 Canonical reader 和 `MarketDataService` 只读验收。

唯一目标范围为：

- `continuous / JM.MAIN`；
- `actual_dominant / MainContractMap rank=1 volume_open_interest`；
- `1m/5m/15m/30m/60m/1d/1w`；
- 窗口起点 `2013-03-22`，终点为当前完整 MainContractMap 的最后交易日。

每个目标只能得到 `KEEP_CANONICAL`、`REDOWNLOAD_DIRECT`、
`REBUILD_AGGREGATE` 或 `REGISTER_DATA_GAP`。全部有效时固定返回：

```text
Stage_C=NO_DATA_WRITE_REQUIRED
writes_authorized=false
repair_count=0
production_writes=false
```

旧的 49,885 资产、30,536 repair actions、24,178 RQData requests 和 2,186 batches
只是 superseded historical evidence。它们不再是 active Stage C 输入，对应的
CLI packet/plan/preflight/apply/verify 路由已从 active parser 移除并 fail-closed。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| GY-DATA-CORE-V2 Task 00～03 | completed on develop | 以各自 PR、CI、Review 和 evidence 为准 |
| GY-DATA-CORE-V2 Task 04 | completed on develop | Canonical 自身 Gate、统一读取与普通消费者回归；legacy Shadow 不是准入 Gate |
| GY-DATA-CORE-V2 Task 05 | completed on develop | trusted consumers 与 fail-closed derived/reference inventory；不含真实删除 |
| GY-DATA-CORE-V2 Task 06 | completed on develop | 固定 EMA21 evaluator + `0028..0031` + live/decision/EOD/Review/Sample/retention；Runtime/live 未启用 |
| GY-DATA-CORE-V2 Task 07 Stage C | implementation candidate | 精简实现待 exact-head CI、独立 Sol Review 与 develop 集成；生产只读验收未执行 |
| GY-DATA-CORE-V2 Task 08 | pending | Stage D Runtime promotion 的独立任务，本任务不启动 |
| 旧派生数据清理 | optional / separate | Stage E 后续独立可选任务，不阻塞 Task 07 |

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者验收扩写为所有历史资产 residual 为零 |
| Task 07 Stage C | Review corrections in progress | exact-head CI 已通过，独立 Sol Review 的 Important 项正在修正；修正后需新 head CI/Review |
| Task 07 production read-only acceptance | pending | 重新回读 PostgreSQL `20260803_0032` 并验收 JM 目标 Canonical；本任务未执行 |
| Task 06 live/EOD contract | passed | 已冻结单一 EMA21 confirmed-close observation 合同；不扩展 centered-XMA 白名单 |
| Task 06 production migration | passed | `0028 -> 0031` empty/disabled smoke 已通过；不授权 Runtime/live enable |
| 旧行情与 legacy 工件删除 | not authorized | 旧行情只读保留；任何删除仍需用户明确批准 |
| release / main / tag | not authorized | 本任务只允许 task -> develop 可逆集成 |
| Task 08 Runtime promotion | pending / not authorized | Runtime 保持独立 detached；health/smoke/rollback 为后续专用 Gate |
| JM Runtime 验收 | pending redesign | 单日自然运行、恢复证据、独立 Review 与用户最终批准 |
| 长稳 / 通知 / 交易就绪 | not ready | 本任务不启用 live、不发送通知、不授权订单或自动交易 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

task 自动集成只适用于通过验收、CI、独立 Review 且 exact head 匹配的可逆开发变更。
生产 migration、真实数据/DB 写入、删除、`main`/release/tag、Runtime/live 和真实通知
仍是人工 Gate。

## 必要事实锚点

| 事实 | 当前证据值 | 边界 |
|---|---|---|
| PostgreSQL revision | `20260803_0032` | Stage B 曾回读；本任务未实时重验 |
| Canonical closeout snapshot | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 历史只读证据；Stage C 将重新验收明确目标 |
| MainContractMap closeout snapshot | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 历史只读证据；不代替 Stage C 重验 |
| legacy compatibility | PR #90～#94 与历史 evidence 保留 | 不再扩展或作为 Task 07 准入 Gate |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | 不由本任务恢复 |

## 不可宣称

- 不可将代码、本地测试、CI 或只读计划写成生产修复或迁移完成。
- 不可将 Task 07 完成条件绑定到 Profile/Binding retirement、Runtime legacy
  reference=0、旧派生数据删除或 legacy 文件总数。
- 不可将 Stage C 扩写为 Runtime、scheduler/live、长稳、通知或交易就绪。
- 不可修改、删除或重解释旧 evidence 中已经发生的事实。
- 不可宣称所有历史资产 residual 为零，也不可把 backtest 或单次 smoke
  写成策略盈利、实盘或自动交易准入。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、
`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
