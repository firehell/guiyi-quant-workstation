# 当前状态

更新时间：2026-07-31

本文件是项目当前状态的仪表盘：只列当前工作、未关闭 Gate、必要事实锚点与防过度宣称的红线。历史过程由 Git 提交和 final receipt 追溯。

## 当前在做什么

当前 active 执行合同为 `docs/tasks/GY-DATA-CORE-V2.md`。任务 00 已完成 canonical、
迁移顺序与治理边界冻结，并通过 PR #76 以 merge commit
`2266d7f7d285b137a2375aeb78f2c4305684b8e0` 合入 `develop`；post-merge
`engineering-test` 成功。任务 01 数据合同与 golden vectors 已通过 PR #78 以 exact task
HEAD `997d978f40245c8967530471aff0c2471c3478d5`、merge commit
`12f5dbc5447f2bc7ed35ffb3fcf18daabb145bee` 合入 `develop`。任务 02 已统一七字段
`DatasetKey`，追加 schema-only revision `20260730_0027`，并以非破坏性只读 view 收窄
canonical MainContractMap；PR #80 以 task HEAD
`9614710c2e70e7c544642d7688146231df49853c`、merge commit
`59c14ffd7e97c39814576f16dc2c413c8fafb5db` 合入 `develop`。下一项为任务 03
staging、quality 与 canonical writer。目标架构仍未完成，未执行生产 migration、真实数据迁移、
消费者切换、删除、release、Runtime 或通知操作。

用户已将旧 S6-10 标记为
`S6-10_PAUSED_BY_OWNER_FOR_CORE_CONVERGENCE`：schema-v4～v7 合同、packet、receipt 与
失败/通过 evidence 全部冻结为历史，不再生成 fresh C2、Approval D、daily child，不执行
旧合同的 mapping、部署、Runtime、通知或真实验收。

旧 `GY-CORE-04～08` 路线已 `superseded / paused`，不得继续执行。`GY-CORE-02` 的 JM
兼容 Facade 与 `GY-CORE-03` 的只读 CLI 壳可在新路线中复用，但旧 Profile/Binding active
selector 不再扩展；已合入的 `GY-CORE-04` ObservationPlan/Adapter 代码保留为 legacy
compatibility，不构成新路线的 Shadow、Runtime 或通知入口。

新路线按任务 00～19 串行执行：先冻结合同，再完成数据合同、Catalog/Manifest/Gap、
canonical writer、统一读取、JM 迁移与消费者切换，之后才处理 live/SignalDecision/EOD、
其他已有品种、legacy 删除和新版单交易日 Runtime Gate。未来 Shadow 与新版 S6-10 仍只验收
一个完整 DCE 交易日；该设计不表示 Runtime Ready。

任务 02 代码已通过独立 Codex Review、35 项隔离 PostgreSQL 16 migration 测试和 exact-head
CI 后进入 `develop`。该事实只证明代码与隔离验证完成；当前生产 revision 仍为
`20260721_0025`，生产 `0026/0027` apply、Catalog 数据写入和真实数据迁移仍需专用 Gate。

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产零 residual |
| GY-DATA-CORE-V2 task 00 | completed on develop | PR #76；task HEAD `67cb7f3427329aa5df29bf63686bc762556752f7`；merge commit `2266d7f7d285b137a2375aeb78f2c4305684b8e0`；未授权真实副作用 |
| GY-DATA-CORE-V2 task 01 | completed on develop | PR #78；task HEAD `997d978f40245c8967530471aff0c2471c3478d5`；merge commit `12f5dbc5447f2bc7ed35ffb3fcf18daabb145bee`；116 项合同/Schema/聚合测试通过；无真实写入 |
| GY-DATA-CORE-V2 task 02 | code and isolated migration validation completed on develop | PR #80；task HEAD `9614710c2e70e7c544642d7688146231df49853c`；merge `59c14ffd7e97c39814576f16dc2c413c8fafb5db`；35 项隔离 PG16 migration tests；生产 apply 未授权 |
| GY-DATA-CORE-V2 task 03 | next / implementation not started | staging、quality、canonical writer；仅 fake adapter/tmp_path/隔离 DB，不调用真实 RQData 或写真实 Parquet/DB |
| GY-CORE-02 Facade / GY-CORE-03 CLI | legacy compatibility / reusable shell | 可复用，但不得继续扩展旧 Profile/Binding selector |
| GY-CORE-04～08 | superseded / paused | 04 代码保留；05～08 禁止按旧路线继续 |
| 旧 S6-10 | paused / frozen historical | 不再执行；恢复入口仅为 `GY-S6-10-R2` 单交易日合同 |
| JM Runtime 验收 | pending redesign | 单日自然运行 + 同一 exact release 独立恢复证据 + 独立 Review + 用户最终批准 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

task 自动集成只适用于通过验收、CI、独立 Review 且 exact head 匹配的可逆开发变更。
生产 migration、真实数据/DB 写入、删除、`main`/release/tag、Runtime/live enable 和真实通知
仍是人工 Gate；代码进入 `develop` 不构成这些操作的批准。

## 必要事实锚点

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | `20260721_0025` | `docs/tasks/S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md` |
| HTDY S6-08 | 已完成限定自然事件与幂等验证；autosend=false | `docs/tasks/JM-LIVE-SIGNAL-EVENT-S6-08.md` 与 final receipt |
| S6-09 单条企业微信 | event 4 only；notification 2；attempt=1 | `data/reports/jm_live_wecom_single_s6_09/` final receipt |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | `docs/tasks/JM-LIVE-STABILITY-S6-10.md` |
| 新数据核心 active target | design frozen / implementation incomplete | `docs/tasks/GY-DATA-CORE-V2.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md` |
| legacy compatibility | GY-CORE-02/03 可复用；GY-CORE-04 代码保留；04～08 旧路线不再执行 | `docs/tasks/GY-CORE-CONVERGENCE.md` |

## 不可宣称

- 不可把数据、消费者或 archive Gate 写成所有历史资产零 residual、Runtime Ready、长稳 Ready、通知 Ready 或自动交易 Ready。
- 不可把 active target、任务 02 已合入代码或任务 00 文档冻结写成数据迁移、生产 migration、
  Profile/Binding 删除、消费者切换或新 `MarketDataService` 已完成。
- `LONG_RUNNING_READY=false` 仅为 `deprecated / not_applicable` 兼容字段；任何单日 Gate
  不得将其设为 true。`JM_RUNTIME_READY` 只能在单日自然运行、同一 exact release 独立恢复
  证据、独立 Review 全部通过且用户最终批准后发布。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；`REJECTED_RESEARCH_CANDIDATE` 不得被翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；原始 XMA 仅保留精确 observation-only policy。

相关业务定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
