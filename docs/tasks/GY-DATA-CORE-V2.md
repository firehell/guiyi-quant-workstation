# GY-DATA-CORE-V2：数据交互核心收口 active 合同

更新时间：2026-08-02

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
migration 验证。生产 schema 后续已在 Task 04 精确 Gate 下升级到 `0027`；Task 04 的已批准
真实数据写入已经完成，closeout 不再执行任何生产写入。任务 03
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
PRODUCTION_MIGRATION_0027_APPLIED
TASK04_COMPLETED_ON_DEVELOP_IF_THIS_COMMIT_IS_REACHABLE
LEGACY_SHADOW_OPTIONAL_DIAGNOSTIC_ONLY
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
`SignalDecision`。Task 06 不生成 `SignalEvent` 或通知；如未来需要 first-seen Event，必须继续使用
既有冻结合同与独立 Gate，不得由 Task 06 决策隐式扩展。
修复、补数、replay 与 EOD 重算永不补发通知。

EOD 重新从 RQData 获取 provider-final 数据，先比较输入指纹，再以原 strategy/schema/recipe
确定性重算结果。StrategyInput trusted builder 固定
`jm_data_core_v2_ema21_direction_observation/v1.0`、`ema21/v1`、`ema_sma_window_v1`、固定参数与
`jm_ema21_confirmed_close_direction_v1`，内部计算 digest，不接受外部 identity、parameters 或摘要。
Runtime 与 EOD 只使用该 confirmed-close EMA21 evaluator；live bar 不复制或晋升为
historical canonical。

### 2.4 Retention 与受控删除

live/decision/event/notification/reconciliation/snapshot/fingerprint 的目标留存为 30 天。
Task 06 branch-local candidate 已实现 exact dry-run digest、apply 前漂移复算和单事务 child-first
删除；永久排除 Canonical、Catalog、Manifest、MainContractMap、DataGap、ResearchSample 与历史
evidence。人工复盘只有在 market phase、system compliance、rule tag 和 lesson 完整，且 EOD
reconciliation 完成后才能幂等提取精简 `ResearchSample`。scheduler 默认 disabled；生产 migration、
真实运行与 Task 07 legacy 删除均未授权。

historical evidence/report/receipt 默认保护。Task 07 只允许在以下条件全部满足后，由独立任务执行：

1. 精确逐文件 deletion manifest；
2. zero active references（active canonical、测试、Gate、文档和 Runtime 引用扫描为零）；
3. independent Sol Review 允许删除；
4. owner 批准 exact scope；
5. 删除后全仓验证与引用扫描。

本合同和任务 00 均不授权删除任何文件、Git 历史、数据库记录、Parquet、evidence、report
或 receipt。report 14/15 是 Git-traceable historical snapshots，不是 active Gate/regression；
不得改写其历史结论或删除历史证据。

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
-> JM canonical apply + physical/catalog/read verification
-> 普通 Web/API/Indicator consumers 切换
-> Task 04 closeout merge
-> Task 05 trusted-consumer switch and read-only derived/reference inventory
-> Task 06 live/EOD 收口
-> Task 07 其他已有品种迁移、legacy 引用为零 + rollback 证据
-> Task 08 release candidate 与 Runtime 验收
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
| 04（原 04～08） | 历史数据闭环、JM 基线迁移、普通消费者切换 | `completed on develop` 在本 closeout commit 经 exact-head CI、独立 Review 并由 merge commit 合入 `develop` 时生效；正式 Gate 为 Canonical 自身物理/Catalog/Gap/统一读取与普通消费者回归，详见 4.0 |
| 05（原 09～10） | Backtest、Signal、Review 可信消费者切换；derived/reference 只读 inventory | completed on develop（本 task PR merge 后生效）；exact-head independent Review=`CLEAN_FOR_INTEGRATION`；inventory 不授权 rebuild/delete，真实 DB/data-root inventory 留作 Task 07 external Gate |
| 06（原 11～14） | live、SignalDecision、EOD、ResearchSample/retention | completed on develop（PR #105 merge 后生效）；固定 EMA21 evaluator；production=`0031`，empty/disabled smoke passed；Runtime/live 未启用 |
| 07（原 15～18） | 其他已有品种迁移、legacy 与历史工件受控清理 | pending / batched data + exact deletion Gate |
| 08（原 19） | release candidate、JM 单交易日 Shadow 与 Runtime 验收 | pending / release + Runtime Gate |

任务必须串行。任务 00～03 均已通过各自测试、独立 Review 与适用 CI/等价 Linux Gate，并
集成 `develop`。Task 04 已批准的生产 migration 和 canonical apply 已完成；本 closeout 只允许
只读复验和文档收口，不授权新的 RQData、Parquet、PostgreSQL、packet、apply、Shadow、删除、
release 或 Runtime 副作用。Task 05 只能在本 closeout PR 合入后另起任务。
后续编号不得跳过：`Task 04 closeout -> Task 05 trusted consumers/inventory -> Task 06 live/EOD ->
Task 07 migration/legacy evidence -> Task 08 release/Runtime`；任何受控删除仍另需独立 Gate。

Task 06 首次隔离 migration 测试发生 URL 覆盖 incident，项目数据库已意外到 empty/disabled
`20260802_0028`。该操作没有事前 Gate，不是合规 acceptance。根因、空表/flags 证据、隔离库复测
和 downgrade/保留选项见 `GY-DATA-CORE-V2-TASK06-MIGRATION-INCIDENT.md`；Owner 已选择保留并追认
当前 empty/disabled `0028`，但该 ratification 不改写事故性质，也不授权继续生产 schema、真实
live/EOD、scheduler、Runtime 或通知操作。
branch-local candidate 后续新增 `20260802_0029`，把 `revision + confirmed` 纳入 immutable live
identity；`20260802_0030` 再以 PostgreSQL trigger 拒绝 SignalDecision UPDATE；`20260802_0031`
持久化 provider-final data version/request digest。Owner 对 PR #105 exact head `300cccbd` 批准
database-only backup 与 `0028 -> 0031` 后，production 已到 `0031`；五张新表全空、既有
SignalEvent 无 decision link、六个 flags 全 false，health 为 disabled。
生产 schema exact scope、备份/回滚与 disabled smoke 见
`GY-DATA-CORE-V2-TASK06-MIGRATION-APPROVAL.md`；该 packet 现记录已执行的 backup、migration 与
disabled/empty smoke receipt，不授权后续 Runtime、live、scheduler 或通知操作。

### 4.0 Task 04 closeout Owner 决策与正式验收（2026-08-02）

以下 Owner 决策取代 4.1～4.3 中当时仍在推进的 legacy historical Shadow Gate：

1. 已下载旧行情作为只读备份保留，不删除；当前已落库 Canonical 数据接受为正式输入，
   不重新下载、不重写；
2. 旧指标和旧派生结果不作为新系统正式输入；
3. legacy 与 Canonical 全历史逐条 OHLCV 一致、13 项 legacy historical Shadow、旧数据大小写
   identity、旧 Profile/Binding 或旧资产兼容修复，不再是 Task 04 或 Task 05 前置条件；
4. PR #92 identity 修复及 PR #93/#94 session compatibility 实现保留为可选诊断或 frozen
   compatibility，不要求新的生产 Shadow；
5. PR #90～#94、既有 Shadow 失败、旧 packet、preflight/apply receipt 与报告全部保留为历史
   evidence，不改写；Shadow plan digest 变化不触发新 packet、preflight 或 apply；
6. 本决策不授权删除、Task 05 实现、release、main/tag、Runtime、live、通知或交易。

Task 04 正式验收口径为：Canonical schema/coverage 完整并可物理复验；Catalog、Manifest digest、
checksum 与文件 row count 一致；DataGap 相交请求 fail-closed；MainContractMap 无缺失/歧义；
`MarketDataService` 能统一读取 continuous、actual_dominant、provider-direct 与 derived 周期；普通
Web/API/指标消费者切换和回归通过。本 closeout commit 经 Draft PR exact-head CI、独立 Review
并由 GitHub merge commit 合入 `develop` 后，Task 04 才是 `completed on develop`。

本次只读现场对账结果：

```text
postgresql_revision=20260730_0027
catalog=85 datasets / 85 partitions / 0 gaps
physical=85 parquet + 85 manifest + 85 prepared = 255 canonical files
staging=0 files
partition_evidence=85/85 checksum + manifest_digest + catalog_identity + coverage + row_count passed
main_contract_map_window=2013-03-22..2026-07-30
main_contract_map_physical_rows=3395
main_contract_map_resolved_trading_days=3245/3245
main_contract_map_missing=0
main_contract_map_ambiguous=0
```

代表性正常窗口 `2026-07-06T00:00:00Z..2026-07-10T15:00:00Z` 已通过：continuous
`JM.MAIN` 的 `1m/1d/1w` direct 与 `5m/15m/30m/60m` derived；actual_dominant `JM2609` 的
`1m/1d` direct 与 `5m/15m/30m/60m` derived；无显式 concrete contract 的 actual_dominant
resolver 也解析为 `JM2609`。所有读取均为只读，不调用 RQData、不写 PostgreSQL/Parquet。
独立的 in-memory Catalog gap fixture 返回 `DataGapError(reason=catalog_gap)`；现有 coverage 缺失和
derived source minute 缺失测试也通过，确认不会填充、缩短或忽略相交缺口。

closeout 本地验证：docs Gate 通过；engineering `192 passed`；secrets scan `9330 files`、零
high-confidence secret；Data Core `459 passed`；普通 Market/API/指标消费者定向 `123 passed`；
Web unit `169 passed / 1 skipped / 0 failed`；Web build `3616 modules`；canonical-enabled mock
E2E `18 passed` 且无 console error；`git diff --check` 通过。独立 Review、Draft PR exact-head CI
与 merge ancestry 仍必须在本 closeout head 上完成，不能由上述本地证据替代。

### 4.1 新任务 04 历史验收快照（已冻结）

本节记录 closeout 决策之前的 Gate 和实现事实，不再提供当前执行授权；其中 packet、apply 与
legacy Shadow 的将来式要求均已由 4.0 取消。

Gate 前代码锚点：

```text
branch=feature/data-core-v2-historical-loop
base=develop@37ad783646c26e81f923f99b57fd11b57912672f
reviewed_code_head=f67958c9695a6dbff3dcbd24cb788f0fe65e1f5b
reviewed_gate_fix_head=54ee8e006f8d4729fc641ce30466eb9186c3cee8
reviewed_night_fix_head=c163feb039fd23d16ffe6571044a135bdd698b8b
develop=e29c2940b8a4c4f0a63c88b80b6a8a4a3b7cbbb5
github_engineering_test=30641513830 success
develop_engineering_test=30644599942 success
task04_engineering_test=30645505589 success
develop_da2233b0_engineering_test=30675343564 success
develop_e29c2940_engineering_test=30678204745 success
production_revision=20260730_0027
first_apply=fail_closed_before_rqdata_or_writes
second_apply=fail_closed_after_empty_management_directory_initialization
third_apply=partial_mapping_and_continuous_1m_1d_then_fail_closed_before_1w_write
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
Data Core (initial partial-week query-anchor fix): 408 passed
Gate/executor/Shadow/CLI/Market focused (Final Review round 4): 81 passed
targeted CLI/Market (Final Review round 5): 58 passed
targeted CLI/API (Final Review round 2): 31 passed
backend full (production Gate D1 fix): 2289 passed, 36 skipped, 0 failed
backend full (night-session trading-day fix): 2292 passed, 36 skipped, 0 failed
backend full (initial partial-week query-anchor fix): 2293 passed, 36 skipped, 0 failed
isolated PostgreSQL migration: 35 passed, temporary database dropped
Web unit: 169 passed, 1 skipped, 0 failed
Web build: passed, 3616 modules, dependency topology acyclic
canonical-enabled Playwright mock smoke: 18 passed
git diff --check: passed
check-secrets: 9326 files, no high-confidence secrets
independent Final Review round 5: Spec PASS, Quality APPROVED, no Critical/Important blockers
independent Gate-fix review: Spec PASS, Quality APPROVED, no Critical/Important blockers
independent production Gate D1 fix review: Spec PASS, Quality APPROVED, no Critical/Important blockers
independent initial partial-week review: Spec PASS, Quality APPROVED, no Critical/Important blockers
GitHub exact-head engineering-test: run 30641513830, success
GitHub post-merge engineering-test for e29c2940: run 30678204745, success
```

当时未完成且不得越过的历史 Gate：

- 生产 PostgreSQL schema 已升级并现场核验为 `20260730_0027`；第三次 apply 后为
  `2 market_datasets / 2 market_partitions / 0 data_gaps`，任务窗口 rank=1 mapping receipt
  为 `3245 rows`，当前 canonical view 的 JM rank=1 总数为 `3395`；
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
- 夜盘修复已由 PR #86 以 task HEAD `c163feb0`、merge commit `e29c2940` 合入 `develop`，
  post-merge GitHub CI run `30678204745` 成功；第三次真实 apply 完成 mapping、continuous
  `JM.MAIN 1m`（`830820 rows`）与 `1d`（`3244 rows`）后，在 continuous `1w` 写入前以
  `CANONICAL_QUALITY_COVERAGE_MISMATCH` fail-closed；
- 根因是 RQData 以 `2013-03-22` 为 direct 1w 查询锚点，但不输出该上市残周 bar，首根为
  `2013-03-29`。当前 TDD 修复保留锚点 session、仅清空 packet-bound 初始残周的 expected
  endpoint；真实只读验证为 `684 expected = 684 actual`，未放宽通用 coverage validator；
- receipt 保持 `in_progress`，其中 mapping、continuous 1m/1d 均有可重验 partition evidence；
  现场未删除已发布文件或 metadata，historical Shadow 未执行；
- 该修复改变 source HEAD，因此所有 `e29c2940` packet/hash/approval 已失效，不得复用；
- approval packet 只允许由提交后的 clean exact head 生成；packet/hash 属于仓库外 Gate 证据，
  不反向写入提交造成 self-drift；
- 当前生产 Gate follow-up fix 尚待新的 clean exact HEAD、GitHub CI、packet 与用户批准；
- canonical 文档不追踪 packet 的瞬时存在状态或具体 hash；生产 Gate 必须现场用 loader 核对
  packet 绑定当前 clean exact head，且不得复用任何旧 packet/hash。

以上是当时不能标记完成、不能进入任务 05 的原因及当时拟议下一动作；该 packet/apply/Shadow
顺序现已由 4.0 Owner 决策取消，不得作为当前执行指令。

### 4.2 Resume Gate 综合复盘历史快照（已冻结，2026-08-01）

PR #88 已把 resume 修复合入 `develop@e3e03a9d`。在复用 production partial state 前完成的
综合复盘新增以下强制验收项：

1. approval-basis receipt identity：同一 HEAD 的不同 initial state 不得碰撞；receipt v2 必须绑定
   basis digest、packet hash 和自身 digest，篡改拒绝，passed 终态不可变；
2. packet/current-state execution runs：actual-dominant M1/D1 不得共享时间口径；连续主导交易日
   合并为有界 provider run，85 个 dataset plan 必须各有非空且可重算的 run；
3. real-provider readonly preflight：apply 前必须以同 packet/current-state 对 85 个 direct DatasetKey
   完成 provider quality 与 Arrow representability 校验；84/85 即使重算 receipt hash 仍拒绝；
4. terminal apply receipt：mapping 精确全集、dataset 精确全集、零 gap、partition evidence 和最终
   state digest 缺一不可 passed；commit 后 receipt fsync 失败不得报告成功，下一进程只从物理
   Catalog/manifest/checksum 重建进度；
5. Shadow fail-closed：生产入口不接受 caller JSON，而是按 approval plan 冻结 legacy exact
   IDs/evidence/path/SHA256 与 Catalog/manifest canonical lineage，按 `(start, end]` 的 query x month
   分块；周线仅扩日历上下文。当时要求 13 项 query matrix 精确，并在结束前重建 state、逐 partition
   重验 canonical 物理证据；
   任一侧为空、共同遗漏 expected bar、缺块、identity/OHLCV 差异、DB rank1 缺失/歧义或
   declared exception 未被实际消费均 blocked；Shadow receipt 绑定 apply receipt/state、source/
   chunk/expected-key/exception digests。

当前生产只读 state 复核为 `41 contracts / 3245 mapping rows / 85 plans / 85 nonempty runs`，未调用
RQData 且无写入。聚焦测试 106 项、Data Core 436 项、后端 2322 项（另 36 skipped）及
engineering 192 项均通过；独立 reviewer 最终为 `Spec PASS / Quality APPROVED`，无
Critical/Important。该 hardening 已由 PR #89 以 task HEAD `d892e916`、merge commit `ca7125a2`
合入 `develop`；post-merge exact-SHA `engineering-test` run `30694755868` 成功。基于该 merge SHA
生成并获批的新 packet 启动真实 preflight 后，在构造 RQData adapter 或产生
PostgreSQL/Parquet/receipt 写入前以 `approval_facts_changed` fail-closed。现场 packet/current-state
逐字节重算无漂移；根因是 progress Gate 将多个同 trading day session 收窄为最后一段，令
actual-dominant 1m 冻结 execution run 与重算 run 不一致。最小修复改为对连续主导日 run 的全部
session 取最早 start 与最晚 end，并新增夜盘/上午/下午三段 session 回归；生产 current-state
只读重算已通过。该修复改变 source HEAD，旧 packet/hash/approval 不得复用。截至该修复尚未
合入时，真实 85/85 preflight、完整 apply 和 13/13 historical Shadow 均未完成；后续实况如下。

多 session 修复已由 PR #90 合入 `develop@48d05fe680d3b2a2f78187b97975d5ccfca5e6a4`，
post-merge `engineering-test` run `30697555087` 成功。同一 exact SHA 的真实 RQData preflight
为 85/85 passed，随后 resume apply 以 exit code 0 完成：终态 receipt schema v2 为
`85 datasets / 85 passed / 0 blocked / mapping 3245`，DB 为
`85 datasets / 85 partitions / 0 gaps`，canonical 为 `255 files`、staging 为 0 files。
生产 Shadow 随后在读取第一个 continuous 1m query 前以
`shadow_legacy_continuous_ambiguous` fail-closed。根因是 migration plan 的 `eligible_assets`
只表示 direct-reuse 集合（生产精确为 1 个 JM2609 1d 资产），却被生产 Shadow 当成 13 项矩阵
的 legacy baseline；这与任务已记录的 `eligible_reuse=1` 直接矛盾，exception 不能绕过空源。
当前 TDD 修复在同一 approval-bound plan 内分离 `shadow_assets`：生产只读重算为 110 个
passed/primary/rqdata exact IDs，覆盖 JM.MAIN 的 1m/1d/1w 与全部 41 个 actual 合约的 1m/1d，
并继续绑定 DB evidence、resolved path、物理 SHA256 及 source interval。该修改改变 source HEAD
与 plan digest，并同步改变 packet-bound receipt path / approval basis，因此旧 packet/hash/approval
及旧 passed receipt 均不得复用。当时的后续 Gate 是新 merge SHA、CI、packet/hash 与用户精确
批准后重跑 85/85 preflight、reconcile/resume apply 和 13 项 historical Shadow；该顺序现已由
4.0 取消，不再阻塞 Task 04 或 Task 05。

上述 baseline 修复已由 PR #91 合入 `develop@7b2568ff01752e72ffca9ebfccf4499064915aa2`，
post-merge `engineering-test` run `30699785142` 成功。同一 exact SHA 的新 packet 获批后，
85/85 preflight 全部为 `reconciled`，没有缺失 execution run；reconcile apply 以 exit code 0
生成 packet-bound schema-v2 terminal receipt（85/85 passed、0 blocked、mapping 3245），且 DB/
physical 仍为 `85 datasets / 85 partitions / 0 gaps / 255 canonical files / staging 0`。
生产 Shadow 已越过 110-asset freeze，但在第一个 continuous 1m 月块进入 exact-ID reader 时以
`market_data_file_identity_mismatch` fail-closed。精确栈与 DB 证据表明：plan/canonical identity
规范化为 `JM.MAIN`，四个 frozen legacy 1m 资产的原始 DB `contract_code` 均为 `jm.MAIN`；
`MarketDataReader.load_bars_from_market_files()` 正确要求原始 DB identity 逐字匹配，生产 Shadow
错误地把 canonical identity 同时当成 reader identity。当前最小 TDD 修复从 inventory 起
分别保存 canonical identity 与 exact DB reader identity，并把后者纳入 `shadow_assets`、approval
plan digest 与 Shadow lineage；选择与最终比较仍使用 `JM.MAIN`，物理读取使用并前后复验
`jm.MAIN`。生产只读首月诊断成功读取 4 个 exact assets / 4050 rows。该修改改变
source HEAD，旧 packet/hash/approval 与 passed receipt 再次失效。当时要求新 merge SHA/CI/packet/
批准后重建 preflight/apply receipt 并执行 13 项 Shadow；该要求现为 frozen historical，不再是
Task 04 或 Task 05 Gate。

### 4.3 历史 session / trading_day 与 canonical replacement 历史快照（已冻结，2026-08-02）

PR #92 将 exact legacy reader identity 合入 `develop@59a403cb`，PR #93 将初始残周 Shadow
anchor 修复合入 `develop@6dfbb7a5`；PR #94 的 session repair 候选 head `fa19e269` 后续以
merge commit `1e3a0edd` 合入 `develop`。基于 PR #93 exact SHA 的新 packet 已完成 85/85 reconciled
preflight 与 terminal reconcile apply；生产 Shadow 后续失败经只读复盘确认不是新的 baseline
或 exception 问题，而是以下三项共享合同漂移：

1. `TradingSessionClock` 只持有当前 `21:00-23:00` 模板，2023 前 calendar flag 又全为 false，
   因而 canonical/preflight expected endpoints 漏掉 2014-12 起的历史夜盘及其历次变更；
2. legacy 1m 的自然日启发式 trading_day 会把周五/节前夜盘标为周六或自然次日，Shadow 在
   聚合前据此做 rank=1 mapping 过滤会丢失完整夜盘并触发 `missing_source_minutes`；
3. legacy datetime 为上海本地 naive，旧 reader 将 UTC 月块直接去除 tzinfo 后下推，可能遗漏
   UTC 月末但上海已进入次月凌晨的合法行。

当时批准的 L3 修复方案及代码合同如下；实现可以保留，但 4.0 已取消其作为 Task 04 准入前置：

- 共享 JM session policy `jm-dce-effective-session-v1` 明确冻结夜盘启用、三段收盘制度、
  2020 暂停区间与周末/节假日规则；2023 起继续使用 DB calendar flags；
- policy document/digest、Catalog manifest identity 和 `replacement_required` 全部进入
  current-state/state digest/approval Gate；progress 必须独立重算，不能信任 receipt；
- legacy 1m trading_day 仅作审计字段，比较时按共享 session membership 重算；本地-naive
  粗筛边界显式使用 `Asia/Shanghai`；
- existing JM 1m partition 不改、不删、不覆盖；新 RQData data version 增加
  `jm-session-v1`，manifest 为 `canonical-manifest-v2-jm-session`，并以
  `overlap_reason=version_replacement` 追加 packet-bound execution-run 版本；suffix 仅由
  replacement publisher 增加，通用 RQData adapter 不改变；
- Catalog 保留全历史 partitions；reader 屏蔽被 replacement 区间并集完整覆盖的旧分区，部分
  相交未完整覆盖时 fail-closed；resume 只补尚无 v2+replacement coverage 的 execution run；
  journal/manifest/DB commit recovery 同时绑定 overlap reason，旧 journal/manifest 保持可读；
- wrong-manifest/partial v2 coverage 仍为 replacement required；Task 04 fresh JM 1m 可用 session-v2
  普通 manifest，D1/W1、legacy files、frozen reports、Task 05、Runtime、通知和交易均不改变。

该候选分支当时未执行 RQData、PostgreSQL 或 canonical 真实写入。当时拟议在新 exact merge SHA
下重新生成 packet/hash，再执行 85/85 preflight、append-only replacement apply、terminal receipt
和 13 项 Shadow；该拟议流程现已取消，不得执行。旧 packet/hash/approval/receipt 继续作为历史
evidence 保留，不得冒充当前授权。

候选分支最终本地验证：相关 Data Core/Market reader/session clock/CLI `509 passed`；后端全量
`2348 passed / 36 skipped / 0 failed`；engineering `192 passed`；Ruff、docs、diff check 与
high-confidence secrets scan 通过。独立 reviewer 最终结论为 `READY`，无
Critical/Important/Minor 阻塞项。以上只记录当时的代码候选证据，不替代本次 closeout 的
Canonical 自身 Gate，也不要求新 packet、apply 或 legacy Shadow receipt。

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
