# Newow V1 回归盯盘初心的观察优先范围修正

日期：2026-09-01  
任务：Issue #291  
适用基线：

- `docs/tasks/2026-08-31-newow-independent-strategy-spec.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-spec-review-amendments.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-implementation-plan.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-implementation-plan-review-amendments.md`

> 本文是 Newow V1 的规范性范围修正。与上述文档冲突时，V1 实施以本文为准。旧文档保留为研究蓝图与 Git lineage，不得继续按其完整 16 项程序直接实施。

## 1. 修正结论

Newow 保留为与 SuBing 完全独立的策略产品族，但 V1 的产品目的从：

```text
完整策略状态机
+ 模拟 OPEN / CLOSE
+ Episode
+ Target / Risk
+ 全量形态库
+ Gold Set
+ 平台化 OOS
```

修正为：

```text
可靠扫描
→ 发现值得打开图表的机会
→ 生成简明、可解释的观察理由
→ Market Web 直接复核
→ 用户决定做或不做
```

Newow V1 是观察策略，不是自动交易决策系统，也不是新的通用策略平台。

项目中心保持：

> 自动盯盘，辅助决策。机器负责发现和整理机会，用户负责最终判断和下单。

## 2. 为什么必须修正

旧 Spec 对因果性、物理合约段、期货交易日和 OOS 的设计是正确的，但首版范围过大，价值交付顺序变成：

```text
先建设 Swing / Structure / Pattern / Risk / Execution / Gold / OOS
→ 很晚才进入真实盯盘和提醒
```

这无法优先解决用户当前最重要的问题：

```text
系统是否真的盯住了所有目标品种？
没有消息是没有机会，还是系统失效？
出现机会时，能否及时叫我并说明原因？
```

因此，V1 必须优先完成真实使用闭环，而不是优先完成研究平台完整度。

## 3. 保持不变的决定

以下决定全部保留：

1. Newow 与 SuBing 完全隔离；
2. `newow_trend_v1 @ newow_tf_1d_v1` 当前只消费 completed D1；
3. `newow_range_v1 @ newow_tf_15m_v1` 当前只消费 completed 15m；
4. 当前不使用 W1、D1→15m、5m 或 1m 的隐藏跨周期输入；
5. 未来 60m / D1 扩展使用新的 immutable Timeframe Profile 和独立证据身份；
6. `actual_dominant` 只能通过权威 rank1 物理合约段解析；
7. completed-only、strict-before、future-leak、prefix invariance、batch/incremental parity 和 fail-closed 不降低；
8. Swing、Range、观察状态和结果窗口不得跨物理合约段；
9. Newow 不读取、筛选、继承或修改 SuBing Action、Episode、Snapshot、Alert、Scope 或 Runtime；
10. `auto_order=false`；不建立账户、委托、真实仓位、保证金或自动交易路径；
11. 牛哇手册只作为产品思想和算法假设来源，具体公式仍为 clean-room 定义；
12. 网页精选历史效果不等于已证明盈利。

## 4. V1 产品目标

### 4.1 牛哇趋势策略

只回答：

```text
日线当前是偏多、偏空还是中性？
今天是否刚刚发生趋势状态转换？
是否出现值得复核的整理区突破？
趋势依据是否正在减弱或失效？
```

它不替用户决定真实开仓、加仓、减仓或平仓。

### 4.2 牛哇震荡策略

只回答：

```text
15m 是否存在有效区间？
区间是偏多、偏空还是中性？
价格是否到达顺方向的观察边缘？
偏离或尾部风险是否开始收缩？
区间是否被突破或失效？
```

它不执行区间下沿买入、上沿卖出或自动止损。

### 4.3 用户看到的最小信息

每个观察至少包含：

```text
品种与当前物理主力合约
策略名称与周期
观察方向
发生时间
当前状态
触发原因 2—4 条
关键位置
数据是否完整
[查看图表]
```

示例：

```text
JM 焦煤｜牛哇震荡策略｜15m
偏空区间，上沿观察已确认

原因：
- 15m 区间偏空
- 当前进入区间上沿
- 正偏离开始收缩
- 出现上冲回落

关键位置：区间上沿 / 中轴 / 下沿
```

## 5. V1 统一输出语义

### 5.1 Snapshot，而不是仓位

持续状态只写入：

```text
NewowObservationSnapshot
```

建议字段：

```text
strategy_instance_id
product
physical_contract
segment_id
frequency
bar_end

market_state
observation_state
direction
reason_codes
reason_summary
key_levels
source_completeness
valid
unavailable_reason
```

Snapshot 回答“现在值得怎么看”，不回答“系统持有什么仓位”。

### 5.2 Observation Event，而不是 OPEN / CLOSE

V1 的持久或 Shadow 事件统一为：

```text
NewowObservationEvent
```

事件字段至少包括：

```text
event_id
strategy_instance_id
product
physical_contract
frequency
observation_type
direction
bar_end
first_seen_at
confirmed_at
invalidated_at
reason_codes
key_levels
source_identity
formula_digest
profile_hash
```

V1 禁止产生：

```text
OPEN
CLOSE
ENTRY_PRICE
POSITION
ADD_POSITION
AVERAGE_COST
REALIZED_PNL
```

### 5.3 事件类型

牛哇趋势策略：

```text
TREND_LONG_STARTED
TREND_SHORT_STARTED
TREND_BREAKOUT_LONG
TREND_BREAKOUT_SHORT
TREND_LONG_WEAKENED
TREND_SHORT_WEAKENED
TREND_INVALIDATED
```

牛哇震荡策略：

```text
RANGE_UP_LOWER_EDGE_WATCH
RANGE_DOWN_UPPER_EDGE_WATCH
RANGE_LONG_CONFIRMATION
RANGE_SHORT_CONFIRMATION
RANGE_INVALIDATED
RANGE_RESOLVED_UP
RANGE_RESOLVED_DOWN
```

持续持有状态不每根 Bar 发事件，只更新 Snapshot。Event 只记录 first-seen 的重要状态变化。

### 5.4 去重

事件唯一身份至少绑定：

```text
strategy_instance_id
+ product
+ physical_contract
+ frequency
+ observation_type
+ direction
+ bar_end
```

相同 first-seen 事件不可因后续完整前缀重算而改写或重发。

## 6. V1 最小内核

旧五内核保留为长期研究蓝图，但 V1 只实现以下最小链路：

```text
Completed Bar
→ 基础指标
→ Range / 简单结构
→ Phase Lite
→ Observation Evidence
→ Observation Lifecycle
```

### 6.1 基础指标

保留：

```text
EMA10 / EMA21
EMA21 slope
MACD 12/26/9
ATR14
VolumeRatio20
OIDelta5（可用时）
DeviationATR
Skew60
ExcessKurtosis60
```

### 6.2 Range / 简单结构

V1 保留独立、因果安全的 `range_detector_lux_v1`。

V1 只需要额外的最小结构信息：

```text
最近已确认的同周期高点
最近已确认的同周期低点
是否实体收盘突破冻结边界
是否重新收回边界
```

不在 V1 建设完整 Structure Graph、BOS/CHOCH 网络、支撑压力 Zone 聚类或多形态图谱。

### 6.3 Phase Lite

阶段层只输出可解释统计状态：

```text
BALANCED
EXPANSION_UP
EXPANSION_DOWN
LOWER_EXTREME
LOWER_CONTRACTION
UPPER_EXTREME
UPPER_CONTRACTION
UNAVAILABLE
```

V1 页面和通知禁止直接称为真实“主力吸筹、洗盘、拉高、出货”。可以显示：

```text
下侧极端
下侧风险收缩
多头扩张
上侧风险收缩
```

偏度、峰度和持仓量在 V1 主要用于理由与质量分，不作为唯一开关；数据缺失时必须明确降级或 unavailable，不能填 0。

### 6.4 Key Level Context

旧“目标与风险内核”在 V1 收缩为：

```text
NewowKeyLevelContext
```

只提供：

```text
EMA21
Range upper / middle / lower
最近确认高点 / 低点
突破位
结构失效参考位
```

这些是用户复核线索，不是自动止损指令或模拟成交计划。

### 6.5 Observation Evidence

证据层输出：

```text
direction
quality_score
reason_codes
blockers
key_levels
```

不输出仓位、目标收益、盈亏比或下单数量。

### 6.6 Observation Lifecycle

旧“风险与执行内核”在 V1 替换为：

```text
COLD
READY
ARMED
CONFIRMED
ACTIVE
INVALIDATED
EXPIRED
UNAVAILABLE
```

职责只有：

```text
confirmed_at
first_seen_at
去重
当前是否仍有效
何时失效
是否具备 Shadow / Alert eligibility
```

不模拟真实执行。

## 7. 牛哇趋势 V1 最小规则

旧 Spec 已冻结的趋势带、EMA21、MACD、Range 突破和参与度公式继续作为研究候选，但输出语义改为 Observation。

### 7.1 趋势状态

```text
YELLOW：偏多趋势
BLUE：偏空趋势
NEUTRAL：中性
```

### 7.2 重要观察

`TREND_LONG_STARTED`：

```text
前一状态不是 YELLOW
当前状态为 YELLOW
close > EMA21
EMA21 slope > 0
MACD 为多头方向
```

`TREND_SHORT_STARTED` 完全镜像。

`TREND_BREAKOUT_LONG`：

```text
当前为 YELLOW
实体收盘突破此前已经确认并冻结的 Range 上沿
参与度至少有一项支持
```

`TREND_BREAKOUT_SHORT` 完全镜像。

`TREND_*_WEAKENED`：

```text
趋势仍未完全反转
但 EMA10/21 差值、EMA21 slope 或 MACD 柱连续收缩
```

`TREND_INVALIDATED`：

```text
趋势带反转
或 close 回到 EMA21 反方向并完成确认
```

V1 不计算 A/B 真实仓位、不自动产生 OPEN/CLOSE、不使用固定 Target1/Target2 管理持仓。

## 8. 牛哇震荡 V1 最小规则

### 8.1 区间方向

保持同周期方向偏置：

```text
EMA21 slope
+ 区间形成前推动方向
+ 最近确认高低点结构
```

二取三得到：

```text
RANGE_UP
RANGE_DOWN
RANGE_NEUTRAL
```

纯中性区间只展示，不产生正式观察事件。

### 8.2 边缘观察

`RANGE_UP_LOWER_EDGE_WATCH`：

```text
RangeBias == RANGE_UP
价格进入区间下部
Range 仍 intact
没有反向实体突破
```

`RANGE_DOWN_UPPER_EDGE_WATCH` 完全镜像。

### 8.3 机会确认

多头确认要求下列至少两项：

```text
跌破下沿后实体收回
下侧偏离 / 偏度风险开始收缩
下沿附近出现简单拒绝K线
```

空头镜像。

输出：

```text
RANGE_LONG_CONFIRMATION
RANGE_SHORT_CONFIRMATION
```

它们表示“值得打开图表复核”，不表示系统已经买入或卖出。

### 8.4 失效与解决

```text
反方向有效突破 → RANGE_INVALIDATED
顺方向有效突破 → RANGE_RESOLVED_UP / DOWN
```

震荡观察结束后不会自动创建趋势策略事件；两条策略独立计算。

## 9. 形态范围修正

V1 关键路径不实现完整命名形态库。

### V1 保留

```text
Lux Range / 矩形区间原语
最近确认高低点
实体突破
边界重新收回
简单 PinBar / 吞没作为位置确认
```

### 后移

```text
三角形
楔形
旗形
双顶 / 双底
头肩顶 / 头肩底
杯柄
三重顶底
圆弧
菱形
谐波形态
```

杯柄仍保留在长期研究蓝图中，但不阻塞 Newow V1 盯盘闭环。

## 10. Historical、Shadow 与 Alert 分阶段

### Stage A：Historical / Web

先完成：

```text
历史状态可视化
历史 Observation Event
触发原因
关键位置
图表直达
```

### Stage B：Shadow

active60 静默计算：

```text
不发送通知
记录应处理品种数
实际处理品种数
正常 / 无观察 / unavailable / error
候选事件数量
重复和短期翻转数量
处理延迟
```

### Stage C：真实 Alert

只有同时满足以下条件才允许单独立项：

1. 当前 Market / Alert Runtime 已达到明确 `RUNTIME_READY`；
2. 能稳定区分“无观察”和“系统未处理”；
3. active60 在自然边界完整处理；
4. PushPlus owner canary 和真实送达边界单独验证；
5. Newow Shadow 的日均事件量和重复率可接受；
6. 用户明确批准 Newow Rule、Scope、audience 和 Runtime promotion。

Stage A/B 的完成不自动授权 Stage C。

## 11. V1 成功标准

### 11.1 可靠性优先

```text
应处理品种数
实际完成品种数
无观察品种数
unavailable品种数及原因
error品种数
处理延迟
数据最后更新时间
```

必须可见。

### 11.2 提醒负担

```text
每日候选数
同品种短时重复数
状态来回翻转数
失效前平均持续时间
```

### 11.3 用户价值

Market Web 支持用户对观察添加最小复核标签：

```text
值得看
不值得看
太早
太晚
方向对但位置差
已参与
未参与
```

V1 的首要价值指标是：

```text
有效减少用户盯盘范围
+ 提供足够的第一层判断线索
```

### 11.4 市场结果只作次级研究

允许只读计算：

```text
后续 3 / 5 / 10 根本周期方向
MFE
MAE
多久失效
是否形成顺方向突破
```

不得自动生成 winner、promotion、盈利、可交易或可实盘结论。

## 12. 被本文覆盖的旧实施内容

以下旧任务不再属于 V1 实施前置：

```text
完整 Causal Swing + Structure Graph
完整 Pattern geometry / lifecycle
Target1 / Target2 交易管理
Risk / Execution 仓位状态机
OPEN / CLOSE Action
Episode与模拟持仓
A点 / B点真实加仓语义
人工 200—300 窗口 Pattern Gold Set
完整 Pattern 分族精度体系
平台化 rolling / prospective OOS 基础设施
完整 performance交易统计面
```

这些内容只在 V1 证明观察价值后，按独立 Issue、独立 Candidate 和独立人工 Gate 逐项恢复。

## 13. V1 不得新增的抽象

禁止为了未来扩展建设：

```text
UniversalStrategyAdapter
通用 Opportunity 平台
通用回测 worker / queue
账户 / 订单 / 仓位域
统一策略 DSL
自动 winner / ranking / promotion
自动参数搜索
```

通用性只保留在：

```text
纯指标函数
不可变 Timeframe Profile
Observation Event 合同
相同的 completed-only / segment / snapshot 模式
```

## 14. 修正后的状态

```text
NEWOW_DIRECTION_RETAINED
NEWOW_V1_SCOPE_REDUCED
OBSERVATION_FIRST
SOURCE_IMPLEMENTATION_NOT_STARTED
ALERT_GATE_BLOCKED_BY_RELIABILITY
AUTO_ORDER_FALSE
```

本修正获得独立 Review 和用户批准后，才能按新的最小 Implementation Plan 进入源码实现。