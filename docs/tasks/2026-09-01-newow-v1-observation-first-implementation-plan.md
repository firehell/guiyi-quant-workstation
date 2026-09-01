# Newow V1 观察优先 Implementation Plan

日期：2026-09-01  
任务：Issue #291  
规范依据：

- `docs/tasks/2026-09-01-newow-v1-observation-first-scope-correction.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-spec.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-spec-review-amendments.md`

> 本计划取代 `2026-08-31-newow-independent-strategy-implementation-plan*` 作为 Newow V1 的实施顺序。旧计划保留为长期研究蓝图，不得按原 16 项程序直接启动。

## 1. 实施目标

V1 只交付一个最小闭环：

```text
可信行情
→ 牛哇趋势 / 震荡观察
→ 简明理由与关键位置
→ Historical + Shadow
→ Market Web 复核
→ 用户反馈
```

真实通知属于后续独立 Gate，不是 V1 源码完成的自动结果。

## 2. 总体开发顺序

```text
P0  现有 Runtime / Alert 可靠性修复与自然 evidence
     └─ 不由 Newow 任务顺便处理，但阻塞 Newow 真实通知

N0  权威修正与旧计划收口
N1  Range Detector + Observation Contracts
N2  牛哇趋势 D1 最小观察器
N3  牛哇震荡 15m 最小观察器
N4  Historical Snapshot + Read-only API + Market Web
N5  active60 Shadow + 覆盖与延迟可观测性
N6  用户复核标签 + 最小结果研究
N7  Newow Alert 独立 Gate（V1 后置）

Later
  完整形态库 / Swing Graph / Target-Risk / Gold Set / 平台化 OOS
```

N2 与 N3 可在 N1 完成后并行；N4 等待两者的公共合同稳定。N7 必须等待 P0、N5、N6 和单独人工批准。

## 3. Task 边界总表

| Task | Lane | 主要交付 | 明确不做 |
|---|---|---|---|
| N0 | Lane 2 docs | 新规范生效、旧计划标记 superseded | 不改源码 |
| N1a | Lane 3 | `range_detector_lux_v1` 共享纯 Kernel | 不接策略/Alert |
| N1b | Lane 3 | Profile、Snapshot、Observation Event、Lifecycle 合同 | 不建 OPEN/CLOSE/Episode |
| N2 | Lane 3 | `newow_trend_v1 @ 1d` Historical observer | 不接 Live/Alert |
| N3 | Lane 3 | `newow_range_v1 @ 15m` Historical observer | 不接 5m/D1过滤 |
| N4a | Lane 2 | immutable snapshot 与只读 API | 请求路径不 replay |
| N4b | Lane 2 | Market Web Newow 工作区 | 浏览器不复制公式 |
| N5 | Lane 3 | active60 Shadow 与运行覆盖摘要 | 不发送通知 |
| N6 | Lane 2/3 | 用户复核标签与最小 outcome report | 不自动排名/晋升 |
| N7 | Lane 3 | 独立 Alert Rule/Scope/Runtime 设计与实现 | 必须另行批准 |

每个可独立集成任务使用独立 Issue、Codex 会话、branch/worktree 和 PR。

---

# Task N0：权威修正与旧计划收口

## 目标

让仓库不存在两套同时可执行的 Newow V1 计划。

## 修改

1. 合入本次两份修正文档；
2. 在 Issue #262、#265 留言说明 V1 被 Issue #291 的观察优先计划覆盖；
3. 旧 Spec 继续作为长期架构和公式来源；
4. 旧 Implementation Plan 标记为 superseded，不删除 Git lineage；
5. 不更新 `STATUS.md`，因为没有产品能力或 Runtime 状态变化；
6. 不更新 `PROJECT_SOURCE.md`，直到 Newow 至少完成 Historical/Web 验收。

## 验收

```text
只有一个 active Newow V1 implementation plan
所有引用都能解析
无源码、migration、Runtime、Alert变更
git diff --check通过
secret scan通过
```

---

# Task N1a：独立 Range Detector

## 目标

完成现有 Issue #258 定义的 `range_detector_lux_v1` 纯 Kernel，作为 Newow 与未来消费者共享的区间原语。

## 保留边界

```text
clean-room
completed-only
confirmed_at != visual_start_at
batch/incremental parity
prefix invariance
物理合约段隔离由consumer负责
```

## 当前 Newow Profile

```text
D1：range_length=20, atr_period=100, multiplier=1.0
15m：range_length=20, atr_period=500, multiplier=1.0
```

## 不做

```text
三角/楔形/旗形/杯柄
通用策略Adapter
Alert
Web策略权威计算
```

## Gate

公式、确认时序、revision 与 repaint zone 必须独立 Sol Review。

---

# Task N1b：Observation Contracts 与最小 Lifecycle

## 目标

建立 Newow 的最小、稳定、可扩展观察合同。

## 建议文件

```text
packages/quant-core/guiyi_quant/newow/
├── contracts.py
├── profiles.py
├── numeric.py
├── phase_lite.py
├── evidence.py
└── observation.py
```

## 必须实现

```text
NewowTimeframeProfile
NewowStrategyBinding
NewowObservationSnapshot
NewowObservationEvent
NewowKeyLevelContext
NewowEvidenceSnapshot
NewowObservationState
```

Observation Lifecycle：

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

## 硬约束

- NumPy/Decimal 纯计算；
- 不读 DB、Redis、文件、网络或系统时钟；
- 不出现 `OPEN/CLOSE/POSITION/PNL`；
- 所有身份包含 formula/profile/source digest；
- 同一 first-seen 事件不可变；
- 新增 60m Profile 不能改变旧 1d/15m 输出。

## 测试

```text
identity stability
serialization round-trip
deterministic reason ordering
same-prefix same-event-id
profile isolation
invalid input fail-closed
```

---

# Task N2：牛哇趋势 D1 最小观察器

## 身份

```text
newow_trend_v1 @ newow_tf_1d_v1
actual_dominant + completed D1
```

## 最小输入

```text
EMA10 / EMA21
EMA21 slope
MACD 12/26/9
ATR14
range_detector_lux_v1
VolumeRatio20
OIDelta5（可用时）
Phase Lite
```

## 最小状态

```text
YELLOW
BLUE
NEUTRAL
```

## Event

```text
TREND_LONG_STARTED
TREND_SHORT_STARTED
TREND_BREAKOUT_LONG
TREND_BREAKOUT_SHORT
TREND_LONG_WEAKENED
TREND_SHORT_WEAKENED
TREND_INVALIDATED
```

## 关键规则

- 只认完成日线；
- 趋势转换和突破是 Observation，不是入场；
- 持续状态只更新 Snapshot，不每根 Bar 产生事件；
- OI 缺失不得伪造；
- D1 close 用于确认，不使用 settlement 替代；
- 当前物理段结束只结束观察状态，不产生模拟平仓。

## 不做

```text
A/B仓位
Target1/2
真实止损
Episode
15m或5m确认
完整命名形态
Alert
```

## 验收

```text
completed-only
strict-before
prefix/append/prepend invariance
batch/incremental parity
physical segment isolation
trend flip dedupe
future range revision不改旧Event
```

---

# Task N3：牛哇震荡 15m 最小观察器

## 身份

```text
newow_range_v1 @ newow_tf_15m_v1
actual_dominant + completed 15m
```

## 最小输入

```text
range_detector_lux_v1
EMA21 slope
区间前推动方向
最近确认高低点
ATR14 / DeviationATR
Skew60 / ExcessKurtosis60
简单位置有效的PinBar/吞没
VolumeRatio20 / OIDelta5（可用时）
```

## Range Bias

```text
EMA方向
+ 区间前推动
+ 最近高低点结构
```

二取三输出：

```text
RANGE_UP
RANGE_DOWN
RANGE_NEUTRAL
```

## Event

```text
RANGE_UP_LOWER_EDGE_WATCH
RANGE_DOWN_UPPER_EDGE_WATCH
RANGE_LONG_CONFIRMATION
RANGE_SHORT_CONFIRMATION
RANGE_INVALIDATED
RANGE_RESOLVED_UP
RANGE_RESOLVED_DOWN
```

## 关键规则

- `RANGE_NEUTRAL` 只展示；
- 只观察顺区间方向的边缘；
- 确认事件要求边界收回、风险收缩、简单K线拒绝中至少两项；
- Range revision 不得改写旧 first-seen Event；
- 同一 `range_id + revision + direction` 最多一个确认事件；
- 顺方向突破只产生 `RANGE_RESOLVED`，不自动移交趋势策略；
- 不读取 D1、5m 或1m。

## 不做

```text
自动下沿买入/上沿卖出
自动止损
Episode
完整Swing Graph
双顶底/头肩/杯柄
Alert
```

## 验收

```text
completed 15m only
session-aware bar identity
night-session trading_day正确
prefix invariance
same range dedupe
range revision anti-backpaint
contract rollover reset
```

---

# Task N4a：Historical Snapshot 与只读 API

## 目标

让 Historical observer 结果可稳定查询，但不把 replay 放进请求路径。

## 建议模块

```text
services/quant-api/app/market_data/newow/
├── source_segments.py
├── engine.py
├── historical_service.py
├── snapshot.py
├── snapshot_store.py
└── snapshot_query.py

services/quant-api/app/api/v1/newow.py
```

## API

```text
GET /api/v1/market/research/newow/definitions
GET /api/v1/market/research/newow/overlay/history
GET /api/v1/market/research/newow/strategy/current
GET /api/v1/market/research/newow/strategy/history
GET /api/v1/market/research/newow/health
```

`current` 在 Stage A 只表示最新已发布 Historical/Post-close Snapshot，不暗示 completed-Live。

## 快照

```text
immutable content-addressed snapshot
atomic current manifest
physical readback
last-known-good保留
```

## 不做

```text
API请求触发replay
API写cache
真实Live状态
AlertEvent作为权威
```

---

# Task N4b：Market Web Newow 复核台

## 目标

让用户从观察记录几秒内完成复核。

## 交互

顶层 Overlay：

```text
none | subing | newow | htdy
```

Newow 内部：

```text
trend | range
```

周期不匹配时明确提示并提供切换：

```text
牛哇趋势策略当前支持D1
牛哇震荡策略当前支持15m
```

## 趋势显示

```text
黄/蓝/中性状态
EMA21
已确认Range
突破或弱化Event
触发原因
关键位置
```

## 震荡显示

```text
Range上下沿/中轴
RangeBias
边缘区域
确认/失效/解决Event
偏离与风险收缩理由
```

## 硬约束

- 浏览器不复制权威公式；
- `visual_start_at` 与 `confirmed_at` 分开；
- FORMING 不画成确认事件；
- 点击观察可直接定位品种、合约、周期和 Bar；
- 默认信息少而清楚，不展示大而全研究面板。

---

# Task N5：active60 Shadow 与盯盘可靠性摘要

## 目标

在不发送通知的前提下，验证 Newow 是否真的能够持续盯盘。

## 每个边界/批次记录

```text
expected_products
processed_products
no_observation_products
observation_products
unavailable_products + reason
error_products + reason
started_at
completed_at
latest_bar_at
processing_latency
```

Newow Shadow 还记录：

```text
事件数量
同品种短时重复数量
状态翻转数量
确认后快速失效数量
```

## Gate

- 不修改现有 SuBing/HTDY Rule 或 Runtime；
- 不调用 transport；
- 不写 production AlertEvent；
- Shadow 失败必须可见，不能被解释为“今天没有机会”；
- 当前仓库 Runtime 未达到 `RUNTIME_READY` 时，不进入 N7。

---

# Task N6：用户复核标签与最小结果研究

## 目标

验证观察是否真正降低用户判断成本，而不是只看模拟收益。

## 用户标签

```text
WORTH_REVIEWING
NOT_WORTH_REVIEWING
TOO_EARLY
TOO_LATE
DIRECTION_OK_LOCATION_BAD
PARTICIPATED
NOT_PARTICIPATED
```

第一版允许本地单用户写入，但必须是独立 research feedback，不修改 Observation Event。

## 次级 Outcome

按观察周期计算：

趋势 D1：

```text
3 / 5 / 10 Bars
```

震荡 15m：

```text
3 / 5 / 8 Bars
```

只报告：

```text
directional return
MFE
MAE
time to invalidation
是否形成顺方向突破
```

## 不做

```text
资金曲线
年化收益
自动排名
winner
promotion
根据Outcome改写人工标签
```

---

# Task N7：真实 Newow Alert（独立后置任务）

## 前置 Gate

全部满足后才允许写 Plan：

1. Market/Alert Runtime 已有可信 `RUNTIME_READY` evidence；
2. active60 自然边界 coverage 完整；
3. “无观察”和“未处理”在状态面可区分；
4. owner PushPlus canary 与真实微信送达边界单独验证；
5. Shadow 至少积累足够自然样本；
6. 日均事件量、重复率和快速失效率在用户可接受范围；
7. 用户批准 Newow Rule code、Scope、audience 和 Runtime promotion。

## 计划方向

只有 first-seen 的高价值事件允许通知，例如：

```text
TREND_LONG_STARTED
TREND_SHORT_STARTED
TREND_BREAKOUT_LONG
TREND_BREAKOUT_SHORT
RANGE_LONG_CONFIRMATION
RANGE_SHORT_CONFIRMATION
```

弱化、失效和持续状态默认只进入 Web，不在 V1 全部推送，防止通知负担反向增加。

## 仍然禁止

```text
自动下单
通知即交易建议
retry/queue/backfill
启动补发
历史replay补Event
根据用户点击自动晋升策略
```

---

# 4. V1 后置研究清单

以下能力不删除，但不进入 V1 关键路径：

```text
完整双尺度Causal Swing
Structure Graph / BOS / CHOCH / Zones
三角、楔形、旗形
双顶底、头肩
杯柄
完整Pattern Lifecycle
A/B仓位与Target-Risk模拟
人工Pattern Gold Set
按形态族precision
完整rolling/walk-forward/prospective OOS平台
```

恢复任一能力必须先回答：

```text
它是否明显减少用户的盯盘或判断成本？
当前V1的实际证据表明缺少它造成了什么问题？
是否有比新增复杂模块更简单的解决方法？
```

---

# 5. 验收矩阵

## 所有源码 Task 的共同 Gate

```text
completed-only
strict-before
future-leak scan
prefix invariance
batch/incremental parity
physical contract isolation
trading_day / session correctness
profile isolation
SuBing isolation
fail-closed
```

## 产品 Gate

```text
Historical可复核
Shadow覆盖可见
无观察与系统异常可区分
原因不超过4条且可解释
点击可定位图表
用户反馈可记录
无OPEN/CLOSE/仓位/订单语义
```

## 真实通知 Gate

```text
P0 Runtime reliability通过
N5 Shadow通过
N6用户价值证据通过
独立Alert Plan批准
独立release批准
独立Runtime promotion批准
```

---

# 6. Codex 执行纪律

每个源码任务：

```text
最新develop
→ 独立task branch/worktree
→ TDD
→ 定向测试
→ 模块测试/lint/typecheck/build
→ 独立Review
→ 人工决定是否集成develop
→ 清理worktree与已合并branch
```

Task N1a、N1b、N2、N3、N5、N7 属于策略公式、因果或 Runtime 可信口径，使用 Lane 3：

```text
Sol + 高推理
新会话
Plan-only先审
独立Review
人工Gate
```

N4 Web/API 和 N6 普通界面可按 Lane 2 执行，但其中涉及事件事实或结果口径的部分仍由 Lane 3 Review。

不得自动：

```text
main merge
tag/release
Runtime promotion
真实通知
生产数据写入
```

---

# 7. 当前结论

```text
允许继续修正规范
允许提交本次Draft PR
不允许启动旧16项Implementation Plan
不允许开始Newow完整形态库
不允许接Newow Alert
不允许修改SuBing
```

本计划通过用户批准和独立 Review 后，首先启动 N0 收口；随后分别为 N1a 与 N1b 建立独立实现任务。