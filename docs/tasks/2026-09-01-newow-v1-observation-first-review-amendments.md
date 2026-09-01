# Newow V1 观察优先规范性自审修正

日期：2026-09-01  
任务：Issue #291  
基线：

- `docs/tasks/2026-09-01-newow-v1-observation-first-scope-correction.md`
- `docs/tasks/2026-09-01-newow-v1-observation-first-implementation-plan.md`

> 本文是上述两份文档的规范性组成部分。发生冲突时，以本文为准。

## 1. Observation Event 必须不可变

主范围文档中 `NewowObservationEvent` 的建议字段包含 `invalidated_at`，这会诱导实现后续更新已经持久化的 first-seen Event，与不可变事件合同冲突。

V1 固定为：

```text
NewowObservationEvent 不包含可后写的 invalidated_at
```

失效必须生成新的独立事件：

```text
TREND_INVALIDATED
RANGE_INVALIDATED
RANGE_RESOLVED_UP
RANGE_RESOLVED_DOWN
```

新事件通过下列字段关联原观察：

```text
related_event_id
related_observation_key
```

原 first-seen Event 永远不修改、不删除、不重写方向或原因。当前是否仍有效只由最新 `NewowObservationSnapshot` 表达。

## 2. Event 只在状态转换时产生

以下状态持续存在时，不得每根 Bar 重复产生 Event：

```text
TREND_LONG_WEAKENED
TREND_SHORT_WEAKENED
RANGE_UP_LOWER_EDGE_WATCH
RANGE_DOWN_UPPER_EDGE_WATCH
```

事件只在：

```text
上一 Lifecycle 状态 != 当前目标状态
AND 当前条件首次成立
```

时产生一次。

条件持续期间只更新 Snapshot；条件先失效、后再次经过新的合法状态转换成立时，才允许形成新的 Event。

## 3. 最小因果高低点原语必须先冻结

V1 不建设完整 Swing / Structure Graph，但趋势和震荡仍引用“最近已确认高点/低点”。因此 N1b 必须实现一个最小纯 Kernel：

```text
CausalExtremeLite
```

固定参数由 Timeframe Profile 提供，V1 默认：

```text
reversal_atr = 1.0
min_leg_bars = 3
atr_period = 14
```

上升腿：

```text
持续跟踪最高 high、其 bar_end 与当时 ATR
当 completed close <= extreme_high - reversal_atr × atr_at_extreme
且 leg_bars >= min_leg_bars
→ 确认最近高点
```

下降腿完全镜像：

```text
completed close >= extreme_low + reversal_atr × atr_at_extreme
且 leg_bars >= min_leg_bars
→ 确认最近低点
```

输出必须区分：

```text
pivot_at
confirmed_at
price
kind
segment_id
```

它只提供最近确认高低点和简单 HH/HL/LH/LL 比较，不提供：

```text
Structure Graph
BOS/CHOCH网络
Zone聚类
形态枚举
```

任何策略只能从 `confirmed_at` 之后使用该极值。

## 4. 参与度 Gate 固定

趋势突破观察的参与度支持固定为：

```text
VolumeRatio20 >= 1.20
OR
(open_interest 可用 AND OIDelta5 > 0)
```

若成交量不可用，且 OI 也不可用或无支持：

```text
PARTICIPATION_UNAVAILABLE_OR_UNSUPPORTED
```

不得产生 `TREND_BREAKOUT_LONG/SHORT` first-seen Event，但仍可在 Snapshot 中显示“价格已突破、参与度未确认”。

OI 缺失不填 0、不前向填充、不跨物理合约段读取。

## 5. Key Level 不是自动止损

`NewowKeyLevelContext.structural_invalidation_reference` 只表示用户复核参考位置。

V1 页面、API 和通知文案不得称其为：

```text
系统止损
自动止损价
必须平仓价
```

允许表述：

```text
结构失效参考
区间失效参考
最近确认高/低点
```

## 6. Shadow 实际启用仍是 Runtime Gate

Task N5 可以实现和测试 Shadow 代码，但以下行为属于受控 Runtime 操作：

```text
安装或修改 launchd
持续启用 active60 Shadow
写生产 Redis / Runtime 状态
真实定时执行
```

代码合入 `develop` 不授权实际启用。

N5 实际启用前必须重新取得：

```text
目标机器
exact tag / commit
服务范围
写入位置
单次 Runtime promotion 意图
```

当前 `STATUS.md` 不是 `RUNTIME_READY` 时，禁止借 Newow 任务顺便切换或修复 Runtime。

## 7. 用户反馈不能改写策略事实

Task N6 的用户标签是独立 research feedback：

```text
feedback_id
observation_event_id
label
created_at
optional_note
```

反馈不得更新：

```text
Observation Event
Snapshot历史
公式参数
Candidate状态
```

V1 默认不引入 production PostgreSQL migration。若后续需要数据库持久化，必须单独建立 Lane 3 migration 任务和真实写入 Gate。

## 8. 最小 Outcome 不等于 OOS

N6 的 3/5/10 或 3/5/8 Bar 结果只能称为：

```text
retrospective observation outcome
```

不得称为：

```text
OOS
walk-forward
prospective evidence
盈利验证
```

正式 OOS 仍属于 V1 之后的独立 Candidate / Protocol 任务，必须冻结公式、cohort、窗口和起始交易日后自然积累，retrospective 不得回填。

## 9. P0 与 Newow 源码可以并行，但 Alert 不能越过 P0

当前 Runtime/Alert 可靠性修复是最高产品优先级。

允许：

```text
P0可靠性任务
与
N1—N4离线Historical/Web任务
并行推进
```

禁止：

```text
以Newow Historical通过
替代Runtime readiness
```

Newow 真实通知仍必须等待 P0、N5、N6 和独立 N7 Gate 全部满足。

## 10. Formula 与产品文案分离

V1 内部保留：

```text
YELLOW
BLUE
LOWER_CONTRACTION
UPPER_CONTRACTION
```

外部中文文案应优先表达：

```text
偏多趋势
偏空趋势
下侧风险收缩
上侧风险收缩
```

不得把统计状态直接宣传为：

```text
主力吸筹完成
主力正在出货
精准买点
精准卖点
高胜率交易
```

## 11. 修正后的第一实施入口

本次文档通过 Review 后：

```text
先执行 N0 文档权威收口
然后并行准备：
- N1a range_detector_lux_v1
- N1b Observation Contracts + CausalExtremeLite
```

不得从旧计划直接启动完整 Pattern、Execution、Episode、Gold Set 或 OOS 任务。

## 12. Review 结论

```text
SCOPE_COHERENT
EVENT_IMMUTABILITY_FIXED
MINIMAL_EXTREME_DEFINED
RUNTIME_GATE_RESTORED
OOS_WORDING_FIXED
SOURCE_IMPLEMENTATION_NOT_STARTED
```
