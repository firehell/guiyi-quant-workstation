# 苏冰 Factor → Signal 研究与盘中观察 V1 Design

Final design：2026-08-13  
Review baseline：`develop@42ffb26ad53cb3187705ed8236b197f14b1c6904`

## 1. Purpose

本设计定义归一量化下一阶段“苏冰”研究能力的 V1 边界。

目标不是恢复旧 Strategy/Backtest，也不是建设通用 Factor 平台，而是在已经冻结的 Data Foundation、Market Research Workspace、Indicator Kernel 和 Market Runtime seam 之上，用最小新增面完成：

```text
Indicator
→ Factor
   ├─ Product Workspace observation
   └─ Calibration Research
          ↓
   approved policy/calibration
          ↓
        Signal
          ↓
   Live human validation
          ↓
   Future Alert V2
```

V1 第一阶段只做**入场方向信号**。系统负责在研究阶段把参数分析前置；盘中只在 completed K 上执行已经冻结的确定性规则，输出 `LONG / SHORT / NONE`。不承担持仓、退出、8K 管理、加减仓、反手、资金、订单或自动交易。

长期原则继续是：

```text
AI 可以辅助研究，但不能自动晋升规则。
信号和通知是人工观察，不是自动交易指令。
auto_order=false。
```

---

## 2. Repository Baseline

当前基线已经满足：

- active universe 60/60 Canonical 闭环完成；
- Historical 唯一事实链为 `Canonical Parquet -> eight-table Catalog -> MarketDataService`；
- 物理 Dataset 只有 `continuous | contract`；`actual_dominant` 只是按 `MainContractMap rank1` 查询拼接；
- Redis Live Overlay 与 Historical Canonical 分离；Live 永不提升为 Canonical；
- Market Research Workspace P0 已存在 Radar、Product Workspace、固定 Kline + Volume + MACD、Product Research；
- Indicator Kernel 是基础指标唯一业务权威；
- Alert V1 已完成独立 HTDY 15m 代码面和 production migration，但真实 WeCom canary 与 Alert Runtime activation 仍是独立 Gate。

本设计不得修改 Data Foundation 的 DatasetKey、八表 Catalog、Canonical 语义、月分区模型或 Historical Gateway。

---

## 3. Core Concept Model

### 3.1 Indicator

Indicator 是基础数学计算，权威仍在：

```text
packages/quant-core/guiyi_quant/indicators/
```

苏冰 V1 复用：

```text
EMA21
MACD
```

不注册一个假的 `subing` Indicator，也不复制 EMA/MACD 算法。

### 3.2 Factor

Factor 是从指标和 K 线派生出来、用于描述市场状态的连续或离散研究特征。

V1 仅保留：

```text
price_vs_ema21
ema21_slope_5_bps
ema21_slope_10_bps
macd_cross
macd_zero_distance_abs
macd_zero_distance_bps
volume_ratio_prev
timeframe_alignment
```

Factor 先保留原始值，不提前压成 `true/false`。例如 slope、zero distance 和 volume ratio 必须保留原值，以支持后续 Calibration 和复盘重算。

### 3.3 Signal

Signal 是经过人工批准的 `SubingSignalPolicy + Calibration` 对 Factor 的确定性判断。

输出固定：

```text
LONG
SHORT
NONE
RESEARCH_PENDING
INSUFFICIENT_DATA
```

V1 不做 score、星级、置信度或综合分数。

### 3.4 Strategy

Strategy 当前不实现。

下列语义只保留在未来 Strategy 研究范围，不进入 V1 executable surface：

```text
EMA21 退出
8K 硬退出
止损 / 止盈
持仓状态
加减仓
反手
仓位和资金管理
完整交易级回测
```

只有未来确实需要系统化管理一笔持仓或完整回测时，才新立项 `Signal -> Strategy`。

---

## 4. Architectural Boundary

最终结构：

```text
                    Indicator Kernel
                    EMA21 / MACD
                          │
                          ▼
               SubingFactorSnapshot
                   │             │
                   │             └─────> Product Workspace
                   │
                   └─────> Calibration Research
                                  │
                                  ▼
                         approved calibration
                                  │
                                  ▼
               SubingSignalEvaluation
                          │
                          ▼
                  Signal Resolver
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        Product Workspace        Future Alert V2
                                  existing Alert Domain
```

后端保持 Functional Core + Imperative Shell：

```text
MarketResearchService
    ↓ 负责读取、identity、Historical/Live orchestration
subing_research.py
    ↓ zero I/O pure calculation
Factor / Signal
```

禁止新增：

```text
SubingRepository
SubingDB
SubingRedis
SubingWorker
SubingScheduler
SubingWebSocket
FactorStore
FactorRegistry
FactorExpressionEngine
RuleEngine
StrategyEngine
Research Memory DB
```

只有第二个真实 consumer 出现并产生稳定重复代码后，才提取共享 research primitive；不得为了“通用性”提前建设 Factor 平台。

---

## 5. Current Dominant Contract Identity

### 5.1 User-facing identity

用户在苏冰模式只选择品种，例如：

```text
JM 焦煤
当前主力 JM2609
```

用户不选择 `series_kind`，也不选择具体 contract。

### 5.2 Calculation identity

苏冰 V1 的 Kline、EMA21、MACD、Slope 和 Live 全部使用**当前 rank1 真实合约自身历史**：

```text
symbol JM
↓
MainContractMap latest rank1
↓
JM2609
↓
SeriesKind.CONTRACT / JM2609
↓
JM2609 Canonical + JM2609 completed Live
```

禁止直接对拼接后的 `actual_dominant` 序列递推 EMA/MACD。

原因：主力换月存在价格跳差，跨 `JM2609 -> JM2610` 递推 EMA/MACD 会制造假 slope / 假 cross。

### 5.3 Historical Calibration identity

历史 Calibration 仍研究“当时的主力品种”，但指标必须 contract-local：

```text
actual_dominant query
↓
resolved_contract_segments
↓
每个 rank1 segment 识别真实 contract
↓
单独读取该 contract 自身含 warm-up 的历史
↓
计算 EMA/MACD/Slope
↓
只保留该 contract 真正处于 rank1 日期区间内的样本
```

`actual_dominant` bars 可以用于解析 rank1 segment，但不得用于跨 segment 指标递推。

---

## 6. Supported Frequencies

苏冰 V1 只支持：

```text
1d
5m
15m
```

其中：

```text
1d  -> Historical Factor / Signal Research + Web
5m  -> Historical + completed Live Observation + future Alert
15m -> Historical + completed Live Observation + future Alert
```

1m / 30m / 60m / 1w 不产生苏冰 V1 Signal。

Market Web 自身仍可保留七周期行情能力；苏冰只是对当前 unsupported frequency 显示不可用，不改变用户的 overlay selection。

---

## 7. Factor Contract

### 7.1 `SubingFactorSnapshot`

建议内部概念字段：

```text
timeframe
bar_end
trading_day
contract
bar_source

close
ema21
price_side

slope_fast_window = 5
slope_slow_window = 10
slope_5_raw
slope_10_raw
slope_5_bps_per_bar
slope_10_bps_per_bar

macd_dif
macd_dea
macd_histogram
macd_cross
macd_cross_level
macd_zero_distance_abs
macd_zero_distance_bps

volume
previous_volume
volume_ratio_prev
```

`price_side`：

```text
ABOVE | BELOW | EQUAL | UNAVAILABLE
```

`macd_cross`：

```text
GOLDEN | DEAD | NONE | UNAVAILABLE
```

Factor Snapshot 不输出 `qualified / entry / buy / sell / flat`。

### 7.2 Slope definition

对最近 N 个 EMA21：

```text
x = 0 ... N-1
y = EMA21 values
```

使用普通最小二乘：

```text
EMA21 ≈ a + b*x
```

`b` 为 raw slope per bar。

归一化：

```text
slope_bps_per_bar = b / mean(EMA21 window) * 10000
```

V1 同时计算 5K 与 10K：

```text
5K  -> 最近变化、走平或拐头观察
10K -> 背景方向
```

`FLAT` 不属于 Factor，而属于 Calibration 后的 Signal 判定。

### 7.3 MACD cross / zero distance

Golden：

```text
prev DIF <= prev DEA
AND current DIF > current DEA
```

Dead：

```text
prev DIF >= prev DEA
AND current DIF < current DEA
```

交叉确认 K 上：

```text
cross_level = (DIF + DEA) / 2
zero_distance_abs = abs(cross_level)
zero_distance_bps = abs(cross_level) / close * 10000
```

不反推未观测的 K 内交叉时刻。

### 7.4 Volume factor

```text
volume_ratio_prev = current_volume / previous_volume
```

若 previous volume <= 0，则 unavailable；不得补零、无穷大或静默替代。

---

## 8. Policy and Calibration

### 8.1 `SubingSignalPolicyV1`

只保存已经明确的方法规则，例如：

```text
EMA21
slope windows = 5 / 10
intraday volume ratio = 3.0
daily volume confirmation ratio = 1.0
intraday timeframes = 5m / 15m
same-boundary resolution = higher timeframe wins
```

基础 EMA/MACD 算法引用 Indicator Kernel 的 policy/version，不在苏冰里复制参数和实现。

### 8.2 `SubingCalibration`

只保存尚需研究和人工批准的阈值：

```text
slope_flat_threshold
macd_zero_band
```

第一版：

```text
calibration = pending
```

则对应条件返回 `RESEARCH_PENDING`，不得人为填入一个“差不多”的阈值以制造可运行 Signal。

### 8.3 Scope

Slope 第一轮优先研究 timeframe-wide threshold：

```text
5m 一个候选
15m 一个候选
1d 一个候选
```

只有真实证据表明少量品种长期不适用时，才允许 product override。

MACD zero-band 第一轮按：

```text
product × timeframe
```

研究，并同时比较 absolute / normalized distance 是否能降低参数数量。

### 8.4 MACD capability Gate

当前 MACD 仍属于已有兼容/展示口径，不得因为苏冰开始使用它，就隐式宣布其已经获得正式 Signal/Live/Alert 资格。

V1 可以先用明确记录的 MACD policy/version 做 Historical/Live **Factor observation**，但在 `SubingSignalEvaluation` 可以把结果晋升为正式 `LONG / SHORT` 之前，必须完成一个独立的 Lane 3 语义审查：

```text
确认 Python MACD policy/version
确认 confirmed 1d/5m/15m 计算口径
补充 golden / edge tests
确认 Historical 与 completed Live 同口径
同步 Indicator deep canonical / registry capability（如实现合同需要）
```

该 Gate 未完成时，即使 Calibration 数值已经存在，也只能保持 research-only，不得接 Alert V2。

---

## 9. Signal Semantics

### 9.1 Condition state

内部条件统一：

```text
PASS
FAIL
RESEARCH_PENDING
UNAVAILABLE
NOT_APPLICABLE
```

Signal 状态优先级：

```text
必需数据缺失
→ INSUFFICIENT_DATA

任一已知硬条件 FAIL
→ NONE

所有已知条件通过，但 Calibration / capability Gate 未冻结
→ RESEARCH_PENDING

所有必需条件通过
→ LONG / SHORT
```

### 9.2 Daily

日线 Required：

```text
price side
slope
MACD cross
MACD zero-band
```

成交量 `>= previous day` 只作为增强确认，不是 hard gate。

日线 V1 不接企微，只保留 Research/Web。

### 9.3 Intraday 5m / 15m

Primary timeframe 必需：

```text
price side
slope
MACD cross
MACD zero-band
volume_ratio_prev >= 3
companion timeframe direction alignment
```

Companion timeframe 只承担：

```text
price / EMA21 direction
slope direction
```

不要求 companion 同时 MACD cross 或 3x volume。

### 9.4 5m/15m behavior

5m 可独立触发，只要求 15m 方向/斜率一致。

15m 也可以独立触发，只要求最新 confirmed 5m 方向/斜率一致；5m 不必同时有完整 trigger。

方向冲突直接 `NONE`。

### 9.5 Same-boundary resolver

若同一 `bar_end`：

```text
5m full LONG
15m full LONG
```

只输出：

```text
LONG
trigger_timeframe = 15m
lower_tf_confirmation = true
resolution = HIGHER_TIMEFRAME_WINS
```

SHORT 同理。

不得重复生成两笔 Signal/Alert。

---

## 10. Confirmed-bar and Lookahead Rules

所有正式 Factor/Signal 只消费 confirmed bars。

多周期对齐：

```text
companion.bar_end <= primary.bar_end
```

绝不能读取更晚的 companion bar。

5m primary：读取最新 confirmed 15m <= T。

15m primary：读取最新 confirmed 5m <= T。

partial Live bar 永不进入 Factor / Signal；即使 partial bar 暂时出现 3x volume 或 MACD 假 cross，也必须忽略。

---

## 11. Live Observation

### 11.1 Existing seam reuse

不新增苏冰 Runtime 数据链。

复用：

```text
LiveMarketService
→ completed 1m
→ existing 5m / 15m aggregation
→ Redis Live Overlay
→ MarketReadService
```

苏冰核心只接受 bars，不知道 Redis。

### 11.2 Current contract only

盘中只观察当前 rank1 真实合约。

如果 Historical current dominant 与 Live subscription contract 不一致：

```text
Historical 可显示
Live Signal fail-closed
reason = contract mismatch
```

绝不能把两个 contract 拼在一起计算指标。

### 11.3 Refresh

Web 不新增第二条 WebSocket。

沿用现有 completed Live bar event 作为 refresh trigger：

```text
new completed primary bar
→ refresh Subing snapshot
```

5m/15m 同一 boundary 上可能出现极短的派生先后顺序差异；若 5m 已到而 15m companion 仍旧，Web 允许一次 bounded delayed refresh，不 polling、不加事务、不加锁。

### 11.4 Live failure

Live unavailable 时不返回 500，不伪装 realtime：

```text
source = canonical only
live_observation = unavailable
```

Historical 仍可读。

---

## 12. Product Workspace UI

### 12.1 Overlay is single-select

主图研究 Overlay：

```text
无
苏冰
火天大有
```

单选，默认苏冰。

苏冰与 HTDY 不允许同时叠加。

### 12.2 SuBing visual

主图：

```text
Kline + EMA21
```

副图继续固定：

```text
Volume
MACD
```

V1 不做：

```text
历史苏冰 signal marker series
EMA21 全历史 slope 分段染色
主图 slope 数字铺满
综合 score
```

### 12.3 Top status strip

顶部只回答“现在值不值得进一步看”，例如：

```text
苏冰 · Live观察 · 10:25
5m ↑ / 15m ↑ · 共振
MACD 金叉 · 距零轴 8.3 · 量 3.42x
已知条件通过 · 研究参数待冻结
```

### 12.4 Research Sidebar

沿用现有 Product Research Sidebar，不新建第二侧栏。

顺序：

```text
苏冰观察
趋势 / 位置
量与持仓
合约 / Runtime
```

苏冰详情显示 Factor value、condition result、primary/companion confirmed time，但不把内部枚举直接暴露给用户。

### 12.5 Unsupported frequency

用户选择苏冰后切到 30m/60m 等 unsupported frequency：

```text
selected_overlay = subing
available_for_current_frequency = false
```

不自动改成“无”，但明确显示苏冰 V1 只支持 5m/15m/1d。

---

## 13. Calibration Research

Calibration 是轻量 Factor Research，不是 Factor Platform，也不是 Backtest。

### 13.1 Research outputs

对历史样本计算：

```text
directional return 3K / 5K / 8K
MFE 3K / 5K / 8K
MAE 3K / 5K / 8K
EMA21 failure within 3K / 5K / 8K
```

这些 future labels 只用于离线研究，永不进入实时 Factor。

### 13.2 Intraday horizon

5m / 15m 的 3/5/8K outcome 严格不跨 `trading_day`。

当日剩余 K 不够：

```text
对应 horizon = unavailable
```

不能拿下一交易日补齐。

### 13.3 Slope calibration first

顺序固定：

```text
Slope Calibration
→ 人工冻结 candidate
→ MACD Zero-Band Calibration
```

禁止同时优化 slope + zero-band。

Slope report 输出 bucket/distribution、样本数、后续结果和候选阈值，不输出“最佳参数”并自动采用。

### 13.4 MACD zero-band research

至少比较：

```text
Cohort A = all confirmed MACD crosses
Cohort B = 除 zero-band 外其他 SuBing 条件已经成立的 crosses
```

报告按 zero distance bucket 比较 3/5/8K outcome。

### 13.5 Discovery / Validation

参数研究必须时间分离：

```text
Discovery
→ candidate frozen
→ later-period Validation
```

同一时间段不得既选 threshold 又宣称 threshold 有效。

候选一旦因为验证结果再次调整，必须形成新的 candidate version 再验证。

### 13.6 Storage

不建研究 DB，不长期保存 raw factor samples。

批量研究采用有界 chunk + streaming aggregate，完成后释放 raw rows。

未来唯一值得版本化保存的是：

```text
人工批准的最小 SubingCalibration
```

而不是可以从 Canonical 重算的历史 Factor 值。

---

## 14. Alert Integration Boundary

### 14.1 V1 current Alert is unchanged

当前 Alert V1 是 HTDY 15m 专用窄应用：

```text
htdy_original_15m
→ current-bar evaluator
→ AlertEvent
→ WeCom
```

苏冰 Factor/Signal 开发阶段不得修改：

```text
alert_rules
alert_events
AlertRuntime
HTDY evaluator
WeCom sender
真实 Alert Runtime 状态
```

### 14.2 Future Alert V2

只有 Calibration 人工批准、MACD capability Gate 完成、Signal 稳定且完成一段 Live 人工观察后，才新立项：

```text
Alert V2 — SuBing Entry Signal Integration
```

未来应复用：

```text
server-side Scope
AlertEvent idempotency
Web historical marker
WeCom sender
Runtime health
activation Gate
```

而不是创建 `SubingAlertService/SubingAlertEvent/SubingWeComSender`。

### 14.3 Do not fake indicator identity

苏冰不是 Indicator。

未来 Alert V2 不应为了兼容当前 `indicator_code` 语义，把 `subing_entry_v1` 冒充 Indicator。需要时允许做一个小而正确的 Alert rule model 调整，但该 migration 属于未来独立设计和真实 Gate。

未来 Signal rule 应采用版本化、不可原地改变语义的 rule identity，保证 `AlertEvent -> rule -> 当时 policy/calibration` 可以复算；具体表结构留给 Alert V2 独立设计。

### 14.4 V1 message scope

第一版未来企微只接：

```text
5m completed Live entry signal
15m completed Live entry signal
```

1d 只保留 Factor/Signal Research 与 Web，不接企微。

企微消息应极简，例如：

```text
【苏冰】JM2609 · 5m
买入信号 · 10:25
```

同刻大周期优先时可补：

```text
5m 同向共振
```

不发送 slope、MACD、volume 等完整分析过程。

系统仍不下单，由用户人工决定处理。

---

## 15. Error / Fail-closed Model

### Request error

非法 symbol / unsupported frequency：HTTP 422。

### Market data error

例如：

```text
current dominant missing
contract canonical missing
partition/mapping invalid
```

复用 MarketDataService 稳定错误码并 fail-closed，不 fallback 到 continuous/other contract/previous dominant。

### Research state

下列属于正常 200 research state：

```text
warm-up insufficient
companion unavailable
calibration pending
MACD capability pending
```

使用：

```text
INSUFFICIENT_DATA
RESEARCH_PENDING
```

### Live unavailable

Historical 保持可读，Live 明确 unavailable，不把旧状态伪装成最新 Live。

---

## 16. Performance

### Realtime Snapshot

当前单用户、单品种页面，按需读取约：

```text
primary ~300 bars
companion ~300 bars
```

执行 EMA21/MACD/Slope/Volume/Signal，5m 最多约每 5 分钟刷新一次。

V1 不需要：

```text
SuBing Redis cache
background precompute
feature cache
1s/10s polling
```

只有真实 profiling 证明性能不足时再做最小优化。

### Calibration

60 品种长历史必须有界处理，不构造全市场巨型内存表。

按：

```text
frequency
→ product
→ bounded time chunk
→ rank1 segment
→ contract-local calculation
→ aggregate
→ discard raw rows
```

---

## 17. Required Tests

必须覆盖：

```text
Factor deterministic calculation
Slope 5K/10K regression + bps/bar
MACD confirmed cross + zero distance
MACD Historical/completed-Live policy parity
Volume invalid denominator
Signal condition priority
5m / 15m companion alignment
same-boundary 15m wins
no future companion
partial-bar poison
rank1 rollover poison
contract-local indicator warm-up
Historical/Live contract mismatch
Canonical + completed Live seam
3/5/8 intraday labels do not cross trading_day
Discovery / Validation time separation
Web overlay single-select
unsupported frequency state
HTDY repaint warning regression
Alert V1 untouched regression
```

两个关键 poison tests：

1. **Rollover poison**：用明显价差的两个合约证明换月后 EMA/MACD 使用新 contract 自身 warm-up，绝不延续旧 contract 状态；
2. **Partial-bar poison**：partial K 即使临时出现 3x volume / MACD cross，Signal 仍停留在上一 completed K。

普通实现验证继续以仓库 `TESTING.md` 为准，至少包含定向 pytest、Ruff、Mypy、Web tests/build 和受影响 Live/Market regression。

---

## 18. Development Sequence

设计批准后，实施仍拆小，不一次完成全部能力：

```text
S0  SuBing Factor Core
    Factor / Policy / pending Calibration / pure tests

S0.5 MACD confirmed-research capability review
    Historical/completed-Live parity + golden/edge tests
    不晋升 Signal，只确认 Factor observation 的可信口径

S1  Current-rank1 Factor Snapshot
    contract-local Historical + completed Live + multi-TF

S2  Product Workspace Factor Observation
    无/苏冰/火天大有单选 + EMA21 + Factor details
    Signal 仍可保持 RESEARCH_PENDING

S3  Factor Calibration — Slope
    3/5/8 labels + discovery/validation + candidate only

Gate
    人工批准 slope candidate

S4  Factor Calibration — MACD Zero-Band
    abs/normalized + product×timeframe + OOS

Gate
    人工批准 zero-band candidate
    + MACD formal Signal capability Gate

S5  SuBing Entry Signal
    LONG/SHORT/NONE + 5m/15m resolver
    Web 展示，但仍不接 Alert V1

Observation period
    人工盘中使用和复盘

Future independent task
    Alert V2 — SuBing Entry Signal Integration
```

如果实现过程中发现 Slope / Zero-Band 或 MACD capability 尚无法冻结，则 Signal 保持 `RESEARCH_PENDING`，不得为了“功能完整”自行选择阈值或放宽 capability。

---

## 19. Lane / Gate Guidance

涉及 Factor 公式、Signal semantics、multi-timeframe causality、MACD capability、Calibration/OOS 的任务属于可信研究口径：

```text
Lane 3
Sol
高推理
Plan-only before implementation
independent review
```

普通 Web 展示实现可单独作为 Lane 2。

代码进入 `develop` 不代表：

```text
Calibration approved
MACD Signal capability approved
Signal promoted
Alert enabled
Runtime switched
main/tag released
```

这些 Gate 互不授权。

---

## 20. Acceptance Definition

苏冰 V1 研究能力完成，只证明：

1. 当前品种自动解析当前 rank1 真实合约；
2. Kline/EMA/MACD/Slope 使用同一真实 contract，不跨换月递推；
3. 1d/5m/15m Factor 由 Python authoritative core 计算；
4. 5m/15m 盘中只消费 completed Live bars；
5. multi-timeframe 不使用未来 companion；
6. raw Factor value 与 Signal gate 分离；
7. Calibration / capability 未批准时明确 `RESEARCH_PENDING`；
8. Signal 仅输出入场方向，不承担持仓/退出；
9. 5m/15m 同刻 full signal 只保留 15m 一条；
10. Web 为 `无 / 苏冰 / 火天大有` 单选；
11. 不新增研究 DB/Redis/worker/scheduler/WebSocket/Factor platform；
12. 不修改 Data Foundation；
13. 当前 Alert V1 保持原样；
14. 未来企微接入必须作为独立 Alert V2，且只接 5m/15m entry signal；
15. `auto_order=false` 始终成立。

本设计不证明盈利、参数长期稳定、Strategy Ready、Backtest Ready、Alert Ready、Runtime Ready 或 release Ready。

---

## 21. Final Design Statement

苏冰 V1 的最终定位：

> **一个基于当前 rank1 真实合约、只使用 confirmed Historical/Live Bar 的轻量 Factor → Signal 研究能力。可重算的 Factor 不长期存储；参数检验和 OOS 全部前置；盘中只执行人工批准后的确定性入场方向规则。第一阶段不建设 Strategy，不建设通用 Factor 平台，也不接现有 Alert V1。未来若验证成熟，再以独立 Alert V2 复用现有 Scope/Event/WeCom/Runtime 基础设施发送 5m/15m 入场方向信号。**
