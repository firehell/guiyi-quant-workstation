# 历史策略 / Research Overlay 设计

更新时间：2026-08-22

本文定义 Market K 线中 SuBing、N Structure、JDJ 的历史因果事件展示边界。它是当前实现任务的设计输入，
不改变 `STATUS.md` 中 release、Runtime、Alert Scope、evidence 或 Gate 状态。

## 1. 目标

在 Market Web 主图上复算并展示历史上**当时已经能够知道**的策略/研究事件，方便人工查看信号出现的
位置、市场阶段与后续走势。

第一版固定语义：

| Overlay | 当前来源 | 第一版周期 | 主图事件文案 | 语义 |
|---|---|---|---|---|
| SuBing | 现有 Formal Signal evaluator / resolver | `5m`、`15m` | `买入信号` / `卖出信号` | Formal Signal 的 Historical Replay |
| N Structure | `n_structure_5m_v1` causal reducer | `5m` | `N↑完成` / `N↓完成` | Research completion event |
| JDJ | 三条现有 JDJ Candidate reducer | `1m` | `跟随多/空`、`再入多/空`、`突破多/空` | Research Candidate trigger |
| 火天大有 | 现有浏览器 observation mirror | `15m` | 沿用 `买观察` / `卖观察` | Indicator Observation |

本功能是**历史因果事件重放**，不是成交回测。第一版不计算持仓、成交、滑点、手续费、盈亏、胜率或
策略排名，也不把 N/JDJ 自动晋升为 Alert Rule。

## 2. 设计原则

### 2.1 共性只放在展示层，不统一策略语义

SuBing、N、JDJ 继续使用各自既有 Policy、reducer、event identity 与时间粒度。后端不得新增通用
`Strategy` / `Opportunity` 计算适配层，也不得在 TypeScript 中复制核心公式。

可以复用的只有：

- HTTP 请求的 `series_kind / symbol / frequency / since / through` 身份；
- Web Overlay capability；
- 历史事件加载、generation 防旧请求污染、marker 映射与去重；
- K 线 marker 渲染。

### 2.2 Historical 只读、按需计算、零持久化

历史事件只从 confirmed Canonical 经 `MarketDataService -> ActualDominantResearchSegmentLoader` 或
既有 Market read boundary 读取并按需复算：

```text
Market Web
  -> source-specific historical overlay HTTP
  -> source-specific service / reducer
  -> ActualDominantResearchSegmentLoader
  -> MarketDataService
  -> confirmed Canonical
```

第一版不新增 DB 表、不写 `alert_events`、不写 Redis、不写 Canonical、不做 materialized cache。个人项目
先接受页面按需计算；只有实际性能数据证明需要时再增加缓存。

### 2.3 事件只画在 evidence Bar，不回标

- SuBing：画在最终 resolved signal 的 `bar_end`。
- N：画在 `CompletedNPattern.completed_at`。
- JDJ：画在 Candidate event 的 `observed_at`。

不得把事件回画到 pivot、reaction、reclaim、first-break、retest 等更早位置。完整序列与任意历史 prefix
在相同 cutoff 前必须产生相同事件集合。

### 2.4 第一版只支持 `actual_dominant`

SuBing/N/JDJ 历史 Overlay 第一版只允许：

```text
series_kind = actual_dominant
```

因为事件 identity 依赖真实 rank1 physical contract segment。`continuous` 或指定 `contract` 图表不得
静默叠加 actual-dominant 事件。Web 保留用户当前 series 选择，只显示明确的 unsupported 状态，不自动切换。

### 2.5 为扩周期预留 capability，不预先抽象新策略

Web 用一个轻量 `ResearchOverlayDefinition` 描述展示能力：

```ts
interface ResearchOverlayDefinition {
  id: ResearchOverlayId
  label: string
  supportedSeriesKinds: readonly SeriesKind[]
  supportedFrequencies: readonly MarketFrequency[]
  mainIndicators: readonly MainIndicatorId[]
  historicalSource: 'none' | 'local' | 'subing' | 'n_structure' | 'jdj'
}
```

它只决定“当前图表能不能显示、需要哪条线、向哪个来源取事件”，不承载策略公式。

未来某来源增加新周期时：

1. 先有该来源被接受的 Policy/公式语义与因果测试；
2. source-specific backend 放开该 `frequency`；
3. 修改 `supportedFrequencies`；
4. 复用同一 historical loader、marker renderer 与 stale-request 防护。

不得仅修改前端 capability 就把一个没有被接受策略语义的周期显示为可用。

## 3. 后端边界

新增独立薄 router，建议：

```text
services/quant-api/app/api/market_research_overlays.py
prefix = /api/v1/market/research
```

第一版三个 source-specific endpoint：

```text
GET /api/v1/market/research/subing/history
GET /api/v1/market/research/n-structure/history
GET /api/v1/market/research/jdj/history
```

共同 query：

```text
series_kind=actual_dominant
symbol=<product>
frequency=<MarketFrequency>
since=<YYYY-MM-DD>
through=<YYYY-MM-DD>
```

三个 endpoint 使用独立 response model，不建立统一“策略事件”后端 DTO；Web 在展示边界把各自事件映射为
`KlineMarker`。

### 3.1 SuBing Historical Formal Signal

新增一个只读 Historical service，但**不复制** `SubingReadService` 的 resolver。

先把当前纯 signal resolution 从 `SubingReadService._resolve_matched_signal()` 收敛为可复用函数，例如：

```python
resolve_subing_matched_signal(primary, companion, *, calibration)
```

`SubingReadService` 和 Historical service 都调用同一函数。

Historical 计算对每个 physical-contract rank1 segment 使用完整 prefix 的 5m/15m Factor：

1. 非 15m boundary 的 5m Bar：以该 5m Factor 为 primary，最近且 `bar_end <= current_5m.bar_end` 的已确认
   15m Factor 为 companion；
2. 同一个 15m boundary：不单独再评 5m incoming event，只按当前 Runtime 行为以 15m primary + 同 boundary
   5m companion 做一次 resolution；
3. 两周期同时 matched 同方向时 15m wins，并保留 `lower_tf_confirmation=true`；
4. 两周期方向冲突时不生成事件；
5. 最终只返回 `MATCHED` 且 `resolved.trigger_timeframe == 请求 frequency` 的事件。

返回最小字段：

```text
event_id
bar_end
trading_day
contract
direction = buy | sell
trigger_timeframe
lower_tf_confirmation
```

Historical replay 不创建 `AlertEvent`，也不冒充自然 Runtime Event。

### 3.2 N Structure

直接复用现有 `NStructureResearchService.completion_events()` / causal reducer，不重写 N 结构。

第一版只投影 completed-N：

```text
n_id
completed_at
trading_day
contract
direction = up | down
completion_level
```

不在本任务增加 N1/N2 区间带、结构状态、range reentry、break event 或买卖 Alert。

### 3.3 JDJ

复用现有 `JdjResearchService` 三条 Candidate event，不合成一个“日进斗金综合信号”：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

返回最小字段：

```text
event_id
candidate_id
source_event_kind
observed_at
trading_day
contract
direction = long | short
trigger_level
```

第一版一次返回三条 Candidate；Web 以文案区分，不新增 Candidate 筛选状态和持久化设置。

## 4. Web 设计

### 4.1 Overlay 选项

主图从：

```text
无 | 苏冰 | 火天大有
```

扩展为：

```text
无 | 苏冰 | N字 | 日进斗金 | 火天大有
```

`ResearchOverlayId` 扩展为：

```text
none | subing | n_structure | jdj | htdy
```

`MainChartPreferences` 结构不变，因此不为此单独升级 localStorage schema version；只扩展
`normalizeResearchOverlay()` 的合法值。

### 4.2 主图线

- SuBing：沿用 EMA21，可继续使用当前可选 EMA10/EMA60。
- N Structure：第一版不新增线，只画 causal completion marker。
- JDJ：固定显示 EMA20，作为 Candidate 的视觉上下文；EMA20 只是展示镜像，不参与 Web 信号计算。
- HTDY：保持现状。

EMA20 复用现有 `calculateEMA()`，并进入现有 EMA derived-data/hover/render 链路，不建立 JDJ 专用线组件。

### 4.3 一个通用 Historical marker loader

新增一个 Web composable，例如 `useHistoricalResearchMarkers()`，只负责：

- 按 Overlay capability 判断是否需要请求；
- 从当前 K 线 `trading_day` 得到 `since/through`；
- replace 时加载整个当前窗口；prepend 时加载新增更早窗口；
- 用 generation + full identity 丢弃切品种/周期/Overlay 后的旧响应；
- 按 source event id 去重；
- source-specific mapper 转换为 `KlineMarker`；
- live mutation 不调用 Historical API。

它不计算任何策略。

### 4.4 Marker

建议第一版文案：

```text
SuBing: 买入信号 / 卖出信号
N:      N↑完成 / N↓完成
JDJ:    跟随多 / 跟随空
        再入多 / 再入空
        突破多 / 突破空
```

多/向上事件在 K 线下方，空/向下事件在 K 线上方。Tooltip 至少显示 source、physical contract、事件时间、
周期；JDJ 额外显示 candidate id。

### 4.5 SuBing Persistent Alert 去重

`KlineMarker` 增加可选 `dedupeKey`，只用于展示合并：

```text
subing:<symbol>:<bar_end>:<resolved-frequency>:<direction>
```

SuBing Historical replay 和 persisted `AlertEvent` 生成同一个 `dedupeKey`。合并顺序让 persisted AlertEvent
覆盖 Historical replay，因此：

- Runtime 启用前仍能看到历史重算信号；
- 已有真实 AlertEvent 的位置只显示一条；
- 不需要向 Alert DB backfill。

N/JDJ 使用自身 event id，不与 Alert 合并。

## 5. Fail-closed 与性能

Backend：

- 非 `actual_dominant`：422；
- source 不支持的 frequency：422；
- symbol / date / identity 非法：422；
- Canonical、rank1 segment、physical contract 或 source identity 不完整：409；
- 不静默缩短窗口、不跨频 fallback、不补未来 Bar。

Web：

- unsupported identity 不发请求，清空该 Overlay 历史 markers，并显示轻量说明；
- identity 改变时先清旧 marker，避免 stale display；
- 同 identity prepend 请求失败时保留已经确认的旧窗口 markers，但显示加载错误；
- Historical API 故障不阻断 K 线本身。

第一版无 Redis/DB/materialized cache。只有在真实使用中观察到 source-specific recomputation 明显影响本地
交互后，才另立性能任务。

## 6. 禁止范围

本任务不得：

- 修改 SuBing/N/JDJ 公式、参数、Calibration、FormalPolicy 或 Candidate identity；
- 在前端重写核心 signal/reducer；
- 建立通用 Strategy/Opportunity backend adapter；
- 把 N/JDJ 注册为 Alert Rule；
- 历史 `AlertEvent` replay/backfill；
- 写 PostgreSQL、Canonical、Redis；
- migration；
- PushPlus 或其他真实通知；
- Runtime/live switch；
- release/main/tag；
- 订单、持仓、撮合、PnL、胜率、score/rank/winner/promotion；
- 更新 `STATUS.md` 把 UI 历史重放声明为 OOS、盈利、有效或 Runtime evidence。

## 7. 验收

### 因果与业务

1. SuBing Historical resolver 与当前 Runtime/`SubingReadService` 共享同一个 pure resolution function。
2. SuBing 同一 15m boundary 最多生成一个 resolved event，并正确保留 higher-timeframe wins、direction conflict
   与 lower-TF confirmation 语义。
3. N marker 时间严格等于 `completed_at`。
4. JDJ marker 时间严格等于 `observed_at`。
5. 三个来源都有 prefix-invariance / no-backpaint 测试。
6. 所有 Historical 事件携带 source 对应 physical contract identity。
7. unsupported series/frequency 明确 fail-closed。

### Web

1. 五个 Overlay 可选择，unsupported 周期不显示 stale marker。
2. SuBing 5m/15m 可见 Historical Formal Signal。
3. N 5m 可见 `N↑/N↓完成`。
4. JDJ 1m 可同时区分三条 Candidate 的多/空触发，EMA20 可见。
5. replace/prepend/快速切 Overlay 不产生重复或旧请求污染。
6. SuBing persisted AlertEvent 与 Historical replay 重合只显示一条，并优先显示 persisted Event。
7. 页面明确使用“历史因果重放 / 非成交回测”语义。

## 8. 实施顺序

为避免先造框架，按纵向切片实施：

1. **Shared shell + SuBing**：只抽取 SuBing 真正需要共享的 resolver、Overlay capability、Historical loader 和
   dedupe contract，先打通一个完整来源；
2. **N Structure**：复用 Task 1 shell，只增加 source-specific endpoint/mapper；
3. **JDJ**：复用 Task 1 shell，增加三 Candidate endpoint/mapper 与 EMA20；
4. **Integration closeout**：全量因果回归、E2E、canonical/architecture 最终对齐和去除重复分支。

Task 2/3 在 Task 1 后技术上可并行；个人项目默认按 `SuBing -> N -> JDJ -> closeout` 顺序执行，减少同时活动分支。
