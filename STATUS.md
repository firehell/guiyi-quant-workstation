# 当前状态

更新时间：2026-08-04

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
| GY-DATA-CORE-V2 Task 00～06 | completed on develop | 以各自 PR、CI、Review 和 evidence 为准 |
| GY-DATA-CORE-V2 Task 07 Stage C | implementation candidate | 精简实现待 exact-head CI、独立 Sol Review 与 develop 集成；生产只读验收未执行 |
| GY-DATA-CORE-V2 Task 08 | pending | Stage D Runtime promotion 的独立任务，本任务不启动 |
| 旧派生数据清理 | optional / separate | Stage E 后续独立可选任务，不阻塞 Task 07 |

## 未关闭 Gate

- Stage C exact-head CI、独立 Sol Review 与 `develop` ancestry 回读。
- 生产 PostgreSQL `20260803_0032` 和 JM 目标 Canonical 的只读验收。
- Task 08 的 Runtime promotion、health/smoke 与 rollback Gate。
- 任何真实 RQData、Parquet、PostgreSQL 修复、删除、release/main/tag、Runtime/live、
  通知或交易操作均未授权。

## 不可宣称

- 不可将代码、本地测试、CI 或只读计划写成生产修复或迁移完成。
- 不可将 Task 07 完成条件绑定到 Profile/Binding retirement、Runtime legacy
  reference=0、旧派生数据删除或 legacy 文件总数。
- 不可将 Stage C 扩写为 Runtime、scheduler/live、长稳、通知或交易就绪。
- 不可修改、删除或重解释旧 evidence 中已经发生的事实。
