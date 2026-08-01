# GY-DATA-CORE-V2：数据交互核心收口 active 合同

更新时间：2026-08-01

## 1. 状态与边界

本文是数据交互核心收口的 active 执行合同。目标设计和任务 00～19 已获一次性预批准。
任务 00 已通过测试、CI 与独立 Codex Review，并由 PR #76 以 merge commit
`2266d7f7d285b137a2375aeb78f2c4305684b8e0` 合入 `develop`；该 Review 不是人类或 Runtime
evidence。任务 01 已通过测试、三轮独立 Codex Review 与 exact-head CI，由 PR #78 以 task
HEAD `997d978f40245c8967530471aff0c2471c3478d5`、merge commit
`12f5dbc5447f2bc7ed35ffb3fcf18daabb145bee` 合入 `develop`。任务 02 已通过测试、独立
Codex Review 与 exact-head CI，由 PR #80 以 task HEAD
`9614710c2e70e7c544642d7688146231df49853c`、merge commit
`59c14ffd7e97c39814576f16dc2c413c8fafb5db` 合入 `develop`。该任务只完成七字段 Catalog
合同、schema-only `0027`、非破坏性 canonical MainContractMap view 与隔离 PostgreSQL
migration 验证。生产 schema 后续已在 Task 04 精确 Gate 下升级到 `0027`；真实数据/DB 写入
仍未完成。任务 03
staging、quality 与 canonical writer 已通过本地测试和独立 Codex Review，并由 PR #82
以 task HEAD `8a892a5a55d7b29b1ca036c89d8d3972bd7ed32a`、merge commit
`3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 合入 `develop`。CI module detector 修复 PR #83
以 task HEAD `882bd64b6b4ee7f31d115c350f13e4cd95df5278`、merge commit
`b03d5e98f50d9ada4364a524ca78c92d1e0bbb42` 先行合入。PR #82 的两次 Linux run 都在修复
生效前启动并跳过 Backend verification；随后已对合入后的 exact commit
`3ceb57bd0661d1fd3c35401a68f2b4345eca3ae1` 使用 official Swift Ubuntu `linux/amd64`
容器、GitHub runner 目录形态、complete Git bundle、clean detached checkout、真实
`plutil` 与 uv-managed Python 3.13 完成等价补验。Ruff 与后端全量通过：
`2186 passed, 36 skipped, 0 failed`；独立 Codex Review 批准。因此任务 03 已完成验收，
任务 04 成为下一项。

```text
ACTIVE_TARGET_FROZEN
IMPLEMENTATION_INCOMPLETE
PRODUCTION_MIGRATION_0027_APPLIED
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

## 4. 压缩后的串行任务与当前状态

2026-07-31 起，原 04～19 按可运行闭环压缩为新任务 04～08。旧编号只作为历史拆分和
lineage，不再逐项调度。

| 任务 | 内容 | 当前状态 |
|---:|---|---|
| 00 | canonical 与治理迁移 | completed on develop；PR #76；task HEAD `67cb7f34`；merge `2266d7f7` |
| 01 | 数据合同与 golden vectors | completed on develop；PR #78；task HEAD `997d978f`；merge `12f5dbc5`；116 tests；无真实写入 |
| 02 | Catalog/Manifest/Gap migration | code + isolated migration validation completed on develop；PR #80；task HEAD `9614710c`；merge `59c14ffd`；35 PG16 tests；生产 schema 已在 Task 04 Gate 下升级到 0027 |
| 03 | staging、quality、canonical writer | completed on develop；PR #82；task HEAD `8a892a5a`；merge `3ceb57bd`；本地 142 targeted、319 data_core、191 engineering tests；post-merge exact Linux backend 2186 passed / 36 skipped / 0 failed；Ruff 与独立 Review 通过；真实 RQData/Parquet/DB 写入未授权 |
| 04（原 04～08） | 历史数据闭环、JM 基线迁移、普通消费者切换 | `BLOCKED_AT_JM_REAL_DATA_GATE`；`develop@da2233b0`/CI 与生产 0027 schema 已完成；第二个 apply 初始化空管理目录后暴露 UTC 夜盘/下一交易日边界错误，未写数据/metadata/receipt；TDD 修复已通过本地测试，尚待新 exact HEAD/CI/packet/批准，详见 4.1 |
| 05（原 09～10） | Backtest、Signal、Review 可信消费者切换 | pending；任务 04 未验收前禁止启动 |
| 06（原 11～14） | live、SignalDecision、EOD、ResearchSample/retention | pending / migration + Runtime + deletion Gate |
| 07（原 15～18） | 其他已有品种迁移、legacy 与历史工件受控清理 | pending / batched data + exact deletion Gate |
| 08（原 19） | release candidate、JM 单交易日 Shadow 与 Runtime 验收 | pending / release + Runtime Gate |

任务必须串行。任务 00～03 均已通过各自测试、独立 Review 与适用 CI/等价 Linux Gate，并
集成 `develop`；任务 04 已推进到 `develop@da2233b0` 且 exact-head CI 成功，生产 schema 已升级
到 `0027`。首个真实 apply 在任何 RQData/Parquet/metadata 副作用前 fail-closed；D1 Gate
修复集成后，第二个真实 apply 初始化空的 canonical/staging 管理目录，随后在
mapping/Parquet/metadata/receipt 持久化前因 UTC 夜盘的下一交易日标签边界错误 fail-closed。
当前修复已通过本地全量测试，但新的 exact HEAD、CI、
packet 与批准尚未完成。
任务 02/03/04 的代码完成不授权生产 migration、真实
RQData、真实 Parquet/DB 写入或其他真实副作用。任务内 Plan、普通修改、Review 修复与已
通过 Gate 的 task→`develop` 集成不再逐项重复请求用户批准。

### 4.1 新任务 04 当前验收快照

Gate 前代码锚点：

```text
branch=feature/data-core-v2-historical-loop
base=develop@37ad783646c26e81f923f99b57fd11b57912672f
reviewed_code_head=f67958c9695a6dbff3dcbd24cb788f0fe65e1f5b
reviewed_gate_fix_head=54ee8e006f8d4729fc641ce30466eb9186c3cee8
develop=da2233b0c3c0b2707cabd1d2774ec22a9ab5f75e
github_engineering_test=30641513830 success
develop_engineering_test=30644599942 success
task04_engineering_test=30645505589 success
develop_da2233b0_engineering_test=30675343564 success
production_revision=20260730_0027
first_apply=fail_closed_before_rqdata_or_writes
second_apply=fail_closed_after_empty_management_directory_initialization
feature_flag=VITE_JM_DATA_CORE_V2_ENABLED=false
state=BLOCKED_AT_JM_REAL_DATA_GATE
```

已实现且本地验证：

- exact coverage 缺口规划、初次调用加最多三次重试、DataGap 登记/修复清除、rank=1 mapping；
- RQData adapter、provider `JM88` 到 canonical `JM.MAIN` 的 unadjusted identity、direct
  `1m/1d/1w` 与 session-based derived `5m/15m/30m/60m`；
- Catalog/manifest/checksum/gap/mapping fail-closed reader 与 `MarketDataService.get_bars()`；
- JM legacy inventory、迁移 plan digest、13 项有效 Shadow query set（continuous 7 项、
  actual-dominant 6 项）与精确 identity/OHLCV/边界比较；actual-dominant `1w` 明确禁止。
  正式 `guiyi data migrate shadow` 不接受 caller-supplied mapping，而是从当前 DB/session
  的 canonical MainContractMap view 为每个 actual-dominant bar 交易日取得 rank=1
  evidence；缺失/歧义或 concrete JM contract 不精确匹配均 fail-closed；
- canonical coverage、bars、EMA、MACD API 和默认关闭的 JM Web 切换；非 JM 保持原路径；
  EMA warm-up 以实际有效前置 bar 计数为准，会跨休市/周末逐步扩窗，不再把
  `N * 自然时间频率` 当作 N 根交易 bar；
- lineage 返回稳定的 source DatasetKey/manifest/data-version identity，并以独立
  `request_identity_token` 绑定 exact request window；
- apply approval packet 绑定 exact task head、0026/0027、JM scope、plan digest、canonical/staging
  root、脱敏 PostgreSQL target、四张目标表、rollback、禁止写 legacy 资产，以及
  exact rank=1 mapping acquisition/write plan（交易日、时间窗、allowed contracts）。
- plan 在生产 0025 直接按 0027 canonical view 的相同 `DISTINCT` 字段、过滤条件和共享
  resolver 读取底层 `main_contract_map`，把既有 rank1 rows 绑定为 approved initial state；
  0026 中间态 fail-closed，0027 才读取新 Catalog/view。`apply` 在 inventory、receipt、root、
  RQData 和 writer 前先要求 exact 0027。标准 CLI pretty packet 可在 8 MiB 有界预解析上限内
  load/self-verify，超过上限在 JSON parse 前拒绝。
- hash-bound `migrate apply` 执行器先后执行 packet preflight、current-facts 重算、clean exact
  head 与 0027 revision 检查；全部通过后才允许创建 `data-core-v2` 根、初始化 RQData/writer。
  direct dataset 矩阵为 continuous `1m/1d/1w`、actual-dominant `1m/1d`，actual sessions
  必须消费 dataset write plan 中的 rank=1 mapping 有效分段，不得发布全局窗口
  coverage；gap 可提交并阻断
  overall status，legacy 路径不可写。
- partial apply 将 approved initial state 与当前可验证状态分开；receipt 仅为可修复缓存，
  无权授权 state drift 或 skip。新进程 resume 必须使用原 packet，并从 exact mapping/
  dataset plan 与当前 Catalog 重建进度；已验证 mapping rows 只覆盖其精确
  approved days；执行器将缺失日按已验证日切分为 approved-index 连续 run，每个
  run 均用精确起止和 expected days 调用 provider/synchronizer，合并后必须形成精确
  day/contract 全集。当前 partition 状态序列化保留 `file_uri/manifest_uri`，并重验 manifest digest
  与物理 checksum；dataset write-plan digest/覆盖窗口必须可独立重算，缺失、过期或被
  篡改 receipt 不影响授权结论且可由重建结果修复。

2026-07-31 read-only inventory/plan：

```text
inventory=915
eligible_reuse=1 (JM2609 direct rqdata 1d, 3 rows)
excluded=914
plan_digest=fbb18529684914b268cbc020d589856aaf44097389b2a670c65c6b1ab6ca1358
window=(2013-03-21T00:00:00Z, 2026-07-29T15:00:00Z]
contracts=JM.MAIN + 41 actual JM contracts
trading_days=3246
session_windows=10576
existing_rank1_rows_bound=3244
missing_rank1_days=2
bound_facts_compact_bytes~=3200172
canonical_root=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/data-core-v2/canonical
staging_root=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/data-core-v2/staging
calls_rqdata=false
writes_postgresql=false
writes_parquet=false
```

验证结果：

```text
Ruff (services/quant-api/app + services/quant-api/tests, --no-cache): passed
mapping/apply focused (Final Review round 5): 46 passed
Data Core (production Gate D1 fix): 404 passed
historical apply (night-session trading-day fix): 32 passed
Data Core (night-session trading-day fix): 407 passed
Gate/executor/Shadow/CLI/Market focused (Final Review round 4): 81 passed
targeted CLI/Market (Final Review round 5): 58 passed
targeted CLI/API (Final Review round 2): 31 passed
backend full (production Gate D1 fix): 2289 passed, 36 skipped, 0 failed
backend full (night-session trading-day fix): 2292 passed, 36 skipped, 0 failed
isolated PostgreSQL migration: 35 passed, temporary database dropped
Web unit: 169 passed, 1 skipped, 0 failed
Web build: passed, 3616 modules, dependency topology acyclic
canonical-enabled Playwright mock smoke: 18 passed
git diff --check: passed
check-secrets: 9326 files, no high-confidence secrets
independent Final Review round 5: Spec PASS, Quality APPROVED, no Critical/Important blockers
independent Gate-fix review: Spec PASS, Quality APPROVED, no Critical/Important blockers
independent production Gate D1 fix review: Spec PASS, Quality APPROVED, no Critical/Important blockers
GitHub exact-head engineering-test: run 30641513830, success
```

未完成且不得越过：

- 生产 PostgreSQL schema 已升级并现场核验为 `20260730_0027`；三张新 metadata 表仍为空；
- 获准的临时 PostgreSQL `guiyi_quant_task04_isolated_test` 已完成
  `0025 -> 0027 -> 0026 -> 0027` 与完整 migration 测试，`35 passed`，随后已删除；
- `5ba8f7c4` 首个真实 apply 已尝试，但因 actual-dominant `1d` 进度窗口误用 1m session 而在
  构造 RQData/CanonicalStore 和创建数据根前以 `approval_facts_changed` fail-closed；
- D1 Gate 自锁已用 TDD 修复，真实旧 packet 离线诊断 `41 -> 0`；但修复改变 source HEAD，
  因此 `5ba8f7c4` packet/hash/approval 全部失效，不得复用；
- D1 修复已集成至 `develop@da2233b0`，同一 exact SHA 的 GitHub CI run `30675343564` 成功；
  使用用户批准的 `07:00Z` 起始 packet 执行第二个真实 apply 时，DCE 夜盘窗口携带下一交易日
  标签，旧自然日上界校验触发 `historical_apply_trading_days_invalid` 并 fail-closed；
- 第二次 apply 初始化了空的 canonical/staging、journal 与 quarantine 管理目录；失败后现场
  复核三张 metadata 表、mapping 增量、canonical/staging 文件与 receipt 均为零；未执行
  historical Shadow；
- 夜盘修复删除错误的 UTC 自然日上下界判断，同时保留 packet mapping trading-day 全量相等
  校验，并锁定 runtime 交易日全集多/少一天均在任何同步调用前拒绝；新增回归测试后
  historical apply `32 passed`、Data Core `407 passed`、后端全量
  `2292 passed / 36 skipped / 0 failed`、Ruff 通过；
- 该修复再次改变 source HEAD，因此所有 `da2233b0` packet/hash/approval 已失效，不得复用；
- approval packet 只允许由提交后的 clean exact head 生成；packet/hash 属于仓库外 Gate 证据，
  不反向写入提交造成 self-drift；
- 当前生产 Gate follow-up fix 尚待新的 clean exact HEAD、GitHub CI、packet 与用户批准；
- canonical 文档不追踪 packet 的瞬时存在状态或具体 hash；生产 Gate 必须现场用 loader 核对
  packet 绑定当前 clean exact head，且不得复用任何旧 packet/hash。

因此新任务 04 仍不能标记完成，也不能进入任务 05。下一动作是提交并集成夜盘交易日 Gate fix，取得
同一 exact SHA 的 CI，重新生成并核验 packet，再由用户批准真实 JM apply 与 Shadow。

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
