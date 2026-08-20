# Multi-Candidate Research & Robustness V1 设计规格

> 状态：DESIGN_APPROVED / PLANNED_ONLY。本文件是 Phase 5 `Multi-Candidate Research & Robustness V1` 的长期设计事实源；它不修改 SuBing/N 公式，不代表任何 Candidate 有效、盈利、可交易、可晋升、Alert Ready、release Ready 或 Runtime Ready。
>
> 日期：2026-08-20
>
> 设计冻结时间：`2026-08-20T21:33:00+08:00`
>
> 规划基线：`develop@45a7c49847e6be54e723a22cb678013f88985a6f`
>
> 上游：Candidate Validation V1 / Phase 4B COMPLETE；N Structural Domain V1 CODE/TEST/EVIDENCE COMPLETE，prospective OOS pending。

## 1. 结论

下一阶段不再增加交易公式，也不立即开发日进斗金。

先建立一个薄的、read-only、research-only 的 **Multi-Candidate Research & Robustness V1**，只比较当前已经冻结的两个真实 Candidate：

```text
subing_lifecycle_v2_candidate_v1
+
n_structure_5m_candidate_v1
```

V1 回答三个问题：

```text
1. Temporal：两个 Candidate 在既有 10-fold rolling 历史窗口中是否持续产生样本？
2. Cross-symbol：同一冻结规则在 active 60 品种上的历史分布是否集中在极少数品种？
3. Redundancy：在共同 jm 历史窗口中，两类 causal event 是高度重复、互补，还是经常方向冲突？
```

数据流：

```text
Exact Candidate / Candidate Protocols
             │
             ├── existing Candidate Validation reports
             │       └── anchor jm temporal dossier
             │
Historical Canonical
      ↑
MarketDataService
      ↑
existing SuBing / N source research
      │
      ├── exact active60 common-window runs
      │       └── cross-symbol descriptive robustness
      │
      └── additive event projection seams
              └── jm event relationship / overlap

                  ↓
     MultiCandidateRobustnessReport
                  ↓
              stdout JSON
                  ↓
       versioned research evidence
```

该阶段不是策略排名器，也不是参数优化器。

## 2. 当前仓库事实与设计前提

### 2.1 两个 Candidate 已冻结

SuBing：

```text
candidate_id    = subing_lifecycle_v2_candidate_v1
source_kind     = subing_lifecycle
policy_id       = subing_lifecycle_v2_research_v1
formula_version = subing_lifecycle_v2
protocol_id     = candidate_validation_v1
```

N：

```text
candidate_id    = n_structure_5m_candidate_v1
source_kind     = n_structure
policy_id       = n_structure_5m_v1
formula_version = n_structure_v1
protocol_id     = n_structure_validation_v1
```

两个 Candidate 都保持：

```text
research_only = true
auto_order    = false
```

### 2.2 两个 source report 刻意不同

SuBing 的 anchor event 是：

```text
Lifecycle transition → ENTRY_CONFIRMED
```

SuBing outcome：

```text
3 / 5 / 8 Bar
directional return
MFE
MAE
EMA21 failure
same-trading-day outcome semantics
```

N 的 anchor event 是：

```text
CompletedNPattern completion
```

N outcome：

```text
3 / 5 / 8 Bar
directional return
MFE
MAE
may cross trading day
never cross rank1 segment
```

V1 不得为了“统一报表”丢失这些语义差异。

### 2.3 两个 historical baseline 已存在

SuBing baseline：

```text
reports/research/candidate_validation/
  subing_lifecycle_v2_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-19.json
```

N baseline：

```text
reports/research/candidate_validation/
  n_structure_5m_candidate_v1/
  jm-retrospective-baseline-freeze-2026-08-20.json
```

两个 baseline 都只有 retrospective / rolling historical evidence；prospective OOS 仍按各自 Protocol 独立累积。

## 3. V1 Scope

V1 精确包含：

```text
A. exact robustness protocol
B. anchor jm temporal dossier
C. active60 cross-symbol common retrospective dossier
D. jm causal event overlap / lead-lag / conflict dossier
E. read-only CLI
F. versioned retrospective evidence
```

V1 精确不包含：

```text
parameter sweep
parameter optimizer
hyperparameter search
new Candidate variant
Candidate score/rank
winner / loser
KEEP / DROP / PROMOTE
profitability / expected_profit
portfolio / broker / order / fill / cost / equity
Web / HTTP API
DB / Redis persistence
worker / queue / scheduler
Alert / Scope / notification
Execution Review integration
main / tag / release / Runtime promotion
JDJ 1m
```

## 4. 为什么 V1 不做“参数稳健性 sweep”

当前两个对象是 **exact Candidate identity**。

如果修改：

```text
SuBing slope / MACD / volume / pivot / confirmation rule
或
N swing / completion / break / structure rule
```

这不是“同一个 Candidate 的参数扰动”，而是新的 Policy/Formula/Candidate identity。

特别是 N Structure V1 刻意没有可优化的 ATR/ZigZag/强中弱阈值族。

因此 V1 冻结：

```text
parameter_perturbation = false
```

未来若确有研究价值，应显式创建：

```text
Candidate V2 / Candidate variant
→ exact policy
→ exact freeze
→ Candidate Validation
→ 再进入 Multi-Candidate comparison
```

不得在 Robustness V1 内偷偷生成没有 lineage 的参数结果。

## 5. Exact Robustness Protocol

新增 Git-tracked：

```text
data/research_protocols/multi_candidate_robustness_v1.json
```

Exact payload：

```json
{
  "schema_version": 1,
  "protocol_id": "multi_candidate_robustness_v1",
  "research_only": true,
  "frozen_at": "2026-08-20T21:33:00+08:00",
  "anchor_symbol": "jm",
  "candidates": [
    {
      "candidate_id": "subing_lifecycle_v2_candidate_v1",
      "source_kind": "subing_lifecycle",
      "policy_id": "subing_lifecycle_v2_research_v1",
      "formula_version": "subing_lifecycle_v2",
      "candidate_protocol_id": "candidate_validation_v1",
      "baseline_request_through": "2026-08-19",
      "source_event_kind": "entry_confirmed",
      "evaluable_unit": "5m_ready_boundary",
      "horizon_semantics": "same_trading_day_only"
    },
    {
      "candidate_id": "n_structure_5m_candidate_v1",
      "source_kind": "n_structure",
      "policy_id": "n_structure_5m_v1",
      "formula_version": "n_structure_v1",
      "candidate_protocol_id": "n_structure_validation_v1",
      "baseline_request_through": "2026-08-20",
      "source_event_kind": "n_completed",
      "evaluable_unit": "5m_canonical_bar",
      "horizon_semantics": "same_rank1_segment"
    }
  ],
  "common_retrospective": {
    "since": "2023-01-01",
    "through": "2026-08-18"
  },
  "cross_symbol_products": [
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn"
  ],
  "event_proximity_bars": [3, 5, 8],
  "parameter_perturbation": false,
  "automatic_ranking": false,
  "automatic_promotion": false
}
```

同 `protocol_id` 内容漂移必须 fail-closed。

### 5.1 为什么 common retrospective 截止 2026-08-18

这是两个 Candidate frozen retrospective 的真实交集：

```text
SuBing retrospective through = 2026-08-18
N retrospective through      = 2026-08-19

intersection through         = 2026-08-18
```

所以 cross-symbol 与 event-overlap 统一使用：

```text
2023-01-01 .. 2026-08-18
```

不允许为了增加样本把 N 的 2026-08-19 单独混入共同比较。

### 5.2 为什么 baseline_request_through 不使用“今天”

Temporal dossier 需要重算两个原始 frozen baseline，而不是借机吸收新的 prospective data：

```text
SuBing request through = 2026-08-19
→ prospective first day 2026-08-20
→ baseline status remains pending

N request through = 2026-08-20
→ 2026-08-20 embargo
→ prospective first day 2026-08-21
→ baseline status remains pending
```

Robustness V1 不能创建新的 prospective OOS 结论。

## 6. Frozen Product Set

`cross_symbol_products` 精确冻结为设计时 active 60。

Robustness service 必须：

1. 按 Protocol 的固定顺序逐品种执行；
2. 不从运行时 `active_products.txt` 静默替换该列表；
3. composition 可校验当前 active set 与 frozen 60 的一致性并报告 drift，但历史 Protocol 仍保留自己的 product identity；
4. 任一品种 source 不可用时产生显式 unavailable record，不得从 denominator 删除；
5. `event_count=0` 是合法 available 结果，不等于 unavailable。

V1 不增加 sector aggregation；先保留逐品种事实。

## 7. Source-specific Event Projection Seams

当前两个 source research service 的 `run()` 都只返回 aggregate result。

为了研究两类事件之间的关系，V1 允许增加 **additive、read-only、source-specific event projection seam**，但不得改变现有 aggregate payload。

### 7.1 SuBing event

新增不可变 DTO：

```python
@dataclass(frozen=True, slots=True)
class SubingLifecycleEntryResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: SubingDirection
    opportunity_key: SubingOpportunityKey
    confirmation_source: ConfirmationSource
```

唯一来源：

```text
SubingLifecycleTransition.to_stage == ENTRY_CONFIRMED
```

`event_id` 使用现有 transition identity，不另造第二套事件 identity。

新增：

```python
SubingLifecycleResearchService.entry_events(
    request: LifecycleResearchRequest,
) -> tuple[SubingLifecycleEntryResearchEvent, ...]
```

实现必须与 `run()` 复用同一 segment loader、Factor、Lifecycle reducer 和 window filter；不得重新实现 SuBing 公式。

### 7.2 N event

新增不可变 DTO：

```python
@dataclass(frozen=True, slots=True)
class NStructureCompletionResearchEvent:
    event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: NDirection
```

唯一来源：

```text
CompletedNPattern.completed_at
```

`event_id = pattern.n_id`。

新增：

```python
NStructureResearchService.completion_events(
    request: NStructureResearchRequest,
) -> tuple[NStructureCompletionResearchEvent, ...]
```

同样复用现有 `evaluate_n_structure_segment()` producer，不允许第二套 Swing/N reducer。

### 7.3 Event projection causality

两种 Event 都必须满足：

```text
completed 5m boundary only
exact physical contract
exact rank1 segment_start_trading_day
segment-local bar index
requested trading-day window filter
prefix-causal existing producer
```

未来 suffix 不得改变已发布 event identity、direction、observed_at 或 segment index。

## 8. Minimal Cross-Candidate Event Contract

新模块只在 source DTO 之后做最小归一化：

```python
class CandidateResearchDirection(StrEnum):
    LONG = "long"
    SHORT = "short"

@dataclass(frozen=True, slots=True)
class CandidateResearchEvent:
    candidate_id: str
    source_kind: str
    source_event_kind: str
    source_event_id: str
    symbol: str
    contract: str
    segment_start_trading_day: date
    observed_at: datetime
    trading_day: date
    segment_bar_index: int
    direction: CandidateResearchDirection
```

该类型只用于 retrospective relationship research；不是 AlertEvent、Signal、Order 或 future formal event。

## 9. Event Relationship / Overlap V1

V1 只在：

```text
symbol = jm
window = 2023-01-01 .. 2026-08-18
```

执行 SuBing ↔ N 双向关系研究。

### 9.1 可比较前提

任意两个事件只有同时满足下面三项才可进入 proximity match：

```text
same symbol
same physical contract
same segment_start_trading_day
```

禁止跨换月连接。

### 9.2 Exact same-boundary

同一 `segment_bar_index`：

```text
same direction
→ exact_same_direction_count

opposite direction
→ exact_opposite_direction_count
```

一个 boundary 若存在多个目标事件，按真实事件数计数，不人工去重成一个“信号”。

### 9.3 Nearest same-direction relationship

对每一个 source event：

1. 只看同 segment、同 direction 的 target events；
2. 计算：

```text
signed_distance_bars = target.segment_bar_index - source.segment_bar_index
```

3. 选择 `abs(signed_distance_bars)` 最小的 target；
4. 绝对距离相等时，按 `(target.segment_bar_index, target.source_event_id)` 升序选第一个，即 deterministic earlier-first tie-break；
5. **不是 one-to-one matching**，同一个 target 可以成为多个 source event 的 nearest target。

双向分别计算：

```text
SuBing → N
N → SuBing
```

不得只保留一个方向。

### 9.4 Frozen proximity buckets

只使用当前两条研究链已经共同出现的：

```text
3 / 5 / 8 bars
```

输出：

```text
within_3_same_direction_source_count
within_5_same_direction_source_count
within_8_same_direction_source_count
```

这里的 denominator 始终是 `source_event_count`。

不得创建新 fit threshold。

### 9.5 Lead / lag descriptors

对 `abs(distance) <= 8` 的 nearest relationships，输出：

```text
nearest_match_count_within_8
signed_distance_min
signed_distance_median
signed_distance_max
target_earlier_count
target_same_boundary_count
target_later_count
same_trading_day_count
cross_trading_day_count
```

同 segment 内可以跨 trading day，因为这里研究的是两个已知 causal event 的历史关系，而不是生成 executable trigger。

### 9.6 禁止的 derived score

V1 不输出：

```text
overlap_score
similarity_score
redundancy_score
correlation_score
winner
better_candidate
```

只输出计数和距离事实。

## 10. Cross-Symbol Robustness V1

### 10.1 每个 Candidate × 每个 frozen product

执行：

```text
source research run
window = common retrospective 2023-01-01..2026-08-18
symbol = exact frozen product
```

总矩阵：

```text
2 candidates × 60 products = 120 source runs
```

V1 默认按 Protocol 顺序串行执行，优先确定性和可诊断性，不引入并发框架。

### 10.2 Per-symbol result

统一最小合同：

```python
class CandidateSymbolStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True, slots=True)
class CommonPriceHorizonSummary:
    sample_count: int
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None

@dataclass(frozen=True, slots=True)
class CandidateSymbolRobustness:
    candidate_id: str
    source_kind: str
    symbol: str
    status: CandidateSymbolStatus
    reason_code: str | None
    event_count: int | None
    evaluable_count: int | None
    evaluable_unit: str
    event_rate_per_1000_evaluable: Decimal | None
    horizon_semantics: str
    horizon_summary: Mapping[int, CommonPriceHorizonSummary] | None
```

映射：

SuBing：

```text
event_count     = funnel_counts[ENTRY_CONFIRMED]
evaluable_count = evaluable_boundary_count
evaluable_unit  = 5m_ready_boundary
```

N：

```text
event_count     = completed_n_counts[up] + completed_n_counts[down]
evaluable_count = evaluable_bar_count
evaluable_unit  = 5m_canonical_bar
```

### 10.3 Event rate

只有：

```text
evaluable_count > 0
```

才计算：

```text
event_rate_per_1000_evaluable
= Decimal(event_count) * Decimal(1000) / Decimal(evaluable_count)
```

不 quantize，不 float 化。

如果 `evaluable_count=0` 但 source 合法返回结果：

```text
status = available
event_rate = null
```

### 10.4 Source unavailable

Source failure：

```text
status = unavailable
reason_code = sanitized stable code
metrics = null
```

报告仍必须保留该 symbol。

禁止：

```text
silent drop
只统计有事件品种
只统计数据好的品种
失败后换另一个品种
```

### 10.5 Candidate-level cross-symbol summary

每个 Candidate 输出：

```text
product_count = 60
available_product_count
unavailable_product_count
symbols_with_events
symbols_without_events

event_rate_available_count
event_rate_min
event_rate_median
event_rate_max

for each 3/5/8 horizon:
  symbols_with_samples
  positive_median_return_symbols
  zero_median_return_symbols
  negative_median_return_symbols
```

这些是描述性分布，不是策略优劣判断。

## 11. Horizon Metric Compatibility

两个 Candidate 都有：

```text
directional_return_bps
mfe_bps
mae_bps
```

因此可以投影成 `CommonPriceHorizonSummary`。

但报告必须同时保留：

```text
SuBing horizon_semantics = same_trading_day_only
N horizon_semantics      = same_rank1_segment
```

并增加：

```text
metric_compatibility_flags = [
  "EVALUABLE_UNIT_DIFFERS",
  "HORIZON_SEMANTICS_DIFFERS"
]
```

因此 V1 禁止直接计算：

```text
N_MFE - SuBing_MFE
N_return / SuBing_return
winner by median return
```

SuBing-specific EMA21 failure 仍保留在原 Candidate report，不塞进 common metric。

## 12. Anchor `jm` Temporal Dossier

V1 不建设第二套 rolling engine。

调用既有两个 Candidate Validation service，分别使用 Protocol 冻结的 baseline request-through：

```text
SuBing → candidate-validation through 2026-08-19
N      → candidate-validation through 2026-08-20
```

并投影统一描述：

```python
@dataclass(frozen=True, slots=True)
class CandidateTemporalDossier:
    candidate_id: str
    candidate_protocol_id: str
    source_kind: str
    anchor_symbol: str
    retrospective_since: date
    retrospective_through: date
    event_unit: str
    retrospective_event_count: int
    rolling_fold_count: int
    folds_with_events: int
    test_event_count_min: int
    test_event_count_median: Decimal
    test_event_count_max: int
    prospective_status: str
    prospective_first_trading_day: date
    prospective_through: date
    horizon_semantics: str
    horizon_summary: Mapping[int, CommonPriceHorizonSummary]
    source_quality_flags: tuple[str, ...]
```

SuBing `event = ENTRY_CONFIRMED`；N `event = completed N`。

必须保留两个 Candidate 自己的 retrospective end 与 prospective first day；不得为了表格整齐改成同一个日期。

## 13. Prospective OOS Boundary

Robustness V1：

```text
creates_new_prospective_protocol = false
backfills_oos                    = false
```

Candidate-specific OOS 仍为：

```text
SuBing → first trading day 2026-08-20
N      → first trading day 2026-08-21
```

本阶段的 versioned robustness evidence 只使用 frozen historical baseline 和共同 retrospective；即使执行时现实时间已经进入 prospective window，也不能把新样本混进该 baseline artifact。

未来 prospective refresh 仍由各 Candidate 自己的 exact protocol 单独运行和 Review。

## 14. Final Report Contract

```python
@dataclass(frozen=True, slots=True)
class CandidateRelationshipSummary:
    source_candidate_id: str
    target_candidate_id: str
    source_event_count: int
    target_event_count: int
    exact_same_direction_count: int
    exact_opposite_direction_count: int
    within_3_same_direction_source_count: int
    within_5_same_direction_source_count: int
    within_8_same_direction_source_count: int
    nearest_match_count_within_8: int
    signed_distance_min: int | None
    signed_distance_median: Decimal | None
    signed_distance_max: int | None
    target_earlier_count: int
    target_same_boundary_count: int
    target_later_count: int
    same_trading_day_count: int
    cross_trading_day_count: int

@dataclass(frozen=True, slots=True)
class CrossSymbolCandidateSummary:
    candidate_id: str
    product_count: int
    available_product_count: int
    unavailable_product_count: int
    symbols_with_events: int
    symbols_without_events: int
    event_rate_available_count: int
    event_rate_min: Decimal | None
    event_rate_median: Decimal | None
    event_rate_max: Decimal | None
    horizon_sign_summary: Mapping[int, HorizonSignSummary]

@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessReport:
    schema_version: int
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    anchor_symbol: str
    common_since: date
    common_through: date
    temporal_dossiers: tuple[CandidateTemporalDossier, ...]
    cross_symbol_results: tuple[CandidateSymbolRobustness, ...]
    cross_symbol_summaries: tuple[CrossSymbolCandidateSummary, ...]
    relationships: tuple[CandidateRelationshipSummary, ...]
    metric_compatibility_flags: tuple[str, ...]
    quality_flags: tuple[str, ...]
```

Report candidate 顺序严格跟 Protocol `candidates` 顺序。

Relationships 顺序固定：

```text
subing → n
n → subing
```

## 15. Quality Flags

V1 只允许数据/完整性型 quality flags，例如：

```text
CROSS_SYMBOL_SOURCE_UNAVAILABLE
BASELINE_PROSPECTIVE_PENDING_SUBING
BASELINE_PROSPECTIVE_PENDING_N
SYMBOL_WITHOUT_EVENT
HORIZON_WITHOUT_SAMPLE
```

不得出现：

```text
GOOD_STRATEGY
BAD_STRATEGY
KEEP
DROP
PROMOTE
PASS
FAIL_STRATEGY
```

## 16. Service Boundary

新增：

```text
MultiCandidateRobustnessService
```

依赖必须显式注入：

```text
exact robustness protocol
exact SuBing Candidate validation runner
exact N Candidate validation runner
SuBing source research runner + event seam
N source research runner + event seam
```

Service 不读取 report JSON 作为算法输入；tracked baseline JSON 只在最终 Evidence Review 做 reproducibility 对照。

所有市场事实仍来自：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
→ existing source reducers
```

不得建立第二 Historical Gateway。

## 17. Composition

Robustness composition 必须使用 Protocol 冻结的 product set 构造 source research runners，避免未来 `active_products.txt` 变化把历史 Protocol 的 60 品种静默替换掉。

允许同时校验：

```text
current active set == protocol frozen set
```

若发生 drift：

```text
MULTI_CANDIDATE_ACTIVE_UNIVERSE_DRIFT
```

fail-closed，要求新 task 判断是否创建 V2 Protocol；不得自行重写 V1。

Candidate manifest/protocol 继续由现有 strict loaders 加载，不复制 loader。

## 18. Read-only CLI

新增：

```text
guiyi research candidate-robustness \
  --protocol multi_candidate_robustness_v1
```

V1 **不提供**：

```text
--since
--through
--symbol
--candidate
--products
--threshold
```

原因：V1 所有比较范围已经由 exact Protocol 冻结，避免运行时 cherry-pick。

CLI 输出：

```text
stdout JSON
readonly=true
research_only=true
```

不写报告文件；版本化 artifact 由明确的 evidence task 捕获 stdout 后加入 Git。

V1 不新增 HTTP/API/Web。

## 19. Error / Fail-closed

建议稳定错误码：

```text
MULTI_CANDIDATE_PROTOCOL_INVALID
MULTI_CANDIDATE_IDENTITY_INVALID
MULTI_CANDIDATE_ACTIVE_UNIVERSE_DRIFT
MULTI_CANDIDATE_BASELINE_INVALID
MULTI_CANDIDATE_EVENT_INVALID
MULTI_CANDIDATE_EVENT_SEGMENT_INVALID
MULTI_CANDIDATE_SOURCE_UNAVAILABLE
MULTI_CANDIDATE_REPORT_INVALID
```

必须 fail-closed：

- robustness protocol drift；
- candidate / policy / formula / candidate-protocol identity mismatch；
- frozen 60 与 current active universe drift；
- baseline rolling window identity mismatch；
- baseline request-through 被运行时改成新日期；
- source event 不在 completed 5m boundary；
- event contract/segment/bar index 不一致；
- event relationship 尝试跨 contract 或 rank1 segment；
- source result products 与 requested symbol 不一致；
- partial cross-symbol failure 被静默丢弃；
- 任何自动 rank/promote 字段进入 report。

## 20. Testing Contract

### 20.1 Protocol

必须证明：

- exact JSON only；
- candidate 顺序固定；
- frozen 60 精确且无重复；
- common window exact；
- baseline request-through exact；
- `[3,5,8]` exact；
- `parameter_perturbation=false`；
- `automatic_ranking=false`；
- `automatic_promotion=false`；
- extra/missing/type/value drift 全部 fail-closed。

### 20.2 Source event projection

必须证明：

- SuBing 只有 ENTRY_CONFIRMED 投影；
- N 只有 Completed N 投影；
- source event id 复用既有 identity；
- contract/segment/trading_day/bar index exact；
- prefix invariance；
- aggregate `run()` before/after byte-equivalent projection；
- source-specific formula/reducer 零变化。

### 20.3 Relationship

必须证明：

- cross-contract 不 match；
- cross-segment 不 match；
- same boundary same direction；
- same boundary opposite direction；
- `signed = target - source`；
- 3/5/8 nested counts；
- symmetric distance tie earlier-first；
- same target 可被多个 source 复用；
- 双向 summaries 不可互相代替；
- same-day/cross-day counts exact；
- 无 score/rank key。

### 20.4 Cross-symbol

必须证明：

- exact 60、exact order；
- 120 matrix cells；
- zero-event symbol retained；
- unavailable symbol retained；
- denominator 不因 unavailable 缩成“成功品种数”；
- Decimal event rate exact；
- source result identity mismatch fail-closed；
- horizon semantics 不被丢掉；
- no silent fallback。

### 20.5 Temporal dossier

必须证明：

- 调用 existing Candidate Validation，不重建 rolling engine；
- SuBing through 固定 2026-08-19；
- N through 固定 2026-08-20；
- 10 folds identities/dates 与 source reports 一致；
- event count normalization exact；
- prospective status 原样保留，不创建新 OOS。

### 20.6 Regression

必须运行：

```text
existing N full chain
existing SuBing zero-regression
existing Candidate Validation tests
new robustness focused tests
Ruff
Mypy
secret scan
git diff --check
```

不得运行真实 provider 写入、Canonical/DB/Redis mutation、Alert send 或 Runtime switch。

## 21. Versioned Evidence

实现与独立 Review 通过后，exact-develop 运行一次：

```text
guiyi research candidate-robustness \
  --protocol multi_candidate_robustness_v1
```

唯一首份 artifact：

```text
reports/research/candidate_robustness/
  multi_candidate_robustness_v1/
    anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

Evidence Review 必须验证：

```text
exact protocol identity
exact two candidate identities
exact frozen 60 product order
common window 2023-01-01..2026-08-18
anchor jm
candidate-specific baseline dates
both relationship directions
no forbidden decision/rank/profit fields
deterministic rerun byte identity
```

还要把本次重新计算出的两个 anchor baseline 与已 tracked Candidate baseline 做 canonical payload 对照，证明 Robustness 没有改写其历史基线。

该 artifact 只能称为：

```text
retrospective multi-candidate robustness dossier
```

不能称为 OOS evidence、strategy ranking 或 promotion evidence。

## 22. Documentation Closeout

完成后更新：

```text
STATUS.md
docs/ARCHITECTURE.md
PROJECT_SOURCE.md
TESTING.md
```

只记录：

- 新 read-only CLI；
- exact robustness protocol；
- retrospective robustness evidence；
- 两个 Candidate 原有 prospective OOS 继续独立累积。

`DECISIONS.md` 仅当实施确实产生新的长期架构决策时才更新；不能为了完成任务机械追加。

## 23. Planned Files

### 新增

```text
data/research_protocols/multi_candidate_robustness_v1.json
services/quant-api/app/market_data/multi_candidate_robustness_policy.py
services/quant-api/app/market_data/multi_candidate_events.py
services/quant-api/app/market_data/multi_candidate_robustness.py
services/quant-api/app/market_data/multi_candidate_robustness_service.py
services/quant-api/tests/test_multi_candidate_robustness_policy.py
services/quant-api/tests/test_multi_candidate_events.py
services/quant-api/tests/test_multi_candidate_robustness.py
services/quant-api/tests/data_foundation/test_multi_candidate_robustness_service.py
reports/research/candidate_robustness/multi_candidate_robustness_v1/
  anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

### 有界修改

```text
services/quant-api/app/market_data/subing_lifecycle_research_service.py
services/quant-api/app/market_data/n_structure_research_service.py
services/quant-api/app/market_data/composition.py
services/quant-api/app/guiyi_cli/research_parser.py
services/quant-api/app/guiyi_cli/research_commands.py
services/quant-api/app/guiyi_cli/main.py
services/quant-api/tests/data_foundation/test_subing_lifecycle_research_service.py
services/quant-api/tests/data_foundation/test_n_structure_research_service.py
services/quant-api/tests/test_research_cli.py
STATUS.md
docs/ARCHITECTURE.md
PROJECT_SOURCE.md
TESTING.md
```

禁止修改：

```text
SuBing policy/calibration/formula
N policy/formula
existing candidate manifests
existing candidate protocols
Alert Registry/Scope
Execution Review schema
Data Foundation schema/Catalog/Canonical
main/tag/runtime files
```

## 24. Implementation Decomposition

Implementation Plan 拆为 8 个可独立 Review Tasks：

```text
Task 1  Exact robustness Protocol + immutable report contracts
Task 2  SuBing/N source-specific causal event projection seams
Task 3  Candidate event relationship / overlap engine
Task 4  active60 cross-symbol common-window robustness
Task 5  anchor jm temporal dossier via existing Candidate Validation
Task 6  orchestration + readonly candidate-robustness CLI
Task 7  cumulative temporal/parity verification + independent Review + develop integration
Task 8  exact-develop real evidence + Evidence Review + canonical closeout
```

## 25. Lane / Risk Classification

本阶段不修改交易公式、不修改正式 backtest 撮合、不写 live/DB/Canonical、不发布，因此没有实现类 Lane 3 Task。

但 temporal / event relationship 有未来函数和身份错配风险，所以：

```text
Task 1  Lane 2 / Sol high
Task 2  Lane 1 / Sol high
Task 3  Lane 1 / Sol high
Task 4  Lane 1 / Sol high
Task 5  Lane 1 / Sol high
Task 6  Lane 2 / Terra medium
Task 7  Lane 1 / Sol high / independent Review
Task 8  Lane 1 / Sol high / independent Evidence Review
```

任何实施过程中需要修改 SuBing/N 公式或 Candidate identity 时：

```text
FORMULA_OR_CANDIDATE_DRIFT
→ stop
→ 新开 Lane 3 / new Candidate task
```

## 26. 完成 Gate

Phase 5 V1 完成最多允许得出：

```text
两个 frozen Candidate 已具有统一可复算的 retrospective robustness dossier；
已描述其 anchor temporal stability、active60 cross-symbol distribution 和 jm event relationship；
prospective OOS 仍由各 Candidate 自己的 Protocol 独立累积。
```

绝不允许从本阶段自动推出：

```text
哪个策略更好
哪个策略应该保留/淘汰
哪个策略盈利
哪个策略可以交易
可以创建第三条 Alert Rule
可以晋升 FormalPolicy
可以 release main/tag
可以 Runtime promotion
```
