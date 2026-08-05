# 当前状态

更新时间：2026-08-05

本文件是项目当前状态仪表盘；历史过程由 Git、任务合同与既有 receipt/report/evidence 追溯。历史 PR、CI、Review、packet、hash 或 receipt 只记录已经发生的事实，不构成当前授权。

## 当前开发模型

普通仓库工作直接在 `develop` 编辑并按影响范围本地验证；本地必要检查是完成声明依据，CI 和协作工具仅作可选补充。当前 Personal Development Mode 迁移只修改仓库文件，不代表重新执行任何 release/tag、生产 DB/正式数据写入、Runtime/live 切换、真实通知、GitHub rules 修改或订单操作。

真实外部操作只接受一次新的、范围明确的用户执行意图，并只用于紧随其后的一次匹配尝试。历史审批材料、dry-run 和先前会话不能复用为执行权限；数据质量、安全、默认关闭与无订单边界始终优先。

## 当前执行线

Task 07 Stage A/B 的最新仓库证据记录 release/main/tag 已收口，且生产 PostgreSQL revision 曾回读为 `20260803_0032`。本次个人开发模式迁移未重新连接生产环境，因此该 revision 仍需在后续生产只读验收中再次精确回读。

Task 07 Stage C 已收窄为“JM 目标 Canonical 验收与精确缺口计划”。历史 candidate 基于 `develop@364753e72458641e226280e326841919539c1354`，仅从 `config/data_core_v2_targets.yaml`、Catalog 和 MainContractMap 生成 JM 显式目标，再通过既有 Canonical reader 和 `MarketDataService` 只读验收。该 commit、既有 CI 和 Review 记录是历史定位信息，不是继续普通开发或验证的前置授权。

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
| GY-DATA-CORE-V2 Task 00～03 | completed on develop | 既有 PR、CI、Review 和 evidence 是完成事实的历史追溯，不是后续授权 |
| GY-DATA-CORE-V2 Task 04 | completed on develop | Canonical 自身质量准入、统一读取与普通消费者回归；legacy Shadow 不是准入条件 |
| GY-DATA-CORE-V2 Task 05 | completed on develop | trusted consumers 与 fail-closed derived/reference inventory；不含真实删除 |
| GY-DATA-CORE-V2 Task 06 | completed on develop | 固定 EMA21 evaluator + `0028..0031` + live/decision/EOD/Review/Sample/retention；Runtime/live 未启用 |
| GY-DATA-CORE-V2 Task 07 Stage C | implementation candidate | 按当前代码运行本地定向与领域验证；生产只读验收未执行 |
| GY-DATA-CORE-V2 Task 08 | pending | Stage D Runtime promotion 的独立业务任务；任何真实切换需新的精确范围执行意图 |
| 旧派生数据清理 | optional / separate | 不阻塞 Task 07；仓库内删除与生产/正式数据删除必须分别分类 |

## 未完成事项与执行边界

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定实现范围 |
| 全历史 residual triage | pending | 不得将消费者验收扩写为所有历史资产 residual 为零 |
| Task 07 Stage C | implementation candidate | 既有 exact-head CI 与 Sol Review 修正记录作为历史事实保留；当前完成依据是适用的本地验证 |
| Task 07 production read-only acceptance | pending | 重新回读 PostgreSQL `20260803_0032` 并验收 JM 目标 Canonical；本次未执行 |
| Task 06 live/EOD contract | passed | 已冻结单一 EMA21 confirmed-close observation 合同；不扩展 centered-XMA 白名单 |
| Task 06 production migration | passed | `0028 -> 0031` empty/disabled smoke 已通过；该事实不授权 Runtime/live enable |
| 旧行情与 legacy 工件删除 | no current execution intent | Git 跟踪的过期代码/文档可按普通仓库删除；生产 DB、正式行情或仓库外工件删除需精确对象范围的新意图 |
| release / main / tag | no current execution intent | 本次不发布；未来每次远端 branch/tag mutation 均需新的 remote/ref/commit 范围意图 |
| Task 08 Runtime promotion | pending / default off | Runtime 保持关闭；未来切换必须满足业务检查并取得该次 scope 的独立意图 |
| JM Runtime 验收 | pending redesign | 保留单日自然运行、恢复和零非法写入等业务验证；协作材料不是授权条件 |
| 长稳 / 通知 / 交易就绪 | not ready | 本次不启用 live、不发送通知；自动订单始终不在项目范围内 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 依据业务验证和实际观察结果；每个真实外部动作分别要求精确 scope 的一次性意图 |

## 必要事实锚点

| 事实 | 当前证据值 | 边界 |
|---|---|---|
| PostgreSQL revision | `20260803_0032` | Stage B 曾回读；本次未实时重验 |
| Canonical closeout snapshot | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 历史只读证据；Stage C 将重新验收明确目标 |
| MainContractMap closeout snapshot | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 历史只读证据；不代替 Stage C 重验 |
| legacy compatibility | PR #90～#94 与历史 evidence 保留 | 不再扩展，也不作为 Task 07 准入或执行授权 |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | 不由本次迁移恢复 |

## 不可宣称

- 不可将代码、本地测试、CI 或只读计划写成生产修复、迁移或真实执行完成。
- 不可将 Task 07 完成条件绑定到 Profile/Binding retirement、Runtime legacy reference=0、旧派生数据删除、legacy 文件总数或协作审批材料。
- 不可将 Stage C 扩写为 Runtime、scheduler/live、长稳、通知或交易就绪。
- 不可修改或重解释旧 evidence 中已经发生的事实，也不可把旧审批材料用作当前授权。
- 不可宣称所有历史资产 residual 为零，也不可把 backtest 或单次 smoke 写成策略盈利、实盘或自动交易准入。
- 不可从 release/tag 意图推导 Runtime/live/通知权限，也不可从任何意图推导订单权限。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。