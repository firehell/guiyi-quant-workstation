# GY-DATA-CORE-V2：数据交互核心收口 active 合同

更新时间：2026-07-30

## 1. 状态与边界

本文是数据交互核心收口的 active 执行合同。目标设计和任务 00～19 已获一次性预批准。
任务 00 已通过测试、CI 与独立 Codex Review，并由 PR #76 以 merge commit
`2266d7f7d285b137a2375aeb78f2c4305684b8e0` 合入 `develop`；该 Review 不是人类或 Runtime
evidence。任务 01 是下一项，仍不得把代码进入 `develop` 解释为任何真实副作用批准。

```text
ACTIVE_TARGET_FROZEN
IMPLEMENTATION_INCOMPLETE
PRODUCTION_MIGRATION_NOT_AUTHORIZED
REAL_DATA_WRITE_NOT_AUTHORIZED
DELETION_NOT_AUTHORIZED
RELEASE_NOT_AUTHORIZED
RUNTIME_NOT_AUTHORIZED
```

本合同不改变 V1 的 observation-only、`auto_order=false`、真实通知默认关闭与禁止自动交易边界。

## 2. Active target

### 2.1 Historical

```text
RQData (only provider)
-> temporary staging
-> schema/session/duplicate/OHLCV/coverage validation
-> one canonical Parquet root (provider 1m / 1d / 1w)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService
-> Web / Indicator / Backtest / Signal / Review
```

- staging 或校验失败数据不长期保留；精确窗口最多自动重试三次，之后登记 DataGap。
- 与 DataGap 相交的读取失败关闭；无关且连续、验证通过的数据可继续使用。
- 5m/15m/30m/60m 只从 canonical 1m 按 TradingSession 确定性聚合。
- `continuous` 与 `actual_dominant` 显式且不可互换。
- `MainContractMap` 只表达 `trading_day -> RQData rank=1 actual_contract`。
- 同键相同数据可幂等合并；OHLCV 或 identity 冲突必须 fail-visible。

### 2.2 Identity 与 lineage

`DatasetKey` 至少固定 provider、dataset_kind、symbol、contract_or_series、base frequency、
adjustment 与 schema version。轻量 lineage 只绑定 DatasetKey、manifest version/digest、
exact query window、source data version 和策略输入/指纹版本；不建立第二个 active resolver
或通用 lineage 图。

### 2.3 Live、decision 与 EOD

live 1m 与盘中聚合保存在 PostgreSQL observation 层。正式策略判断目标为不可变
`SignalDecision`；SignalEvent/通知仅由未来实时、合同允许的首次 confirmed 新信号产生。
修复、补数、replay 与 EOD 重算永不补发通知。

EOD 重新从 RQData 获取 provider-final 数据，先比较输入指纹，再以原 strategy/schema/recipe
确定性重算结果。live bar 不复制或晋升为 historical canonical。

### 2.4 Retention 与受控删除

live/decision/event/notification/reconciliation/snapshot/fingerprint 的目标留存为 30 天。
人工复盘完成后只提取精简 `ResearchSample` 长期保留；该机制尚未实现或启用。

historical evidence/report/receipt 默认保护。6B 只允许在以下条件全部满足后，由独立任务执行：

1. 精确逐文件 deletion manifest；
2. 替代 regression/release/runtime 必要证据；
3. active canonical、测试、Gate、文档和 Runtime 引用扫描为零；
4. 独立 Review 允许删除；
5. 用户批准 exact scope；
6. 删除后全仓验证与引用扫描。

本合同和任务 00 均不授权删除任何文件、Git 历史、数据库记录、Parquet、evidence、report
或 receipt。report 14/15 与仍被 Gate/Runtime 引用的工件必须保护。

## 3. Legacy compatibility 与替换关系

- `GY-CORE-02` Facade：可复用壳；不得继续扩展旧 Profile/Binding active selector。
- `GY-CORE-03` CLI：可复用只读/编排壳；不得把 Shim 解释为新数据核心已完成。
- `GY-CORE-04`：代码已合入但旧路线 superseded；仅保留 legacy compatibility。
- `GY-CORE-05～08`：paused/superseded，禁止继续旧 Shadow、release、Runtime 与删除路线。
- `docs/tasks/GY-CORE-CONVERGENCE.md`：frozen historical，不再提供 active 授权。
- `docs/tasks/GY-CORE-01-ARCHITECTURE-INVENTORY.md` 与
  `docs/tasks/GY-CORE-02-ACTIVE-DATASET-FACADE-PLAN.md`：旧路线盘点/计划快照，
  其中 future references 全部 frozen historical。
- `TESTING.md` 与 `docs/SIGNAL_EVENTS.md` 中对已合入 GY-CORE-04 的测试或实现描述：
  legacy implementation facts，不是继续旧 GY-CORE-05～08 的授权。
- `JM-LIVE-STABILITY-S6-10.md`、`V1-FINAL-ACCEPTANCE-S6-11.md` 中的
  `GY-S6-10-R2` 只保留旧 S6-10 paused/frozen historical 与未来 Runtime Gate 边界；
  实际恢复入口必须服从本合同任务 19 及新的专用批准。

Profile/ActiveBinding/复杂 lineage 的退出顺序固定为：

```text
新合同与 golden vectors
-> Catalog/Manifest/Gap 与 canonical writer
-> MarketDataService
-> JM dry-run/apply/Shadow
-> consumers 逐个切换
-> live/EOD 收口
-> 其他已有品种迁移
-> legacy 引用为零 + rollback 证据
-> 独立删除任务
```

## 4. 串行任务与当前状态

| 任务 | 内容 | 当前状态 |
|---:|---|---|
| 00 | canonical 与治理迁移 | completed on develop；PR #76；task HEAD `67cb7f34`；merge `2266d7f7` |
| 01 | 数据合同与 golden vectors | next / implementation not started；纯内存，无真实写入 |
| 02 | Catalog/Manifest/Gap migration | develop 已有 PR #75 代码；生产 migration 未授权，合同验收待独立复核 |
| 03 | staging、quality、canonical writer | pending |
| 04 | incremental sync、retry、gap、mapping | pending |
| 05 | MarketDataService | pending |
| 06 | JM migration dry-run | pending |
| 07 | JM apply、补数与 historical Shadow | pending / real-data Gate |
| 08 | Web/Market/Indicator consumers | pending |
| 09 | Backtest/rollover consumer | pending |
| 10 | Signal/Review consumers | pending |
| 11 | live identity/upsert/aggregation | pending / migration+Runtime Gate |
| 12 | Schema/Digest/Fingerprint/SignalDecision | pending |
| 13 | EOD reconciliation/rebuild/no-resend | pending |
| 14 | ResearchSample/30-day retention | pending / deletion Gate |
| 15 | 其他已有品种分批迁移 | pending / batched data Gate |
| 16 | legacy Profile/Binding/scripts removal | pending / all-consumer Gate |
| 17 | historical artifact deletion manifest | pending / Plan-only |
| 18 | historical artifact deletion | pending / exact deletion approval |
| 19 | JM one-trading-day Shadow/Runtime acceptance | pending / release+Runtime Gate |

任务必须串行。任务 00 通过测试、CI、独立 Review 并自动集成 `develop` 后，才可启动任务 01；
已先行存在的局部代码不得绕过这一治理 Gate。任务内 Plan、普通修改、Review 修复与已通过
Gate 的 task→`develop` 集成不再逐项重复请求用户批准。

## 5. 任务 00 验收与 Review

原始任务 00 canonical 范围仅为：

```text
AGENTS.md
STATUS.md
PROJECT_SOURCE.md
DECISIONS.md
docs/ARCHITECTURE.md
docs/DATA_CENTER.md
docs/DEVELOPMENT.md
docs/tasks/GY-CORE-CONVERGENCE.md
docs/tasks/GY-DATA-CORE-V2.md
```

2026-07-30 owner-approved 治理修订允许修改以下 9 个文件：

```text
AGENTS.md
PROJECT_SOURCE.md
DECISIONS.md
STATUS.md
docs/DEVELOPMENT.md
docs/WORKTREE_RELEASE_WORKFLOW.md
docs/tasks/GY-DATA-CORE-V2.md
docs/decisions/ADR-WS-003-develop-release-worktree-lifecycle.md
docs/decisions/ADR-WS-004-five-layer-manual-pr.md
```

因此任务 00 最终允许范围是以上两份清单的并集（12 个文件）；治理修订本身必须严格限于
第二份 9 文件清单。任何其他文件仍触发 Stop Gate。

验收要求：

- active target、legacy compatibility、frozen historical 可明确区分；
- `STATUS.md` 不宣称实现、迁移、删除或 Runtime 已完成；
- 旧 GY-CORE-04～08 明确 superseded/paused；
- 6B 只定义受控机制，不授权或执行删除；
- 文档检查、引用扫描与 `git diff --check` 通过；
- 独立 Review 无阻塞、CI 通过且 PR head SHA 精确匹配后，才可自动合入 `develop`。
- 自动集成不授权生产 migration、真实写入、删除、main/release/tag、Runtime/live 或通知。

## 6. Stop Gates

需要新架构选择、修改冻结口径、超出允许文件、base/并发漂移、三轮后检查仍失败，或需要
凭据、生产环境、真实写入、删除、release、tag、main、Runtime、通知时立即停止。

自审只能发现和修复本任务内问题，不能代替独立 Review。
