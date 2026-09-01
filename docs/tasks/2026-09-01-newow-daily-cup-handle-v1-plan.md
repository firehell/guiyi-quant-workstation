# Newow 日线杯柄趋势观察 V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Every source task remains review-gated; this document does not authorize implementation, Shadow enablement, notification, release, or Runtime promotion.

**Goal:** 只实现一个可解释、因果安全、面向 active60 的日线杯柄趋势观察器，从全市场中筛出少量值得用户打开图表复核的候选。

**Architecture:** 权威公式位于 NumPy-only `quant-core`；Application 仅通过 `MarketDataService` 读取 `actual_dominant + completed D1`，按真实 rank1 物理合约段逐 Bar 运行同一增量观察状态机；HTTP 只读已发布快照，Web 只绘制 typed API 数据。V1 不建设通用 Pattern Engine、Structure Graph、Target/Risk、Episode、牛哇震荡策略或其他形态。

**Tech Stack:** Python 3.12、NumPy、FastAPI/Pydantic、Vue 3/TypeScript、现有 Canonical/MarketDataService/Snapshot 模式。

**Spec basis:**

- `docs/tasks/2026-08-31-newow-independent-strategy-spec.md`
- `docs/tasks/2026-08-31-newow-independent-strategy-spec-review-amendments.md`
- `docs/tasks/2026-09-01-newow-v1-observation-first-scope-correction.md`
- 本文是 Issue #293 对 Newow V1 的最新规范性范围覆盖；发生冲突时，V1 以本文为准。

## Global Constraints

- 显示名称保持“牛哇趋势策略”；内部公式身份固定为 `newow_trend_cup_handle_v1`。
- 当前唯一数据身份为 `actual_dominant + completed D1`；不读取 W1、60m、15m、5m 或 1m。
- Newow 不读取、筛选、继承或修改任何 SuBing/HTDY Action、Episode、Snapshot、Alert、Scope 或 Runtime 状态。
- `auto_order=false`；V1 不产生 OPEN/CLOSE、仓位、订单、手数、保证金、结算盈亏或自动止损。
- 所有正式观察必须 completed-only、strict-before、prefix invariant、batch/incremental parity、same-physical-contract isolated、fail-closed。
- 牛哇 v3.6 更新说明和手册只提供产品行为线索；不得声称已获得私有公式，也不得用其“99分”等宣传结果证明盈利。
- 真实 PushPlus、Rule/Scope、Runtime、main/tag/release 均为独立人工 Gate。

---

## 1. Newow 在 V1 中的价值

Newow V1 不是再造一个交易平台，而是补充一个与 SuBing 不同的盯盘视角：

```text
SuBing：15m 短线机会观察
Newow：D1 中期趋势整理完成前后的杯柄观察
```

它只解决三件事：

1. 自动扫描 60 个品种，避免人工逐张翻日线图；
2. 把“真杯柄”和 V 形反弹、宽幅震荡、下跌反弹、浅坑、长柄、无量突破区分开；
3. 在柄部已完成或放量突破时给出简明理由、关键位置和图表直达，由用户决定是否参与。

用户可感知闭环：

```text
active60 completed D1
→ 杯柄候选评分
→ FORMING / READY / BREAKOUT / INVALIDATED
→ 盘后观察清单
→ Market Web 查看杯、柄、突破位和量能
→ 用户标记是否值得看
```

## 2. V1 唯一产品与状态

### 2.1 产品身份

```text
display_name        = 牛哇趋势策略
strategy_code       = newow_trend_cup_handle_v1
profile_id          = newow_cup_handle_d1_v1
frequency           = 1d
series_kind         = actual_dominant
live_capable        = false
alert_capable       = false
auto_order          = false
```

未来 60m 不在 V1 写周期特判；若 D1 证明有价值，再创建独立的 `newow_cup_handle_60m_v1` Profile、Candidate 和证据身份。

### 2.2 观察状态

```text
UNAVAILABLE       数据或身份不足
NONE              当前无合法候选
FORMING           杯体可识别，柄部尚未完成；仅 Web 展示
READY             柄部完成且质量达标，等待突破；Shadow first-seen
BREAKOUT_ACTIVE   completed D1 放量突破已确认；Alert 候选
WEAKENED          突破后退回枢轴附近，但尚未破坏柄部
INVALIDATED       形态或突破已失效；生成独立关联事件
EXPIRED           READY 后固定窗口内未突破；生成独立关联事件
```

原 first-seen Event 永不更新。失效、过期或突破均创建新的 linked Event；当前状态由 Snapshot 表达。

### 2.3 事件类型

```text
CUP_HANDLE_READY
CUP_HANDLE_BREAKOUT
CUP_HANDLE_WEAKENED
CUP_HANDLE_INVALIDATED
CUP_HANDLE_EXPIRED
```

`FORMING` 不持久化事件，不进入未来通知。

## 3. 杯柄规则来源与 clean-room 定义

外部更新说明明确强调：

- 柄部缩量、突破放量；
- V 形底扣分；
- 左杯口之前必须存在趋势；
- 柄部长短收紧；
- 杯深下限从 8% 提升到 10%；
- 重点过滤宽幅震荡和下跌反弹。

牛哇手册还明确：杯子形成于一段上涨后的回调；杯底相对平缓且量能收缩；右侧回升到杯口附近；柄部回撤通常不超过右侧上涨幅度三分之一、持续约一到两周；突破柄部高点为买入信号，重新跌回柄部区域属于假突破。

V1 将这些内容转化为可审计规则，具体阈值属于归一量化研究定义。

## 4. 权威输入与期货边界

输入只接受同一真实物理合约段内、严格递增的 completed D1：

```text
product
physical_contract
segment_id
trading_day
bar_end
open / high / low / close
volume
open_interest optional
source_identity
```

期货硬边界：

- 杯、柄、枢轴和观察生命周期不得跨 rank1 物理合约切换；换月后从 NONE 重新开始。
- 不使用连续合约拼接形态，不对换月跳空做复权后再识别杯柄。
- 夜盘数据归属 Canonical `trading_day`，不按自然日期判断日线。
- 成交量和持仓量只在同一物理合约内比较；OI 缺失保持 unavailable，不填 0，不跨合约取值。
- OI 只作为期货参与度说明，不作为 V1 杯柄成立的硬 Gate。
- Historical owner 可知性不足的窗口不得进入 prospective 证据。

## 5. 杯柄候选几何

### 5.1 锚点

```text
L = left_rim
B = cup_bottom
R = right_rim
H = handle_low / handle_high（按方向）
P = breakout_pivot
```

严格时间顺序：

```text
tL < tB < tR < tH <= t
```

所有锚点由截至当前 completed Bar 的前缀确定。允许 FORMING 候选随新 Bar 演化；一旦进入 READY，候选 identity、L/B/R/H/P、confirmed_at 和 score breakdown 冻结。

### 5.2 V1 D1 Profile 初始参数

```text
pretrend_lookback_bars       = 20..60
cup_min_bars                 = 25
cup_max_bars                 = 90
handle_min_bars              = 5
handle_max_bars              = 15
cup_depth_min_pct            = 0.10
cup_depth_preferred_max_pct  = 0.35
cup_depth_hard_max_pct       = 0.50
rim_tolerance_pct            = 0.05
rim_tolerance_atr            = 1.00
handle_max_right_leg_ratio   = 1/3
handle_max_depth_pct         = 0.15
handle_must_stay_above_mid   = true
ready_distance_to_pivot_atr  = 1.00
breakout_buffer_atr          = 0.10
ready_expiry_bars            = 20
```

### 5.3 前置趋势硬 Gate

看涨杯柄要求：

```text
left_rim_close > EMA21_at_left_rim
EMA21_slope_10_at_left_rim > 0
且下面至少一项成立：
- pretrend_return_pct >= 10%
- pretrend_move_atr >= 4.0
```

看跌杯柄完全镜像。这样过滤“下跌趋势中的普通反弹”，但不照搬股票市场必须上涨 30% 的硬阈值。

### 5.4 杯深与杯口

```text
rim_price = (L.price + R.price) / 2
cup_depth_pct = abs(rim_price - B.price) / rim_price
```

硬要求：

```text
10% <= cup_depth_pct <= 50%
杯深 >= 3.0 × median_ATR_in_cup
abs(L.price - R.price) <= min(5% × rim_price, 1.0 × ATR_at_R)
```

10%—35%获得完整得分；35%—50%保留但扣分；低于 10% 直接拒绝。

### 5.5 U 形纯度与 V 形扣分

定义底部带：

```text
bottom_band = B.price ± 25% × cup_depth
```

质量特征：

```text
bottom_span_bars
left_leg_bars / right_leg_bars
midline_cross_count
quadratic_fit_rmse_atr
```

规则：

- 底部带至少持续 3 根 D1；只有 1 根尖底时扣 15 分。
- 左右腿时长比在 0.5—2.0 内得满分；超出区间扣分。
- 杯内多次完整穿越中轴、形成宽幅来回震荡时扣分；超过固定 crossing 上限拒绝。
- 二次曲线拟合只参与质量分，不作为唯一形态判定，以免过拟合。

### 5.6 柄部

硬要求：

```text
5 <= handle_bars <= 15
handle_retrace <= 1/3 × right_leg_advance
handle_depth_pct <= 15%
handle_extreme 保持在杯体上半部（看跌镜像）
```

柄部长于 15 根、回撤过深或跌入杯体下半部，候选失效。

### 5.7 量价确认

柄部缩量：

```text
median(handle_volume) <= 0.80 × median(right_leg_volume)
median(handle_volume) <= 0.90 × median(previous_20_volume)
```

突破放量：

```text
completed close > P + 0.10 × ATR14          # 看涨
completed close < P - 0.10 × ATR14          # 看跌
breakout_volume >= 1.20 × median(previous_20_volume)
breakout_volume >= 1.50 × median(handle_volume)
```

几何突破但量能不足时只输出 Web diagnostic：

```text
BREAKOUT_VOLUME_UNCONFIRMED
```

不生成 `CUP_HANDLE_BREAKOUT` Event。

## 6. 100 分质量分

```text
前置趋势              15
杯体深度/杯口/时长      25
U 形纯度               20
柄部质量                20
量能结构                20
总分                   100
```

状态门槛：

```text
FORMING  >= 65 且杯体硬条件通过
READY    >= 80 且柄部、缩量、距离枢轴条件通过
BREAKOUT >= 85 且实体突破与放量硬条件通过
```

截图中的“真杯柄 99 分过线”仅作为存在评分引擎的线索，不代表本项目必须使用 99 分阈值，也不作为效果证据。

## 7. 多空处理

杯柄是一种形态族，V1 合同支持：

```text
BULLISH_CUP_HANDLE
BEARISH_CUP_HANDLE
```

实现使用同一个方向归一化几何函数，不复制两套算法。开发顺序先完成看涨 fixture，再用镜像 fixture 验证看跌；两者结果分开统计，任一方向可因证据不足而单独保持 Shadow-only。

## 8. 最小模块边界

### Quant-core

```text
packages/quant-core/guiyi_quant/newow/
├── __init__.py
├── models.py          # frozen contracts/enums only
├── profiles.py        # newow_cup_handle_d1_v1
├── cup_handle.py      # candidate enumeration, scoring, lifecycle transition inputs
└── numeric.py         # only cup-handle-specific pure helpers
```

不创建：

```text
patterns/ 通用目录
structure.py
phase.py
target_risk.py
execution.py
UniversalStrategyAdapter
```

### Application

```text
services/quant-api/app/market_data/newow/
├── cup_handle_engine.py
├── cup_handle_historical.py
├── cup_handle_snapshot.py
└── cup_handle_query.py
```

职责仅为：

- 从 `MarketDataService` 读取 actual-dominant D1；
- 按 rank1 物理段驱动唯一逐 Bar engine；
- 生成 immutable observation snapshot/event；
- 原子发布后供 HTTP 只读。

### API/Web

```text
services/quant-api/app/api/market_research_newow.py
services/quant-api/app/schemas/market_research_newow.py
apps/quant-web/src/api/newow.ts
apps/quant-web/src/types/newow.ts
apps/quant-web/src/composables/useNewowCupHandle.ts
apps/quant-web/src/components/market/NewowCupHandlePanel.vue
apps/quant-web/src/pages/market/chart.vue
```

Web 不重算形态和分数。

## 9. Historical 与 Incremental

唯一权威入口：

```python
CupHandleObserver.step(completed_d1_bar)
```

Historical 逐 Bar 调用该入口；盘后增量也调用同一入口。每一步输出：

```text
current candidate snapshot
new first-seen event(s)
linked invalidation/expiry event(s)
diagnostics
```

必须证明：

- full batch 与逐 Bar incremental 逐字段一致；
- 任意 prefix 的 READY/BREAKOUT identity 不因未来数据改变；
- FORMING 可以演化，但不能回画成过去已经 READY；
- 主力切换清空候选，不生成交易退出语义；
- 相同前缀重复计算事件幂等。

## 10. Web 最小体验

### Radar/清单

按以下优先级展示：

```text
BREAKOUT_ACTIVE
READY（按距枢轴和分数排序）
FORMING（默认折叠）
UNAVAILABLE / ERROR 单独统计
```

每项只展示：

```text
品种 / 当前主力
看涨或看跌
状态
总分
距突破位
柄部量能比
2—4条主要理由
[查看日线图]
```

### 图表

只绘制：

```text
L 左杯口
B 杯底
R 右杯口
柄部区间
P 突破枢轴
失效参考位
成交量缩放与突破量能标记
```

Tooltip 同时显示：

```text
pivot_at
confirmed_at
first_seen_at
score breakdown
```

不显示买入、卖出、仓位或目标收益。

## 11. Targeted Gold Set

由于 V1 只做一个形态，保留一个小型、专用而非平台化的人工 Gold Set：

```text
80—120 个 D1 窗口
```

至少覆盖：

- 真看涨杯柄、真看跌杯柄；
- V 形底；
- 宽幅震荡；
- 下跌趋势反弹；
- 杯深小于 10%；
- 柄部过长或过深；
- 柄部未缩量；
- 突破未放量；
- 主力换月附近；
- OI 缺失。

标注者不得看到未来收益。Gate：

```text
READY precision >= 80%
BREAKOUT precision >= 85%
confirmed identity stability = 100%
cross-contract candidate = 0
```

召回率只做观察，不为提高召回放松硬 Gate。

## 12. 最小结果评价

不建设完整回测和资金曲线。对 first-seen BREAKOUT 仅记录：

```text
3 / 5 / 10 / 20 D1 后的方向性变化
MFE
MAE
3 Bar 内是否跌回枢轴
是否跌破柄部失效位
```

报告必须标记：

```text
retrospective observation outcome
gross
pre-cost
not OOS
not tradability evidence
```

## 13. 实施顺序

### C0：范围收口

- 本文合入后，将 Issue #291 标记为已被 #293 的更窄 V1 范围取代。
- #263、#266、#292 保留 Git lineage，不删除历史文档。
- 不更新 `PROJECT_SOURCE.md` 或 `STATUS.md`，直到代码和真实产品面发生变化。

### C1：杯柄纯 Kernel

**Branch:** `feature/newow-cup-handle-kernel`

**Deliverable:** Profile、contracts、候选枚举、评分、看涨/看跌镜像、因果测试和 Gold fixtures。

**Gate:** Sol 高推理独立公式 Review；全部 causality/prefix/golden 测试通过后才允许合入 develop。

### C2：日线观察器与 Historical Snapshot

**Branch:** `feature/newow-cup-handle-observer`

**Deliverable:** actual-dominant D1 分段、唯一 step engine、immutable Snapshot/Event、原子 snapshot、只读 query。

**Gate:** batch/incremental、segment isolation、night trading_day、idempotency、fail-closed 全部通过。

### C3：只读 API 与 Market Web

**Branch:** `feature/newow-cup-handle-web`

**Deliverable:** 只读 API、Radar 杯柄清单、D1 图表锚点和评分解释。

**Gate:** HTTP 请求路径不得 replay 或写 cache；Web 不复制公式；浏览器 smoke 通过。

### C4：active60 盘后 Shadow

**Branch:** `research/newow-cup-handle-shadow`

**Deliverable:** 盘后离线/Shadow 批次、expected/processed/none/forming/ready/breakout/unavailable/error/latency 摘要。

**Gate:** 合并代码不等于真实启用；真实盘后调度或外部写入另需一次明确授权。

### C5：用户复核与最小结果

**Branch:** `research/newow-cup-handle-review`

**Deliverable:** 值得看、不值得看、V形误报、震荡误报、太早、太晚等用户标签；最小 forward outcome。

**Gate:** 用户标签与策略事实分离；结果不能修改历史事件或阈值。

### C6：独立通知 Gate

只有同时满足以下条件才另开任务：

```text
现有 Runtime/Alert 已取得自然可靠性证据
active60 Shadow 覆盖稳定
READY/BREAKOUT 每日数量可接受
重复率和快速失效率可接受
用户确认观察确实有价值
用户明确批准 Newow Rule/Scope/transport
```

默认产品建议为“每日盘后一条杯柄摘要”，不在本计划实现，也不改变现有 Alert 两表和 one-shot 边界。

## 14. 明确后移

```text
牛哇震荡策略
15m / 60m Newow
其他全部命名形态
完整 Swing / Structure Graph
偏度峰度阶段内核
通用 Pattern Engine
A/B 加仓语义
Target/Risk / Episode
完整回测平台
自动 winner / promotion
```

这些内容只有在 D1 杯柄观察器证明能减少盯盘和提高复核效率后，才允许重新立项。

## 15. 验收矩阵

### 公式与形态

- 正例和硬负例 fixture 覆盖截图中明确提到的五类改进；
- 10% 杯深下限、V 形扣分、前置趋势、柄长、量能规则均有独立测试；
- 看涨与看跌分别报告，不混成一个总体数字。

### 因果与身份

- completed-only；
- no negative shift / centered window / future pivot；
- prefix invariance；
- batch/incremental parity；
- READY 后锚点和评分冻结；
- first-seen Event immutable；
- 物理合约段隔离；
- 主力换月不拼接形态。

### 产品价值

- 每次盘后明确 expected / processed / unavailable / error；
- 无候选与系统未运行可以区分；
- Web 能在一次点击内看到杯、柄、枢轴、量能和主要理由；
- FORMING 不通知；READY 只 Shadow；BREAKOUT 才具备未来 Alert eligibility；
- 不出现自动交易、仓位、收益承诺语言。

## 16. Review Gate

本计划为 Lane 3 / Plan-only。批准本计划只允许按 C1 新建独立实现任务和 worktree，不授权：

- 自动合入 develop；
- 真实 Shadow 调度；
- 真实通知；
- production DB/Redis/RQData/Canonical 写入；
- main、tag、release 或 Runtime promotion。

最终结论在独立 Review 后只能是：

```text
允许继续实现 C1
要求修正后再实现
阻塞
```
