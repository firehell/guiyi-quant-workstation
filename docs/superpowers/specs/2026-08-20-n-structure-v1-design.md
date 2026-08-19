# N 字 Structural Domain V1 设计规格

> 状态：Design approved by user；Planning Review 已收敛 Important findings。本文是 N 字 Structural Domain V1 的设计事实源，不代表策略有效、Candidate 可晋升、Alert Ready 或任何 production 授权。
>
> 日期：2026-08-20
>
> 初始探索基线：`develop@c62376b65b7776da113a2cc21f4db42a84753f69`
>
> 最终 Planning Review 基线：`develop@c4b96177350b33bb59356f76615ad5a05762c327`
>
> 上游阶段：`Candidate Validation V1 / Phase 4B COMPLETE`
>
> 原始研究来源：用户提供的《期货技术教程讲义【L修订打印版】》第四章 4.1～4.6（波动、N 字、强弱/支撑压力、分型、结构阶梯）。

## 1. 结论

下一阶段建立一个独立、research-only、5m-only 的 **N 字 Structural Domain V1**。

它不是“再加一个指标”，而是把原书中的价格波动归纳转换为可因果复算、可做历史验证的结构事实：

```text
completed 5m Historical Canonical
→ sequential causal swing reducer
→ confirmed structural pivots
→ UP_N / DOWN_N
→ causal completion
→ N2_ORIGIN / ORIGIN break facts
→ N1-N2 range-band raw observation
→ BULL / BEAR / RANGE structure
→ trailing structural defense
→ Historical research evidence
→ Candidate Validation
```

V1 的目标不是自动交易，也不是证明 N 字有效，而是建立第二个真实 Candidate producer，使归一量化第一次拥有与 SuBing 独立的纯价格结构研究域。

## 2. 来源事实与工程冻结必须分开

本文使用两类语义：

```text
SOURCE_DERIVED
= 原书第四章明确写出的思想/命名/关系

GUIYI_ENGINEERING_V1
= 原书没有给出程序精确定义时，为了因果、确定性和无重绘而冻结的机器规则
```

任何 `GUIYI_ENGINEERING_V1` 规则都不能在代码、报告或文档中伪称“原书公式”。

## 3. SOURCE_DERIVED：原书明确支持的内容

### 3.1 波动归纳

原书 4.1 明确：

- 连续不破前一根 K 线最低价时，从最低点向最高点归纳；
- 连续不突破前一根 K 线最高价时，从最高点向最低点归纳；
- 每一根 K 线完成收盘后可以继续调整归纳连线；
- N 字是价格波动的最小单元；
- 高低点逐级抬高形成多头结构，逐级降低形成空头结构，两者都不能持续成立则为盘整结构。

### 3.2 N 字只有两种

原书 4.2 只定义：

```text
UP_N   上攻 N
DOWN_N 下杀 N
```

阶段只定义：

```text
N1     = ORIGIN → N1_EXTREME
N1_N2  = N1_EXTREME → N2_ORIGIN（抵抗阶段）
N2     = N2_ORIGIN → N 完成
```

本项目不再使用旧讨论中的“N1/N2/N3/N4 四种 N 或四阶段”简称。

### 3.3 两低一高 / 两高一低

原书 4.3：

```text
UP_N 基础   = 两低一高
DOWN_N 基础 = 两高一低
```

UP_N 的 N1-N2 阶段没有跌破 N1 起点才保留多头基础；DOWN_N 对称。

### 3.4 N 字破坏

原书明确区分：

```text
破坏 N2 起点
→ 当前 N 的延续/分型发生变化
→ 不等于方向已经确认反转

破坏 N1 起点（整个 N 的 ORIGIN）
→ 更强的方向破坏确认
```

### 3.5 区间带与强弱

原书 4.4 明确：

- N1-N2 是抵抗阶段；
- N1 被突破确认后形成后续可观察的支撑/压力“区间带”；
- 原书以强/中/弱定性描述后续表现；
- “该回不回”为最强；
- N2 应流畅，N1 越短越好。

但原书没有给出可直接编码的强/中/弱数值阈值，也没有给出区间带 1/3、1/2、ATR 或百分比分层公式。

因此 V1 只输出可复算的区间带和原始回踩事实，不机器化 `STRONG/MEDIUM/WEAK`。

### 3.6 Structure

原书 4.1、4.6：

```text
Structure 至少由 2 个 N 组成

BULL  = 高点和低点逐个抬高
BEAR  = 高点和低点逐个降低
RANGE = 不能持续逐个抬高，也不能持续逐个降低
```

多头结构主要防守末尾低点，空头结构主要防守末尾高点；防守点被破坏时，原方向结构结束。

### 3.7 本 V1 不实现的原书内容

```text
N 字递归分型成更大 N
5m → 30m / 更大周期递归结构
K 线合并分型
趋势大分型
KDJ 与 N 字
M/W/头肩/旗形等形态
突破交易模板
仓位、加仓、止盈止损
```

这些后续若做，必须另开 Spec。

## 4. GUIYI_ENGINEERING_V1：总边界

### 4.1 Timeframe

```text
source_timeframe = 5m only
```

只消费 completed Historical Canonical 5m actual-dominant。

V1 禁止：

```text
1m
15m direction context
30m / 60m
Live Redis Overlay
multi-timeframe confirmation
recursive fractal
```

### 4.2 唯一历史入口

```text
NStructureResearchService
→ ActualDominantResearchSegmentLoader
→ MarketDataService.query_actual_dominant_trading_days()
→ Historical Canonical
```

不得直接读 Parquet/RQData/Redis，不得自己判断 rank1，不得用自然日时刻猜夜盘 Session，不得跨频 fallback。

### 4.3 Segment-local

Swing、N、Structure 全部绑定真实 rank1 contract segment：

```text
same rank1 segment
→ 可跨 trading_day 连续归纳

rank1 segment changed
→ unresolved Swing / incomplete N / active structure computation 在新 segment 重新开始
→ 不跨真实合约连接 N
```

交易日切换本身不 reset；真实合约 segment 切换才 reset。

## 5. Exact N Policy

Git-tracked：

```text
data/research_policies/n_structure_5m_v1.json
```

Exact payload：

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
    "outside_bar": "reset_unresolved_epoch",
    "inside_bar": "continue_current_or_stay_unresolved",
    "extreme_tie": "keep_first"
  },
  "n_pattern": {
    "base_origin_equal_allowed": true,
    "completion": "first_strict_n1_extreme_breach",
    "same_boundary_completion_break": "record_both_without_intrabar_order_claim",
    "completed_identity_immutable": true,
    "n2_break_is_reversal": false,
    "origin_break_is_stronger_direction_break": true
  },
  "range_band": {
    "definition": "n1_n2_price_span_v1",
    "reentry_starts": "after_completion_boundary",
    "strong_medium_weak_labels": false
  },
  "structure": {
    "minimum_completed_n": 2,
    "kinds": ["bull", "bear", "range"],
    "outside_bar_preserves_active_direction_unless_defense_breaks": true,
    "defense_break": "strict",
    "break_to": "range"
  },
  "outcome": {
    "entry_price": "completion_bar_close",
    "horizons_bars": [3, 5, 8],
    "may_cross_trading_day": true,
    "may_cross_rank1_segment": false
  }
}
```

同 `policy_id` 内容漂移必须 fail-closed。上述机器语义任何实质变化都需要新的 policy/formula identity。

## 6. Sequential Causal Swing Reducer

### 6.1 不复用 SuBing Pivot

现有 `subing_structure.ConfirmedPivot` 是 strict 2-left/2-right、SuBing-specific 的 5m primitive。N 来源采用在线 previous-bar 归纳，因此建立独立：

```text
NSwingPivot
NSwingTrace
```

N 模块不得反向依赖 SuBing 类型。

### 6.2 State

```text
UNRESOLVED
UP_LEG
DOWN_LEG
```

单次遍历，只读当前 prefix。

### 6.3 UNRESOLVED

Segment 第一根 bar 只是 seed，不发布 Pivot。

```text
current.high > previous.high
AND current.low >= previous.low
→ UP_LEG

current.low < previous.low
AND current.high <= previous.high
→ DOWN_LEG

inside/equal
→ stay UNRESOLVED
```

### 6.4 UP_LEG

```text
current.low >= previous.low
→ continue UP_LEG
→ running HIGH 只在 strict higher high 时更新

current.low < previous.low
AND current.high <= previous.high
→ confirm running HIGH
→ confirmed_at = current.bar_end
→ switch DOWN_LEG
→ current.low 成为新 DOWN running low seed
```

### 6.5 DOWN_LEG

完全对称：

```text
current.high <= previous.high
→ continue DOWN_LEG
→ running LOW 只在 strict lower low 时更新

current.high > previous.high
AND current.low >= previous.low
→ confirm running LOW
→ switch UP_LEG
→ current.high 成为新 UP running high seed
```

### 6.6 equal / tie

```text
equal high / equal low = 不破
```

运行极值价格相等时：

```text
keep first pivot_time
```

不把 Pivot identity 推迟到后面的 tie bar。

### 6.7 inside bar

```text
current.high <= previous.high
AND current.low >= previous.low
```

已在方向 leg：保持该 leg；UNRESOLVED：继续 unresolved。Inside bar 不产生方向切换。

### 6.8 outside bar 与 epoch barrier

```text
current.high > previous.high
AND current.low < previous.low
```

OHLC 无法证明 intrabar 先高还是先低，因此：

```text
AMBIGUOUS_OUTSIDE_BAR_RESET
→ 当前 boundary 不 confirm Pivot
→ 当前 boundary 不用于完成新 N
→ unresolved/current leg reset
→ incomplete N attempt reset
→ 以 current bar 作为新 seed
→ swing_epoch += 1
```

`NSwingPivot` 必须携带 `epoch: int`，N 的三个 Pivot 必须属于同一个 epoch；**任何 N 不得跨 outside reset 连接。**

不得用 close/open/中点/K 线颜色猜 intrabar 顺序。

### 6.9 Outside 对已存在 level facts 的影响

Outside ambiguity只影响“先后顺序型”Swing/N completion。

对 bar 开始前已经存在的 immutable N/Structure：

```text
current low/high 是否 strict 穿越既有 N2/ORIGIN/defense level
```

是 path-independent 的 OHLC 事实，因此仍可记录 N break / Structure defense break。

## 7. NSwingPivot 合同

```python
class NSwingPivotKind(StrEnum):
    HIGH = "high"
    LOW = "low"

@dataclass(frozen=True, slots=True)
class NSwingPivot:
    pivot_id: str
    epoch: int
    kind: NSwingPivotKind
    source_timeframe: BarFrequency
    pivot_time: datetime
    confirmed_at: datetime
    price: Decimal
    contract: str
    segment_start_trading_day: date
```

硬约束：

- `epoch >= 0`；
- `source_timeframe=M5`；
- aware `pivot_time < confirmed_at`；
- price 为 finite positive Decimal；
- contract/segment identity 合法；
- `pivot_id` 含 contract + segment start + timeframe + epoch + kind + pivot_time；
- confirmed 后未来 prefix 不可改价、改时、改 epoch 或删除。

## 8. N Pattern

### 8.1 四个机器点与三个来源阶段

机器点：

```text
ORIGIN
N1_EXTREME
N2_ORIGIN
COMPLETION
```

阶段仍只叫：

```text
N1
N1_N2
N2
```

### 8.2 UP_N base

同一 epoch 的 alternating Pivots：

```text
LOW(origin)
→ HIGH(n1_extreme)
→ LOW(n2_origin)
```

有效：

```text
n2_origin.price >= origin.price
```

Equality 允许，因为来源说“没有跌破 N1 起点”。

### 8.3 DOWN_N base

```text
HIGH(origin)
→ LOW(n1_extreme)
→ HIGH(n2_origin)
```

有效：

```text
n2_origin.price <= origin.price
```

### 8.4 reset / replacement

- Outside reset 直接终止 active incomplete attempt；新 epoch 不得连接旧 Pivot。
- 同 epoch 内，如果尚未 completion 又出现更新的合法三 Pivot base，旧 incomplete attempt 只计 `incomplete_attempt_replaced_count`，不保存为长期事件。

### 8.5 completion

用户已确认：第一次 completed 5m strict breach `N1_EXTREME` 即 causal completion。

```text
UP_N   current.high > n1_extreme.price
DOWN_N current.low  < n1_extreme.price
```

Equal 不完成；outside reset boundary 不完成。

Completion 可以发生在确认 N2_ORIGIN 的同一 completed boundary，只要该 boundary 不是 outside reset。

### 8.6 same-boundary completion + break

如果一个**非 outside** completion bar 同时 strict 穿越新 N 自己的 N2_ORIGIN 或 ORIGIN：

```text
1. 仍按 first strict N1 breach 创建 CompletedNPattern
2. 同 `bar_end` 立即记录相应 N2_ORIGIN_BROKEN / ORIGIN_BROKEN event
3. 不声称 intrabar 先完成还是先破坏
4. 两者只表示“截至该 completed boundary，这些价格事实均已发生”
```

这避免利用未知 intrabar 顺序，又不回写“第一根 N1 突破”事实。

### 8.7 immutable completion

```python
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

一旦完成：三个 Pivot、`completed_at`、level、close 不改；future extension 不能回写所谓“最终 N2 极值”。

### 8.8 overshoot exact formula

这是 `GUIYI_ENGINEERING_V1` raw observation，不参与 identity：

```text
UP_N:
(current.high - n1_extreme.price) / n1_extreme.price * 10000

DOWN_N:
(n1_extreme.price - current.low) / n1_extreme.price * 10000
```

使用 finite Decimal；level 必须 > 0。

## 9. N Break Events

### 9.1 UP_N

```text
current.low < n2_origin.price → N2_ORIGIN_BROKEN
current.low < origin.price    → ORIGIN_BROKEN
```

### 9.2 DOWN_N

```text
current.high > n2_origin.price → N2_ORIGIN_BROKEN
current.high > origin.price    → ORIGIN_BROKEN
```

Equal 不算破坏。

同一 boundary 可记录两条 event；固定排序：

```text
N2_ORIGIN_BROKEN
ORIGIN_BROKEN
```

每个 N/kind 最多一次。`N2_ORIGIN_BROKEN` 不得命名 reversal confirmed。

## 10. N1-N2 Range Band V1

原书给出“区间带”概念但没给机器边界，因此明确标记：

```text
GUIYI_ENGINEERING_N1_N2_SPAN_V1
```

### 10.1 exact span

```text
band_lower = min(n1_extreme.price, n2_origin.price)
band_upper = max(n1_extreme.price, n2_origin.price)
```

UP role=`support_reference`；DOWN role=`resistance_reference`。

### 10.2 first re-entry

只从 `bar_end > completed_at` 开始观察；completion bar 自己不算 re-entry。

```text
UP_N   current.low  <= band_upper → first re-entry
DOWN_N current.high >= band_lower → first re-entry
```

Re-entry 的 equality 是 touch，不是 break，因此允许 `<= / >=`。

首次 re-entry 记录 immutable event；后续可在 current research snapshot 继续计算 deepest reentry，但不得回写 first event identity。

### 10.3 禁止分类

V1 不输出：

```text
STRONG
MEDIUM
WEAK
```

不引入 1/3、1/2、ATR、百分比等阈值。

## 11. Structure V1

### 11.1 kinds

```text
UNDEFINED
BULL
BEAR
RANGE
```

### 11.2 structure evidence epoch

新 directional structure 的建立/重新建立必须只使用同一个 current `swing_epoch` 的证据：

```text
completed_n_in_epoch >= 2
+ 两个可比较 confirmed HIGH
+ 两个可比较 confirmed LOW
```

Outside reset 不允许把 pre-reset Pivot 与 post-reset Pivot 拼成一个新的 N/Structure establishment evidence pair。

### 11.3 initial / RANGE classification

同 epoch 最新两 HIGH：`H_prev,H_curr`；最新两 LOW：`L_prev,L_curr`。

```text
H_curr > H_prev AND L_curr > L_prev → BULL
H_curr < H_prev AND L_curr < L_prev → BEAR
otherwise                            → RANGE
```

全部 strict；任一 equality 都不算方向推进。

### 11.4 BULL

建立时：

```text
trailing_defense = latest qualifying LOW
```

只有新的 same-epoch higher-high + higher-low qualifying pair 完成时，defense 才推进到新的 confirmed LOW。

```text
current.low < trailing_defense.price
→ BULL_STRUCTURE_BROKEN
→ RANGE
```

Equal 不破；break bar 不自动 BEAR。

### 11.5 BEAR

对称：

```text
trailing_defense = latest qualifying HIGH
current.high > trailing_defense.price
→ BEAR_STRUCTURE_BROKEN
→ RANGE
```

### 11.6 outside reset while directional structure is active

Outside reset 本身不因“路径不明”自动删除已建立 BULL/BEAR。

顺序：

1. 先用 current high/low 检查已有 trailing defense；若 strict break，directional structure → RANGE；
2. 无 defense break，则保留 active directional structure；
3. swing epoch reset，post-reset Pivot 不可与 pre-reset Pivot 拼成新的 defense-advance pair；
4. 只有 post-reset epoch 自己形成足够的 same-direction qualifying evidence，才允许 future defense advance；
5. opposite-looking post-reset pivots不能在 defense 未破时直接自动反转现有 directional structure。

### 11.7 immutable history

使用 snapshot + transition，不用“未来修改一个 Episode 对象”：

```python
@dataclass(frozen=True, slots=True)
class NStructureSnapshot:
    observed_at: datetime
    epoch: int
    kind: NStructureKind
    established_at: datetime | None
    trailing_defense: NSwingPivot | None
    completed_n_count_in_epoch: int

@dataclass(frozen=True, slots=True)
class NStructureTransition:
    transition_id: str
    transition_at: datetime
    from_kind: NStructureKind
    to_kind: NStructureKind
    reason_code: str
    trailing_defense_pivot_id: str | None
```

Historical snapshot/transition 不回写；新的 boundary 追加新 snapshot/event。

## 12. Boundary Evaluation Order

每根 completed bar 的固定顺序：

```text
1. 对 bar 开始前已存在的 Completed N 检查 N2/ORIGIN strict level break
2. 对 bar 开始前已存在的 directional Structure 检查 trailing defense strict break
3. 执行 Swing reducer boundary
   - outside → reset epoch，不 confirm Pivot/N
4. 消费本 boundary 新 confirmed Pivot
5. 更新/替换 incomplete N base
6. 若本 boundary strict breach N1，创建新 Completed N
7. 对“本 boundary 新完成的 N”立即检查同-boundary N2/ORIGIN break，允许同 timestamp 记录
8. 从 next boundary 起观察 Range Band first re-entry
9. 基于 same-epoch completed-N + Pivot evidence 建立/推进 Structure
10. append immutable snapshot/transition/event
```

不得调整成需要 intrabar ordering 的算法。

## 13. Prefix Invariance

对于任意 prefix `P` 与 suffix `F`：

```text
P 内已 confirmed Pivot
P 内已 Completed N
P 内已 N break/re-entry event
P 内已 Structure transition/snapshot
```

在 `P+F` 中必须保持相同 identity、时间、价格、epoch、方向和原因。

允许未来变化的只有：

- unresolved/current leg；
- incomplete N attempt；
- active range-band current assessment（非 first immutable event）；
- active structure 后续新的 defense snapshot；
- 新事实追加。

## 14. Shared Actual-Dominant Research Segment Loader

第二个 producer 出现后，允许把 SuBing 当前私有的“probe requested window → restore true rank1 segment → read true segment prefix”抽成：

```text
ActualDominantResearchSegmentLoader
```

唯一依赖仍是 MarketDataService public methods：

```text
query_actual_dominant_trading_days
dominant_segment_for_day
```

职责：

```text
requested trading-day window
→ exact actual-dominant probe
→ restore containing true rank1 segment identity
→ read from true first segment start to requested through
→ validate cross-frequency segment consistency when multiple frequencies requested
→ return full causal prefix + segment identities
```

不得 import Catalog/store/RQData/Redis；SuBing 必须 zero regression。

## 15. NStructureResearchService

```python
@dataclass(frozen=True, slots=True)
class NStructureResearchRequest:
    since: date
    through: date
    symbol: str | None
```

每个 true segment 只跑一次 N kernel；Reducer 从 segment true start warm-up，但 report 只统计 `since..through` 内事实。

至少输出：

```text
products
segment_count
evaluable_bar_count
confirmed_pivot_count
ambiguous_outside_reset_count
incomplete_attempt_replaced_count
completed_n_counts: up/down
n_break_counts: n2_origin_broken/origin_broken
range_band_reentry_count
structure_established_counts: bull/bear/range
structure_break_counts: bull/bear
3/5/8 price horizon summary at N completion
```

## 16. Price-Only Outcome

N completion 是 directional research event；entry timestamp=`completed_at`，entry price=`completion_bar_close`。

共享 primitive：

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

### 16.1 exact price formulas

LONG：

```text
return = (future_final_close - entry_close) / entry_close * 10000
mfe    = (max(future_high) - entry_close) / entry_close * 10000
mae    = (min(future_low) - entry_close) / entry_close * 10000
```

SHORT：

```text
return = (entry_close - future_final_close) / entry_close * 10000
mfe    = (entry_close - min(future_low)) / entry_close * 10000
mae    = (entry_close - max(future_high)) / entry_close * 10000
```

### 16.2 N horizon boundary

N Structure 可以跨 trading day，因此 3/5/8 future bars：

```text
may cross trading_day = true
may cross rank1 segment = false
```

不足 horizon 或即将跨 segment → 해당 outcome=None。

### 16.3 SuBing zero regression

现有 SuBing 的：

```text
factor availability/alignment checks
same-trading-day rule for 5m/15m
EMA21 failure
```

保持不变。只有在旧 SuBing 校验已经接受 future bars 后，才可复用共享 price arithmetic。

## 17. Read-only CLI

新增：

```text
guiyi research n-structure
  --since YYYY-MM-DD
  --through YYYY-MM-DD
  [--symbol jm]
```

只读 Historical research；`readonly=true`；不写 DB/Canonical/Redis，不读 Live，不通知，不创建 Alert/Execution Review，不输出交易动作。

V1 不新增 HTTP/API/Web。

## 18. 第二个 Candidate

Exact Candidate：

```json
{
  "schema_version": 1,
  "candidate_id": "n_structure_5m_candidate_v1",
  "source_kind": "n_structure",
  "policy_id": "n_structure_5m_v1",
  "formula_version": "n_structure_v1",
  "research_only": true
}
```

Git-tracked：

```text
data/research_candidates/n_structure_5m_candidate_v1.json
```

## 19. N Candidate Validation Protocol

用户在 `2026-08-20 00:22 +08:00` 明确授权后续推荐语义一次性完成；当时 `trading_day=2026-08-20` 的夜盘已经于前一日 21:00 开始。因此整个 2026-08-20 trading day 必须 embargo。

Exact protocol：

```json
{
  "schema_version": 1,
  "protocol_id": "n_structure_validation_v1",
  "research_only": true,
  "candidate_frozen_at": "2026-08-20T00:22:00+08:00",
  "retrospective": {
    "since": "2023-01-01",
    "through": "2026-08-19"
  },
  "embargo_trading_days": ["2026-08-20"],
  "rolling_stability": {
    "reference_months": 12,
    "test_months": 3,
    "step_months": 3,
    "first_test_since": "2024-01-01",
    "last_test_through": "2026-06-30"
  },
  "prospective_oos": {
    "first_trading_day": "2026-08-21"
  },
  "horizons_bars": [3, 5, 8]
}
```

Git-tracked：

```text
data/research_protocols/n_structure_validation_v1.json
```

语义：

```text
2023-01-01..2026-08-19 = retrospective
2026-08-20             = embargo/warm-up only
>=2026-08-21            = true prospective OOS eligible
```

2026-08-20 绝不能被 retrospective 或 prospective report window 计入。

Rolling 固定 12m reference + 3m test + 3m step，首 test=2024Q1，末 test=2026Q2，共 10 folds。

## 20. Candidate Validation 第二 producer 的最小抽象

当前 Candidate Validation 是合理的 SuBing-first 实现。第二 producer 出现后只抽真实共性：

### 20.1 Shared schedule

```text
CandidateValidationRequest
CandidateValidationIdentityError
CandidateValidationWindowError
CandidateValidationSourceError
RollingValidationWindow
rolling month generator
prospective pending/evaluated helper
```

SuBing existing report/payload 100% 不变。

### 20.2 Source-specific reports

不得强行统一：

```text
SuBing confirmation source / V1-V2 overlap / EMA21
N Swing / N / Structure counts
```

N 使用自己的 `NCandidateWindowResult` / report；不建 Strategy Plugin、动态 Registry 或 DB candidate table。

## 21. N Candidate Report

Top-level：

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

N window 至少：

```text
segment_count
evaluable_bar_count
confirmed_pivot_count
completed_n_counts
n_break_counts
range_band_reentry_count
structure_established_counts
structure_break_counts
3/5/8 PriceHorizonEvaluation
```

Stability 只做无阈值描述：

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
account_return
```

## 22. 第一份 evidence

```text
candidate = n_structure_5m_candidate_v1
protocol  = n_structure_validation_v1
symbol    = jm
--through = 2026-08-20
```

因为 prospective 从 2026-08-21 开始：

```text
prospective_oos.status = pending
```

Artifact：

```text
reports/research/candidate_validation/
  n_structure_5m_candidate_v1/
    jm-retrospective-baseline-freeze-2026-08-20.json
```

该报告不得把 2026-08-20 放进 retrospective/prospective metrics，也不能证明策略有效。

## 23. Error / fail-closed

稳定域：

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

必须 fail-closed：

- exact policy malformed/drift；
- non-5m input；
- bars 非严格排序；
- contract/segment identity 不一致；
- outside bar 被强行裁决；
- N 跨 outside epoch；
- N/Candidate/Protocol identity drift；
- rank1/calendar/Session/Canonical 不可用；
- prospective 把 2026-08-20 算 OOS；
- partial source success；
- Decimal 非 finite/entry price <=0。

## 24. 测试合同

### 24.1 Swing

必须证明：

- UNRESOLVED 无未来数据；
- UP/DOWN 只用 previous/current/prefix state；
- equal 不破；
- equal extreme keep first；
- inside 不反转；
- outside reset epoch、不产生 Pivot/N completion；
- N 不跨 epoch；
- trading-day change same segment 不 reset；
- rank1 segment reset；
- prefix invariance。

### 24.2 N

- LOW-HIGH-LOW + `n2>=origin` UP base；
- HIGH-LOW-HIGH + `n2<=origin` DOWN base；
- first strict N1 breach completion；
- equal N1 no completion；
- same-boundary completion+break 记录边界事实但不声称 intrabar 顺序；
- overshoot exact Decimal formula；
- completion identity immutable；
- N2/ORIGIN strict event once；
- N2 break 不自动 reversal；
- future 不回写 completed N。

### 24.3 Range Band

- exact N1-N2 span；
- UP support / DOWN resistance symmetry；
- re-entry 只从 completion 后下一 boundary 开始；
- touch equality 可算 re-entry；
- 无 STRONG/MEDIUM/WEAK key。

### 24.4 Structure

- minimum 2 completed N in same evidence epoch；
- strict HH+HL → BULL；LH+LL → BEAR；otherwise RANGE；
- equal non-directional；
- trailing defense 只由 qualifying pair 推进；
- strict defense break → RANGE；
- break 不自动反手；
- outside 可 path-independently break defense；
- outside 未破 defense 时保留 active direction，但不跨 epoch 拼新 pair；
- historical snapshot/transition immutable；
- prefix invariance。

### 24.5 Research/Candidate

- MarketDataService 唯一 Historical path；
- exact trading-day query；
- true segment prefix warm-up；
- SuBing segment loader zero regression；
- N outcomes 可跨 trading day、不可跨 segment；
- SuBing same-day/EMA21 zero regression；
- shared Candidate schedule 不改变 SuBing payload；
- N retrospective through 2026-08-19；
- 2026-08-20 embargo；
- prospective starts 2026-08-21；
- 10 rolling folds；
- same-prefix determinism；
- CLI readonly；
- no decision/profit fields。

## 25. Non-goals / YAGNI

```text
1m N
15m/30m/60m N
multi-timeframe confirmation
recursive fractal N
K-line merge fractal
strong/medium/weak numerical classifier
parameter optimizer
ATR/ZigZag reversal threshold
volume/OI as N identity condition
KDJ/MACD confirmation
shape recognition
Web overlay
HTTP N API
Alert Rule / Scope / notification
Execution Review integration
DB/Redis persistence
worker/queue/scheduler
account/order/position/cost/PnL/equity
automatic Candidate promotion
JDJ 1m
```

## 26. 架构

```text
Historical Canonical 5m
        ↑
MarketDataService
        ↑
ActualDominantResearchSegmentLoader
        │
        ├────────────────┐
        ↓                ↓
SuBing Lifecycle     N Structure V1
(existing)           Swing(epoch)
                     → N Pattern
                     → Break/Band raw facts
                     → BULL/BEAR/RANGE
                          │
                          ↓
                NStructureResearchService
                          │
                    guiyi research n-structure
                          │
                          ↓
                  N Candidate Validation
                          │
                          ↓
                 versioned evidence
```

## 27. Implementation Tasks

```text
Task 1  Exact N Structure Policy
Task 2  Sequential causal Swing reducer + epoch barrier
Task 3  N completion + same-boundary break + Range Band facts
Task 4  BULL/BEAR/RANGE Structure + trailing defense
Task 5  Shared actual-dominant research segment loader + SuBing zero regression
Task 6  Price-only outcomes + NStructureResearchService + readonly n-structure CLI
Task 7  Shared Candidate validation schedule + SuBing Candidate zero regression
Task 8  N Candidate/Protocol + N-specific Candidate Validation + CLI routing
Task 9  Full causality/prefix/static regression + independent implementation Review + develop closeout
Task 10 exact-develop real jm N baseline + Candidate evidence + independent Evidence Review
```

Tasks 1～4 是价格结构公式/因果可信语义，Lane 3；本 Spec/Plan 的 docs merge 不授权实现，实施前仍需用户批准 Lane 3 Plan。Tasks 5～8 是 research/shared engineering，仍不得推导 production 权限。Task 10 是只读 Historical research。

## 28. Planning Review Findings 已处理

本轮 Planning Review 修正：

1. outside reset 新增 `swing_epoch` barrier，N/新 Structure establishment 不得跨 ambiguous reset 拼接；
2. outside ambiguity 与“已存在 level breach”分开，已有 N/Structure level crossing 仍可记录；
3. 新 N completion 与自身 N2/ORIGIN 同 boundary crossing 定义为并列 boundary facts，不声称 intrabar 先后；
4. `completion_overshoot_bps` 补精确公式；
5. Range Band first re-entry 补 exact touch 规则并排除 completion bar；
6. Structure 改用 immutable snapshot/transition，明确 outside 后 active direction 与 evidence epoch 关系；
7. N 3/5/8 outcome 明确可跨 trading day、禁止跨 rank1 segment，同时保持 SuBing same-day zero regression；
8. N Candidate Protocol 增加 exact `embargo_trading_days=[2026-08-20]`。

## 29. 完成 Gate

N Structural Domain V1 完成只意味着：

```text
5m causal price structure kernel exists
+ Historical N/Structure research exists
+ second Candidate producer exists
+ jm retrospective/rolling evidence exists
+ prospective boundary frozen correctly
```

不意味着：

```text
N 字有效 / 可交易
第三条 Alert Rule ready
Candidate 可自动晋升
允许 release main/tag
允许 Runtime promotion
```

只有后续 prospective OOS、稳定性和人工 Review 提供足够证据时，才允许讨论 promotion。
