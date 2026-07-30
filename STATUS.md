# 当前状态

更新时间：2026-07-30

本文件是项目当前状态的仪表盘：只列当前工作、未关闭 Gate、必要事实锚点与防过度宣称的红线。历史过程由 Git 提交和 final receipt 追溯。

## 当前在做什么

当前阶段为 V1-B 的 JM Stage 6 与指标/策略可信验证主线。用户已将旧 S6-10 标记为
`S6-10_PAUSED_BY_OWNER_FOR_CORE_CONVERGENCE`：schema-v4～v7 合同、packet、receipt 与
失败/通过 evidence 全部冻结为历史，不再生成 fresh C2、Approval D、daily child，不执行
旧合同的 mapping、部署、Runtime、通知或真实验收。

当前唯一执行序列是 `GY-CORE-00 → ... → GY-CORE-08 → GY-S6-10-R2 →
GY-S6-10-R2-RUN`。未来 Shadow 与新版 S6-10 只验收一个完整 DCE 交易日，必须覆盖夜盘、
三段日盘、23 个 confirmed 15m 桶、EOD、幂等和零非法写入；任一失败整日重启，单日 Ledger
append-only。恢复能力由同一 exact release 的独立 Runtime、RQData/网络和 Mac 恢复证据补足。

`GY-CORE-02 Active Dataset Facade` 的仓库实现状态为
`CODE_COMPLETE_EXTERNAL_GATE_PENDING`：JM historical `GET /api/v1/market/bars` 已接入
兼容 Facade；其余消费者和 live P0 均未迁移。受控 SQLite/`tmp_path` 回归只证明 response
equivalence 与零写入，不证明 PostgreSQL、canonical Parquet、RQData、Runtime、notification、
profitability、trading 或 release Ready。

`GY-CORE-03 Unified CLI` 的仓库实现状态为 `CODE_COMPLETE_EXTERNAL_GATE_PENDING`：
独立 `guiyi` entrypoint 首轮仅提供 `data verify`、`runtime status` 与 `runtime plan`。
JM `data verify` 复用 GY-CORE-02 Facade；`runtime status` 复用既有 health service；
`runtime plan` 只包装 scheduler dry-run payload。旧 `guiyi-data check-bars` 和
`rqdata_reference_metadata_gap_apply_plan.py` 保留原入口与输出形状，改为共享 service Shim。
本任务没有实现 data sync、Runtime once/run、EOD、notification、backup 或任何真实写入。

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产零 residual |
| GY-CORE-02 Active Dataset Facade | CODE_COMPLETE_EXTERNAL_GATE_PENDING | JM historical bars compatibility Facade 已实现；live source-mode schema/upsert/aggregation P0 仍须在 GY-CORE-05 Shadow 前由独立 Lane 3 完成 |
| GY-CORE-03 Unified CLI | CODE_COMPLETE_EXTERNAL_GATE_PENDING | 首轮只读命令与两个兼容 Shim 已实现；尚未授权 Runtime、data sync、EOD、通知或 backup 写入 |
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
| GY-CORE-02 | `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；只迁移 JM historical `GET /api/v1/market/bars`，非 JM 保持 legacy workbench | `docs/ARCHITECTURE.md` §2.0.1、`docs/DATA_CENTER.md` §2.1.2 |
| GY-CORE-03 | `CODE_COMPLETE_EXTERNAL_GATE_PENDING`；首轮 `guiyi` 只读 CLI + 两个 legacy Shim，不包含真实写入 | `docs/ARCHITECTURE.md` §2.0.2、`TESTING.md` |
| 核心收口 | GY-CORE-00/01 已完成；GY-CORE-02 已合入 develop；GY-CORE-03 等待独立 Review/PR 集成 Gate | `docs/tasks/GY-CORE-CONVERGENCE.md` |

## 不可宣称

- 不可把数据、消费者或 archive Gate 写成所有历史资产零 residual、Runtime Ready、长稳 Ready、通知 Ready 或自动交易 Ready。
- `LONG_RUNNING_READY=false` 仅为 `deprecated / not_applicable` 兼容字段；任何单日 Gate
  不得将其设为 true。`JM_RUNTIME_READY` 只能在单日自然运行、同一 exact release 独立恢复
  证据、独立 Review 全部通过且用户最终批准后发布。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；`REJECTED_RESEARCH_CANDIDATE` 不得被翻转。
- 不可宣称 `HTDY_XMA_SEMANTICS_AUDITED`；原始 XMA 仅保留精确 observation-only policy。

相关业务定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
