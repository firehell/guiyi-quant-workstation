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
`59c14ffd7e97c39814576f16dc2c413c8fafb5db` 合入 `develop`。任务 03 staging、quality 与
canonical writer 已由 PR #82 以 task HEAD
`8a892a5a55d7b29b1ca036c89d8d3972bd7ed32a`、merge commit
`3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 合入 `develop`；其 CI module detector 修复由
PR #83 以 task HEAD `882bd64b6b4ee7f31d115c350f13e4cd95df5278`、merge commit
`b03d5e98f50d9ada4364a524ca78c92d1e0bbb42` 先行合入。任务 03 的本地测试与独立 Review
已通过；PR #82 两次 Linux run 虽因 CI 竞态跳过 Backend verification，合入后的 exact
commit `3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 已在 official Swift Ubuntu
`linux/amd64` 容器中以 GitHub runner 目录形态、clean detached checkout、真实 `plutil` 与
uv-managed Python 3.13 完成等价补验：Ruff 通过，后端全量 `2186 passed, 36 skipped,
0 failed`，独立 Review 批准。因此任务 03 已完成验收。压缩后的新任务 04（原 04～08）
正在 `feature/data-core-v2-historical-loop` 实现历史同步、统一读取、JM dry-run/Shadow 与
普通消费者切换。Final Review round 3 修复后的当前分支已通过 Data Core
`384 passed`、Gate/执行器/Shadow/CLI 联合回归 `48 passed`；round 2 的
CLI/API 触达回归为 `31 passed` 且 Web build 通过；round 1 的
Web unit 基线为 `169 passed / 1 skipped`；
的更广基线为后端全量 `2242 passed / 36 skipped`、隔离 PostgreSQL migration
`35 passed`与 canonical 开关下 Playwright `18 passed`，本轮尚未重跑这三项。功能仍默认关闭。
hash-bound 写入执行器已实现并仅用 fake provider、临时 SQLite/Parquet 验证，未执行真实 apply。
它现在绑定 exact rank=1 mapping acquisition plan，actual-dominant 仅按 mapping-valid
session 分段写入；actual-dominant Shadow 的 unresolved series 必须返回 concrete JM
contract，并与当日 rank=1 mapping evidence 一致。partial resume 不再信任可编辑
receipt；它仅是可修复缓存。可 skip 进度必须由 approved initial state、exact plan 与
当前 Catalog/mapping 重建，并对每个当前分区重验 manifest digest 与物理文件
checksum；仅部分覆盖不得借缓存 write plan 声称完成。
生产 revision 实测仍为
`20260721_0025`，未执行生产 migration、真实 RQData/Parquet/PostgreSQL 写入、删除、
release、Runtime 或通知。当前任务状态只能是 `BLOCKED_AT_JM_REAL_DATA_GATE`，尚未通过
独立 Review、进入 `develop` 或完成真实 historical Shadow。

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
| GY-DATA-CORE-V2 task 03 | completed on develop | PR #82；task HEAD `8a892a5a55d7b29b1ca036c89d8d3972bd7ed32a`；merge `3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1`；本地 142 targeted、319 data_core、191 engineering tests；post-merge exact Linux backend `2186 passed, 36 skipped, 0 failed`；Ruff 与独立 Review 通过；无真实写入 |
| GY-DATA-CORE-V2 task 04（原 04～08） | BLOCKED_AT_JM_REAL_DATA_GATE | Gate 前代码、dry-run inventory/plan、统一读取与默认关闭的 JM Web/API/指标切换已完成本地验证；写入执行器仅完成 fake/local 验证，生产 0026/0027、真实 JM apply/Shadow、独立 Review 与 develop 集成未完成 |
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
| 新数据核心 active target | design frozen / tasks 00～03 accepted；task 04 blocked at real-data Gate | `docs/tasks/GY-DATA-CORE-V2.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md` |
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
