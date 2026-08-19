# N 字 Structural Domain V1 设计规格

> 状态：Design approved by user；后续未逐项确认项按已授权的推荐方案冻结。本文件是 N 字 Structural Domain V1 的设计事实源，不代表策略有效、Candidate 可晋升、Alert Ready 或任何 production 授权。
>
> 日期：2026-08-20
>
> 规划基线：`develop@c62376b65b7776da113a2cc21f4db42a84753f69`
>
> 上游阶段：`Candidate Validation V1 / Phase 4B COMPLETE`
>
> 原始研究来源：用户提供的《期货技术教程讲义【L修订打印版】》第四章 4.1～4.6（波动、N 字、强弱/支撑压力、分型、结构阶梯）。

## 1. 结论

下一阶段建立一个独立、research-only、5m-only 的 **N 字 Structural Domain V1**。

它不是“再加一个指标”，而是把原书中的价格波动归纳转换为可因果复算的结构事实：

```text
completed 5m Historical Canonical
→ sequential causal swing reducer
→ confirmed structural pivots
→ UP_N / DOWN_N
→ completion
→ N2_ORIGIN / ORIGIN break events
→ N1-N2 range-band raw observation
→ BULL / BEAR / RANGE structure
→ trailing structural defense
→ Historical research evidence
→ Candidate Validation
```

V1 的目标不是自动交易，也不是证明 N 字有效，而是建立第二个真实 Candidate producer，使归一量化第一次拥有与 SuBing 独立的纯价格结构研究域。

## 2. 研究来源：原书明确支持什么

以下内容属于 **SOURCE_DERIVED**，设计必须保留原书语义，不得把工程补充伪装成书中原公式。

### 2.1 波动归纳

原书 4.1 明确：

- 连续不破前一根 K 线最低价时，从最低点向最高点归纳；
- 连续不突破前一根 K 线最高价时，从最高点向最低点归纳；
- 每一根 K 线完成后可以继续调整归纳连线；
- N 字是价格波动的最小单元；
- 高低点逐级抬高形成多头结构，逐级降低形成空头结构，不能持续向上也不能持续向下形成盘整结构。

### 2.2 N 字命名

原书 4.2 只定义两种 N：

```text
UP_N   上攻 N
DOWN_N 下杀 N
```

并只定义三个阶段：

```text
N1           = ORIGIN → N1_EXTREME
N1_N2        = N1_EXTREME → N2_ORIGIN（抵抗阶段）
N2           = N2_ORIGIN → completion
```

本项目 **不使用“N1/N2/N3/N4 四种 N 或四阶段”** 的旧讨论简称。

### 2.3 两低一高 / 两高一低

原书 4.3 明确：

```text
UP_N 基础   = 两低一高
DOWN_N 基础 = 两高一低
```

UP_N 的 N1-N2 阶段不得跌破 N1 起点；DOWN_N 对称。

### 2.4 N 字破坏

原书明确区分：

```text
破坏 N2 起点
→ 当前 N 的延续被结束/进入分型
→ 不等于方向已经确认反转

破坏 N1 起点（整个 N 的 ORIGIN）
→ 更强的方向破坏确认
```

### 2.5 区间带与强弱

原书 4.4 明确描述：

- N1-N2 是抵抗阶段；
- N1 被突破后形成可作为后续支撑/压力观察的“区间带”；
- 书中把后续表现定性为强、中、弱；
- “该回不回”为最强；
- N2 应流畅，N1 越短越好。

但是原书 **没有给出可直接编码的强/中/弱数值阈值，也没有给出区间带分层比例公式**。

因此 V1 只保留可复算的区间带和原始回踩事实，不机器化强/中/弱标签。

### 2.6 结构

原书 4.1、4.6 明确：

```text
结构至少由 2 个 N 组成

BULL  = 高点和低点逐个抬高
BEAR  = 高点和低点逐个降低
RANGE = 不能持续逐个抬高，也不能持续逐个降低
```

多头结构主要防守“末尾低点”，空头结构主要防守“末尾高点”。末尾低点/高点被严格破坏时，当前结构结束。

### 2.7 V1 明确不包含的原书内容

以下虽然存在于原书，但超出 V1：

```text
N 字递归分型成更大 N
5m → 30m / 更大周期递归结构
K 线合并分型
趋势大分型
KDJ 与 N 字
形态学（M/W/头肩/旗形等）
突破交易模板
仓位、加仓、止盈止损
```

## 3. 归一量化 V1 工程冻结

以下内容属于 **GUIYI_ENGINEERING_V1**。它们是为了把来源思想变成确定、可测试、无未来函数的机器合同。

### 3.1 周期

```text
source_timeframe = 5m only
```

只消费 completed Historical Canonical 5m actual-dominant。

V1 不使用：

```text
1m
15m direction context
30m / 60m
Live Redis Overlay
跨周期分型
```

### 3.2 历史入口

唯一链：

```text
NStructureResearchService
→ MarketDataService.query_actual_dominant_trading_days()
→ Historical Canonical
```

不得：

- 直接读 Parquet；
- 直接读 RQData；
- 读 Redis Live；
- 自己判断 rank1；
- 用自然日时间猜夜盘 Session；
- 跨频 fallback。

### 3.3 Segment 边界

N 字、Swing、Structure 均是 **rank1 contract segment-local**：

```text
same rank1 segment
→ 可跨 trading_day 连续归纳

rank1 segment changed
→ reset unresolved Swing / active N / current Structure
→ 不跨真实合约连接 N 字
```

交易日切换本身不 reset；主力真实合约切换才 reset。

## 4. Exact N Policy

新增 Git-tracked policy：

```text
data/research_policies/n_structure_5m_v1.json
```

Exact identity：

```text
policy_id       = n_structure_5m_v1
formula_version = n_structure_v1
research_only   = true
source_timeframe= 5m
```

同 `policy_id` 内容漂移 fail-closed。任何下面机器语义变化必须产生新的 policy/formula identity，而不是覆盖 V1。

推荐 exact payload：

```json
{
  "schema_version": 1,
  "policy_id": "n_structure_5m_v1",
  "formula_version": "n_structure_v1",
  "research_only": true,
  "source_timeframe": "5m",
  "swing": {
    "breach_basis": "previous_bar_high_low",
    "equal_is_breach": false,
    "outside_bar": "reset_unresolved",
    "inside_bar": "continue_current_or_stay_unresolved",
    "extreme_tie": "keep_first"
  },
  "n_pattern": {
    "completion": "first_strict_n1_extreme_breach",
    "completed_identity_immutable": true,
    "n2_break_is_reversal": false,
    "origin_break_is_stronger_direction_break": true
  },
  "range_band": {
    "definition": "n1_n2_price_span_v1",
    "strong_medium_weak_labels": false
  },
  "structure": {
    "minimum_completed_n": 2,
    "kinds": ["bull", "bear", "range"],
    "defense_break": "strict"
  }
}
```

## 5. Sequential Causal Swing Reducer

### 5.1 核心原则

V1 不复用 `subing_structure.ConfirmedPivot`。

原因：现有 SuBing Pivot 是严格 2-left/2-right、5m-only、带 SuBing 命名和语义；N 字来源采用在线 sequential 归纳，两者不是同一个 primitive。

N 字建立自己的：

```text
NSwingPivot
NSwingTrace
```

但不得因此复制 MarketDataService 或 rank1 resolver。

### 5.2 状态

```text
UNRESOLVED
UP_LEG
DOWN_LEG
```

Reducer 始终只消费当前 prefix：

```python
reduce_n_swings(bars[:i])
```

未来 Bars 不得改变已经 confirmed 的 Pivot。

### 5.3 UNRESOLVED 初始化

Segment 第一根 bar 只建立 unresolved seed，不产生 Pivot。

在 UNRESOLVED：

```text
current.high > previous.high
AND current.low >= previous.low
→ establish UP_LEG

current.low < previous.low
AND current.high <= previous.high
→ establish DOWN_LEG

inside/equal
→ remain UNRESOLVED
```

在 unresolved 期间保存 seed high/low 的第一出现位置，仅用于启动运行极值；不把 seed 自动发布为 confirmed Pivot。

### 5.4 UP_LEG

普通情况：

```text
current.low >= previous.low
→ continue UP_LEG
→ running HIGH 只在 strict higher high 时更新
```

反转：

```text
current.low < previous.low
AND NOT (current.high > previous.high)
→ confirm running HIGH
→ confirmed_at = current.bar_end
→ switch DOWN_LEG
```

### 5.5 DOWN_LEG

对称：

```text
current.high <= previous.high
→ continue DOWN_LEG
→ running LOW 只在 strict lower low 时更新

current.high > previous.high
AND NOT (current.low < previous.low)
→ confirm running LOW
→ switch UP_LEG
```

### 5.6 equal / tie

用户已冻结：

```text
equal high / equal low = 不破
```

运行极值遇到相等值：

```text
price 相等
→ keep first pivot_time
→ 不把 pivot identity 推迟到后面的 tie bar
```

### 5.7 inside bar

如果：

```text
current.high <= previous.high
AND current.low >= previous.low
```

则：

- 已在 UP_LEG：继续 UP_LEG；
- 已在 DOWN_LEG：继续 DOWN_LEG；
- UNRESOLVED：仍 UNRESOLVED。

Inside bar 不产生方向切换。

### 5.8 outside bar

如果：

```text
current.high > previous.high
AND current.low < previous.low
```

OHLC 无法证明 intrabar 先高还是先低。

因此：

```text
AMBIGUOUS_OUTSIDE_BAR_RESET
→ 当前 boundary 不 confirm Pivot
→ 不 confirm / complete N
→ 不改变已发布历史事实
→ active unresolved Swing / active incomplete N reset
→ 以 current bar 作为新的 unresolved seed
```

不得用 close、open、中点、颜色或主观顺序猜测 intrabar path。

## 6. NSwingPivot 合同

建议 immutable contract：

```python
class NSwingPivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True, slots=True)
class NSwingPivot:
    pivot_id: str
    kind: NSwingPivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date
```

硬约束：

- `source_timeframe=M5`；
- `pivot_time < confirmed_at`；
- Decimal finite；
- contract normalized；
- identity 包含 contract + segment start + timeframe + kind + pivot time；
- confirmed 后不可被未来 prefix 改价、改时间或删除。

## 7. N Pattern

### 7.1 点位

V1 使用四个机器点：

```text
ORIGIN
N1_EXTREME
N2_ORIGIN
COMPLETION
```

这四个是工程点名；阶段仍严格叫：

```text
N1
N1_N2
N2
```

### 7.2 UP_N base

从 alternating confirmed pivots 中识别：

```text
LOW(origin)
→ HIGH(n1_extreme)
→ LOW(n2_origin)
```

有效 base：

```text
n2_origin.price >= origin.price
```

这里使用 `>=`，因为原书要求 N1-N2 阶段“没有跌破 N1 起点”；equal 不属于破坏。

### 7.3 DOWN_N base

```text
HIGH(origin)
→ LOW(n1_extreme)
→ HIGH(n2_origin)
```

有效 base：

```text
n2_origin.price <= origin.price
```

### 7.4 incomplete attempt replacement

一个 base 形成后，如果尚未 completion 就确认出新的同侧 Pivot，使最新三 Pivot 已经形成新的候选结构，则旧 incomplete attempt 被内部替换。

V1 不把 failed/incomplete attempt 保存成长期 Candidate event；只允许 research diagnostics 计数。

### 7.5 completion

用户已冻结：**第一次 completed 5m 严格突破 N1_EXTREME 即 causal completion**。

UP_N：

```text
current.high > n1_extreme.price
→ complete UP_N
```

DOWN_N：

```text
current.low < n1_extreme.price
→ complete DOWN_N
```

Equal 不算突破。

Completion 可以发生在确认 N2_ORIGIN 的同一个 completed bar，只要该 bar 本身不是 ambiguous outside bar，且所有信息都在该 boundary 收盘后已知。

### 7.6 immutable identity

Completed N 一旦形成：

- `origin / n1 / n2` 不改；
- `completed_at` 不改；
- `completion_level=n1_extreme.price` 不改；
- 后续创新高/新低不回写“最终 N2 极值”；
- 后续走势只产生新的 assessment/event。

建议：

```python
class NDirection(StrEnum):
    UP = "up"
    DOWN = "down"

@dataclass(frozen=True, slots=True)
class CompletedNPattern:
    n_id: str
    direction: NDirection
    origin: NSwingPivot
    n1_extreme: NSwingPivot
    n2_origin: NSwingPivot
    completed_at: datetime
    completion_level: Decimal
    completion_bar_close: Decimal
    completion_overshoot_bps: Decimal
    range_band: NRangeBand
```

`completion_overshoot_bps` 是研究观察，不参与 N identity。

## 8. N 字破坏事件

用户已冻结：completed N 永久保留；破坏只产生后续 immutable event。

### 8.1 UP_N

```text
current.low < n2_origin.price
→ N2_ORIGIN_BROKEN

current.low < origin.price
→ ORIGIN_BROKEN
```

### 8.2 DOWN_N

```text
current.high > n2_origin.price
→ N2_ORIGIN_BROKEN

current.high > origin.price
→ ORIGIN_BROKEN
```

Equal 不算破坏。

同一 bar 可以同时满足两个 break；两条 immutable event 都保留，当前强状态以 `ORIGIN_BROKEN` 为最高。

`N2_ORIGIN_BROKEN` 不得被命名为 reversal confirmed。

## 9. N1-N2 Range Band V1

### 9.1 来源与工程化边界

原书明确说 N1-N2 是抵抗阶段，并在 N1 突破后形成区间带，但没有机器化边界公式。

归一量化 V1 明确把下面定义标为：

```text
GUIYI_ENGINEERING_N1_N2_SPAN_V1
```

### 9.2 定义

```text
band_lower = min(n1_extreme.price, n2_origin.price)
band_upper = max(n1_extreme.price, n2_origin.price)
```

UP_N 完成后角色：`support_reference`。

DOWN_N 完成后角色：`resistance_reference`。

### 9.3 只输出 raw observation

允许：

```text
band_reentered
first_reentered_at
deepest_reentry_price
n2_origin_broken
origin_broken
completion_close_beyond_level
completion_overshoot_bps
```

禁止 V1 机器输出：

```text
STRONG
MEDIUM
WEAK
```

也不得使用 1/3、1/2、ATR、百分比等未经来源或验证冻结的阈值。

## 10. Structure V1

用户已选择 **N + Structure V1**，不是只做 detector。

### 10.1 Structure kinds

```python
class NStructureKind(StrEnum):
    UNDEFINED = "undefined"
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
```

### 10.2 minimum evidence

Structure classification 只在同一 segment 内至少已经出现：

```text
completed_n_count >= 2
```

并且至少有可比较的最近两个 confirmed HIGH 和最近两个 confirmed LOW。

### 10.3 initial classification

最新两个 confirmed highs：`H_prev, H_curr`

最新两个 confirmed lows：`L_prev, L_curr`

```text
H_curr > H_prev AND L_curr > L_prev
→ BULL

H_curr < H_prev AND L_curr < L_prev
→ BEAR

otherwise
→ RANGE
```

所有比较 strict；equal 不属于逐级抬高/降低。

这条是原书“逐个抬高 / 逐个降低 / 两者都不是”的机器化直接映射。

### 10.4 BULL state

BULL 建立时：

```text
trailing_defense = latest qualifying confirmed LOW
```

只有新的 higher-high + higher-low 组合完成时，`trailing_defense` 才向上移动到新的 confirmed LOW。

在没有 strict break 前，单纯短期回撤或某一高点未创新高不删除 BULL 历史事实。

严格破坏：

```text
current.low < trailing_defense.price
→ BULL_STRUCTURE_BROKEN
→ close current BULL structure
→ current state becomes RANGE pending new directional evidence
```

不在 break bar 自动宣称 BEAR。

### 10.5 BEAR state

完全对称：

```text
trailing_defense = latest qualifying confirmed HIGH

current.high > trailing_defense.price
→ BEAR_STRUCTURE_BROKEN
→ current state becomes RANGE
```

### 10.6 RANGE state

RANGE 无 trailing defense。

当后续最近两个 high/low 同时严格抬高时：

```text
RANGE → BULL
```

同时严格降低时：

```text
RANGE → BEAR
```

### 10.7 immutable history

已经建立、结束的 Structure 不删除。

建议：

```python
@dataclass(frozen=True, slots=True)
class NStructureEpisode:
    structure_id: str
    kind: NStructureKind
    established_at: datetime
    closed_at: datetime | None
    trailing_defense: NSwingPivot | None

@dataclass(frozen=True, slots=True)
class NStructureTransition:
    transition_id: str
    transition_at: datetime
    from_kind: NStructureKind
    to_kind: NStructureKind
    reason_code: str
```

## 11. Prefix invariance / causality

核心不变量：

对于任意 prefix `P` 和未来 suffix `F`：

```text
所有在 P 内已经 confirmed 的 Pivot
所有在 P 内已经 completed 的 N
所有在 P 内已经发生的 N break event
所有在 P 内已经发生的 Structure transition
```

在 `P + F` 中必须保持相同 identity、时间、价格和方向。

允许未来变化的只有：

- unresolved/current leg；
- incomplete N attempt；
- current active range-band assessment；
- current active structure 的 trailing defense 向有利方向推进；
- 新事件追加。

禁止 repaint 已确认历史事实。

## 12. Historical Research Service

新增：

```text
NStructureResearchService
```

Request：

```python
@dataclass(frozen=True, slots=True)
class NStructureResearchRequest:
    since: date
    through: date
    symbol: str | None
```

只调用 `MarketDataService.query_actual_dominant_trading_days()`。

### 12.1 segment warm-up

Window 从某个 rank1 segment 中间开始时，不能从 `since` 零状态启动 Swing。

V1 必须复用/抽取一份最小 `ActualDominantResearchSegmentLoader`：

```text
requested trading-day window
→ discover actual-dominant segments via MarketDataService
→ restore true segment start through MarketDataService / dominant segment identity
→ read causal segment prefix
→ reducer runs from true segment start
→ report only since..through observations
```

该 helper 仍只是 MarketDataService 的 research composition，不是第二历史 Gateway。

由于 SuBing Lifecycle Research 现在也有相同 segment-prefix 需求，第二 producer 出现后，允许把它从 SuBing 私有实现抽成共享 research read helper，并用上游 regression 证明 SuBing 零变化。

## 13. N Research Result

V1 Historical CLI 输出 source facts，建议至少包括：

```text
products
segment_count
evaluable_bar_count
confirmed_pivot_count
ambiguous_outside_reset_count
incomplete_attempt_replaced_count
completed_n_counts: up / down
n_break_counts: n2_origin_broken / origin_broken
range_band_reentry_count
structure_established_counts: bull / bear / range
structure_break_counts: bull / bear
3/5/8 bar price outcome summary at N completion
```

### 13.1 3/5/8 outcome

N completion 是 directional research event。

V1 允许抽取一个 **price-only** 共享 outcome primitive：

```text
PriceDirectionalOutcome
PriceHorizonEvaluation
```

字段：

```text
directional_return_bps
mfe_bps
mae_bps
```

不要求 N Candidate 使用 SuBing 的 EMA21 failure，因为 N Structural Domain 是纯价格结构。

如果从现有 SuBing research outcome 中抽取共享 price-only 计算，必须保持现有 SuBing payload/数值完全不变；SuBing 的 EMA21 failure 继续留在 SuBing-specific projection。

## 14. Read-only CLI

新增：

```text
guiyi research n-structure
  --since YYYY-MM-DD
  --through YYYY-MM-DD
  [--symbol jm]
```

语义：

- Historical-only；
- `readonly=true`；
- 不写 DB/Canonical/Redis；
- 不读 Live；
- 不发通知；
- 不创建 Alert/Execution Review；
- 不输出交易动作。

V1 不新增 HTTP/API/Web；先把结构语义和 evidence 做正确。

## 15. 第二个 Candidate：N Structure Candidate V1

Candidate identity：

```text
candidate_id    = n_structure_5m_candidate_v1
source_kind     = n_structure
policy_id       = n_structure_5m_v1
formula_version = n_structure_v1
research_only   = true
```

新增：

```text
data/research_candidates/n_structure_5m_candidate_v1.json
```

同 Candidate ID 内容漂移 fail-closed。

## 16. N Candidate Validation Protocol

由于 N 字设计在 `2026-08-20 00:22 +08:00` 才最终冻结，而国内期货 `trading_day=2026-08-20` 的夜盘已经在前一日 21:00 开始，因此 V1 不允许把 2026-08-20 trading day 冒充真正 prospective OOS。

Exact protocol：

```text
protocol_id = n_structure_validation_v1
candidate_frozen_at = 2026-08-20T00:22:00+08:00
retrospective = 2023-01-01 .. 2026-08-19
prospective_oos_first_trading_day = 2026-08-21
```

`trading_day=2026-08-20` 是 freeze-overlap / embargo day：

```text
可以作为未来运行时的历史 warm-up
不能算 retrospective
不能算 prospective OOS
```

Rolling historical stability 沿用已经验证的固定协议：

```text
reference = 12 calendar months
test      = 3 calendar months
step      = 3 calendar months
first test= 2024Q1
last test = 2026Q2
10 folds
```

Git-tracked：

```text
data/research_protocols/n_structure_validation_v1.json
```

## 17. Candidate Validation 第二 producer 的最小抽象

当前 Candidate Validation V1 的 report/policy 仍带有 SuBing-specific key 和 identity。这在只有一个 Candidate 时是正确的 YAGNI；N 成为第二个 producer 后，允许抽取 **实际重复的最小共性**。

V1 只抽两类：

### 17.1 Shared validation schedule

抽取：

```text
CandidateValidationRequest
CandidateValidationIdentityError
CandidateValidationWindowError
CandidateValidationSourceError
rolling window generator
prospective pending/evaluated boundary helper
```

要求：

- SuBing Candidate existing report/payload 100% 不变；
- N Candidate 使用自己的 source-specific window/report；
- 不建动态 Strategy Plugin；
- 不建在线 Candidate Registry；
- 不建 DB candidate table。

### 17.2 Shared price outcome

只在实际能保持 SuBing zero-regression 的情况下抽取 price-only return/MFE/MAE primitive。

不强行统一：

```text
SuBing confirmation source
V1/V2 overlap
EMA21 failure
N pivot/N/structure counts
```

这些继续 source-specific。

## 18. N Candidate Report

N-specific report 不假装与 SuBing 字段完全同构。

至少：

```text
schema_version
candidate_id
policy_id
formula_version
protocol_id
research_only
symbol
retrospective
rolling_folds
rolling_stability
prospective_oos
quality_flags
```

每个 N window 至少：

```text
segment_count
evaluable_bar_count
confirmed_pivot_count
completed_n_counts
n_break_counts
range_band_reentry_count
structure_established_counts
structure_break_counts
3/5/8 price horizon summary
```

Stability V1 只做无阈值描述：

```text
fold_count
folds_with_completed_n
completed_n_min
completed_n_max
completed_n_median
```

禁止：

```text
KEEP
DROP
PROMOTE
PASS_STRATEGY
profitability
expected_profit
```

## 19. 第一份真实 evidence

首份 evidence：

```text
candidate = n_structure_5m_candidate_v1
symbol    = jm
protocol  = n_structure_validation_v1
```

第一份 retrospective/rolling baseline 固定：

```text
--through 2026-08-20
```

因为 prospective 从 2026-08-21 才开始，所以该 artifact：

```text
prospective_oos.status = pending
```

建议路径：

```text
reports/research/candidate_validation/
  n_structure_5m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-20.json
```

该报告不能证明策略有效。

## 20. Error / fail-closed

建议稳定错误域：

```text
N_STRUCTURE_POLICY_INVALID
N_STRUCTURE_CONTRACT_INVALID
N_STRUCTURE_SERIES_INVALID
N_STRUCTURE_SOURCE_UNAVAILABLE
N_STRUCTURE_SEGMENT_IDENTITY_INVALID
N_CANDIDATE_MANIFEST_INVALID
N_CANDIDATE_PROTOCOL_INVALID
CANDIDATE_VALIDATION_IDENTITY_MISMATCH
CANDIDATE_VALIDATION_WINDOW_INVALID
CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE
```

以下必须 fail-closed：

- malformed exact policy；
- non-5m input；
- bars 非严格排序；
- contract/segment identity 不一致；
- outside bar 被错误强行裁决；
- candidate/protocol identity drift；
- rank1 / trading calendar / Session / Canonical 不可用；
- prospective 尝试把 2026-08-20 算 OOS；
- partial source failure。

## 21. 测试合同

必须证明：

### 21.1 Swing

- UNRESOLVED 初始化无未来数据；
- UP/DOWN 切换只用 current + previous + prefix state；
- equal 不破；
- equal extreme keep first；
- inside bar 不反转；
- outside bar reset，不产生 Pivot/N；
- segment change reset；
- trading-day change same segment 不 reset；
- prefix invariance。

### 21.2 N

- LOW-HIGH-LOW + `n2>=origin` 可形成 UP base；
- HIGH-LOW-HIGH + `n2<=origin` 可形成 DOWN base；
- first strict N1 breach completion；
- equal N1 不 completion；
- completion identity immutable；
- N2/ORIGIN strict break events；
- N2 break 不自动 reversal；
- post-completion future 不重写 completed N。

### 21.3 Range band

- exact N1-N2 span；
- support/resistance role symmetry；
- raw re-entry only；
- 无 STRONG/MEDIUM/WEAK key。

### 21.4 Structure

- minimum 2 completed N；
- higher-high + higher-low → BULL；
- lower-high + lower-low → BEAR；
- neither → RANGE；
- equal → RANGE/non-directional；
- BULL trailing low only advances after qualifying pair；
- BEAR trailing high symmetric；
- strict defense break closes structure；
- break 后先 RANGE，不自动反手；
- historical episodes/transitions immutable。

### 21.5 Research / Candidate

- only MarketDataService historical path；
- exact trading-day query；
- segment-prefix warm-up；
- SuBing zero regression after shared extraction；
- 10 rolling folds；
- retrospective through 2026-08-19；
- 2026-08-20 excluded from prospective；
- prospective starts 2026-08-21；
- same-prefix determinism；
- CLI readonly；
- no forbidden decision/profit fields。

## 22. Non-goals / YAGNI

N Structural Domain V1 不做：

```text
1m N
15m/30m/60m N
multi-timeframe confirmation
recursive fractal N
K-line merge fractal
strong/medium/weak numerical classifier
parameter optimizer
ATR/ZigZag reversal thresholds
volume/OI as N identity condition
KDJ/MACD confirmation
shape recognition
Web overlay
HTTP N API
Alert Rule
notification
Execution Review integration
DB/Redis persistence
worker/queue/scheduler
account/order/position/cost/PnL/equity
automatic Candidate promotion
JDJ 1m
```

## 23. 架构图

```text
Historical Canonical 5m
        ↑
MarketDataService
        ↑
ActualDominantResearchSegmentLoader
        │
        ├───────────────┐
        ↓               ↓
SuBing Lifecycle    N Structure V1
(existing)          (new)
                        │
                        ├─ Swing
                        ├─ N Pattern
                        ├─ Break / Band raw facts
                        └─ BULL/BEAR/RANGE Structure
                        │
                        ↓
                 NStructureResearchService
                        │
                        ├─ guiyi research n-structure
                        │
                        ↓
                N Candidate Validation
                        │
                        ↓
               versioned research evidence
```

## 24. 实施拆分

Implementation Plan 应拆成以下独立 Gate：

```text
Task 1  Exact N Structure Policy + immutable domain contracts
Task 2  Sequential causal Swing reducer
Task 3  N Pattern completion + immutable break/band facts
Task 4  BULL/BEAR/RANGE Structure reducer + trailing defense
Task 5  Shared actual-dominant research segment loader extraction + SuBing zero regression
Task 6  NStructureResearchService + readonly n-structure CLI + price outcomes
Task 7  Shared Candidate validation schedule extraction + SuBing Candidate zero regression
Task 8  N Candidate/Protocol + N-specific Candidate Validation + CLI dispatch
Task 9  Full causality / prefix / parity / static regression + independent implementation review + develop integration
Task 10 exact-develop real `jm` N baseline + Candidate evidence + independent evidence review + closeout
```

Tasks 1～4 涉及价格结构公式与因果语义，按 Lane 3 处理；只允许在本 Spec/Plan 经人工批准后实现，并要求独立 Review。它们可以在批准后合入 `develop`，但不因此授权 Runtime、Alert、真实写入或 promotion。

Tasks 5～8 为 research/read-only/common engineering：Lane 1/2，仍以 Sol 审查 temporal leakage 与共享抽取。

Task 10 是只读 Historical research，不是 production mutation。

## 25. 完成 Gate

N Structural Domain V1 完成只意味着：

```text
5m causal price structure kernel exists
+ N/Structure Historical research exists
+ second Candidate producer exists
+ jm retrospective/rolling evidence exists
+ prospective boundary frozen correctly
```

不意味着：

```text
N 字有效
N 字可交易
可发第三条 Alert
可修改 SuBing
可 release main/tag
可 Runtime promotion
```

只有后续 prospective OOS、跨窗口稳定性和人工 Review 提供足够证据时，才允许讨论 Candidate promotion。
