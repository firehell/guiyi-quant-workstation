# Phase 8 — Five-Candidate Evidence Convergence & Relationship Topology V1 Design

日期：2026-08-22

状态：Approved for implementation planning

## 1. 目的

Phase 8 不继续增加新指标，也不对现有 Candidate 自动排名。它把当前五条已冻结 Candidate 的 retrospective / rolling / cross-symbol evidence 收敛成一套可审查的研究事实，并进一步明确 Candidate 之间哪些是可比较关系、哪些是结构依赖、哪些只允许做同边界重合研究、哪些跨周期关系当前没有定义。

Phase 8 精确包含两部分：

```text
Phase 8A — Five-Candidate Research Dossier V1
  已有 evidence 收敛 + comparability boundary

Phase 8B — Five-Candidate Relationship Topology V1
  结构依赖 + exact same-boundary overlap + existing relationship reference
```

Phase 8 完成后进入 prospective OOS / walk-forward / shadow 主线；Phase 8 本身不产生 KEEP / DROP / ITERATE / PROMOTE，也不把任何 retrospective evidence 描述为盈利、有效、可交易或 Runtime-ready。

## 2. 当前事实基线

实施开始前必须重新读取最新 `develop` 的 `STATUS.md`、`AGENTS.md`、`docs/DEVELOPMENT.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` 与相关源码。本文不冻结 `develop` commit；任务必须从实施当时的最新 `develop` 创建工作区，并 fail-closed 处理 canonical 冲突。

当前五条 Candidate：

1. `subing_lifecycle_v2_candidate_v1`
2. `n_structure_5m_candidate_v1`
3. `jdj_trend_follow_1m_candidate_v1`
4. `jdj_trend_reentry_6_1m_candidate_v1`
5. `jdj_key_level_breakout_1m_candidate_v1`

当前 frozen evidence：

- SuBing baseline：retrospective `2023-01-01..2026-08-18`，prospective first trading day `2026-08-20`；
- N baseline：retrospective `2023-01-01..2026-08-19`，`2026-08-20` embargo，prospective first trading day `2026-08-21`；
- 三条 JDJ baseline：retrospective `2023-01-01..2026-08-20`，`2026-08-21` embargo，prospective first trading day `2026-08-24`；
- `multi_candidate_robustness_v1`：SuBing + N，完整 `2 × 60 = 120` cells，当前 `98 available / 22 typed unavailable`；
- `jdj_active60_robustness_v1`：三条 JDJ，完整 `3 × 60 = 180` cells，当前 `147 available / 33 typed unavailable`。

因此 Phase 8 明确禁止制造一个“五 Candidate common retrospective window”。每套 evidence 必须保留自己的 source window 和 horizon semantics。

## 3. 核心原则

### 3.1 证据收敛不等于新研究计算

Phase 8A 只组合 Git-tracked frozen artifacts，不调用 `MarketDataService`、`ActualDominantResearchSegmentLoader`、Candidate runner 或 robustness runner，不建立 DB Session，不重新计算 horizon / sector / yearly / relationship 指标。

### 3.2 Comparability 与 Relationship 分离

`comparability` 回答“两个 Candidate 的某类 evidence / metric 能不能横向比较”。

`relationship` 回答“两个 Candidate 的信息生成路径或事件事实之间是什么关系”。

不能因为两个 Candidate 都有 `event_count`、`horizon_summary` 等同名字段就假设语义可比较。

### 3.3 Dependency 不能伪装成独立共振

JDJ 三条 Candidate 都消费 strict-before 的 N Structure context。Key-Level Breakout 还直接消费同 epoch 的 N pivot lineage。因此 N + JDJ 不能被解释成两条完全独立信号的“共振”。

### 3.4 Phase 8B 不研究 future performance

Phase 8B 只研究 information topology：existing relationship、structural dependency、exact same-boundary overlap。禁止按重合组合重新计算 future return、MFE、MAE、positive outcome rate 或任何收益/胜率结论。

### 3.5 不新增隐含参数

禁止为跨 timeframe relationship 发明 `±N` 分钟、same-day、lead/lag 等参数。JDJ↔JDJ V1 只允许 exact same-boundary；N→JDJ 只允许结构依赖事实。

## 4. Phase 8A — Five-Candidate Research Dossier V1

### 4.1 架构

```text
five_candidate_research_dossier_v1 protocol
        ↓ exact path + SHA-256 + identity validation
7 frozen JSON artifacts
  = 5 candidate-validation baselines
  + 120-cell SuBing/N robustness
  + 180-cell JDJ robustness
        ↓ pure projection only
FiveCandidateResearchDossierService.run(request)
        ↓
deterministic compact dossier JSON
```

新增只读 CLI：

```text
guiyi research candidate-dossier \
  --protocol five_candidate_research_dossier_v1
```

`candidate-dossier` 是 artifact composition，不属于 `candidate-robustness` source recomputation。

### 4.2 Frozen source artifacts

协议只保存 repository-relative path，不允许绝对路径。运行时以 `PROJECT_ROOT / relative_path` 解析，并要求 resolved path 仍在 `PROJECT_ROOT` 内。

七个 source artifact 固定为：

| Kind | Repo-relative path | Expected SHA-256 |
|---|---|---|
| SuBing baseline | `reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/jm-retrospective-baseline-freeze-2026-08-19.json` | `1a1b3064dcb9084adc7347e024c001a2fe7c4bb7ba909c6c80f31659ecc3b3d1` |
| N baseline | `reports/research/candidate_validation/n_structure_5m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-20.json` | `12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6` |
| JDJ Trend Follow baseline | `reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json` | `63a9f3021ae30eab777d838c39493f1ef195c07edc49f5471cbbb2de98621fef` |
| JDJ Trend Reentry 6 baseline | `reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json` | `63f9dfdd29eabfa2c7b44fbe24aa31198dddffae60fab856e9d1b2684cb35bea` |
| JDJ Key-Level Breakout baseline | `reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/jm-retrospective-baseline-freeze-2026-08-21.json` | `6e06b894bb05a0de2c857be0143cdd44d0b7479b33ad712a0db88197bbdcab10` |
| SuBing/N robustness | `reports/research/candidate_robustness/multi_candidate_robustness_v1/anchor-jm-active60-retrospective-freeze-2026-08-20.json` | `6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433` |
| JDJ robustness | `reports/research/candidate_robustness/jdj_active60_robustness_v1/active60-retrospective-freeze-2026-08-21.json` | `f6078a5bc9d3071cb6f0366982dc709cf95087b5ec8b1872b72d1fd4b7790d87` |

任何 missing、path escape、非 UTF-8、非 JSON object、SHA drift、candidate/protocol/window/order drift 都整体失败为：

```text
FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID
```

不得把 source artifact integrity failure 降级成 Candidate `unavailable`。

### 4.3 Dossier protocol

新增：

`data/research_protocols/five_candidate_research_dossier_v1.json`

固定语义：

```text
schema_version = 1
protocol_id = five_candidate_research_dossier_v1
research_only = true
readonly = true
candidate_order = 精确五条 Candidate 顺序
source_artifacts = 精确七条 repo-relative path + expected_sha256
comparability_pair_order = 精确十个 canonical unordered pair
prospective_consumed = false
new_metric_calculation = false
new_relationship_calculation = false
parameter_perturbation = false
automatic_scoring = false
automatic_ranking = false
automatic_promotion = false
```

`frozen_at` 在 Task 1 由实现写入协议并自此 exact freeze；不得在同一 V1 中静默变化。

### 4.4 Candidate dossier contract

顶层：

```text
schema_version
command = "guiyi research candidate-dossier --protocol five_candidate_research_dossier_v1"
status = "ok"
protocol_id
frozen_at
research_only = true
readonly = true
prospective_consumed = false
candidate_order[5]
source_artifacts[7]
candidate_dossiers[5]
metric_catalog
comparability_pairs[10]
quality_flags
safety
```

每个 `CandidateDossier` 包含：

```text
identity:
  candidate_id
  source_kind
  policy_id
  formula_version
  source_event_kind
  source_timeframes
  evaluable_unit
  horizon_semantics
  horizons_bars

baseline:
  artifact_id
  symbol = "jm"
  validation_protocol_id
  baseline_request_through
  retrospective_since
  retrospective_through
  retrospective_event_count
  evaluable_count
  rolling_fold_count
  folds_with_events
  prospective:
    first_trading_day
    through
    status
    consumed = false
    embargo_trading_days
  quality_flags

robustness:
  artifact_id
  robustness_protocol_id
  retrospective_since
  retrospective_through
  matrix_cell_count = 60
  available_symbol_count
  unavailable_symbol_count
  unavailable_reason_counts
  zero_event_symbol_count
  zero_sample_symbol_count_by_horizon
  sector_evidence
  yearly_evidence
  quality_flags

evidence_references:
  temporal
  cross_symbol
  sector
  yearly
  horizon
  quality
```

Phase 8A 保留 source-specific horizon semantics：

- SuBing：`5m` clock + `15m` anchor；`entry_confirmed`；`5m_ready_boundary`；horizon `3/5/8`；`same_trading_day_only`；
- N：`5m`；`n_completed`；`5m_canonical_bar`；horizon `3/5/8`；`same_rank1_segment`；
- JDJ：`1m` source + strict-before `5m` N context；各自 source event kind；`1m_canonical_bar`；horizon `3/5/8/20`；source outcome 保持 same trading day + physical contract + rank1 segment 语义。

### 4.5 Missingness contract

三种状态必须保持互斥：

1. `unavailable`：typed reason，所有 source count / metric 为 `null`；
2. `available + event_count=0`：真实 zero-event，不是 unavailable；
3. `sample_count=0`：该 horizon 的数值 metric 全部为 `null`，不是数值 0。

当前两套 source matrix 合计精确 `300` cells；当前事实为 `245 available / 55 unavailable`。这是 source evidence inventory，不是 Candidate 排名。

### 4.6 Comparability catalog

固定枚举：

```text
SUPPORTED_EXISTING
SUPPORTED_SAME_FAMILY
NOT_YET_DEFINED
NOT_COMPARABLE
```

十个 canonical unordered pair：

| Pair | Status | V1 meaning |
|---|---|---|
| SuBing ↔ N | `SUPPORTED_EXISTING` | 复用既有双向 relationship 与 compatibility flags；不直接比较 source-specific event-rate / horizon performance |
| SuBing ↔ 任一 JDJ | `NOT_COMPARABLE` | 只并列 identity / coverage / prospective；不发明跨 5m/1m 对齐 |
| N ↔ 任一 JDJ | `NOT_YET_DEFINED` | 8A 只记录 JDJ 已知依赖 N context；不生成 pair metric |
| 任意两个 JDJ | `SUPPORTED_SAME_FAMILY` | 可并列 event-rate、3/5/8/20、yearly、sector、availability；不新增 overlap / lead-lag |

`metric_catalog` 至少区分：

- 五条都可比的 evidence completeness / availability / zero-event / zero-sample / rolling-fold / prospective status；
- 仅 JDJ 同 family 可横向比较的 event-rate、long/short count、3/5/8/20 source outcome、yearly、symbol-balanced sector；
- SuBing/N 同名 horizon 字段必须带 `EVALUABLE_UNIT_DIFFERS` / `HORIZON_SEMANTICS_DIFFERS`，不得转为统一 performance。

## 5. Phase 8B — Five-Candidate Relationship Topology V1

### 5.1 目的

Phase 8B 研究五条 Candidate 的 information topology，而不是重新研究收益。它冻结四种 relation kind：

```text
EXISTING_EVENT_RELATIONSHIP
STRUCTURAL_CONTEXT_DEPENDENCY
EXACT_SAME_BOUNDARY_OVERLAP
UNDEFINED_CROSS_TIMEFRAME
```

十个 pair 的关系：

| Pair | Relation kind |
|---|---|
| SuBing ↔ N | `EXISTING_EVENT_RELATIONSHIP` |
| N ↔ Trend Follow | `STRUCTURAL_CONTEXT_DEPENDENCY` |
| N ↔ Trend Reentry 6 | `STRUCTURAL_CONTEXT_DEPENDENCY` |
| N ↔ Key-Level Breakout | `STRUCTURAL_CONTEXT_DEPENDENCY` |
| TF ↔ R6 | `EXACT_SAME_BOUNDARY_OVERLAP` |
| TF ↔ KLB | `EXACT_SAME_BOUNDARY_OVERLAP` |
| R6 ↔ KLB | `EXACT_SAME_BOUNDARY_OVERLAP` |
| SuBing ↔ TF | `UNDEFINED_CROSS_TIMEFRAME` |
| SuBing ↔ R6 | `UNDEFINED_CROSS_TIMEFRAME` |
| SuBing ↔ KLB | `UNDEFINED_CROSS_TIMEFRAME` |

### 5.2 N → JDJ structural dependency

三条 JDJ 都从 `JdjBarContext` 消费 strict-before N facts：

- Trend Follow：N trend 作为 `trend_filter`；
- Trend Reentry 6：N trend 作为 `trend_filter`；
- Key-Level Breakout：N trend + same-epoch eligible pivot 作为 `trend_and_pivot_source`。

因此 N→JDJ 只验证 lineage 是否完整，不计算 N completion 到 JDJ trigger 的 `±N` proximity。

固定 analysis window：

```text
2023-01-01 .. 2026-08-19
```

该 run 必须独立以 `through=2026-08-19` 执行，禁止先消费 `2026-08-20` 再在输出层过滤，因为 `2026-08-20` 是 N prospective/embargo 边界之外的数据。

输出 identity 精确：

```text
3 JDJ candidates × active60 = 180 dependency cells
```

available cell 只允许输出：

```text
candidate_id
symbol
dependency_role
event_count
events_with_trend_snapshot_lineage
events_with_exact_pivot_lineage  # KLB only; TF/R6 = null
```

约束：

- Trend Follow / Trend Reentry 6：`events_with_trend_snapshot_lineage == event_count`；
- Key-Level Breakout：`events_with_trend_snapshot_lineage == event_count` 且 `events_with_exact_pivot_lineage == event_count`；
- 不满足即 fail-closed，不生成部分可信结果。

### 5.3 JDJ ↔ JDJ exact same-boundary overlap

JDJ 三条 Candidate 同为 1m、同 physical contract、同 rank1 segment、共享一次 `run_batch()` 的 1m/5m source 与 strict-before N context，所以 V1 可以研究不带任何人为窗口的 exact overlap。

固定 analysis window：

```text
2023-01-01 .. 2026-08-20
```

exact boundary key：

```text
symbol
contract
segment_start_trading_day
trading_day
segment_bar_index
observed_at
```

方向单独分：

```text
same_direction
opposite_direction
```

输出 identity 精确：

```text
3 unordered JDJ pairs × active60 = 180 overlap cells
```

available cell：

```text
left_candidate_id
right_candidate_id
symbol
status = available
left_event_count
right_event_count
exact_same_boundary_same_direction_count
exact_same_boundary_opposite_direction_count
left_events_with_same_direction_match
right_events_with_same_direction_match
```

禁止新增：

```text
±1 / ±3 / ±5 / ±8
lead / lag
correlation
causal effect
future return conditioned on overlap
overlap score
```

### 5.4 Existing SuBing ↔ N relationship

不重算。只引用现有 `multi_candidate_robustness_v1` frozen relationship，保留其自身 `2023-01-01..2026-08-18` window、same symbol + same physical contract + same rank1 segment 及已有 `3/5/8` proximity 语义。

### 5.5 SuBing ↔ JDJ

V1 固定为 `UNDEFINED_CROSS_TIMEFRAME`。不读取行情、不做关系计算。未来若确有研究价值，必须另行冻结 cross-timeframe alignment protocol，不能扩写 Phase 8 V1。

## 6. Phase 8B protocol

新增：

`data/research_protocols/five_candidate_relationship_topology_v1.json`

固定语义：

```text
schema_version = 1
protocol_id = five_candidate_relationship_topology_v1
research_only = true
readonly = true
candidate_order = exact 5 candidates
pair_order = exact 10 unordered pairs

analyses.subing_n:
  relation_kind = EXISTING_EVENT_RELATIONSHIP
  source = exact frozen multi_candidate_robustness_v1 artifact
  recompute = false

analyses.n_jdj_context_dependency:
  relation_kind = STRUCTURAL_CONTEXT_DEPENDENCY
  since = 2023-01-01
  through = 2026-08-19
  candidates = exact 3 JDJ
  proximity = null
  future_outcomes = false

analyses.jdj_exact_overlap:
  relation_kind = EXACT_SAME_BOUNDARY_OVERLAP
  since = 2023-01-01
  through = 2026-08-20
  pairs = exact 3 unordered JDJ pairs
  proximity = null
  future_outcomes = false

analyses.subing_jdj:
  relation_kind = UNDEFINED_CROSS_TIMEFRAME
  recompute = false

parameter_perturbation = false
automatic_scoring = false
automatic_ranking = false
automatic_promotion = false
prospective_consumed = false
```

Phase 8B protocol 还必须冻结 Task 5 生成的 Phase 8A dossier artifact repo-relative path + SHA256，以及既有 SuBing/N robustness artifact path + SHA256。8A SHA 只有在 Task 5 artifact 真正生成后才可写入 8B protocol；不得用占位值。

## 7. Phase 8B report contract

顶层：

```text
schema_version
command = "guiyi research candidate-relationships --protocol five_candidate_relationship_topology_v1"
status
protocol_id
frozen_at
research_only
readonly
prospective_consumed
candidate_order
pair_order
relationship_catalog[10]
existing_relationship_references
n_jdj_dependency_results[180]
jdj_exact_overlap_results[180]
quality_flags
safety
```

必须保留完整 `180 + 180 = 360` identity cells。source unavailable 使用 typed unavailable row；不得删除 row，也不得把 unavailable 伪装成 zero-event。

Phase 8B CLI：

```text
guiyi research candidate-relationships \
  --protocol five_candidate_relationship_topology_v1
```

与 `candidate-dossier` 不同，该命令属于 Historical source recomputation，会通过现有 read-only research composition 构造 `JdjResearchService`，但不得写 DB / Canonical / Redis。

## 8. Error / fail-closed semantics

Phase 8A：

- protocol invalid → `FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID`；
- source artifact integrity / identity invalid → `FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID`；
- report shape / invariant invalid → `FIVE_CANDIDATE_DOSSIER_REPORT_INVALID`。

Phase 8B：

- protocol invalid → `FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID`；
- 8A / existing relationship artifact identity invalid → `FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID`；
- JDJ source unavailable → 对该 symbol 保留 typed unavailable cells；
- JDJ context / event identity / overlap invariant invalid → 整体 execution fail-closed，不把 contract corruption 降级为 source unavailable；
- report invariant invalid → `FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID`。

CLI 错误继续使用现有 redacted JSON error path，不输出 stack trace、绝对路径或 source artifact 内容。

## 9. Determinism

两个 Phase 8 CLI 均必须：

- fixed candidate / artifact / pair / symbol ordering；
- fixed dict key construction；
- Decimal 使用仓库既有 canonical JSON string renderer；
- 同输入连续两次 stdout byte-identical；
- parsed JSON 语义相等；
- tracked evidence artifact 必须来自 exact CLI stdout，不手工编辑。

Phase 8A artifact：

`reports/research/candidate_dossier/five_candidate_research_dossier_v1/five-candidate-retrospective-evidence-freeze-2026-08-22.json`

Phase 8B artifact：

`reports/research/candidate_relationships/five_candidate_relationship_topology_v1/five-candidate-relationship-topology-freeze-2026-08-22.json`

## 10. 禁止范围

Phase 8 全部禁止：

- 新增第六条 Candidate；
- 修改任何 Candidate formula / policy / parameter；
- parameter sweep；
- 自动 score / rank / winner；
- KEEP / DROP / ITERATE / PROMOTE；
- 用 retrospective overlap 组合重新定义新 Candidate；
- overlap 后 future outcome / 盈利 / 胜率研究；
- Five-Candidate common retrospective window；
- 消费 N `2026-08-20` 作为 N→JDJ dependency source；
- 消费 JDJ `2026-08-21` embargo；
- 消费 `2026-08-24+` JDJ prospective OOS；
- 修改或回填其他 Candidate prospective；
- backtest / fill / order / position / cost / equity / PnL；
- Alert / Scope / Runtime / Execution Review 变更；
- DB / Canonical / Redis 写入；
- main / tag / release / Runtime promotion；
- 订单路径；`auto_order=false` 始终不变。

## 11. 完整 Phase 8 Gate

Phase 8 只有同时满足以下条件才可关闭：

1. Five-Candidate Research Dossier V1 frozen；
2. Five-Candidate Relationship Topology V1 frozen；
3. 五条 Candidate identity 未变化；
4. 五个 baseline source hash 未变化；
5. 120-cell / 180-cell robustness source evidence 未变化；
6. 8A 完整保留 300 source cells；
7. 8B 完整保留 180 dependency + 180 overlap identity cells；
8. SuBing↔N 不重复计算；
9. N→JDJ 被标记为 structural dependency，不描述为独立信号共振；
10. JDJ↔JDJ 只做 exact same-boundary overlap；
11. SuBing↔JDJ 保持 undefined；
12. 不存在 Five-Candidate common retrospective；
13. 不消费 prospective OOS；
14. 不消费 N/JDJ embargo；
15. 不做参数扫描、组合 Candidate 或自动排名；
16. 不计算 overlap 后 future return；
17. 无 DB / Canonical / Redis write；
18. 无 Alert / Execution Review / Runtime / release 状态变化；
19. `auto_order=false`。

最终 canonical 只允许声明“五条 frozen Candidate 的 retrospective evidence、comparability 与 relationship topology 已被冻结”，不得声明 Candidate 优劣、有效性、盈利、可交易或可晋升。
