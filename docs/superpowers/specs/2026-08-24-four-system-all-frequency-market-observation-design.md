# 四体系 Active60 全周期 Market Observation 设计

更新时间：2026-08-24  
状态：用户已批准产品方案；本文件完成提交前 Review 后形成正式阶段二 Design Spec。它授权后续 implementation planning，不授权代码实现、Alert Scope 变更、真实通知、Runtime switch/promotion、main/tag/release、正式数据/DB/Redis 写入、prospective OOS 消费或订单能力。

## 1. 目标与当前事实

阶段一已经完成 JDJ Strategy V1 从 JM 1m 到当前 active universe 任意单产品的 `actual_dominant + 1m` Historical reference replay。当前 `STATUS.md` 已记录固定窗口 capability smoke 为 `60 ok / 0 typed_unavailable / 0 command_failed`；该结果只证明 replay capability coverage，不证明盈利、有效性或可交易性。

阶段二只解决一个产品目标：

> **把苏冰、N字、日进斗金、火天大有四个既有体系完整铺到 active60 的正式七周期主图观察面，同时严格保留原生周期、正式研究身份和 Alert 边界。**

正式 Market 周期仍只有：

```text
1m / 5m / 15m / 30m / 60m / 1d / 1w
```

当前主图仍有六个选择：

```text
无｜苏冰｜N字｜日进斗金｜日进斗金策略｜火天大有
```

当前正式/原生语义分别是：

- SuBing：`actual_dominant + 5m/15m` Formal Signal；
- N Structure：`actual_dominant + 5m`，Policy=`n_structure_5m_v1`；
- JDJ Candidate：`actual_dominant + 1m`，Policy=`jdj_1m_policy_v1`，趋势上下文=`5m N Structure`；
- JDJ Strategy：当前 active product 的 `actual_dominant + 1m` reference replay，execution=`1m`、trend context=`5m`；
- HTDY original：原始 observation-only 公式，当前 Web capability 只开放 `15m`。

阶段二不得把“全周期可显示”解释为“所有周期都成为正式策略”。

## 2. 核心产品边界

阶段二永久冻结下面三个集合的区分：

```text
可观察周期
    ⊃
正式研究 / 原生策略周期
    ⊃/≠
Alert 周期
```

精确含义：

1. **原生周期**继续运行当前已经冻结的 Formal/Candidate/Strategy/Observation 语义；
2. **非原生周期**只使用当前所选周期的 confirmed Canonical Bars 形成 source-specific single-timeframe observation；
3. 非原生 observation 不生成新的 Formal Signal、Candidate identity、Strategy profile、OOS identity、AlertEvent、PnL 或交易执行语义；
4. Alert Registry、production Rule Scope 和 transport 在阶段二完全不变；
5. Web 不复制 Python 业务公式，不建立通用 Strategy/Opportunity adapter。

阶段二完成后的主图顶部固定收口为：

```text
无｜苏冰｜N字｜日进斗金｜火天大有
```

`JDJ Candidate` 退出 Market 主图用户入口，但其 reducer、CLI、retrospective evidence、prospective OOS identity 和研究事实继续保留；不得删除或改写。

## 3. Review 后的关键修正

提交前 Review 对已批准方案做了四项收敛，均不改变产品目标。

### 3.1 SuBing 非原生周期只暴露用户明确要求的事实

非 `5m/15m` SuBing observation 只公开：

- EMA21 与当前价格位于均线上/下；
- MACD 金叉/死叉；
- 金叉/死叉发生点距离 0 轴的距离；
- 当前 Bar 成交量。

现有 `SubingFactorSnapshot` 内部还包含 slope、previous volume、volume ratio 等事实，但阶段二不得因为字段已经存在就把它们扩成新的 UI 判定或非原生 Policy。尤其不得定义“距 0 轴 ≤ X”“量比 ≥ Y”后生成买卖点。

### 3.2 N/JDJ 正式 Policy identity 不能被改造成多周期 Policy

`n_structure_5m_v1` 和 `jdj_1m_policy_v1` 都把 source timeframe 写入 exact immutable Policy。阶段二不能复制七份 JSON Policy，也不能修改 exact checker 让正式 Policy 接受任意周期。

允许的唯一复用方式是：

```text
frequency-neutral formula / state-machine seam
        ↑
        ├── existing exact native wrapper
        └── narrow single-TF observation wrapper
```

正式 wrapper 的 public facts 必须 exact parity；Observation wrapper 使用独立 observation identity，不能复用 `*_5m_v1`、`*_1m_candidate_v1` 等正式 identity。

### 3.3 JDJ 1d/1w 不能机械复用 intraday `same_trading_day` reset

现有 JDJ Candidate 是 intraday 体系，状态在 trading day 切换时重置。若把该行为直接应用到 `1d/1w`，每个 Bar 几乎都会形成新的 trading day，跨 Bar setup 无法建立。

因此阶段二冻结：

- 非原生 `5m/15m/30m/60m` JDJ observation：仍在每个 trading day 内独立运行；
- 非原生 `1d/1w` JDJ observation：只在同一 physical contract + 同一 rank1 segment 内连续运行，不使用 intraday `same_trading_day` reset；
- 该差异必须在 response metadata 中明确为 non-native observation semantics，绝不能回写 `jdj_1m_policy_v1`。

这是为了让日/周线的“当前周期观察”具有可解释的跨 Bar 状态，而不是把 intraday execution rule 假装成日/周正式策略。

### 3.4 Observation 必须恢复真实 rank1 segment 上下文

Observation 不能从浏览器当前可视窗口第一根 Bar 直接开始计算，否则：

- EMA/MACD warmup 会随翻页变化；
- N swing/pattern epoch 可能从错误位置重新起算；
- JDJ setup 可能随着 prepend 历史而改写此前 marker。

继续复用 `ActualDominantResearchSegmentLoader`：先对请求窗口 probe rank1 segment，再从真实 `segment.start_trading_day` 读取到 `through`，最后只把请求窗口内的 observation facts 投影给 Web。

不得建立第二套 warmup、第二套 dominant resolver 或 viewport-local strategy state。

## 4. 最终行为矩阵

| 体系 | 原生周期 | 原生周期行为 | 非原生周期 | 非原生行为 | 阶段二 Alert |
|---|---|---|---|---|---|
| 苏冰 | 5m / 15m | 现有 Formal Signal、companion 与 same-boundary resolver | 1m / 30m / 60m / 1d / 1w | 当前周期 Factor Observation | 不改 |
| N字 | 5m | 现有 `n_structure_5m_v1` | 1m / 15m / 30m / 60m / 1d / 1w | 当前周期 N Formula Observation | 无 |
| 日进斗金 | 1m | 当前 JDJ Strategy V1 reference replay | 5m / 15m / 30m / 60m / 1d / 1w | 当前周期 JDJ Setup Observation | 无 |
| 火天大有 | 15m | 当前 original observation | 1m / 5m / 30m / 60m / 1d / 1w | 同公式当前周期 observation | 不改 |

其中：

- “原生”不等于“可交易”；所有产品面始终是研究观察；
- HTDY 原生 15m 仍然是 repainting accepted 的 observation-only，不升级为 Formal Research；
- 非原生 observation 只说明“用这一套规则观察当前周期时出现什么结构/事实”，不证明该周期有效。

## 5. 总体架构

采用“正式链不动 + source-specific Observation Projection”方案：

```text
Canonical Parquet
      ↓
MarketDataService
      ↓
ActualDominantResearchSegmentLoader（SuBing / N / JDJ）
      │
      ├──────── native path ────────┐
      │                             │
      │  SuBing 5m/15m              │
      │  N 5m                       │
      │  JDJ Strategy 1m            │
      │                             │
      └── single-TF observation ────┤
                                    │
         SuBing other TF            │
         N other TF                 │
         JDJ other TF               │
                                    ↓
                              Market Web

HTDY：继续现有 local observation rendering path，只扩 capability frequency。
```

禁止新增：

- `GenericStrategyAdapter`；
- `UniversalObservationEngine`；
- `MultiTimeframeStrategyFramework`；
- Opportunity DB/domain；
- Observation DB/cache；
- worker / queue / scheduler；
- 60×7×4 后台预计算；
- per-product / per-frequency strategy 参数。

允许共享的只有 Web/API 通用机械能力：request identity、confirmed window、generation stale-response guard、event-id dedupe、typed error handling 和 marker rendering。

## 6. 数据身份与 Scope

### 6.1 Active universe

SuBing、N、JDJ observation 的产品 admission 继续来自当前 `active_products.txt`，不得维护第二份 60 品种 allowlist。

“支持 active60”的含义仍然是：单产品 endpoint 可以对当前 active universe 任意 symbol 按需计算，而不是一次请求批量计算 60 品种。

### 6.2 Series kind

保持现有边界：

- SuBing / N / JDJ：只支持 `actual_dominant`；
- HTDY：保持现有 `continuous / actual_dominant / contract` capability。

Overlay 不拥有 Market display dataset identity。用户选择不支持的 series kind 时必须明确 unavailable，禁止自动切换到 `actual_dominant`。

### 6.3 Rank1 segment

SuBing、N、JDJ 每个 physical contract segment 独立计算。不得：

- 跨换月继承 swing/setup memory；
- 跨 segment 拼接 state；
- 用 continuous 替代缺失 actual_dominant；
- 在 segment identity 不完整时猜测。

## 7. SuBing 设计

### 7.1 Native 5m / 15m

现有链完全不改：

```text
5m Factor + 15m Factor
→ existing Calibration / FormalPolicy
→ existing same-boundary resolver
→ Formal Signal
```

必须保留当前 Event ID、direction、bar_end、trigger timeframe、lower-TF confirmation 和 same-boundary resolution。

### 7.2 Non-native single-TF observation

适用：

```text
1m / 30m / 60m / 1d / 1w
```

只读取当前所选 frequency，复用现有 SuBing Factor math，**不调用 `evaluate_subing_signal()` / `resolve_subing_matched_signal()`**。

每个 MACD 金叉/死叉 observation event 最小字段：

```text
event_id
bar_end
trading_day
contract
segment_start_trading_day
frequency
macd_cross                  # golden | dead
macd_cross_level
macd_zero_distance_abs
macd_zero_distance_bps
close
ema21
price_side                  # above | below | equal
volume
```

不公开 slope threshold、Calibration result、Formal conditions、previous-volume ratio 或 matched direction。

### 7.3 Web presentation

非原生 SuBing：

- 主图继续显示 EMA21；
- MACD 金叉/死叉发生 Bar 显示轻量 marker；
- tooltip 只展示：金/死叉、距 0 轴、价格在 EMA21 上/下、当前成交量；
- 不显示“买/卖”“通过/失败”“强/弱”等综合判断。

## 8. N Structure 设计

### 8.1 Native 5m

`n_structure_5m_v1` exact Policy、Event ID、pivot confirmation、completion、structure state 与 retrospective/OOS identity 完全冻结。

### 8.2 Frequency-neutral formula seam

当前 N 计算链为：

```text
Swing
→ N Pattern
→ Structure
```

阶段二允许把**公式规则本身**从“Policy identity + source timeframe”中机械分离，但不得改变规则值。

建议内部边界：

```text
NFormulaRules
  - breach basis
  - equal breach rule
  - outside/inside handling
  - tie handling
  - completion rule
  - same-boundary ambiguity rule
  - N2/origin break semantics
  - range-band semantics
  - structure semantics

Native N wrapper
  - exact n_structure_5m_v1
  - source_timeframe=5m
  - existing public identity

N Observation wrapper
  - current selected frequency
  - same NFormulaRules
  - observation identity only
```

不为 observation 创建新的 research policy JSON，也不把 outcome horizons 带入主图 observation。`outcome` 是正式研究合同，不是显示 N 结构所必需的部分。

### 8.3 Non-native projection

当前周期 Bars 运行 Swing → Pattern → Structure；Web projection 与现有 5m N overlay 保持同类视觉语义，只投影在**确认/完成 Bar**，不得回标到 pivot/source Bar。

Observation response 不产生 price outcome、rank、score、Candidate 或 OOS 结论。

## 9. JDJ 设计

### 9.1 1m 主图统一使用 Strategy V1

顶部删除独立“日进斗金策略”选项后：

```text
日进斗金 + 1m
→ existing /jdj-strategy/history
→ ENTRY / ADD / REDUCE / EXIT reference markers
```

同时统一显示 EMA20。原 `JDJ Candidate` marker 不再作为 Market 主图 1m 的用户入口；后台 Candidate reducer/evidence/OOS 不变。

正式 Strategy profile 继续精确为：

```text
strategy_id             = jdj_intraday_futures_v1
profile_id              = jdj_active60_1m_v1
execution_frequency     = 1m
trend_context_frequency = 5m
```

所有 risk / quantity / partial-profit / add / daily-pause / daily-stop / session-flatten 语义完全不改。

### 9.2 Non-native 只做 Setup Observation

适用：

```text
5m / 15m / 30m / 60m / 1d / 1w
```

当前所选 frequency 同时承担：

- EMA20 的 price series；
- N Swing/Pattern/Structure observation context；
- JDJ setup trigger series。

不读取第二个 timeframe。

只观察当前三类 setup rule family：

```text
trend_follow
trend_reentry_6
key_level_breakout
```

不产生 Strategy execution action。

### 9.3 JDJ formula seam

现有 `jdj_1m_policy_v1` 继续 immutable。不得直接让现有 reducer 在 30m 时生成带 `*_1m_candidate_v1` 的 Event ID。

建议机械拆分：

```text
JdjSetupRules
  - EMA20 calculation contract
  - previous-bar dynamic trigger / equal rule
  - trend-follow setup state machine
  - trend-reentry-6 setup state machine
  - key-level-breakout setup state machine

Native Candidate wrapper
  - exact jdj_1m_policy_v1
  - existing Candidate IDs and facts

Single-TF Observation wrapper
  - current frequency
  - N observation context from same frequency
  - observation-only IDs
```

正式 Candidate wrapper 必须 exact parity。

### 9.4 Causal strict-before

Single-TF observation 仍必须遵守：当前 Bar 的 JDJ setup 只能消费**上一已完成 Bar boundary 及以前**已经确认的 N Structure / pivot facts。

不得在同一 Bar：

```text
先用当前 Bar 确认 pivot / N structure
再反过来让同一 Bar 形成依赖该事实的 JDJ setup
```

### 9.5 Intraday 与 D1/W1 state scope

- `5m/15m/30m/60m`：setup state 在 trading day 切换时重置；
- `1d/1w`：setup state 在同一 `ResolvedContractSegment` 内连续，换 physical contract / rank1 segment 时重置；
- 两种行为都只是 `jdj_single_tf_observation_v1` 的 projection rule，不改变 Formal JDJ Policy。

### 9.6 Non-native public output

只返回 setup observation：

```text
event_id
observation_version
frequency
setup_kind
direction
observed_at
trading_day
contract
segment_start_trading_day
trigger_level
```

如果某 setup 需要 marker 解释，可增加该 setup 已有、非执行型的最小 source fact，例如 reaction boundary 或 frozen key level；不得带 execution management 字段。

明确禁止输出：

```text
ENTRY / ADD / REDUCE / EXIT
quantity
position_quantity_after
reference fill
PnL / equity
stop_price / target_price
daily pause / daily stop
margin / commission / slippage
```

## 10. HTDY 设计

阶段二不改 HTDY formula、metadata 或风险身份，只把 Web capability frequency 从 `15m` 扩到全部七周期。

继续使用现有 local observation rendering path；不新增 HTDY Historical API。

所有周期继续显示原风险语义：

```text
observation_only
future_looking = true
repainting_accepted = true
historical_backtest_allowed = false
```

`future_dependency_horizon_bars=24` 仍按“Bar 数”解释；在日线/周线上不得改写成天数或额外校准。

阶段二不改变 HTDY Alert：production 仍只看现有 Rule/Scope，非 15m HTDY observation 永远不产生 AlertEvent。

## 11. HTTP 设计

不建立统一 Overlay endpoint。保留现有 source-specific native routes，新增三个窄 observation routes：

```text
GET /api/v1/market/research/subing/observation/history
GET /api/v1/market/research/n-structure/observation/history
GET /api/v1/market/research/jdj/observation/history
```

共同 request shape：

```text
series_kind=actual_dominant
symbol=<active product>
frequency=<allowed non-native frequency>
since=<date>
through=<date>
```

每个 route 自己验证 allowed frequency，不由 generic adapter 决定业务语义。

### 11.1 Common observation metadata

建议每个 response 明确：

```text
observation_only = true
formal_evidence = false
oos_eligible = false
alert_eligible = false
auto_order = false
```

JDJ 额外：

```text
single_timeframe = true
```

### 11.2 Status

Observation response 至少区分：

```text
ready
insufficient_data
```

- `ready + events=[]` 是合法结果，表示当前窗口没有 observation event；
- `insufficient_data` 只用于输入 facts 尚不足以形成该体系最基础计算（例如 EMA/MACD/JDJ EMA readiness）；
- 不为 N 人工发明“至少多少 Bar 才算 ready”的新阈值：source/segment 合法但没有 N completion 时允许 `ready + events=[]`。

身份或 source 失败继续用 typed HTTP error fail-closed。

## 12. Event identity

所有 non-native observation event ID 必须与正式 identity 隔离，并至少包含：

```text
system
observation_version
symbol
physical_contract
segment_start_trading_day
frequency
event-specific identity
```

建议 observation version：

```text
subing_single_tf_observation_v1
n_structure_single_tf_observation_v1
jdj_single_tf_observation_v1
```

禁止复用：

```text
subing_entry_signal_v1
n_structure_5m_v1
jdj_*_1m_candidate_v1
jdj_active60_1m_v1
```

## 13. Web capability 与路由

### 13.1 Overlay ID 收口

`ResearchOverlayId` 最终只有：

```text
none
subing
n_structure
jdj
htdy
```

删除 Web 层 `jdj_strategy` choice；这不删除后端 `/jdj-strategy/history` route。

### 13.2 Frequency-dependent mode resolver

当前 `ResearchOverlayDefinition.historicalSource` 是静态值，无法表达“同一个 JDJ choice 在 1m 走 Strategy、其他周期走 Observation”。

阶段二允许新增一个**仅属于 Web capability routing** 的 resolver，例如：

```text
resolveResearchOverlayMode(overlay, seriesKind, frequency)
```

返回 source-specific mode：

```text
none
subing_native
subing_single_tf_observation
n_native
n_single_tf_observation
jdj_strategy_native
jdj_single_tf_observation
htdy_local_observation
unsupported
```

这不是 Strategy adapter：它不计算公式、不统一 response 业务含义，只决定 Web 应调用哪条现有/新增 source-specific projection。

### 13.3 JDJ 统一 UX

```text
JDJ + 1m
→ /jdj-strategy/history
→ EMA20 + reference action markers

JDJ + other TF
→ /jdj/observation/history
→ EMA20 + setup observation markers
```

### 13.4 状态 Tag

主图附近只显示一个轻量状态：

```text
苏冰 · 5m       原生周期
苏冰 · 30m      单周期观察
N字 · 5m        原生周期
N字 · 60m       单周期观察
日进斗金 · 1m   原生策略
日进斗金 · 30m  单周期观察
火天大有 · 15m 原始观察周期
火天大有 · 60m 单周期观察
```

不得显示“有效”“推荐”“强信号”等研究结论。

## 14. localStorage Preference V4

当前主图偏好是 V3，并可能保存 `jdj` 或 `jdj_strategy`。

阶段二升为 V4：

```text
old jdj          → jdj
old jdj_strategy → jdj
```

其他 overlay、optional EMA、period、realtimeFollow 保留。

V4 之后不保留隐藏的 `jdj_strategy` UI mode。

## 15. Historical / Live 边界

阶段二新增的 SuBing/N/JDJ non-native observation **只消费 confirmed Historical Canonical**。

现有 Historical marker composable 在 `live` mutation 时不重新请求 Historical Research；该原则继续保留。

因此：

```text
confirmed Canonical Bar
→ 可以形成 non-native observation

未确认 Live Bar
→ 不形成新的 non-native SuBing/N/JDJ event
```

阶段二不新增 Live reducer、不接 Redis、不接 Alert Runtime。

HTDY 保持现有 observation-only local display 语义及 repaint 风险提示，不借本阶段扩出新的正式 Live/Research 身份。

## 16. Pagination、warmup 与 deterministic projection

SuBing/N/JDJ observation service 必须：

1. 使用请求 `since..through` probe 当前涉及的真实 rank1 segment；
2. 由 shared loader 回到首个真实 segment 的 `start_trading_day` 加载上下文；
3. 每个 segment 独立计算；
4. 最后只返回 `since..through` 内的 observation events。

这样 `prepend` 更早历史时，已经确认的 later events 不应因为“warmup 起点变了”而重新编号或改写。

Web 继续使用：

- full identity check；
- generation stale-response guard；
- event-id dedupe；
- confirmed coverage intersection。

不得缓存 viewport-local reducer state。

## 17. Error contract

### 17.1 Invalid request / unsupported mode

以下返回 422 typed error：

- 非 `actual_dominant` 调 SuBing/N/JDJ observation；
- symbol shape 非法；
- frequency 不是该 observation route 的 allowed non-native set；
- `since > through`。

### 17.2 Active universe / source / segment identity

以下保持 409 typed error：

- active universe 合同损坏；
- Canonical source unavailable；
- rank1 segment identity 缺失/冲突；
- formula exact native wrapper 自检失败。

禁止 fallback：

```text
actual_dominant → continuous
30m → 15m
1w → 1d
缺 segment → 跨合约拼接
```

### 17.3 Insufficient data

输入身份和 source 均正确，但指标尚未 ready 时返回 200 + `insufficient_data`，Web 显示：

```text
当前周期历史不足，暂无法形成观察
```

不要显示成“系统读取失败”。

## 18. Native parity Gate

阶段二的最高优先级不是“新周期能出 marker”，而是**原生链零漂移**。

### 18.1 SuBing 5m/15m

必须保持：

```text
Event count
Event ID
bar_end
direction
trigger timeframe
same-boundary resolution
lower-TF confirmation
```

### 18.2 N 5m

必须保持：

```text
pivot identity / confirmed_at
completion identity / observed_at
structure state
Event ID
```

### 18.3 JDJ 1m

必须保持阶段一 Golden / parity：

```text
ENTRY / ADD / REDUCE / EXIT
Event ID / Episode ID
reference price
quantity
position quantity
stop / target / reward-risk
daily pause / stop
session flatten
```

### 18.4 HTDY 15m

现有 shared golden 必须继续一致。

任何 native parity 漂移均视为阶段二阻塞，不得以“只是为了全周期观察”接受。

## 19. Causal / prefix invariance Gate

SuBing/N/JDJ non-native observation 必须对已确认历史满足：

```text
projection(full_series) restricted to prefix N
==
projection(prefix_N)
```

并验证：

- 未来 Bar 不能修改此前 SuBing MACD cross identity；
- 未来 Bar 不能修改此前已确认 N completion；
- 未来 Bar 不能让 JDJ 在旧 Bar 上使用后来才确认的 pivot/structure；
- prepend 更早历史只补充更早 event，不改写 later event ID。

HTDY 不适用严格 prefix invariance，因为它明确接受 centered XMA future dependency/repaint；HTDY 继续使用自己的 repaint scan/golden 合同，不能被 SuBing/N/JDJ 的 causal Gate 误判。

## 20. 测试与验收

### 20.1 Unit / formula parity

必须覆盖：

- SuBing native 5/15 unchanged；
- N native 5m unchanged；
- JDJ Candidate/Strategy 1m unchanged；
- HTDY 15m unchanged；
- observation event ID 含 frequency 且不碰正式 identity namespace。

### 20.2 Observation matrix

覆盖七周期的代表性 ready/empty/insufficient cases：

```text
1m / 5m / 15m / 30m / 60m / 1d / 1w
```

尤其覆盖：

- SuBing MACD golden/dead cross 与 zero distance；
- N completion confirmation-bar projection；
- JDJ 5m～60m trading-day reset；
- JDJ 1d/1w segment-continuous state；
- HTDY all-frequency capability；
- rank1 segment rollover reset；
- insufficient indicator history。

### 20.3 API tests

至少验证：

```text
SuBing 5m/15m → native route
SuBing 30m     → observation route
N 5m           → native route
N 60m          → observation route
JDJ 1m         → strategy route
JDJ 30m        → observation route
JDJ 1d/1w      → non-intraday observation state scope
unsupported series/frequency → typed error
```

### 20.4 Web tests

至少覆盖：

- 顶部只剩五个 choice；
- V3 `jdj_strategy` preference 自动迁移为 V4 `jdj`；
- 1m JDJ 请求 Strategy endpoint；
- 非 1m JDJ 请求 Observation endpoint；
- SuBing/N native 与 observation mode 正确路由；
- HTDY 七周期均可选择；
- rapid symbol/frequency/overlay switch 不接受 stale response；
- prepend 历史后 event-id dedupe 正确。

### 20.5 Active60 read-only acceptance smoke

实现完成后需要一次有界 read-only capability smoke，目标是验证当前 active universe 不存在 per-product admission 漏洞或 frequency routing 漏洞。

该 smoke：

- 不建立 batch API、仓库内 batch service 或持久化 artifact；
- 可以由仓库外 shell loop 逐行读取 `active_products.txt`；
- 使用短固定窗口；
- 对 SuBing/N/JDJ observation 记录 `ready | insufficient_data | typed_unavailable | command_failed`；
- 允许业务上合理的 `insufficient_data`，但 `unsupported`、identity drift、silent fallback 和 command crash 必须为 0；
- HTDY 的 all-frequency coverage 主要由 unit/Web matrix 与 existing kernel golden 验证，不需要为了本阶段新增后端 batch endpoint。

该 smoke 只证明 capability coverage，不形成策略有效性、ranking 或 OOS 结论。

## 21. 推荐实现顺序

本 Design 只定义依赖顺序，不替代后续 writing-plans：

```text
1. Web capability contract + JDJ choice 收口 + preference V4
2. SuBing single-TF observation
3. N formula seam + all-frequency N observation + 5m parity
4. JDJ setup-rule seam + single-TF observation + 1m parity
5. HTDY all-frequency capability + 四体系统一 Web presentation
6. Full regression + causal/parity Gate + active60 read-only smoke + canonical closeout
```

N 必须先于 JDJ，因为 non-native JDJ observation 依赖同周期 N context。

## 22. 明确禁止范围

阶段二不得顺手实现：

- SuBing 非原生买/卖综合信号；
- 新 Alert Rule 或现有 Alert Scope/transport 变化；
- N Alert / JDJ Alert；
- 新 Candidate / 新 OOS protocol；
- 新 Strategy profile；
- per-frequency threshold tuning；
- per-product parameter override；
- RQAlpha adapter 扩展；
-正式 backtest engine；
- PnL / score / rank / winner / KEEP / DROP / PROMOTE；
- DB/Redis observation persistence；
- worker/queue/scheduler/cache；
- main/tag/release/Runtime promotion；
- 真实通知、正式数据或 production DB mutation；
- 自动订单。

## 23. Canonical closeout 要求

代码实现和完整验收通过后，再更新 active canonical：

- `PROJECT_SOURCE.md`：四体系 active60 七周期观察能力、native vs observation 边界、JDJ 单入口；
- `DECISIONS.md`：记录“non-native single-TF observation 不改变 formal identity”的长期决策；
- `STATUS.md`：只记录真实实现、测试和 read-only smoke 结果，不提前宣布 release/Runtime-ready；
- 相关 active OpenSpec：只有实际 executable behavior 属于现有 active spec 职责时才更新；不得为了保存过程恢复已退役的 task/spec 治理面。

设计文档本身不是 current status，也不授权任何外部 mutation。

## 24. 完成定义

阶段二只有同时满足以下条件才可声明完成：

1. Market 顶部固定为：
   `无｜苏冰｜N字｜日进斗金｜火天大有`；
2. 当前 active60 任意产品可以在正式七周期切换四体系 capability；
3. SuBing 5/15、N 5m、JDJ 1m、HTDY 15m native facts 零漂移；
4. 非原生 SuBing 不产生 Formal Signal；
5. 非原生 N 不产生 Candidate/OOS identity；
6. 非原生 JDJ 不产生 reference execution 或 Strategy action；
7. 非 15m HTDY 不改变 Alert scope；
8. SuBing/N/JDJ observation 满足 segment identity、strict-before 与 prefix-invariance Gate；
9. 无跨频 fallback、跨合约 memory、viewport-start drift 或 stale response；
10. active60 read-only capability smoke 无 unsupported/identity drift/silent fallback/command crash；
11. 未触碰 Alert、Runtime、release、正式写入或订单路径。

## 25. Lane 与下一 Gate

本阶段涉及 N/JDJ 公式 seam、正式 Policy wrapper parity、future-leakage/strict-before 与 Strategy identity，因此后续 implementation planning 和实现均按 **Lane 3** 对待。

推荐后续调度：

```text
Sol + 高推理
新会话
Plan-only
独立 Review
人工批准后实现
```

本 Spec 提交后仍需用户 Review。只有用户明确批准本文件后，才进入 Superpowers `writing-plans`；不得在本次设计提交中直接开始实现。
