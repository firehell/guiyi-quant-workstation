# 当前状态

更新时间：2026-08-02

本文件是项目当前状态仪表盘：只列当前任务、未关闭 Gate、必要事实锚点与防过度宣称红线。
历史过程由 Git、任务合同及既有 receipt/report/evidence 追溯。

## 当前在做什么

当前 active 执行合同为 `docs/tasks/GY-DATA-CORE-V2.md`。Task 00～03 已按各自 PR、测试、
独立 Review 与 CI 合入 `develop`。Task 04 已完成 JM historical canonical 数据落库、
Catalog/Manifest/checksum/Gap、统一 `MarketDataService` 读取，以及普通 Web/API/指标消费者
切换和回归；本 closeout commit 经 Draft PR 的 exact-head CI、独立 Review 与 GitHub
merge commit 合入 `develop` 后，Task 04 状态生效为 `completed on develop`。

Task 04 的正式验收只依赖 Canonical 自身：

```text
canonical schema + coverage
-> Catalog / Manifest / physical checksum
-> DataGap fail-closed
-> MainContractMap completeness
-> MarketDataService representative reads
-> ordinary Web / API / indicator consumer regression
```

legacy 与 Canonical 全历史逐条 OHLCV 一致、13/13 legacy historical Shadow、旧 Profile/Binding
兼容扩展，以及因 Shadow plan digest 变化重新生成 packet/preflight/apply receipt，均不再是
Task 04 或 Task 05 的准入 Gate。PR #90～#94、既有 Shadow 失败、identity/session compatibility
实现、旧 packet 与 receipt 继续作为 frozen historical evidence 或可选诊断能力保留，不删除、
不改写，也不继续执行生产 Shadow。

2026-08-02 closeout 只读现场对账：

- PostgreSQL revision：`20260730_0027`；
- Catalog：`85 datasets / 85 partitions / 0 gaps`；
- physical：`85 Parquet + 85 Manifest + 85 prepared metadata = 255 canonical files`；
- staging：`0 files`；
- 85/85 partitions 的物理 checksum、Manifest digest、Catalog identity、coverage 与 row count
  全部复验一致；
- MainContractMap 目标窗口 `2013-03-22..2026-07-30` 有 3395 条保留版本的物理 view rows，
  解析为 3245 个唯一 DCE 交易日，缺失 0、歧义 0；
- `continuous / JM.MAIN` 的 provider-direct `1m/1d/1w` 与 canonical 1m 确定性聚合
  `5m/15m/30m/60m` 通过；
- `actual_dominant / JM2609` 的 provider-direct `1m/1d` 与 canonical 1m 确定性聚合
  `5m/15m/30m/60m` 通过；无显式合约的 resolver 查询也解析到 JM2609；
- 所有现场读取均报告 `calls_rqdata=false / writes_parquet=false / writes_postgresql=false`。

本次不重新下载 RQData、不重写 Canonical Parquet、不修改生产 PostgreSQL、不生成或批准新
packet、不执行 preflight/apply/legacy Shadow，也不删除旧行情、Profile、Binding、receipt、
report、evidence 或 legacy reader。

Task 05 的 Backtest / Signal / Review canonical consumer 切换仍在独立 task worktree 的 independent
review fix round 中。derived/reference inventory 的第一版被 Review 阻断，当前只允许 fail-closed
修复与测试；不得把此前的 branch-local 记录解释为完成、合入 `develop` 或通过 Review。真实
PostgreSQL/data root 只读盘点仍是 external Gate。

## 数据核心任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| GY-DATA-CORE-V2 Task 00 | completed on develop | PR #76；治理和 canonical target 冻结 |
| GY-DATA-CORE-V2 Task 01 | completed on develop | PR #78；数据合同与 golden vectors |
| GY-DATA-CORE-V2 Task 02 | completed on develop | PR #80；Catalog/Manifest/Gap schema 与隔离 migration 验证；生产 revision 已是 0027 |
| GY-DATA-CORE-V2 Task 03 | completed on develop | PR #82；staging、quality 与 canonical writer |
| GY-DATA-CORE-V2 Task 04 | completed on develop（本 closeout commit 可从 develop 到达时生效） | Canonical 自身 Gate、统一读取与普通消费者回归；legacy Shadow 不再是准入 Gate |
| GY-DATA-CORE-V2 Task 05 | review fix round in progress | inventory independent review has unresolved Critical findings; earlier test results are historical and not final acceptance |
| GY-DATA-CORE-V2 Task 06～08 | pending | live/EOD、其他品种/受控清理、release/Runtime 分别保留独立 Gate |

## 未关闭 Gate

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定受控任务 |
| 全历史 residual triage | pending | 不得将消费者 Ready 扩写为所有历史资产 residual 为零 |
| Task 05 可信消费者切换 | blocked at independent Review | fix round and fresh Review/CI are required; not an integration, release or Runtime Gate |
| Task 07 inventory external read-only Gate | pending | 真实 PostgreSQL/data root 必须另行显式只读运行；不授权 migration、rebuild、delete 或 repair |
| 旧行情与 legacy 工件删除 | not authorized | 旧行情只读保留；任何删除需独立 exact deletion Gate |
| release / main / tag | not authorized | 本 closeout 只合入 develop |
| Runtime promotion | not authorized | Runtime 保持独立 detached，不同步本任务 |
| JM Runtime 验收 | pending redesign | 单日自然运行、同一 exact release 恢复证据、独立 Review 与用户最终批准 |
| 长稳 / 通知 / 交易 Ready | not ready | 本任务不启用 live、不发送通知、不授权订单或自动交易 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 仅在各独立 receipt 与新版 JM Runtime Gate 完成后进行 |

task 自动集成只适用于通过验收、CI、独立 Review 且 exact head 匹配的可逆开发变更。
生产 migration、真实数据/DB 写入、删除、`main`/release/tag、Runtime/live enable 和真实通知
仍是人工 Gate；代码进入 `develop` 不构成这些操作的批准。

## 必要事实锚点

| 事实 | 当前值 | 证据 |
|---|---|---|
| PostgreSQL revision | `20260730_0027` | Task 04 closeout 只读 Alembic 现场核验 |
| Canonical current state | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 closeout DB、Manifest 与物理 checksum 只读复验 |
| MainContractMap | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 closeout 只读 mapping audit |
| legacy compatibility | PR #90～#94 实现与历史 evidence 保留；不再扩展或作为准入 Gate | `docs/tasks/GY-DATA-CORE-V2.md` |
| 旧 S6-10 | owner-paused；schema-v4～v7 frozen historical | `docs/tasks/JM-LIVE-STABILITY-S6-10.md` |
| Task 05 | review fix round in progress | `scripts/derived_reference_inventory.py` is fail-closed work in progress; real DB/data root inventory not run |

## 不可宣称

- 不可宣称所有历史资产 residual 为零。
- 不可把 Task 04 完成扩写为 release、Runtime promotion、Runtime Ready、长稳 Ready、通知 Ready
  或交易 Ready。
- 不可把 Canonical 数据验收写成旧 Profile/Binding 已删除，或写成旧行情、receipt、report、
  evidence 已获删除授权。
- 不可把既有 legacy Shadow 失败、PR #90～#94 或历史 packet/receipt 改写成新的生产授权。
- 不可把 `report_id=14` trust audit、任何 backtest 或单次 smoke 写成策略盈利或实盘准入。
- 不可把 Task 05 branch-local 完成写成 `develop` merge、release、Runtime、notification、deletion 或
  profitability；Task 07 删除前仍须 exact manifest、zero active refs、independent Sol Review 与 owner approval。
- 不可把 HTDY realtime exception 写成历史回测、OOS、收益或交易资格；
  `REJECTED_RESEARCH_CANDIDATE` 不得被翻转。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/BACKTEST_ENGINE.md`、
`docs/SIGNAL_EVENTS.md` 与 `docs/INDICATOR_KERNEL.md`。
