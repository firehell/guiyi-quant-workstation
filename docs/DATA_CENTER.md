# DATA_CENTER.md

更新时间：2026-08-05

## 0. Active target 与迁移状态

当前 active universe 已在代码合同中收口为 69 个，唯一入口为
`data/universe/active_products.txt`。以下 21 个品种已禁止新增下载、Canonical 写入和统一行情读取：
粳稻、普麦、早籼稻、强麦、动力煤、线材、胶合板、纤维板、聚丙烯月均价、聚乙烯月均价、
聚氯乙烯月均价、国际铜、棉纱、原木、铸造铝合金、胶版印刷纸、粳米，以及 2/5/10/30 年期
国债期货。历史文件和数据库 DML 尚未执行，必须等待
`docs/tasks/GY-DATA-PRODUCT-RETIREMENT-21.md` 的 exact deletion Gate。

数据核心 V2 的 active target 已冻结。Task 04 closeout commit 经 exact-head CI、独立 Review 和
GitHub merge commit 合入 `develop` 后，historical canonical 与普通 Web/API/指标消费者迁移完成；
Backtest/Signal/Review 可信消费者切换留给 Task 05：

```text
RQData
-> temporary staging
-> validation
-> one historical canonical Parquet root
   (provider-direct 1m/1d/1w + persisted preaggregated 5m/15m/30m/60m)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService
-> consumers
```

- 数据集由不可歧义的 `DatasetKey` 定位；`continuous` 与 `actual_dominant` 显式且不可互换。
- 正式历史合同仅支持 `1m/5m/15m/30m/60m/1d/1w`；其他值以
  `UNSUPPORTED_FREQUENCY` 拒绝，不接受别名或大小写转换。
- source role 固定为 `1m/1d/1w=provider_direct` 与
  `5m/15m/30m/60m=preaggregated_from_1m`；七者都是持久化 Canonical dataset。
- 请求只读同频 Catalog/partition；缺 dataset、partition、coverage 或显式 gap 都返回
  DataGap，不从 1m 或其他周期动态聚合。live confirmed-bar 聚合不属于该禁止范围。
- actual-dominant 覆盖按 rank=1 mapping 有效分段计算；`1w` 使用该周最后交易日
  的 rank=1 具体合约。
- PostgreSQL 只保存轻量 catalog、manifest/checksum、coverage、quality、gap、mapping 与任务状态。
- 与 gap 相交的读取必须失败关闭；同一唯一键数据相同可幂等合并，OHLCV/identity 冲突必须可见。
- 旧 Profile/ActiveBinding/复杂 lineage 仅为 legacy compatibility，不再扩展为 active selector。
- V2 migration asset 只有 trusted historical bars 及最小 Catalog/Manifest/Gap/MainContractMap
  metadata。旧 indicator/cache、Backtest、Signal/Review、live/EOD/Sample、permanent derived
  period、重复 raw/standard/canonical bar layer 和 Profile/Binding/legacy lineage 均为 rebuild-only
  或 compatibility-only，不迁移为新的 active input。
- report 14/15 是 Git-traceable historical snapshots，不是 active Gate 或 regression；保留其
  历史结论和证据，不做重写或删除。
- Task 04 完成不表示 Task 05、release、Runtime、长稳、通知或交易 Ready，也不表示所有历史资产
  residual 为零。

### Task 07 JM 目标 Canonical 验收与精确缺口计划（2026-08-04）

Task 07 Stage C 不再扫描或迁移全量 legacy 资产。目标集合只由
`config/data_core_v2_targets.yaml`、Catalog 与 MainContractMap 生成：

- `continuous / JM.MAIN`；
- `actual_dominant / rank=1 volume_open_interest`；
- `1m/5m/15m/30m/60m/1d/1w`；
- `2013-03-22` 至当前完整 MainContractMap 最后交易日的精确窗口。

`guiyi data task07 assess` 首先开启 `REPEATABLE READ READ ONLY` 快照并要求 revision
精确为 `20260803_0032`，然后只通过 `HistoricalCatalog` / `CanonicalHistoricalReader` /
`MarketDataService` 验证目标 DatasetKey、schema、Manifest、checksum、row count、分区可读性、
窗口/session/trading-day 覆盖、主键唯一、时间单调和七周期同频读取。
actual-dominant `1w` 按 ISO 周最后交易日的 MainContractMap 归属。

Direct `1m/1d/1w` 失败只输出 exact-window `REDOWNLOAD_DIRECT`；aggregate
`5m/15m/30m/60m` 失败只在同身份与同窗口 Canonical 1m 验证可信时输出
`REBUILD_AGGREGATE`，否则 `REGISTER_DATA_GAP`。这些都只是精确缺口计划，
`writes_authorized=false / production_writes=false`，不实施修复。目标全部通过时
固定为 `Stage_C=NO_DATA_WRITE_REQUIRED / repair_count=0`，不为了 receipt/manifest 重写有效数据。

旧 legacy-wide inventory、packet、repair/batch 数字、Runtime reference 和 retirement 路线
都是 superseded historical evidence；旧 evidence 保持原事实，但不再提供 active apply
入口。Task 07 不以 Profile/Binding retirement、Runtime legacy reference=0、legacy 文件数
或旧派生数据删除为完成条件。Runtime promotion 属于 Task 08；旧派生数据清理
是后续独立可选任务。

### 0.0 Task 04 closeout 正式准入

RQData 是唯一上游行情数据源；canonical Parquet 是受治理的正式历史存储，不是第二上游来源。
Canonical 准入依赖自身 schema、coverage、Manifest digest、物理 checksum、Catalog、DataGap、
MainContractMap 与代表性 `MarketDataService` 读取。legacy 与 Canonical 全历史逐条一致不是正式
准入条件；legacy historical Shadow 仅保留为可选诊断或 frozen compatibility，不是 Task 04 或
Task 05 前置 Gate。

2026-08-02 只读现场复验：PostgreSQL revision `20260730_0027`；Catalog
`85 datasets / 85 partitions / 0 gaps`；物理目录为 `85 Parquet + 85 Manifest + 85 prepared =
255 canonical files`，staging 0；85/85 partitions 的 checksum、Manifest digest、Catalog identity、
coverage 与 row count 一致。MainContractMap 在 `2013-03-22..2026-07-30` 的 3395 条保留版本
物理 rows 解析为 3245/3245 个唯一 DCE 交易日，缺失 0、歧义 0。

正常窗口 `2026-07-06T00:00:00Z..2026-07-10T15:00:00Z` 已通过 continuous `JM.MAIN`
的 direct `1m/1d/1w`、derived `5m/15m/30m/60m`，以及 actual_dominant `JM2609` 的 direct
`1m/1d`、derived `5m/15m/30m/60m`；无显式合约的 actual_dominant resolver 也解析为 JM2609。
读取不调用 RQData、不写 PostgreSQL/Parquet。DataGap 相交请求继续 fail-closed，不得填充、
缩短或忽略缺口；in-memory Catalog gap fixture 已返回 `DataGapError(reason=catalog_gap)`，coverage
缺失与 derived source minute 缺失回归也通过。

旧行情、旧 Profile/Binding、旧 Parquet、PR #90～#94 实现、packet、receipt、report 与 evidence
均保留，不删除、不改写。PR #92 identity 修复以及 PR #93/#94 session compatibility 可以继续作为
可选诊断或 frozen legacy compatibility；本 closeout 不生成新 packet，不执行 preflight、apply、
replacement 或生产 legacy Shadow。

### 0.0.1 Task 04 read-only plan 与 Gate 历史快照（已冻结）

本节至 0.0.3 保留 closeout 决策前的实现、失败与当时 Gate，不再提供当前执行授权；其中所有
新 packet、preflight/apply、replacement 和 13 项 legacy Shadow 的将来式要求均已取消。

2026-07-31 候选分支完成了 historical sync/reader、JM inventory/plan/Shadow query set、
MarketDataService 与默认关闭的 JM Web/API/公共指标切换。当时的 `07:00Z` read-only plan 对
915 个 JM legacy 资产分类为 1 个可复用 direct RQData 1d 资产和 914 个排除项；exact window
为 `(2013-03-21T07:00:00Z, 2026-07-29T15:00:00Z]`，plan digest 为
`fbb18529684914b268cbc020d589856aaf44097389b2a670c65c6b1ab6ca1358`。plan 命令本身没有调用
RQData，也没有写 PostgreSQL 或 Parquet。

拟议新根与旧 `data/parquet/canonical` 分离：

```text
canonical=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/data-core-v2/canonical
staging=/Volumes/扩展盘/guiyi-quant-workstation/data/parquet/data-core-v2/staging
```

生产 PostgreSQL 已在 Task 04 精确 Gate 下升级并现场核验为 `20260730_0027`。Task 04 临时
隔离 PostgreSQL 已完成完整 migration 往返（`35 passed`）并删除。CLI 在数据库打开前先
自校验 packet/hash，打开只读 session 后重算 inventory、plan、git head、roots 与 PostgreSQL
target，并要求 clean exact head 和 revision `20260730_0027`，之后才构造 RQData/CanonicalStore。
packet/current facts 绑定 Catalog/partition/gap/mapping、calendar/session 和 exact
per-DatasetKey write plan 摘要；apply 以原子持久 partial receipt 支持按 dataset 对账恢复。

绑定 `develop@e29c2940` 的第三次真实 apply 已完成任务窗口 rank=1 mapping `3245 rows`，并发布
continuous `JM.MAIN` 1m `830820 rows` 与 1d `3244 rows`；当前 Catalog 为 `2 datasets / 2
partitions / 0 gaps`。continuous direct 1w 随后在写入前以
`CANONICAL_QUALITY_COVERAGE_MISMATCH` fail-closed：`2013-03-22` 是 RQData 查询锚点，但 provider
不输出该上市残周 bar。当前 TDD 修复保留 anchor session、仅从 expected endpoints 排除该
packet-bound 残周，真实只读验证为 `684 expected = 684 actual`；通用 quality Gate 未放宽。
该修复在当时尚待新 merge SHA/CI/packet/批准，完整 apply 与 historical Shadow 尚未完成，
当时状态为 `BLOCKED_AT_JM_REAL_DATA_GATE`。此状态已被 0.0 closeout 正式准入取代。

### 0.0.2 Task 04 resume/preflight/terminal receipt hardening 历史快照（已冻结）

resume 修复已经进入 `develop@e3e03a9d`。再次真实 apply 前的仓库审计把执行合同继续收紧：

- partial receipt 路径由 exact HEAD 与 approval basis digest 共同决定；scope、plan、initial
  state、PostgreSQL target、roots 或 rollback 任一变化都会生成不同路径；caller-selected 路径
  在 packet 构造/校验阶段拒绝；
- receipt schema v2 同时绑定 approval basis digest 与 packet hash，并校验自身 digest；状态仅为
  `in_progress -> blocked -> in_progress` 或 `in_progress -> passed`，passed 后不可修改；只有 mapping
  精确全集、85 个 dataset 精确全集、零 gap、非空 partition evidence 与最终 current-state digest
  全部成立才能终态 passed；
- current-state/packet write plan 新增 `execution_runs`。continuous 使用 exact scope；
  actual-dominant 按 rank=1 连续主导日合并，M1 使用对应 session 边界，D1 使用交易日午夜微窗口，
  apply/preflight 均消费经过 progress Gate 重算验证的 current-state runs；
- `guiyi data migrate preflight` 是 RQData read-only Gate：不构造 CanonicalStore/publisher，不写 DB、
  Parquet、gap 或 apply receipt；它对 `3 continuous + 41*2 actual = 85` 个 direct DatasetKey 完成
  provider batch quality 与 Arrow/Parquet physical representability 验证，并输出 hash-bound receipt；
  `migrate apply` 必须消费同 packet、同 approval basis、同 current-state digest 的精确 85/85 receipt；
- historical Shadow 不再接受 caller-supplied legacy/canonical 整包 JSON；启动时重算 packet-bound
  legacy inventory/plan；migration `eligible_assets` 只用于 direct reuse，独立 `shadow_assets` 冻结
  passed/primary/rqdata baseline exact IDs、DB evidence、resolved path 与物理 SHA256，月块只读
  该集合；canonical 从 Catalog/manifest 读取。两侧按 `(start, end]` 和 `query x calendar month`
  分块比较，周线只扩日历上下文而不扩查询窗口；derived expected keys 独立由 session 生成。
  13 项矩阵必须精确；apply passed receipt/current-state、source lineage、chunk rows/expected-key digest
  和 exception digest 均进入 Shadow receipt。结束前重新构造 current state 并逐 partition 重验
  canonical manifest/checksum/row count。任一侧为空、共同遗漏 expected bar、缺块、实际差异、
  范围外 query、同 key 冲突或未消费 declared exception 均 fail-closed。

生产只读复核为 `revision=20260730_0027`、`contracts=41`、`trading_days=3245`、
`mapping_rows=3245`、`dataset_plans=85`、`execution_runs=85`、`empty_execution_runs=0`。
该复核没有调用 RQData，也没有写 PostgreSQL、Parquet 或 receipt；这是 PR #89 hardening
合入后、PR #90 real Gate 前的历史快照，后续实况如下。

多 session Gate 修复合入 `develop@48d05fe680d3b2a2f78187b97975d5ccfca5e6a4` 后，真实
85/85 preflight 与完整 resume apply 已通过：Catalog 为 85 datasets / 85 partitions / 0 gaps，
canonical 为 255 files 且 staging 为空。生产 Shadow 随后在比较前以
`shadow_legacy_continuous_ambiguous` fail-closed；根因是 1 个 direct-reuse `eligible_asset` 被误当成
13 项矩阵的 legacy baseline。当前修复将两类集合分开，生产只读冻结 110 个 approval-plan-bound
baseline exact IDs，完整覆盖 JM.MAIN 1m/1d/1w 与 41 个 actual 合约 1m/1d。该修改改变 plan digest
和 source HEAD，也改变 packet-bound receipt path / approval basis；旧批准与旧 passed receipt
均不可复用。当时拟议由新 exact SHA 依次完成 85/85 preflight、reconcile/resume apply 和 13 项
Shadow；该顺序现已取消，不再是 Task 04 或 Task 05 Gate。

Shadow baseline 修复合入 `develop@7b2568ff01752e72ffca9ebfccf4499064915aa2` 后，同一
exact SHA 的新 packet 已完成 85/85 reconciled preflight 与 packet-bound terminal apply receipt；
Catalog/physical 保持 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0。生产 Shadow
随后在第一个 continuous 1m 月块进入 exact-ID reader 时以
`market_data_file_identity_mismatch` fail-closed。根因不是 bar 差异，而是 canonical plan identity
`JM.MAIN` 被同时用于读取 legacy DB 原始 identity `jm.MAIN`。当前修复从 inventory 起分别冻结
规范化 canonical identity 与 exact DB reader identity，并将两者纳入 approval plan digest 与
Shadow lineage：前者用于 dataset 选择/Shadow 比较，后者仅用于 exact-ID 物理读取且在读取前后
逐字复验；生产只读首月诊断已成功读取 4 个 frozen assets / 4050 rows。
该 source change 使旧 packet/approval/passed receipt 失效。当时拟议的新 exact SHA
preflight -> reconcile apply receipt -> 13 项 Shadow 链路现为 frozen historical，不再执行。

上述 hardening 后续由 PR #89 合入 `develop@ca7125a2`，post-merge CI 成功。首次绑定该 merge
SHA 的真实 preflight 在 provider 初始化前以 `approval_facts_changed` fail-closed：progress Gate
用单个 session 覆盖同一 trading day 的多段 DCE session，导致 actual-dominant 1m execution run
重算缺失夜盘和上午段。当前 TDD 修复仅将同一连续主导日 run 的全部 session 合并为最早 start /
最晚 end；不放宽 mapping、coverage、partition、manifest 或 checksum Gate。修复合入并取得新的
exact-SHA packet 批准前，当时仍禁止真实 preflight/apply/Shadow；closeout 决策进一步取消了
该后续执行链。

### 0.0.3 JM 历史 session 与 append-only canonical replacement 历史快照（已冻结）

PR #92/#93 已依次将 exact legacy reader identity 与初始残周 Shadow anchor 修复合入
`develop@6dfbb7a5`。随后生产 Shadow 的只读失败不允许通过 exception 或裁剪 legacy 制造通过；
根因收敛为同一历史语义漂移：

- 2014-12 起 JM 夜盘存在 effective-dated 变化：`21:00-02:30`、`21:00-23:30`、
  `21:00-23:00`，并在 2020-02 至 2020-05 暂停；2023 前生产 calendar flags 不能表达这些历史事实；
- legacy 1m 的 trading_day 是自然日启发式字段，周五或节前夜盘不能作为 rank=1 mapping 的
  权威过滤键，必须按共享 session membership 重算，零匹配/多匹配 fail-closed；
- frozen legacy Parquet datetime 是上海本地 naive 值，UTC 查询窗口下推 DuckDB 前必须先转换为
  `Asia/Shanghai` 的 naive 边界，随后仍按精确 UTC 语义过滤。

修复合同冻结为 `jm-dce-effective-session-v1`，其完整 policy document 与 digest 进入
current state、approval packet 和 resume progress 校验。受旧 session policy 影响的 existing
JM 1m 数据集不能因 coverage 非空而被视为完成；`replacement_required` 必须根据
legacy-affected approved repair windows 是否已被 `canonical-manifest-v2-jm-session` +
`version_replacement` 完整覆盖独立重算。后续扩展出来的非 legacy tail 不得误走 replacement。

canonical 修复只允许 append-only：只有 replacement publisher 为 RQData 1m data version 增加
`jm-session-v1` 后缀，并写入 `overlap_reason=version_replacement`；Task 04 fresh JM 1m 使用
session-v2 manifest 但不增加 replacement suffix，D1/W1 与通用 RQData adapter 保持原口径。
旧 Parquet/manifest/metadata 全部保留。Catalog 的审计接口返回全部分区；effective reader
屏蔽被 replacement 区间并集完整覆盖的旧分区，部分相交但未完整覆盖时 fail-closed；已发布的
v2 replacement execution run 在 resume 时不得重写。发布仍使用既有 journal + DB commit
recovery；wrong-manifest replacement、部分 replacement 或 policy drift 不得从 receipt 恢复为完成。

这是当时的 L3 数据语义与 canonical 写入修复。PR #94 候选 head `fa19e269` 后续以 merge commit
`1e3a0edd` 合入 `develop`，但没有执行真实 1m replacement。其代码保留为 frozen compatibility；
当时拟议的 85/85 preflight、reconcile/replacement apply、terminal receipt 与 13 项 Shadow 已由
0.0 closeout 决策取消。旧 packet、批准与 terminal receipt 仅作历史 evidence，不授权删除、
Task 05、Runtime、通知或交易。

active 合同与任务顺序见 `docs/tasks/GY-DATA-CORE-V2.md`。以下既有 Gate 与实现事实继续有效，
但分类为 `legacy compatibility` 或 `frozen historical`；不得用它们覆盖 active target。

### 0.1 Legacy compatibility 与 frozen historical 结论

当前数据层最终状态已进入全历史重审口径：

```text
CONSUMER_DATA_CONTRACT_READY
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_INVENTORY_READY
FULL_HISTORY_AUDIT_V2_READY
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT
MARKET_RESEARCH_MODE_READY
INDICATOR_BINDING_CONSISTENT
JM_HISTORICAL_CATCHUP_READY
JM_REFERENCE_METADATA_FRESH
JM_LIVE_TARGET_FRESHNESS_READY
JM_LIVE_CONTEXT_READY
```

2026-07-18 的 `CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已从合入后的主干独立复跑。direct PostgreSQL `READ ONLY` snapshot、真实 Parquet、49 条消费者矩阵和 13 个 Hard Gate 全部通过，状态为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。通过证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前 `consumer_golden_query_final_gate_20260718/` 保留为修复前失败快照。

`DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT` 与阶段 C 消费者契约 Gate 均已通过。全局 `DATA_LAYER_REAUDIT_REQUIRED` 仍用于 Audit V2 的更广泛 residual，不能用本次 Ready 隐去历史资产 warning/failed/partial 边界。

因此 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是既有 formal consumer 的准入结论，而 `DATA_LAYER_REAUDIT_REQUIRED` 是非阻塞的全历史维护 backlog；二者可并列存在。前者不表示 historical residual 为零，也不授权 OOS 结论、T3/T4 live/archive、SignalEvent、企业微信或自动交易。

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不能覆盖当前数据层最终验收。以下 Phase 3 DB 口径仅作为旧审计模型历史快照保留：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |

本文件后续章节保留数据链路、历史处理链和阶段证据。凡历史章节出现 `metadata_gap=0`、`covered_passed=17203`、`metadata_gap=1853`、`pre_2020_weekly_missing=34`、actual contract 旧固定 gap 或 `DATA-PART-TARGET-CLOSURE`，均只表示对应审计模型下的历史快照，不代表当前确定下载缺口、当前批量修复清单或数据层最终 ready。

基于旧 `1853 / 34 / 45` 数字的批量修复继续暂停。B2-01 至 B2-09、阶段 C C2-01 至 C2-05、阶段 4 指标契约和阶段 5 策略可信验证均已完成。Stage 6 S6-03 至 S6-06 的既有数据 Gate 保持不变。S6-07 D1 正常自动归档与 D2 停机漏跑自动补偿均已通过；中间发生的 schema/checkpoint 漂移和 1w 聚合失败均先 fail-closed，再通过 hash-bound recovery deployment、独立 service approval 与同日 retry 恢复。最终 `JM_EOD_INCREMENTAL_AUTOMATION_READY` receipt 已发布，且 SignalEvent、通知、scan task、strategy signal 四类 counter 均零增量。该结论不自动触发通知、订单或自动交易。D4-00 HTDY 审计证据已落盘且不重开公式审计，但不改变本文件的数据层 Gate 语义。Audit V2 residual 维护为非阻塞 P1，不自动触发行情下载、通知或订单。

### S6-07 EOD incremental automation

```text
TradingCalendar / TradingSession
-> safe delay 120m
-> earliest missing trading day first (max 5 per scan)
-> provider-final stability x2
-> S6-06 archive-contract-v2 create-only materialization
-> quality / manifest / metadata / Profile consumer verification
-> JM_EOD_ARCHIVE_DAY_PASSED receipt
-> independent PostgreSQL watermark
```

盘后调度不进入 live 20 秒 polling cycle。它使用独立开关、Redis singleton lease/heartbeat、checkpoint、JSON log、runtime health 和 launchd label。服务级批准绑定 `JM_ARCHIVE_PASSED` receipt、commit/依赖锁、脱敏 DB identity、Runtime/output root、挂载设备和固定策略；任一事实漂移停止新归档。前一交易日失败时保持当前 watermark，不允许跳日；provider final pending 只等待，provider/DB 暂时故障按 `5/15/30/60/120/240` 分钟重试，六档用尽后下一次失败进入 blocked 并等待显式同日恢复。

当前状态为 `JM_EOD_INCREMENTAL_AUTOMATION_READY`。D1=`2026-07-22` 证明正常自动归档；D2=`2026-07-24` 证明 enabled 保持为 true、scheduler 在 eligible 窗口停机后，由同一独立 label 重新加载并自动发现漏跑日。D2 create-only batch=`s607_20260724_19e6ca31`，7 个资产与 7 行 manifest 均通过 checksum/quality/metadata，8 条 consumer binding 已验证，required 七项共同 `active_binding_end=2026-07-24`，watermark 前进且 lag=0。最终 receipt 位于 `data/reports/jm_eod_incremental_automation_s6_07/real_acceptance_20260724_19e6ca31/completion_receipt.json`。该 Gate 不代表 `JM_RUNTIME_READY`、`LONG_RUNNING_READY`、SignalEvent、通知或自动交易 Ready。

### S6-04 historical/live context

```text
current actual-contract primary/passed historical tail
+ latest live trading day confirmed/passed bars
-> evaluator preview
```

key 固定为 `(actual_contract, period, bar_datetime)`。同 key OHLCV 标准化后一致时保留 historical；不一致 fail-closed，live 不覆盖 historical。historical 文件 checksum、实际使用窗口 hash 和前一 DCE 交易日覆盖分别验证；最终 merged key 必须等于独立保存的 live trigger key。主力切换只解析新 actual contract，不跨合约 warm-up 或回退旧主力。

## 1. 定位

active target 把唯一 provider RQData 变成本地可信、可追溯、可复算的数据资产：

```text
RQData -> staging -> validation -> one canonical parquet root
-> Catalog/Manifest/Gap/MainContractMap -> MarketDataService
-> Market / Backtest / Signal / Review
```

PostgreSQL 只保存元数据、任务、质量和业务事实，不保存全量历史分钟线。

## 2. Legacy compatibility active 入口（迁移期）

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究使用 `quality_status=passed`。validation、legacy_reference、candidate、旧 TqSdk / 天勤和交易练习者数据不得进入默认读取。

迁移期既有主周期规则：

```text
passed 1m standard parquet
-> local aggregation
-> 5m / 15m / 30m / 60m / 1d quality passed
-> active metadata registration
```

新 active target 同样不允许从 RQData 直接拉取 5m/15m/30m/60m 形成 canonical；
目标 1d/1w 则保留 provider 直接序列，不再把旧 derived 1d 与 provider direct 1d 混为一谈。

## 2.1 quality_warning 消费边界

OHLC envelope 校验对二进制浮点舍入使用确定性容差：`max(1e-12, 1e-12 * max(abs(O/H/L/C), 1))`。该规则只消除远小于最小变动价位的机器精度噪声；超过容差的 `high/low` 越界仍为 hard failure。历史 quality 证据不因规则修正被原地升级，需通过新 data version 重新验证。

Stage 5-B reference metadata gap 已收口；target coverage 剩余 **105 条 `quality_warning`**（15 个唯一文件，abnormal price warning）。这些资产**不得为覆盖率升级为 `passed`**。

| 模块 | 默认行为 | warning 允许条件 |
|---|---|---|
| Market | 允许展示（active 入口 `!= failed`） | 始终允许，但必须返回质量字段并在 UI 提示 |
| Backtest | formal 严格 `passed-only` | 不允许；仅隔离的 legacy / experiment research-only 路径可自行承担风险 |
| Signal | 默认阻断 | Stage 9 前 `allow_warning_quality=false` |
| Review | 可展示历史 note | extra 记录 `data_quality_status`；warning 不可作信号证据 |

读取分层：

```text
active 入口（Market 默认）
  provider in (rqdata, local_parquet)
  data_role = primary
  quality_status != failed

strict 入口（Backtest / Signal / Market Research）
  上述条件 + quality_status = passed
```

该质量消费边界已纳入本节；历史实施过程由 Git 追溯。

## 2.1.1 Market / Indicator 双模式契约

`access_mode` 与 `data_mode` 是两个独立维度：

```text
access_mode = browser | research
data_mode = historical | live
```

- Browser 默认无 Profile 也可读取 active `rqdata/local_parquet + primary + quality != failed`；传入 Profile 时仍按 observation policy 允许 non-failed 展示。warning、unchecked、跨文件异值冲突、actual/continuous 和 historical/live 语义必须显式返回，且 `strict_research_ready=false`。
- Research 必须显式 `profile_id`，通过既有 `ProfileLineageResolver` 执行 active binding、passed-only、identity、物理文件和 coverage 校验；缺失或不满足时 fail-closed，binding/lineage 漂移返回 409。
- Research bars 解析 binding 一次并固定 `market_data_file_id + binding_snapshot + lineage_token`。EMA、MACD、visible window 与 warm-up 必须携带并核对同一 file ID/token，不得重新选择当前 binding。
- 1d/1w 以 `trading_day`、分钟线以 `datetime` 合并同值重复；同 key 不同 OHLCV 不静默去重，返回 `cross_file_conflicts` 和不含物理路径的资产证据。
- Web route 保存 `access_mode/profile_id/data_mode`；Live 强制 Browser observation 并清除严格研究 Profile，不与 historical bars 静默合并。

状态：`COMPLETED / MARKET_RESEARCH_MODE_READY / INDICATOR_BINDING_CONSISTENT`。本契约不改变全局 `DATA_LAYER_REAUDIT_REQUIRED`，也不代表 live runtime ready。

## 2.1.2 GY-CORE-02 JM active dataset compatibility Facade（可复用 legacy）

`ActiveDatasetResolver`、`MarketDataService`、`DatasetDescriptor` 和 `BarsResult` 现构成
JM-only compatibility Facade。它仍委托既有 Profile / workbench / reader historical 链，
只对一次读取的选择结果执行冻结和校验；不得据此新增 active 数据选择规则。

- Browser historical 的 `assets[]` 可含有序的多个合法 `rqdata/local_parquet + primary +
  quality != failed` 资产；research 只能使用一个已固定的 `passed` 资产。
- 同一 frozen file set 的 IDs/evidence 必须共同绑定 bars、quality、cross-file conflicts、
  coverage 与 lineage；historical lineage token 保持既有 token。
- actual dominant `rank=1` 以 exact-date strict/effective identity 比较；mapping 歧义必须
  fail-closed。pinned file 缺失或 fallback 无/多候选也不得静默选择。
- 仅 JM 的 `GET /api/v1/market/bars` historical 分支已使用 Facade；非 JM 继续既有
  workbench path。coverage、live API routes、indicator/MACD、`/api/klines`、backtest、
  signal、review 均未迁移。

live 仅提供 browser/read-only 的实际 JM 合约读取，要求显式且唯一 provider/source mode 和
`tail=false`；strict/research live 明确不支持。live snapshot token 仅标识本次 response window，
不是持久化 source-mode DB/schema identity。source-mode schema/upsert/aggregation P0 仍是独立
Lane 3；“须在 `GY-CORE-05` Shadow 前完成”是旧路线的 frozen historical 约束。新路线由
`GY-DATA-CORE-V2` 任务 11 收口，并在任务 19 前接受独立 Gate。本项不产生数据、Profile
binding、migration、Runtime、notification、trading 或 release 授权。

## 2.2 V1 全历史数据契约

状态：

```text
V1_DATA_CONTRACT_FROZEN
```

机器契约位于 `services/quant-api/app/services/rqdata_ingest/full_history_contract.py`。本节是长期语义事实源；纯模块提供 Audit V2 可复用的字段与算法。冻结契约不表示各品种 provider earliest evidence 已盘点完成，也不表示 Profile binding 或 formal consumer 已验收。

### 2.2.1 时间与 expected window

```text
audit_end = 2026-07-10
timezone = Asia/Shanghai
```

- `trading_day` 优先使用 provider 字段；夜盘 bar 归属下一交易日，周分组使用 trading day 的 ISO week。
- continuous 1m `expected_start = max(listed semantic start, authoritative provider first valid 1m bar)`。
- continuous direct 1d `expected_start = max(listed semantic start, provider first valid completed daily bar)`；可以早于 2010。
- continuous direct 1w 从 provider 第一条完成交易周 bar 开始，不要求等于上市日。
- 1m/1d `expected_end` 为不晚于 audit end 的最后完成交易日；1w 为不晚于 audit end 的最后完成交易周 bar。
- 缺少权威 provider earliest evidence 时，V2 将 canonical physical minimum 记录为 `start_boundary_supported`；缺少物理支持时为 `start_boundary_unverified`。两者均不等于 provider authoritative exact，并保持严格 data Gate fail-closed；不使用统一 2020/2023 起点。

provider earliest evidence 优先级：

1. 带查询参数、provider/version、时区和 checksum 的 provider earliest 快照。
2. 可证明完整的既有 provider raw response。
3. checksum 可验证的 canonical Parquet + manifest，只证明 observed physical coverage。
4. PostgreSQL metadata，只证明 registration/quality 状态。
5. listing metadata，只提供上市语义下界。

物理文件最早时间、manifest 文件名、DB start_time 或 listing date 均不得单独解释为 provider 理论最早时间。

### 2.2.2 first listed week

- 使用交易日历确定 provider weekly bar 所属周的最后实际交易日，不硬编码星期五。
- 上市当周存在 provider completed weekly bar 时，以该 bar 日期作为 expected start。
- 上市当周未形成完成周 bar 时，顺延到 provider 下一条 completed weekly bar。
- 节假日短周以该周最后实际交易日作为完成日。
- calendar 不完整、最后交易日未收盘、bar 不是周末实际交易日或 provider evidence 不权威时保持 unresolved/partial。

### 2.2.3 数据角色

| 角色 | V1 契约 |
|---|---|
| direct 1m | continuous 和 rank=1 actual 的基础分钟资产 |
| derived 5m/15m/30m/60m | 只允许从 passed 1m 本地聚合 |
| direct 1d | 长周期研究和 provider reference；通过 Profile/quality Gate 后可消费 |
| derived 1d | 日内研究的日线方向上下文，只允许从 passed 1m 聚合 |
| direct 1w | 长周期研究、Market 展示和 provider reference；actual-dominant 使用该周最后交易日的 rank=1 具体合约 |
| actual dominant | 七种正式历史周期均可查询，只覆盖 `MainContractMap.rank=1` 有效日期段；5m/15m/30m/60m 使用持久化同频 partition，不要求所有挂牌合约全量分钟数据 |
| live | 只存在 live DB 观察层；盘后重新获取 provider 最终历史数据并通过完整 Gate 后才能进入 historical canonical |

### 2.2.4 partial / confirmed

historical `confirmed` 同时要求：目标 bucket 已完成、数据来自盘后 provider 最终历史获取、quality 通过、registration 与 lineage 完整。`partial` 只能用于 live preview 或审计说明，不得进入 historical formal consumer。

周线完成需满足：交易日历完整、该周最后实际交易日已收盘、provider completed bar 存在。live 聚合的 confirmed bar 仍不自动成为 historical canonical。

### 2.2.5 五层状态与 legacy Profile eligibility（冻结历史）

以下状态必须独立记录，禁止用一层成功替代另一层：

```text
physical_coverage: covered / partial / missing / unverified
registration: registered / missing / not_required / unavailable
quality: passed / warning / failed / unchecked
reference_metadata: passed / warning / missing / not_applicable / unavailable
profile_eligibility: eligible / blocked / unresolved / not_applicable
```

Profile eligibility 是 legacy compatibility 的历史口径，不能作为 Backtest、Signal 或 Review 的
active selector。V2 formal consumer 必须只通过 `MarketDataService` 消费
`canonical_consumer_input_v1` 所固定的 DatasetKey、manifest digest、query window、mapping 与
quality/Gap 证据。

### 2.2.6 formal consumer 准入

| Consumer | 默认准入 | warning 边界 |
|---|---|---|
| Market | 五层完整、confirmed、quality passed/warning | 允许展示，必须返回并显示 warning |
| Backtest | confirmed、passed、`canonical_consumer_input_v1` + MarketDataService | 显式 opt-in 仅为 research warning run，不计入最终 Ready Gate |
| Signal | confirmed、passed、`canonical_consumer_input_v1` + MarketDataService | warning、partial、failed、unchecked 全部阻断 |
| Review | passed 可作正式证据 | warning 只可带标签展示，不可作信号证据 |

所有 formal consumers 均阻断 registration missing、reference metadata gap、historical partial 与
canonical identity/manifest/mapping drift。report 14/15 只能读取和引用为 Git-traceable historical
snapshots，不是 active Gate/regression；禁止更新、回填、重算覆盖、替换 lineage 或删除证据。

## 2.2.7 Audit V2（2026-07-17）

状态：

```text
FULL_HISTORY_AUDIT_V2_READY
DATA_LAYER_REAUDIT_REQUIRED
```

V2 读取 B2-01 的全部物理 inventory 和 direct PostgreSQL reference metadata，按 `product + period + source_role` 动态生成 expected window/year。旧 final audit 的统一 `DEFAULT_MINUTE_START=2023-01-03`、固定 `2020..2026` 年目录和旧 `1853 / 34 / 45` 数字均不参与新 Gate。

输出位于 `data/reports/full_history_audit_v2_20260710/`。正式结果为 90 个产品、720 个 expected window、7964 条动态年度区间、12726 条 rank=1 actual 1m/1d 目标。当前 reference gap 为 90 个 `trading_calendar_gap` 和 90 个 `trading_session_gap`；physical coverage 为 468 covered / 252 partial；quality 保持 693 passed / 6 warning / 21 failed。

代表品种 direct support：

| product | 1m | 1d | 1w completed | status |
|---|---|---|---|---|
| a | 2010-01-04 | 2002-03-15 | 2002-03-15 | start_boundary_supported |
| al | 2010-01-04 | 2000-01-05 | 2000-01-07 | start_boundary_supported |
| ag | 2012-05-10 | 2012-05-10 | 2012-05-11 | start_boundary_supported |
| jm | 2013-03-22 | 2013-03-22 | 2013-03-22 | start_boundary_supported |

这些日期来自可读 canonical physical evidence，不是 authoritative provider earliest snapshot。此处的 `FULL_HISTORY_AUDIT_V2_READY` 只表示引擎和报告可复查；calendar/session、partial/failed quality 和 Profile eligibility residual 仍须独立治理，不能被解释为全历史资产零 residual。严格消费者准入已在后续 C2-05 Gate 取得 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`，见 8.8。

## 2.3 数据阶段收口审计（2026-07-13）

以下为 2026-07-13 A2-01 的历史状态快照；C2-05 已在 2026-07-18 通过，当前消费者准入结论见 8.8：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

本轮只做只读审计与文档事实源整理，不写 DB、Parquet、manifest、checksum 或 quality status，不调用 RQData。收口包：

```text
data/reports/data_stage_closure/
```

Phase 3 DB 口径事实源为 `data/reports/data_layer_final_audit_phase3_20260712/`。A2-01 后，该口径改为历史审计模型快照，不再作为当前确定下载缺口：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

本轮复跑 `scripts/rqdata_data_layer_final_audit.py` 时，PostgreSQL 因 `fe_sendauth: no password supplied` 不可用，API snapshot 返回 502，审计降级为 `db_snapshot_source=manifest_only`。该复跑结果保存在 `data/reports/data_stage_closure/final_audit/`，用于记录环境 Gate，不作为数据完成度唯一口径。

边界说明：

- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论。
- 更新后的数据层最终验收为 `DATA_LAYER_REAUDIT_REQUIRED`；旧 `1853 / 34 / 45` 不再直接驱动批量修复。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 不等于 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 通过。
- 105 条 `quality_warning` 保持 warning，不升级为 passed。
- 当前不能宣称“全品种周线从上市以来完整”。
- 本结论不授权 Stage 9、企业微信、live runtime、自动交易或实盘。

## 3. JM 最新主连资产

产品：`jm`
研究合约：`jm.MAIN`
窗口：`2023-01-03..2026-07-10`

| period | rows | min datetime | max datetime | derivation | quality |
|---|---:|---|---|---|---|
| 1m | 290715 | 2023-01-03 09:01 | 2026-07-10 15:00 | RQData direct | passed |
| 5m | 58143 | 2023-01-03 09:05 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 15m | 19381 | 2023-01-03 09:15 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 30m | 10116 | 2023-01-03 09:30 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 60m | 5909 | 2023-01-03 10:00 | 2026-07-10 15:00 | aggregated from 1m | passed |
| 1d | 851 | 2023-01-03 00:00 | 2026-07-10 00:00 | grouped by trading_day from 1m | passed |

所有派生 parquet 都包含唯一 `source_interval=1m`，并通过 checksum、DuckDB、row_count 和 PostgreSQL quality report 核对。

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260711.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260711.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`

最新六个目标 data_version 在 `market_data_files` 中每周期只有一条登记，均为 `provider=rqdata / data_role=primary / quality_status=passed`。

## 4. Stage 8.6 分层

### 全品种 `stage8_6_1d_first`

- products：90
- product `active_passed=82`
- product `active_partial=8`
- current snapshot manifest-level discovered active records `active_passed=1326`
- asset `audit_pending=8`
- Stage 9：90 `stage9_blocked`

旧任务表中的 `176 active_passed / 8 audit_pending` 是较早的 Stage 8.6 asset baseline。2026-07-11 `data-audit` 快照纳入了更多 actual-contract manifest-level records，因此当前 asset passed count 为 1326。该数字不代表完整目标覆盖率。

当前 1326 口径：

- 唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `actual_contract` 1244 行，其中 1241 passed / 3 pending。
- `dominant_main` 90 行，其中 85 passed / 5 pending。
- 当前 snapshot 全部为 `1d`，不是多周期全量覆盖。
- provider 从路径推断均为 `rqdata`。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在该报告中逐文件独立证明。
- 1326 passed 记录均有 DB 登记；3 个 pending 缺 `market_data_files`；5 个 pending 是 quality warning。

8 个 pending（TASK-012 已分流，不再作为模糊尾巴）：

- `bb/rs/wh/wr/zc` 主连 1d：`accepted_warning`（abnormal price，不升级 passed）。
- `L2609F/PP2609F/V2609F` actual-contract 1d：`registration_not_needed`（snapshot product=l/pp/v 误报；`l_f/pp_f/v_f` 已 active_passed）。

证据：`data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`

### JM 最新主连 `jm_main_six_period_latest`

- products：1 `active_passed`
- main assets：6/6 `active_passed`
- 该 profile 只审计最新 `jm.MAIN` 六周期，不把历史 actual-contract 片段混入六周期计数。
- Stage 9 仍 blocked；数据 Gate 不授权企业微信发送。

## 4.1 目标覆盖矩阵审计

说明：本节以下保留目标覆盖矩阵从 2026-07-11 到 2026-07-12 的处理链。中间状态用于追溯，不覆盖 §0 和 §2.2 的当前最终口径。

2026-07-11 新增 `TASK-2026-07-11-002-data-target-coverage-audit`，用于区分“已经发现到的 active 资产快照”和“目标资产应覆盖矩阵”。

输出目录：

```text
data/reports/target_coverage_audit_20260711/
```

矩阵粒度：

```text
product x contract_role x symbol/contract x period x year x status
```

2026-07-11 修复前运行结果：

- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：2091 rows。
- 主工程复跑已使用 `db_snapshot_source=database`；未写 DB、未写 Parquet、未调用 RQData。

覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 16156 |
| covered_warning | 1039 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |
| row_count_mismatch | 8 |

元数据矩阵状态：

| status | count |
|---|---:|
| covered_passed | 2445 |
| metadata_gap | 831 |
| not_applicable | 504 |

Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| source_interval_unverified | 1039 |
| missing_db_registration | 108 |
| quality_failed | 105 |
| row_count_mismatch | 8 |

2026-07-12 `TASK-2026-07-12-002-ad-ec-op-weekly-metadata-row-count-repair` 仅对 `ad/ec/op` 三条旧版本周线 `market_data_files.row_count` 做受控 PostgreSQL metadata 修复：

- `ad` / `db_file_id=44115`：47 -> 55。
- `ec` / `db_file_id=44133`：134 -> 148。
- `op` / `db_file_id=44159`：36 -> 42。
- 未写 Parquet、manifest、checksum、data_version、data_role、quality_status；未调用 RQData。

修复后目标覆盖矩阵：

- 输出目录：`data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/`。
- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：2083 rows。
- `db_snapshot_source=database`。

修复后覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 16164 |
| covered_warning | 1039 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |

修复后 Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| source_interval_unverified | 1039 |
| missing_db_registration | 108 |
| quality_failed | 105 |

`row_count_mismatch` 已清零；该结论只覆盖这 3 条旧版本周线 DB metadata stale，不代表 provenance、missing registration、quality failed/warning 已处理。

2026-07-12 `TASK-2026-07-12-005-source-interval-provenance-repair-apply` 对 `source_interval_unverified` 做受控 Parquet/metadata 修复：

- 输入：`data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv`。
- Pilot：5 files applied，`source_interval_unverified` 1039 -> 1019。
- Full：276 selected / 271 applied / 5 skipped / 0 blocked。
- 写入范围：canonical Parquet 新增 `source_interval=1m`，同步 manifest checksum、DB `market_data_files.checksum/file_size_bytes`，并同步 61 个已有 processed summary checksum。
- 未调用 RQData；未改 `row_count`、`data_version`、`data_role`、`quality_status`；未处理 `missing_db_registration`、`quality_failed` 或 reference metadata gaps。

source interval 修复后目标覆盖矩阵：

- 输出目录：`data/reports/target_coverage_audit_20260712_after_source_interval_full/`。
- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15164 rows。
- `issue_register.csv`：1044 rows。
- `db_snapshot_source=database`。

source interval 修复后覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 17203 |
| metadata_gap | 105 |
| missing_db_registration | 108 |
| not_applicable | 273 |

source interval 修复后 Issue 类型：

| issue_type | count |
|---|---:|
| missing_continuous_contract_map | 546 |
| missing_contract_universe | 285 |
| missing_db_registration | 108 |
| quality_failed | 105 |

`source_interval_unverified` 已清零；该结论只覆盖 provenance metadata 和 checksum/file_size 同步。

2026-07-12 `TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run` 对 108 条 `missing_db_registration` 做只读 reconcile：

- 108 target rows 按 `standard_path` 去重为 93 个物理文件。
- 93 个文件均存在，DuckDB / manifest metadata 校验通过。
- `already_registered=87`。
- `duplicate_path_versions=6`，均为 `L2609F` 六周期的两个历史 `data_version` 指向同一路径。
- `eligible_for_registration=0`，`blocked_metadata_mismatch=0`。
- `market_data_files: 71098 -> 71098`，`data_quality_reports: 65466 -> 65466`。
- 根因是 actual-contract manifest 文件名解析将 `l_f/pp_f/v_f` 错分为 `l/pp/v`，导致 manifest 与 DB evidence 无法合并。
- 本任务未写 DB、Parquet 或 manifest，未调用 RQData，未提供 apply 入口。
- 人工 Gate 结论：不需要且不授权受控 DB 登记；六条同路径多版本只报告，不删除、合并、归档或修改。

LPV reconcile 后权威 target coverage 复跑（分支修复代码 + 主工程完整数据目录）：

- 输出：`data/reports/target_coverage_audit_20260712_after_lpv_reconcile/`。
- `target_asset_catalog_rows: 17689 -> 17581`；删除的 108 行是 `l_f/pp_f/v_f` 被错分到 `l/pp/v` 后产生的 phantom targets，不是新增 covered assets。
- `physical_inventory_rows=15056`。
- `covered_passed=17203`，`metadata_gap=105`，`not_applicable=273`。
- `issue_register_rows: 1044 -> 936`。
- 剩余 issue：546 `missing_continuous_contract_map`、285 `missing_contract_universe`、105 `quality_failed`。
- `missing_db_registration=0`，且未改变既有 105 条 `quality_failed` 语义。

解释边界：

- 目标覆盖矩阵不是 Stage 8.6 active snapshot 的替代结论。
- 本次主工程复跑已取得 DB 只读元数据快照，元数据缺口可进入后续只读根因分类。
- `missing_db_registration` dry-run 已证实为审计匹配误报，不授权新增 DB 登记；`quality_failed` 已由 TASK-007 证实为 stale processed summary 误报并转为 `quality_warning`，reference metadata gaps 仍需独立 metadata-only Gate。
- 2026-07-12 metadata repair 只修复 `ad/ec/op` 三条 row_count stale；source interval apply 只修复 provenance metadata，不授权 Stage 9。

2026-07-12 `TASK-2026-07-12-007-residual-data-risk-closeout-dry-run` 对剩余风险做只读 closeout：

- `quality_failed_root_cause_audit` 输入 105 target rows，去重为 15 个唯一文件。
- 15 个文件全部分类为 `stale_processed_summary_failed`。
- 当前 DB、manifest、quality report 均为 `warning`；误报根因是 `processed/v1b/*_v2_parquet_*.json` 仍保留旧 `quality_status=failed`。
- 本任务修正 target coverage audit 质量状态合并口径：DB/manifest 当前 active evidence 优先，processed summary 只在没有 active evidence 时兜底。
- `duplicate_path_version_reconcile` 输入 6 条 `L2609F` 同路径多版本，全部分类为 `duplicate_path_versions`，仅输出 current/superseded 对照，不删除、不归档、不合并、不改 DB。
- `reference_metadata_gap_reconcile` 历史输入 831 rows：`needs_contract_universe_sync: 285`，`needs_continuous_contract_sync: 546`，`partial_year_rows: 0`。
- 输出目录：
  - `data/reports/quality_failed_root_cause_audit_20260712/`
  - `data/reports/duplicate_path_version_reconcile_20260712/`
  - `data/reports/reference_metadata_gap_reconcile_20260712/`
  - `data/reports/target_coverage_audit_20260712_after_residual_closeout/`
- 本任务未写 DB、Parquet 或 manifest，未调用 RQData，未修改 `data_version/data_role/quality_status/checksum`。

Residual closeout 后权威 target coverage 复跑：

- `target_catalog_rows=17581`。
- `physical_inventory_rows=15056`。
- `covered_passed=17203`。
- `covered_warning=105`。
- `not_applicable=273`。
- `metadata_gap=831`。
- `issue_register_rows=936`。
- Issue 类型：546 `missing_continuous_contract_map`、285 `missing_contract_universe`、105 `quality_warning`。
- `quality_failed=0`，`missing_db_registration=0`。
- 105 条 warning asset 不升级为 `passed`，仍需人工理解其异常价 warning；reference metadata gaps 只能进入后续 metadata-only sync/apply Gate。

2026-07-12 `TASK-2026-07-12-008-reference-metadata-gap-apply-plan` 已将 reference metadata gaps 转成 no-write apply plan：

- 输入：`data/reports/reference_metadata_gap_reconcile_20260712/reference_metadata_gap_ledger.csv`。
- 输出目录：`data/reports/reference_metadata_gap_apply_plan_20260712/`。
- `candidate_rows=831`：
  - `needs_contract_universe_sync=285`。
  - `needs_continuous_contract_sync: 546`。
- `batch_count=11`：
  - `contract_universe`：2020、2021、2022、2023。
  - `continuous_contract_map`：2020、2021、2022、2023、2024、2025、2026。
- 本任务仅生成 `apply_candidate_rows.csv`、`apply_batches.csv` 和 Markdown plan，不执行生成命令。
- 安全边界：`writes_database=False`、`writes_parquet=False`、`writes_manifest=False`、`calls_rqdata=False`。
- 后续若进入真实 apply，必须另开人工 Gate；只允许 metadata-only 写 `futures_contract_universe`、`futures_continuous_contract_map` 和相关 task/raw manifest metadata。
- 后续 apply 仍不得写 K 线 Parquet、`market_data_files`、`data_quality_reports`、质量状态、策略、回测、信号、live runtime 或交易执行。

2026-07-12 `TASK-2026-07-12-009-reference-metadata-gap-apply` 已执行 metadata-only apply，并完成 Stage 5-B reference metadata gap 收口：

- 新增受控 apply runner：`scripts/rqdata_reference_metadata_gap_apply.py`。
- 真实写入必须显式使用 `--apply --confirm-metadata-only`。
- `contract_universe` 4 个批次全部成功：
  - candidates：285。
  - status：285 `success`。
  - 写入/更新：`futures_contract_universe`。
  - `rows_fetched_sum=652928`。
- `continuous_contract_map` 7 个 RQData SDK 直接批次已尝试但无数据：
  - candidates：546。
  - status：546 `no_data`。
  - 当前 `rqdatac 3.2.5` runtime 不暴露文档要求的 `futures.get_continuous_contracts`。
  - 不允许用 `get_dominant` 或主力映射替代 `front_month` / `next_month` 连续合约。
- derived `continuous_contract_map` apply 已完成：
  - candidates：546。
  - status：546 `success`。
  - `rows_fetched_sum=234812`。
  - `calls_rqdata=False`，该证据不是 RQData SDK `get_continuous_contracts` 直接接口验收。
- apply ledger 安全列均为：
  - `writes_parquet=False`。
  - `writes_market_data_files=False`。
  - `writes_quality_status=False`。
- Reference reconcile after full reference metadata apply：
  - `needs_contract_universe_sync=0`。
  - `needs_continuous_contract_sync=0`。
  - `partial_year_rows=831`。
- Target coverage after full reference metadata apply：
  - `covered_passed=17203`。
  - `covered_warning=105`。
  - `not_applicable=273`。
  - `issue_register_rows=105`。
  - Issue 类型：105 `quality_warning`。
- Stage 5-B reference metadata gap 已收口；105 条 `quality_warning` 是独立后续 Gate，不属于 reference metadata gap 失败项。
- 输出目录：
  - `data/reports/reference_metadata_gap_apply_batch_01_contract_universe_2020_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_02_contract_universe_2021_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_03_contract_universe_2022_20260712/`
  - `data/reports/reference_metadata_gap_apply_batch_04_contract_universe_2023_20260712/`
  - `data/reports/reference_metadata_gap_apply_derived_continuous_contract_map_20260712/`
  - `data/reports/reference_metadata_gap_reconcile_after_continuous_contract_map_derived_20260712/`
  - `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/`

## 5. 真实合约与 live 边界

- `continuous_contract` 用于研究、方向和连续图。
- `actual_contract` 来自 `MainContractMap.rank=1`，用于真实成本、trigger price、提醒和复盘。
- `JM2609` 是特定映射日期的真实合约证据，不得硬编码为长期主力。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 historical active。
- 盘后归档必须重新经过 gap、duplicate、trading_day、OHLC、manifest、checksum 和 quality Gate。

## 6. 质量规则

每个正式资产至少检查：

- DuckDB 可读与 row_count。
- datetime/trading_day 边界。
- duplicate、必填空值、OHLC、volume、open_interest。
- manifest/checksum 与文件一致。
- DB data_role/quality 与质量报告一致。
- 派生周期 `source_interval=1m`。

自然午休、夜盘、周末和节假日 gap 仅作为样本记录；交易时段内缺口需要交易日历增强后才能精确分类。

## 7. 安全与后续

- RQData credential/license 只从环境变量读取，不写仓库或日志。
- 数据脚本失败时保留失败状态，不登记为 primary passed。
- Stage 5-B reference metadata gap 已清零；不得把 derived continuous map 结果改写为 RQData SDK `get_continuous_contracts` 直接接口验收。
- 后续不得为了消除或重建 metadata gap 将 `get_dominant` 写入 `front_month` / `next_month` continuous map。
- 105 条 `quality_warning` 消费边界已定义（§2.1）；TASK-011 负责代码统一执行。
- live ingest / scheduler、全品种多周期扩展和 actual-contract 批量修复必须另开 Plan。

## 8. Full History Audit V2 物理事实 inventory（2026-07-17）

`FULL-HISTORY-PHYSICAL-INVENTORY-001` 新增独立 inventory 工具，不复用旧 target matrix，只聚合当前 canonical Parquet、全部字段匹配 manifest、全部 processed summary、direct PostgreSQL `market_data_files` 与按 `file_id` 关联的 `data_quality_reports`。

### 8.1 B2-04B 受控 residual 修复边界（2026-07-17）

Audit V2 的 actual rank=1 目标必须裁剪到每个 `product + period` 的 direct supported start，并在裁剪后去重。静态 `trading_sessions` 是运行时配置，不是可按年份机械要求的全历史 reference metadata，因此 Audit V2 将其标为 `not_applicable`，不生成 `trading_session_gap`。

quality evidence 保持分层：physical inventory 分别输出 `quality_statuses_db`、`quality_statuses_manifest`、`quality_statuses_processed`，同时保留兼容聚合列。Audit V2 当前 Gate 优先 direct PostgreSQL evidence；processed summary 的原始 evaluator 状态继续作为 provenance 保留，warning 不升级为 passed。

B2-04A 四个 repair queue 以文件 SHA-256、action type allowlist、显式 action IDs 和 deterministic ledger 冻结。任何 metadata、DB、Parquet 或 RQData 操作必须使用独立 batch approval；通用实施指令不授权生产写入。当前 CLI 只支持 dry-run plan 和 approval verification，不提供生产 apply。

正式 quick 输出位于：

```text
data/reports/full_history_audit_v2_20260710/
```

当前事实：

```text
status=FULL_HISTORY_PHYSICAL_INVENTORY_READY
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
audit_end=2026-07-10
physical_file_count=24763
physical_inventory_rows=27234
manifest_rows_seen=38092
manifest_asset_rows=16298
processed_period_records=1437
market_data_file_rows=25134
quality_report_rows=25134
db_snapshot_source=direct_postgresql
```

异常事实：

- 4 条 DB rows 指向已不存在的 `experiments/rqdata_sample_acceptance/output/...` jm 样本文件。
- 4934 行存在同路径多 version identity；inventory 保留每条 path identity，不选择 active 版本。
- 未发现空文件、Parquet 读取失败、schema mismatch、schema inconsistency 或 audit-end 之后的物理最大时间。

安全边界：

```text
writes_database=false
writes_parquet=false
calls_rqdata=false
expected_matrix_generated=false
```

该 `READY` 只代表当前事实 inventory 可复查，不代表 expected coverage、Profile binding 或 Market/Backtest/Signal 消费 Gate 已通过。旧 `1853/34/45` 数字继续作为历史快照，不得由本 inventory 重新推导。

### 8.2 B2-04B post-repair 事实（2026-07-17）

受控 residual repair 完成后，full-checksum inventory 与 direct PostgreSQL Audit V2 重新执行：

```text
physical_file_count=25495
physical_inventory_rows=27837
market_data_file_rows=25495
quality_report_rows=25495
checksum_matched_rows=27837
checksum_mismatch_rows=0
declared_conflict_rows=0
missing_physical_rows=0
path_drift_rows=0
audit_v2_products=90
audit_v2_expected_windows=720
audit_v2_gap_count=0
profile_binding_changed=false
```

RQData closure 只登记 71 个 `candidate + passed` actual-contract 日线资产；其中 32 个供应商 direct daily 存在 settlement-close/OHLC envelope 冲突，改用新 1m raw 本地聚合日线。异常旧 raw 不覆盖，warning 不升级为 passed，active Profile 不切换。`DATA_LAYER_REAUDIT_REQUIRED` 继续作为更高层 Gate 状态，本次 repair 完成不等同于自动宣布数据层 final ready。

### 8.3 B2-05 derived-period consumer Gate（2026-07-17）

`FULL-HISTORY-DERIVED-PERIODS-005` 将派生周期分成三层：JM V1-B actual consumer hard target、90 品种 Profile eligibility inventory，以及无当前 hard consumer 的 on-demand/deferred target。不得用 Profile 声明自动要求 90 品种重建全部 derived 1d，也不得用 long-horizon direct 1d 冒充 intraday Profile 的 derived 1d。

派生 lineage 只有在以下证据同时成立时才为 verified：

```text
processed summary exact source path
+ registered passed-primary 1m source
+ source version/checksum
+ source_interval=1m
+ source_bar_count
+ target-window coverage
+ physical checksum
+ session-aware bucket recomputation
```

direct PostgreSQL 全量核验覆盖 90 品种、548 consumer/Profile targets。受控修复将旧 `CNFE/jm/regular` 置为 inactive，并登记 DCE JM 夜盘、上午两段和下午时段；目标窗口 851 个交易日中 827 个允许夜盘，24 个节后首日不允许夜盘。修复后既有 5m/15m 与 passed-primary 1m 逐 bucket 完全匹配，无需重建。

Backtest derived 1d 另生成一份 `candidate + passed` 新版本，窗口 `2023-06-28..2026-06-26`，精确记录 source file id/path/version/checksum/profile、`source_interval=1m` 和 `source_bar_count`。最终 8 条 JM hard target residual 为 0，状态为 `DERIVED_PERIOD_TARGETS_VERIFIED`；Profile binding 未切换，未调用 RQData，长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。正式证据位于 `data/reports/full_history_audit_v2_20260710/derived_periods_005_final_001/`。

### 8.4 B2-06 actual rank=1 / roll Gate（2026-07-17）

`ACTUAL-DOMINANT-ROLL-V2-006` 将范围冻结为两层：canonical 90 品种的 `provider=rqdata / rule=volume_open_interest / rank=1` mapping/roll inventory，以及 JM V1-B 的 Backtest/Review、Signal/live historical-reference hard targets。JM hard target 要求 actual-contract `1m/1d` coverage、confirmed trigger、换月边界和 per-field 交易参数 lineage；其余 89 品种 inventory residual 不自动升级为 consumer repair。

Stage 1 只读核验使用 direct PostgreSQL read-only transaction，只新增全新报告目录。Stage 2 在用户批准的固定 ledger 内增加 resolver code fix、mapping/manifest metadata repair 和最小 local rebuild；每批独立校验 hash、before-state、事务边界与 rollback scope，全流程不调用 RQData、不切换 Profile binding。

Mac mini direct PostgreSQL 的 JM quick 与 canonical 90-product full 已于 2026-07-18 执行。正式 full 事实为：

```text
status=ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED
product_count=90
rank1_mapping_count=287608
hard_jm_residual_count=0
formal_residual_count=0
inventory_residual_count=1054
mapping_rows_inserted=11
manifest_rows_added=10
superseded_db_rows=3
local_rebuild_files=2
db_snapshot_source=direct_postgresql
calls_rqdata=false
profile_binding_changed=false
final_verify_writes_database=false
final_verify_writes_parquet=false
final_verify_writes_manifest=false
```

historical/live resolver 和 parameter precedence 已统一到共享 helper；trigger evidence 显式要求 actual confirmed bar。11 个 JM 缺日由本地 evidence 补登记为 JM2609；10 个唯一 1d winner 增加精确 manifest，3 个窄窗口 duplicate 标为 superseded；最后只从本地 raw 重建 JM2609 三日 1m/1d，并通过 DB、passed quality、checksum、DuckDB 和 trading-day boundary 核验。

最终 JM hard/formal residual 均为 0，状态为 `ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED`。1054 条 90 品种 inventory residual 保持非 hard，不自动扩大为下载目标。旧 actual `45` 继续作为历史审计模型快照，不进入 B2-06 代码、测试、统计、Gate 或 repair ledger。最终证据位于 `data/reports/full_history_audit_v2_20260710/actual_dominant_roll_006_final_002/`，修复 ledger 位于相邻 `actual_dominant_roll_006_repairs/`；长期状态仍为 `DATA_LAYER_REAUDIT_REQUIRED`。

### 8.5 B2-07 Profile target-aware selection（2026-07-18）

`DATA-PROFILE-FULL-HISTORY-RULES-007` 将 Profile target 从旧 2020/2023/pilot catalog 迁移到 Audit V2、B2-05 derived lineage 与 B2-06 rank=1 consumer evidence。`intraday_research_v1` 的 direct 1m 使用 provider/listing-aware target，5m/15m/30m/60m/derived 1d 必须继承同 Profile passed 1m lineage；`long_horizon_daily_v1` 的 continuous 1d/1w 使用 direct full-history target，actual 仅使用 V1 rank=1 有效区间；`live_observation_v1` 明确 observation-only、historical/live 分离且不具备 trusted-backtest 资格。

候选选优先验证 provider/role/quality、physical、checksum、metadata、sealing、lineage 和完整 target ranges，再选择 canonical/current。覆盖已满足后不再用更早 `start_ts` 无条件获胜；provider-earliest target 下的 2023 窄窗口、warning under passed-only、frozen report 14 reference 和 conflicting duplicates 均 fail-closed。候选报告新增 target/coverage/selection evidence；旧 schema 无法进入 dry-run/apply/verify。

本 Task 只生成只读 candidate 与 blocked evidence，不执行 binding apply，不修改 DB、Parquet、manifest 或 report 14，不调用 RQData。`PROFILE_FULL_HISTORY_SELECTION_READY` 仅表示 selection engine ready，长期状态继续为 `DATA_LAYER_REAUDIT_REQUIRED`。

Mac mini direct PostgreSQL read-only generate 解析 90 品种、734 个 target，生成 925 条 candidate evidence，其中 265 条 current 全部覆盖目标，660 条按精确原因阻断。随后 dry-run 对 265 条 current 复验 target coverage 和物理 SHA-256，结果 241 would-change、24 unchanged、0 error、0 schema reject；事务保持 read-only，未执行 binding apply。正式证据位于 `data/reports/full_history_audit_v2_20260710/profile_rules_007_final_002/`。

### 8.6 B2-08B Profile binding rollout（2026-07-18）

B2-08A 的 265 个 current candidate 以输入 SHA-256、批次 operation count、before-state SHA 和 identity 集合冻结。受控 rollout 实际变更 241 个 binding，24 个 unchanged 保持原 active，660 个 blocked 没有进入 apply。Pilot 15 行与 JM2605 新 identity 均完成 apply、verify、rollback 演练和再次 apply；JM2605 rollback 使用 `restore_absent`，只把本批新行标为 superseded，不删除历史记录。

最终事实：

```text
status=PROFILE_ACTIVE_BINDINGS_VERIFIED
current_candidates=265
would_change=241
unchanged=24
active_match_count=265
blocked_candidates=660
blocked_candidates_applied=0
duplicate_active_groups=0
golden_queries=8/8 passed
writes_database_table=profile_active_bindings
writes_parquet=false
writes_manifest=false
calls_rqdata=false
report14_changed=false
```

MarketDataFile、DataQualityReport、DataProfile、四个 live 表和 report 14 的 before/after 内容摘要一致。Golden Query 通过 `DataProfileRegistry` 与 `MarketDataReader(profile_id=...)` 读取 historical canonical RQData，不读取 live table。正式证据位于 `data/reports/full_history_audit_v2_20260710/profile_rollout_008b/`；该 marker 只证明 eligible current candidate rollout 完成，长期状态仍为 `DATA_LAYER_REAUDIT_REQUIRED`。

### 8.7 B2-09 Data Asset / Profile acceptance（2026-07-18）

`DATA-ASSET-PROFILE-ACCEPTANCE-009` 在 `main@d19b67dc` 与 direct PostgreSQL read-only snapshot 上统一复核 B2 资产、actual、derived period 和 Profile rollout 证据。Asset Gate 9/9、Profile Gate 5/5 通过，hard blocked register 为 0；265 个 current candidate 与 active binding 全部匹配，duplicate active、passed-only non-passed、historical/live boundary violation 和 unexplained superseded active 均为 0。`report_id=14` 与冻结摘要一致，验收过程不写 DB、Parquet、manifest 或 Profile binding，也不调用 RQData。

验收标记为 `DATA_ASSET_PROFILE_READY_FOR_CONSUMER_CONTRACT`，正式报告位于 `data/reports/full_history_audit_v2_20260710/acceptance_009/`。该标记作为阶段 C formal consumer contract 审计的前置证据；其后的消费者最终 Gate 见 8.8。

### 8.8 C2-05 consumer Golden Query final Gate（2026-07-18）

`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 从合入后的 `main@f7f8ad2b`、阶段 B 同一 data root 和 direct PostgreSQL read-only snapshot 独立复跑。12 组固定 Golden Query 在 Market research bars/indicator、Backtest resolver、Signal source 和 Review exact-bars 中核对 Profile、file ID、data version、immutable binding snapshot、quality policy、OHLCV hash、actual/continuous mapping 与 source interval。

49 条消费者矩阵与 13 个 hard gate 全部通过：strict consumer escape path、arbitrary formal path、warning 进入 Backtest/Signal、`.MAIN` 作为 actual、bars/indicator binding mismatch、daily duplicate、静默吞掉不同值冲突和 duplicate active binding 均为 0；`report_id=14` MD5、155 trades 与 239 orders 未变化。正式结论为 `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`，证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`；先前非 rerun 目录仍为不可改写的失败历史快照。

本 Gate 不改写数据库、Parquet、manifest、Profile binding、report 14、历史 Signal/Review 或 live runtime，也不调用 RQData。`DATA_LAYER_REAUDIT_REQUIRED` 仅继续约束全历史 residual 治理，不能用来否定已通过的严格消费者准入，也不能被此 Ready 标记扩写为全历史零 residual 或 live/notification Ready。
