# 当前状态

更新时间：2026-08-06

本文件是项目当前状态仪表盘；历史过程由 Git、任务合同与既有证据追溯。历史协作材料不构成当前授权（见 `AGENTS.md` / `DECISIONS.md`）。

## 当前开发模型

普通仓库工作直接在 `develop` 编辑并按影响范围本地验证；本地必要检查是完成声明依据。协作门禁与可选工具边界见 `AGENTS.md` / `DECISIONS.md`。当前 Personal Development Mode 迁移只修改仓库文件，不代表重新执行任何 release/tag、生产 DB/正式数据写入、Runtime/live 切换、真实通知、GitHub rules 修改或订单操作。

真实外部操作只接受一次新的、范围明确的用户执行意图，并只用于紧随其后的一次匹配尝试。历史审批材料、dry-run 和先前会话不能复用为执行权限；数据质量、安全、默认关闭与无订单边界始终优先。

## 当前执行线

21 品种退役已完成生产执行：活动品种池为 69，目标品种的 8,625 个文件
（1,466,729,156 bytes）和 1,141,643 条 PostgreSQL 记录已删除，复验残留文件/记录均为 0。
保留品种已完成 443 个 RQData 直供目标与 608 个 Canonical 聚合目标刷新；
生产 Runtime 为 `runtime-20260805-b81a9d99` / `b81a9d9941f0cca74ea2a0c73b449861b121d139`。
通知、live 及退役 HTDY label 保持关闭，自动交易仍不在项目范围。

Task 07 Stage A/B 的最新仓库证据记录 release/main/tag 已收口，且生产 PostgreSQL revision 曾回读为 `20260803_0032`。本次个人开发模式迁移未重新连接生产环境，因此该 revision 仍需在后续生产只读验收中再次精确回读。

Task 07 Stage C 已收窄为“JM 目标 Canonical 验收与精确缺口计划”。历史 candidate 基于 `develop@364753e72458641e226280e326841919539c1354`，仅从 `config/data_core_v2_targets.yaml`、Catalog 和 MainContractMap 生成 JM 显式目标，再通过既有 Canonical reader 和 `MarketDataService` 只读验收。该 commit 与既有协作记录是历史定位信息，不是继续开发的前置授权。

仓库当前已移除旧 Web/backend backtest 子系统与 S6-08/S6-09/S6-10 控制面：不再提供
`/api/backtests/**`、`/ws/backtests/**`、`/backtest`、`/backtest/batch`、`/settings`、
`guiyi-backtests` worker/queue、`guiyi runtime plan` 或 runtime health scheduler component。
Market、watchlists、runtime status、Signal/Data/Review 非回测路径、Task 06、盘后 scheduler 与
Canonical data 保留。此处只描述 `develop` 仓库事实，不代表 release、Runtime promotion、生产 DB/
正式数据删除、host output 清理或服务停止已经发生。

唯一目标范围为：

- `continuous / JM.MAIN`；
- `actual_dominant / MainContractMap rank=1 volume_open_interest`；
- `1m/5m/15m/30m/60m/1d/1w`；
- 窗口起点 `2013-03-22`，终点为当前完整 MainContractMap 的最后交易日。

每个目标只能得到 `KEEP_CANONICAL`、`REDOWNLOAD_DIRECT`、`REBUILD_AGGREGATE` 或 `REGISTER_DATA_GAP`。全部有效时固定返回：

```text
Stage_C=NO_DATA_WRITE_REQUIRED
writes_authorized=false
repair_count=0
production_writes=false
```

旧的 49,885 资产、30,536 repair actions、24,178 RQData requests 和 2,186 batches 只是 superseded historical evidence。它们不再是 active Stage C 输入，对应的 CLI packet/plan/preflight/apply/verify 路由已从 active parser 移除并 fail-closed。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| GY-DATA-CORE-V2 Task 00～03 | completed on develop | 完成事实可由历史证据追溯；不是后续授权 |
| GY-DATA-CORE-V2 Task 04 | completed on develop | Canonical 自身质量准入、统一读取与普通消费者回归；legacy Shadow 不是准入条件 |
| GY-DATA-CORE-V2 Task 05 | completed on develop | trusted consumers 与 fail-closed derived/reference inventory；不含真实删除 |
| GY-DATA-CORE-V2 Task 06 | completed on develop | 固定 EMA21 evaluator + `0028..0031` + live/decision/EOD/Review/Sample/retention；Runtime/live 未启用 |
| GY-DATA-CORE-V2 Task 07 Stage C | implementation candidate | 按当前代码运行本地定向与领域验证；生产只读验收未执行 |
| GY-DATA-CORE-V2 Task 08 | pending | Stage D Runtime promotion 的独立业务任务；任何真实切换需新的精确范围执行意图 |
| GY-DATA-PRODUCT-RETIREMENT-21 | completed / released | 21 品种全链路删除、69 品种七周期刷新、Runtime 发布与残留验证完成 |
| 旧派生数据清理 | optional / separate | 不阻塞 Task 07；仓库内删除与生产/正式数据删除必须分别分类 |
| scripts-cli-consolidation | implementation on develop | 统一 `guiyi data download/aggregate/live/sync/audit`；旧 scripts/rqdata_* 与 plan/migrate/task07 已移除；正式数据/RQData/Runtime 未执行 |
| Backtest/S6 repository retirement | implementation on develop | 旧 API/Web/worker/queue/CLI、S6-08/09/10 control plane 与 tracked legacy evidence 已退出；完整 backend/frontend 验证与任何外部清理由后续任务负责 |

## 未完成事项与执行边界

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定实现范围 |
| 全历史 residual triage | pending | 不得将消费者验收扩写为所有历史资产 residual 为零 |
| Task 07 Stage C | implementation candidate | 历史协作修正记录仅作事实保留；当前完成依据是适用的本地验证 |
| Task 07 production read-only acceptance | pending | 重新回读 PostgreSQL `20260803_0032` 并验收 JM 目标 Canonical；本次未执行 |
| Task 06 live/EOD contract | passed | 已冻结单一 EMA21 confirmed-close observation 合同；不扩展 centered-XMA 白名单 |
| Task 06 production migration | passed | `0028 -> 0031` empty/disabled smoke 已通过；该事实不授权 Runtime/live enable |
| 21 品种行情与 legacy 工件删除 | passed | 生产 DB/三个数据 root 残留为 0；仓库内 1,035 个专属历史 manifest 已删除，混合审计报告不作整文件删除 |
| release / main / tag | released | PR #155 合入 develop，PR #156 合入 main；Runtime tag 为 `runtime-20260805-b81a9d99` |
| Task 08 Runtime promotion | pending / default off | Runtime 保持关闭；未来切换必须满足业务检查并取得该次 scope 的独立意图 |
| JM Runtime 验收 | pending redesign | 保留单日自然运行、恢复和零非法写入等业务验证；协作材料不是授权条件（见 `AGENTS.md`） |
| 长稳 / 通知 / 交易就绪 | not ready | 本次不启用 live、不发送通知；自动订单始终不在项目范围内 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 依据业务验证和实际观察结果；每个真实外部动作分别要求精确 scope 的一次性意图 |

## 必要事实锚点

| 事实 | 当前证据值 | 边界 |
|---|---|---|
| PostgreSQL revision | `20260803_0032` | 本次退役 preflight、删除和刷新均实时回读 |
| 21 品种退役 receipt | packet `fee133a5…`; residual DB/files `0/0` | 删除已提交，rollback tag 只回退代码，数据恢复需从 RQData 重建 |
| Canonical closeout snapshot | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 历史只读证据；Stage C 将重新验收明确目标 |
| MainContractMap closeout snapshot | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 历史只读证据；不代替 Stage C 重验 |
| legacy compatibility | PR #90～#94 与历史 evidence 保留 | 不再扩展，也不作为 Task 07 准入或执行授权 |
| 旧 backtest/S6 控制面 | retired from repository | 历史事实仅由 Git 追溯，不保留 compatibility 或恢复入口 |

## 不可宣称

- 不可将代码、本地测试、CI 或只读计划写成生产修复、迁移或真实执行完成。
- 不可将 Task 07 完成条件绑定到 Profile/Binding retirement、Runtime legacy reference=0、旧派生数据删除、legacy 文件总数或协作审批材料。
- 不可将 Stage C 扩写为 Runtime、scheduler/live、长稳、通知或交易就绪。
- 不可修改或重解释旧 evidence 中已经发生的事实，也不可把旧审批材料用作当前授权。
- 不可宣称所有历史资产 residual 为零，也不可把历史 backtest 或单次 smoke 写成策略盈利、实盘或自动交易准入。
- 不可从 release/tag 意图推导 Runtime/live/通知权限，也不可从任何意图推导订单权限。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
