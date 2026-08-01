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
REAL_DATA_APPLY_PARTIAL_BLOCKED
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
| 04（原 04～08） | 历史数据闭环、JM 基线迁移、普通消费者切换 | `BLOCKED_AT_JM_REAL_DATA_GATE`；PR #86 已合入 `develop@e29c2940` 且 post-merge CI 成功；第三个真实 apply 已写入 rank=1 mapping 与 continuous 1m/1d，随后在 continuous 1w 上市残周质量 Gate fail-closed；TDD 修复与本地/真实只读验证通过，尚待新 exact HEAD/CI/packet/批准，详见 4.1 |
| 05（原 09～10） | Backtest、Signal、Review 可信消费者切换 | pending；任务 04 未验收前禁止启动 |
| 06（原 11～14） | live、SignalDecision、EOD、ResearchSample/retention | pending / migration + Runtime + deletion Gate |
| 07（原 15～18） | 其他已有品种迁移、legacy 与历史工件受控清理 | pending / batched data + exact deletion Gate |
| 08（原 19） | release candidate、JM 单交易日 Shadow 与 Runtime 验收 | pending / release + Runtime Gate |

任务必须串行。任务 00～03 均已通过各自测试、独立 Review 与适用 CI/等价 Linux Gate，并
集成 `develop`；任务 04 已推进到 `develop@e29c2940` 且 post-merge exact-head CI 成功，生产
schema 已升级到 `0027`。首个真实 apply 在任何 RQData/Parquet/metadata 副作用前
fail-closed；D1 Gate 修复集成后，第二个真实 apply 初始化空的 canonical/staging 管理目录，
随后在 mapping/Parquet/metadata/receipt 持久化前因 UTC 夜盘的下一交易日标签边界错误
fail-closed。夜盘修复集成后，第三个真实 apply 完成 mapping 与 continuous 1m/1d 的原子发布，
再在 continuous 1w 上市残周覆盖检查处 fail-closed。当前 1w 查询锚点修复已通过本地全量、
真实 RQData 只读验证与独立 Review，但新的 exact HEAD、CI、packet 与批准尚未完成。
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

未完成且不得越过：

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

因此新任务 04 仍不能标记完成，也不能进入任务 05。下一动作是提交并集成 initial partial-week
query-anchor fix，取得同一 exact merge SHA 的 CI，重新生成并核验 packet，再由用户批准从已验证
partial receipt 安全续跑真实 JM apply 与 Shadow。

### 4.2 Resume Gate 综合复盘与当前验收增量（2026-08-01）

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
   分块；周线仅扩日历上下文。13 项 query matrix 必须精确；结束前重建 state 并逐 partition
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
及旧 passed receipt 均不得复用。尚待新 merge SHA、CI、packet/hash 与用户精确批准后，按同一
新 packet 重跑 85/85 preflight、reconcile/resume apply 生成新 passed receipt，再执行 13/13
historical Shadow；Task 04 仍不得进入 Task 05。

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
source HEAD，旧 packet/hash/approval 与 passed receipt 再次失效；仍须新 merge SHA/CI/packet/批准后
按同 packet 重建 preflight/apply receipt 并执行 13/13 Shadow，Task 04 不得进入 Task 05。

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
