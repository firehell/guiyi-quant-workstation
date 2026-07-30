# 当前状态

更新时间：2026-07-30

本文件是项目当前状态的仪表盘：只列当前工作、未关闭 Gate、必要事实锚点与防过度宣称的红线。历史过程由 Git 提交和 final receipt 追溯。

## 当前在做什么

当前 active 执行合同切换为 `docs/tasks/GY-DATA-CORE-V2.md`。本轮只冻结新数据核心
canonical、迁移顺序与治理边界；目标架构尚未完成，未执行生产 migration、真实数据迁移、
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

develop 已存在新 `data_core` Catalog ORM 与 migration 代码（PR #75）。该事实仅表示代码进入
集成分支；未经独立合同 Review、隔离 migration 验证和专用 DB Gate，不得据此宣称任务 01/02
验收完成或生产 schema 已应用。

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产零 residual |
| GY-DATA-CORE-V2 task 00 | pending independent review | 只冻结 active target 与治理迁移；不实现数据核心 |
| 新 data_core Catalog/migration 代码 | code present on develop | PR #75 已合入；不等于合同验收、生产 migration 或数据迁移完成 |
| GY-CORE-02 Facade / GY-CORE-03 CLI | legacy compatibility / reusable shell | 可复用，但不得继续扩展旧 Profile/Binding selector |
| GY-CORE-04～08 | superseded / paused | 04 代码保留；05～08 禁止按旧路线继续 |
| 旧 S6-10 | paused / frozen historical | 不再执行；恢复入口仅为 `GY-S6-10-R2` 单交易日合同 |
| JM Runtime 验收 | pending redesign | 单日自然运行 + 同一 exact release 独立恢复证据 + 独立 Review + 用户最终批准 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

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
- 不可把 active target、PR #75 的代码或任务 00 文档冻结写成数据迁移、生产 migration、
  Profile/Binding 删除、消费者切换或新 `MarketDataService` 已完成。
- `LONG_RUNNING_READY=false` 仅为 `deprecated / not_applicable` 兼容字段；任何单日 Gate
  不得将其设为 true。`JM_RUNTIME_READY` 只能在单日自然运行、同一 exact release 独立恢复
  证据、独立 Review 全部通过且用户最终批准后发布。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；`REJECTED_RESEARCH_CANDIDATE` 不得被翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；原始 XMA 仅保留精确 observation-only policy。

相关业务定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
