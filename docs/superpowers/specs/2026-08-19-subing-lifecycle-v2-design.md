# SuBing Lifecycle V2 设计规格

> 状态：Design Approved
>
> 日期：2026-08-19
>
> 代码基线：`develop@f5330a8e5341480928d5dd4c249e39cb9910fefe`（`main -> develop` 同步完成后的功能基线）
>
> Review 基线：`develop@232cc8614cc2f9b9ae80b0d95c01afa5ecb48943`（仅增加上一版设计草案）
>
> 范围：SuBing 5m / 15m research-only 生命周期。本文不修改 `subing_entry_signal_v1`、Alert、Scope、Clawbot、Execution Review、Data Foundation 或 production Runtime。

## 1. 结论

SuBing V1 继续作为冻结的正式入场观察；V2 在旁边增加一条**纯函数、可复算、research-only** 的生命周期链，回答：

```text
方向形成
→ 准备
→ 触发
→ 确认
→ 延续
→ 退出风险
→ 本轮机会结束
```

V2 不表达真实持仓，不创建 AlertEvent，不发送通知，不写数据库。它的第一目标是产生足够可解释的 Shadow 样本，判断当前 `jm` 长时间零正式 SuBing Event 到底卡在哪一层，而不是直接放松生产 V1。

第二轮 Review 后，首版只保留当前任务必需的最小组件：

```text
existing SuBing Factor / Signal
ConfirmedPivot
BreakoutAssessment
RetestAssessment
LifecycleReducer
LifecycleSnapshot / LifecycleTrace
```

明确不提前建设完整 StructuralRange、N 字、通用 Research Framework、生命周期数据库或在线多 Policy 系统。

## 2. 来源与政策地位

本文区分四类事实：

| 标记 | 含义 |
| --- | --- |
| `EXISTING_ACCEPTED` | 当前仓库和 accepted policy 已冻结的正式语义 |
| `SOURCE_HYPOTHESIS` | 用户交易资料中的研究思想，尚不是正式机器规则 |
| `NEW_DESIGN_PROPOSAL` | 本文为 V2 首版提出的确定性工程合同 |
| `RESEARCH_PENDING` | 有首版 baseline，但有效性必须靠 Shadow / OOS / Walk-forward 再判断 |

`SOURCE_HYPOTHESIS` 包括：大周期定方向、小周期择时；5m/15m 共振；前高/前低突破；突破后约 3 根 K 线确认；回踩不破后二次突破；均线、MACD、成交量、持仓量和上一根 K 高低点用于机会质量或退出观察。

BOLL、MACD 背离和“五项满足三项”保留为来源假设，首版不机器化。

## 3. V1 冻结边界

以下全部保持 `EXISTING_ACCEPTED`，V2 不改变：

```text
SubingFactorResult / SubingSignalEvaluation
calculate_subing_factor_series()
evaluate_subing_signal()
resolve_same_boundary_subing_signals()
accepted calibration: subing_intraday_v1
SubingReadService primary_signal / resolved_signal
subing_entry_signal_v1
Alert Runtime / Alert tables / current Scope
Clawbot notification
1d RESEARCH_PENDING
current-rank1 segment-local / no pre-rank1 warm-up / no cross-roll inheritance
MarketDataService unique Historical Gateway
auto_order=false
```

当前 V1 的正式多头/空头匹配仍要求 primary EMA21 位置、5/10 slope、MACD cross、`volume_ratio_prev >= 3` 和 companion 方向条件全部通过。V2 不改这些条件。

`FORMAL_V1` 定义为当前 `resolved_signal.status == MATCHED`，且**只有它**继续进入现有正式 Alert。

## 4. 计算与数据边界

Lifecycle evaluator 是纯函数：

```text
current-rank1 segment-local completed 5m Bars
+ current-rank1 segment-local completed 15m Bars
+ existing aligned V1 facts
+ exact research Policy
→ SubingLifecycleTrace
```

硬约束：

- evaluator 内无 I/O；
- 不直接读 Parquet、Redis、PostgreSQL 或 RQData；
- Historical 仍只经 `MarketDataService`；
- Live 仍只经现有 completed-Live seam；
- 不写 DB / Redis / Canonical；
- 不依赖上一次 Runtime 内存；
- 相同输入前缀得到相同结果；
- 目标复杂度为单次顺序扫描 `O(n)`。

实现时可从现有 `SubingReadService` 抽取一个**苏冰私有的窄 aligned-input helper/dataclass**，用于复用 current-rank1、segment、5m/15m Bars 和 source facts。首版不要求新增公开 `SubingLifecycleReadService`，也不得形成第二条历史读链。

## 5. 三轴生命周期模型

### Availability

```text
READY
UNAVAILABLE
```

### Direction

```text
LONG
SHORT
NONE
```

### Stage

```text
IDLE
SETUP_ARMED
ENTRY_CONFIRMED
CONTINUATION
EXIT_RISK
CLOSED
```

含义：

- `IDLE`：数据可用，但没有 active opportunity；
- `SETUP_ARMED`：双周期方向环境形成，尚未完成确认；
- `ENTRY_CONFIRMED`：本 boundary 首次确认一个 research opportunity；
- `CONTINUATION`：确认后的核心趋势依据仍在，当前无确认风险；
- `EXIT_RISK`：出现软风险，但尚未硬失效；
- `CLOSED`：本轮 opportunity 明确结束。

`UNAVAILABLE` 不是 stage。数据不可用不能伪造 `EXIT_RISK` 或 `CLOSED`。

## 6. 唯一评价时钟

```text
completed 5m bar_end = 唯一 lifecycle clock
completed 15m       = trend anchor
```

每个真实 completed 5m boundary 最多产生一条顶层 transition。

非 15m boundary 使用当前 5m + 截至该时点最新 completed 15m。

15m boundary 必须等待同一 `bar_end` 的 5m / 15m 都可用，再：

```text
1. 校验 contract / segment identity
2. 更新 completed 15m anchor
3. 评价现有 V1 双周期事实
4. 复用 existing same-boundary resolver
5. 执行一次 lifecycle transition evaluation
```

不得先按 5m 转一次，再按 15m 转一次。

任何需要未来 Bar 才能确认的事实只记录在实际 `confirmed_at`，不得回填到更早的形态时间。

## 7. Direction Context 与 Setup

V2 setup context 复用现有 Factor 和 accepted slope Calibration，不新增 slope 数值。

LONG：5m 和 15m 都满足：

```text
close > EMA21
slope5_bps_per_bar > accepted threshold
slope10_bps_per_bar > 0
```

SHORT 镜像。

双周期数据可用但方向没有共同形成：

```text
availability = READY
direction = NONE
stage = IDLE
```

`SETUP_ARMED`：

```text
availability == READY
AND direction in {LONG, SHORT}
AND 无 active confirmed opportunity
AND 当前尚未完成 FORMAL_V1 或 V2 confirmation
```

MACD cross、volume ratio 和 Pivot Break 属于 trigger/evidence，不属于 Direction Context。

内部进度只保留：

```text
WAITING_TRIGGER
HOLD_CONFIRMING
RETEST_CONFIRMING
```

不增加更多顶层 stage。

## 8. Entry Confirmation

确认来源：

```text
FORMAL_V1
MOMENTUM_HOLD
PIVOT_BREAK_HOLD
PIVOT_RETEST_REBREAK
```

同一 boundary 的 trigger priority：

```text
FORMAL_V1 > PIVOT_BREAK > MACD_CROSS
```

不并行维护结构和动能两套 confirmation state machine。

### 8.1 `FORMAL_V1`

```text
resolved_signal.status == MATCHED
→ ENTRY_CONFIRMED
```

可从 `IDLE` 或 `SETUP_ARMED` 直接发生，并继续由现有 V1 自己决定是否创建 AlertEvent。

如果一个 V2 research opportunity 已经通过其他来源确认，之后同方向 V1 才匹配，只记录 `FORMAL_V1_LATE_MATCH` supporting fact，不创建第二个 lifecycle opportunity。

### 8.2 Persistence Context

Trigger 后不再要求每根 Bar 都保持 setup 时的强 slope5 threshold。

LONG：

```text
5m close > 5m EMA21
5m slope10 > 0
15m close > 15m EMA21
15m slope10 > 0
无 opposite FORMAL_V1
```

SHORT 镜像。

### 8.3 `MOMENTUM_HOLD`

触发：

```text
LONG  → 任一周期 GOLDEN MACD cross
SHORT → 任一周期 DEAD MACD cross
```

触发 Bar 计第 1 根。连续 3 个**可评价** completed 5m boundary 保持 Persistence Context，且触发周期没有明确反向 MACD cross：

```text
ENTRY_CONFIRMED / MOMENTUM_HOLD
```

失败统一关闭为 `MOMENTUM_HOLD_FAILED`。

### 8.4 `PIVOT_BREAK_HOLD`

Confirmed Pivot 被真实 close cross 后，触发 Bar 计第 1 根。

连续 3 个可评价 5m boundary 的 close 保持在 Pivot 突破侧，并保持 Persistence Context：

```text
ENTRY_CONFIRMED / PIVOT_BREAK_HOLD
```

如果在站稳完成前出现合法 retest，**retest 判定优先于 hold_count 推进**，切换 `RETEST_CONFIRMING`。

### 8.5 `PIVOT_RETEST_REBREAK`

首次 Pivot Break 时冻结：

```text
LONG  → rebreak_reference_price = trigger_bar.high
SHORT → rebreak_reference_price = trigger_bar.low
```

合法 retest：

```text
LONG:  low <= bound_reference_price  AND close >= bound_reference_price
SHORT: high >= bound_reference_price AND close <= bound_reference_price
```

Retest Bar 不计入再突破窗口。从下一可评价 5m boundary 起，最多等待 3 根。

LONG 再突破：

```text
previous_close <= rebreak_reference_price
current_close > rebreak_reference_price
current_close >= bound_reference_price
Persistence Context 保持
```

SHORT 镜像。

成功：`ENTRY_CONFIRMED / PIVOT_RETEST_REBREAK`。

超时：`CLOSED / RETEST_REBREAK_TIMEOUT`。

完成 Bar 硬收回原 Pivot 另一侧：`CLOSED / PIVOT_RETEST_INVALIDATED`。

### 8.6 Waiting Trigger

`WAITING_TRIGGER` 不按固定 Bar 数超时；只要双周期 Direction Context 仍成立，就继续等待。

## 9. 成交量与持仓量

V1 的 `volume_ratio_prev >= 3` 保持正式硬条件。

V2 首版只记录 supporting evidence：

```text
volume_ratio_prev
volume_expansion_present
open_interest_delta
open_interest_direction
```

`open_interest_delta = current.open_interest - previous.open_interest`，仅当连续两根 completed 5m Bar 的 OI 均可用时计算；否则 unavailable。首版不设 OI 阈值。

这些证据用于 Shadow 比较，不作为 V2 `ENTRY_CONFIRMED` 的统一门槛。

## 10. Confirmed Pivot

首版只做 5m strict Pivot，不做 StructuralRange / ZigZag。

Policy baseline：

```text
source_timeframe = 5m
left_span = 2
right_span = 2
tie_policy = reject
```

HIGH：

```text
high[i] > high[i-2]
high[i] > high[i-1]
high[i] > high[i+1]
high[i] > high[i+2]
```

LOW 镜像。并列最高/最低不确认 Pivot。

时间：

```text
pivot_time   = 极值 Bar 的 bar_end
confirmed_at = 右侧第 2 根 completed 5m Bar 的 bar_end
```

formal lifecycle 只能在 `confirmed_at` 以后使用 Pivot。Preview 首版不进入 API、Opportunity identity、transition 或 Alert。

参考位：

```text
LONG  → 当前 trading_day 内最近一个 confirmed HIGH Pivot
SHORT → 当前 trading_day 内最近一个 confirmed LOW Pivot
```

且必须 `pivot.confirmed_at < trigger_boundary`；刚在当前 boundary 才确认的 Pivot 不能同 Bar 被声明突破。

`WAITING_TRIGGER` 中候选 Pivot 可以更新；发生 `PIVOT_BREAK` 后：

```text
bound_reference_pivot_id
bound_reference_price
```

永久绑定当前 Opportunity，不得换成后来的 Pivot。

无 Pivot 只让结构路径暂时不可用，不影响 FORMAL_V1 / MOMENTUM_HOLD。

## 11. Breakout / Retest

Breakout 必须是真实 close cross：

```text
LONG:  previous_close <= pivot.price AND current_close > pivot.price
SHORT: previous_close >= pivot.price AND current_close < pivot.price
```

仅 intrabar high/low 刺穿只记 evidence，不开启结构 confirmation。

Retest 使用第 8.5 节定义；首版不增加 ATR / bps 容忍带。

## 12. Trading Day 与 Rank1 Segment

未确认的：

```text
SETUP_ARMED / WAITING_TRIGGER
SETUP_ARMED / HOLD_CONFIRMING
SETUP_ARMED / RETEST_CONFIRMING
```

不跨 `trading_day`。首次遇到下一 `trading_day` 的**可评价** 5m boundary：

```text
CLOSED / UNCONFIRMED_TRADING_DAY_ROLLOVER
```

如果下一交易日首个 boundary 不可用，不产生伪关闭；等到可评价 boundary 再处理。

已确认的：

```text
ENTRY_CONFIRMED
CONTINUATION
EXIT_RISK
```

允许在同一 current-rank1 segment 内跨 trading day，仅记录 `crossed_trading_day=true`。

任何 lifecycle / Pivot / EMA / MACD 都不跨 rank1 segment。新 segment 从 `IDLE` 重新计算，只输出 `boundary_reset=segment_changed`，不在新合约中伪造旧 opportunity 的 `CLOSED`。

## 13. Continuation / Exit Risk / Closed

确认后职责：

```text
15m = trend anchor
5m  = early risk observation
```

`CONTINUATION` 不要求重新 MACD cross、量比 >= 3 或再次 Pivot Break。

### 13.1 5m Lower-TF Risk

候选：

```text
LOWER_TF_EMA21_BREACH
LOWER_TF_SLOPE5_REVERSAL
LOWER_TF_MACD_OPPOSITE_CROSS
LOWER_TF_BOUND_PIVOT_REENTRY
```

单个可评价 5m risk 只进入 `WATCHING`。连续 2 个可评价 5m boundary 存在 lower-TF risk：

```text
EXIT_RISK
```

中间恢复则计数清零。

上一根 K 高低点破坏只保存 supporting evidence，不作为首版硬 risk trigger。

### 13.2 15m Anchor Soft Risk

完成 15m boundary 以下任一项可直接进入 `EXIT_RISK`：

```text
ANCHOR_EMA21_BREACH
ANCHOR_SLOPE5_REVERSAL
ANCHOR_MACD_OPPOSITE_CROSS
TIMEFRAME_ALIGNMENT_LOST
```

### 13.3 Recovery

只在 completed 15m boundary：

```text
无 hard close
15m close 恢复到 EMA21 正确侧
15m slope10 方向仍正确
无 15m opposite MACD cross
当前 5m 无 lower-TF risk
Pivot opportunity 的 15m close 仍在 bound Pivot 正确侧
```

则 `EXIT_RISK → CONTINUATION`。

### 13.4 Hard Close Priority

```text
1. OPPOSITE_FORMAL_V1
2. OPPOSITE_DIRECTION_CONTEXT_CONFIRMED
3. ANCHOR_TREND_BROKEN
4. STRUCTURE_INVALIDATED
```

`OPPOSITE_DIRECTION_CONTEXT_CONFIRMED`：5m + 15m 同时形成完整反向 Direction Context。

`ANCHOR_TREND_BROKEN`：

```text
LONG:  15m close < EMA21 AND 15m slope10 < 0
SHORT: 15m close > EMA21 AND 15m slope10 > 0
```

`STRUCTURE_INVALIDATED` 只用于 Pivot confirmation source：

```text
LONG:  completed 15m close < bound_reference_price
SHORT: completed 15m close > bound_reference_price
```

MACD divergence 首版不实现。

## 14. Reducer Deterministic Priority

每个可评价 completed 5m boundary：

```text
0. 校验 identity / availability
1. 若上一 boundary 为 CLOSED，内部重置为 IDLE
2. 处理 active confirmed opportunity
3. 处理 active SETUP_ARMED opportunity
4. 处理 IDLE
5. assert transition_count <= 1
```

Active confirmed opportunity：

```text
OPPOSITE_FORMAL_V1
→ OPPOSITE_DIRECTION_CONTEXT_CONFIRMED
→ ANCHOR_TREND_BROKEN
→ STRUCTURE_INVALIDATED
→ EXIT_RISK recovery
→ 15m soft risk
→ 5m consecutive risk
→ CONTINUATION
```

Active setup：

```text
FORMAL_V1
→ trading_day rollover
→ direction context invalidation
→ current confirmation success / failure
→ PIVOT_BREAK
→ MACD_CROSS
→ WAITING_TRIGGER
```

IDLE：

```text
FORMAL_V1
→ aligned Direction Context
→ remain IDLE
```

同一 boundary 若旧 opportunity 关闭且相反方向条件也成立，只关闭旧 opportunity；新方向最早下一可评价 5m boundary 创建。

## 15. Unavailable

以下情况 fail-closed：

```text
5m / 15m warm-up 不足
contract / segment mismatch
future companion
stale identity
Live contract mismatch
Calibration invalid / unavailable
Lifecycle Policy invalid / unavailable
```

当前 boundary：

```text
availability = UNAVAILABLE
```

并且不：

- 创建 Opportunity；
- 生成 transition；
- 推进 hold / retest / risk count；
- 触发 trading-day rollover close；
- recovery；
- 伪造 `EXIT_RISK` / `CLOSED`。

Snapshot 保留 `current_opportunity_key`、`last_confirmed_stage`、`last_confirmed_at` 和 `unavailable_reason`。

## 16. Identity 与输出

### Opportunity identity

```text
policy_id
+ symbol
+ contract
+ segment_start_trading_day
+ direction
+ origin_at
```

`origin_at`：首次 `SETUP_ARMED` boundary；若 `IDLE` 直接 FORMAL_V1，则为 confirmed boundary。

Identity 创建后不可修改。

### Transition identity

```text
opportunity_key
+ transition_at
+ to_stage
```

### `SubingLifecycleTrace`

领域层完整结果：

```text
formula_version
policy_id
segment identity
confirmed_pivots
completed_opportunities
confirmed_transitions
current_snapshot
```

用于 prefix-invariance、Shadow 和研究 CLI，不持久化数据库，也不默认进入 HTTP。

### `SubingLifecycleSnapshot`

API/Web 最小投影：

```text
formula_version
policy_id
research_only=true
availability / unavailable_reason
direction / stage
current_opportunity_key
entry_progress
trigger_kind / trigger_timeframe / triggered_at
confirmation_source / confirmed_at
hold_count / hold_required
bound_reference_pivot
current_risk_codes / risk_progress / lower_tf_risk_count
last_confirmed_stage / last_confirmed_at
latest_transition
crossed_trading_day / boundary_reset
formal_v1_matched
```

`lifecycle.research_only` 永远为 `true`，包括 `confirmation_source=FORMAL_V1`。

V2 的 condition evidence 使用独立扩展类型，可记录：

```text
code
state = PASS / FAIL / PENDING / UNAVAILABLE
observed_value: Decimal | None
threshold: Decimal | None
unit: str | None
source_timeframe: 5m / 15m / None
```

V1 `SubingConditionResult` 不修改。

## 17. Research Policy

Policy identity：

```text
subing_lifecycle_v2_research_v1
```

```json
{
  "schema_version": 1,
  "policy_id": "subing_lifecycle_v2_research_v1",
  "formula_version": "subing_lifecycle_v2",
  "research_only": true,
  "supported_timeframes": ["5m", "15m"],
  "clock_timeframe": "5m",
  "trend_anchor_timeframe": "15m",
  "setup": {
    "requires_both_timeframes": true,
    "calibration_id": "subing_intraday_v1"
  },
  "pivot": {
    "source_timeframe": "5m",
    "left_span": 2,
    "right_span": 2,
    "tie_policy": "reject",
    "same_trading_day_only": true,
    "breakout_basis": "close_cross"
  },
  "entry_confirmation": {
    "hold_required_bars": 3,
    "hold_count_includes_trigger_bar": true,
    "retest_rebreak_max_bars": 3,
    "unavailable_boundary_policy": "pause",
    "trigger_priority": ["formal_v1", "pivot_break", "macd_cross"]
  },
  "risk": {
    "lower_tf_consecutive_bars": 2,
    "anchor_soft_risk_immediate": true,
    "recovery_requires_completed_15m": true
  },
  "trading_day": {
    "unconfirmed_setup_cross_trading_day": false,
    "confirmed_opportunity_cross_trading_day": true
  }
}
```

规则：

- Git-tracked，唯一 active research baseline；
- HTTP 不允许动态覆盖；
- 不 hot reload；
- 不写 DB；
- 同 `policy_id` 内容漂移 fail-closed；
- 参数变化创建新 Policy ID；
- 只引用 accepted Calibration ID，不复制 slope threshold 数值。

`setup` 只绑定 `calibration_id`；slope10 方向条件读取该 accepted Calibration，不属于本 Policy 的
exact JSON 字段。

## 18. API / Web / Shadow

现有 `/api/v1/market/research/subing` 保留：

```text
primary
companion
primary_signal
resolved_signal
```

additive 新增 `lifecycle`。

相同 `now`、相同 current-rank1 Bar 前缀下，5m / 15m 请求必须返回相同 lifecycle identity / stage；请求周期差异仍只体现在 existing V1 `primary_signal`。

1d：

```text
lifecycle.availability = UNAVAILABLE
lifecycle.unavailable_reason = SUBING_LIFECYCLE_INTRADAY_ONLY
```

AlertRuntime 不导入 lifecycle evaluator。

Web 使用“准备 / 研究确认 / 延续 / 退出风险 / 已结束”等研究文案；V2 marker 不得使用与正式 V1 买卖信号相同的视觉语义。首版只展示 Confirmed Pivot，不展示 Preview。

Shadow 后续增加只读 `guiyi research subing-lifecycle`，只经 `MarketDataService` 读取 Historical Canonical，按 rank1 segment 独立复算。

最小报告：

```text
funnel: data_ready / direction_aligned / setup_armed / trigger_observed / entry_confirmed
confirmation_source counts
V1/V2 overlap: v1_and_v2 / v2_only / v1_only / v2_to_v1_lead_bars
risk / recovery / close_reason counts
3 / 5 / 8 bar directional return / MFE / MAE / EMA21 failure
```

这些是研究观察，不是账户收益或正式回测结果。

第一轮优先检查 `jm` 零自然 SuBing Event 的漏斗位置，不直接修改 V1 production Rule。

## 19. 因果与测试合同

### Prefix invariance

对任意 cutoff `T`，未来追加 Bars 后，`T` 以前已经 confirmed 的事实不得变化：

- Pivot identity、`pivot_time / confirmed_at / price`；
- Opportunity identity；
- Transition identity；
- `confirmed_at`；
- 已完成 transition / close reason；
- 已关闭 Opportunity 不得重新打开。

允许变化的只有尚未 confirmed 的 Preview / progress 和 `T` 之后的新事实。

### V1 zero regression

必须锁定 existing：

```text
Factor outputs
Signal conditions
same-boundary resolver
SubingReadService primary_signal / resolved_signal
AlertRuntime SuBing behavior
Alert Event / notification behavior
1d RESEARCH_PENDING
```

### Historical / Live consistency

相同 completed Bar 前缀：Canonical-only 与 Historical + completed Live 必须产生相同 lifecycle trace。15m boundary 结果不得依赖 5m/15m 消息到达顺序。

### Required V2 cases

至少覆盖：

- strict HIGH/LOW、tie reject、2-left/2-right、Pivot confirmation delay；
- current confirmation boundary 不得同时 Breakout；
- FORMAL_V1 / MOMENTUM_HOLD / PIVOT_BREAK_HOLD / PIVOT_RETEST_REBREAK；
- trigger priority；
- unavailable pauses all counts；
- unconfirmed trading-day rollover；
- confirmed cross-trading-day；
- one lower-TF risk = WATCHING，two = EXIT_RISK；
- 15m soft risk / recovery；
- all hard close paths；
- one top-level transition per boundary。

## 20. Non-goals 与 YAGNI

首版不做：

```text
修改 subing_entry_signal_v1
扩大 Alert Scope / 新正式 Rule / V2 通知
生命周期 DB / event store / Redis cache / background worker / queue
通用 Strategy Plugin Engine / Rule DAG / Research Platform
第二套 MarketDataService / Parquet direct read
完整 StructuralRange / ZigZag / ATR Pivot
N1/N2/N3/N4
BOLL / MACD divergence / 五项满足三项综合评分
HTTP 动态参数 / 在线多 Policy
cross-roll lifecycle
Preview Pivot 正式消费
账户 / 持仓 / 自动加减仓 / 订单
```

只有真实性能或研究需求出现后，才允许新任务增加缓存、evidence persistence 或新的结构模块。

## 21. 风险与后续验证

- `SETUP_ARMED` 仍可能偏严，因为 5m/15m 都使用 existing accepted slope5 threshold；若 Shadow 证明 direction alignment 极少，只能新建 research Policy 版本研究，不修改 existing Calibration 或同 ID Policy。
- 2-left/2-right Pivot 是 research baseline，可能偏敏感或偏迟；调整必须新 Policy ID。
- 5m risk 可能频繁，因此首版使用连续 2 个可评价 lower-TF risk 或 completed 15m soft risk 才进入 `EXIT_RISK`。
- 已确认 opportunity 允许跨 trading day 可能不符合纯日内习惯；Shadow 必须拆分 same-day / cross-day 样本，但系统不推断真实持仓。

## 22. 实现拆分

后续 implementation plan 应拆成独立可审查任务：

```text
Task 1  Research Policy + immutable lifecycle domain models
Task 2  Confirmed Pivot pure kernel + prefix-invariance
Task 3  Lifecycle reducer: setup / entry / trading-day / identity
Task 4  Continuation / risk / recovery / close
Task 5  narrow aligned-input refactor + lifecycle projection + V1 regression
Task 6  additive API lifecycle snapshot
Task 7  Web lifecycle strip / funnel / research markers
Task 8  read-only Shadow CLI / report
Task 9  jm evidence review
```

Tasks 1–8 不修改 production Alert Rule、Scope、Runtime、Clawbot、DB 或 Canonical。Task 9 如需开发态 Runtime reload 或真实 observation，必须重新取得对应 Gate。

## 23. 最终 Review

第二轮 Review 结论：**设计合理，可以进入 implementation plan。**

理由：

1. V1 正式公式和 Alert 语义完全冻结；
2. V2 是纯函数 read-model，不新增生产状态或数据事实源；
3. 5m clock / 15m anchor、Pivot confirmation 和 prefix-invariance 提供明确因果边界；
4. research confirmation 与正式 V1 Alert 明确隔离；
5. 删除了早期草案中不必要的 `CONTEXT_READY / INVALIDATED / ENDED` 顶层状态和完整 `StructuralRange` 前置设计；
6. 不要求新增公开 Lifecycle service，不建设通用研究框架；
7. 参数只有一个 exact research Policy baseline，避免个人项目出现不必要的在线版本治理；
8. Shadow 漏斗先解释零信号，再决定是否有价值创建后续 V2 Policy 或正式候选。

因此本文件作为 SuBing Lifecycle V2 首版 implementation plan 的唯一设计输入。
