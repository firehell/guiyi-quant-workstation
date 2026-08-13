# 苏冰 Factor → Signal 研究与盘中观察 V1 Design

Final design：2026-08-13  
Review baseline：`develop@1f6d8a300136be1539bb4c2d498955a9ea01e3cf`（本轮 Spec review 前）

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

V1 第一阶段只做**入场方向信号**。系统负责在研究阶段把参数分析前置；盘中只在 completed K 上执行已经冻结的确定性规则。不承担持仓、退出、8K 管理、加减仓、反手、资金、订单或自动交易。

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
- 当前 contract Canonical 的维护范围只覆盖该 contract 实际被 `MainContractMap` 映射为 rank1 的交易日，不假设保存其完整上市生命周期；
- Redis Live Overlay 与 Historical Canonical 分离；Live 永不提升为 Canonical；
- Market Research Workspace P0 已存在 Radar、Product Workspace、固定 Kline + Volume + MACD、Product Research；
- `MarketResearchService` 当前是 Historical-only 的 P0 研究读模型，不承担 Redis Live seam；
- `MarketReadService` 是既有 Historical/Live 展示 seam；
- Indicator Kernel 是基础指标唯一业务权威；
- Alert V1 已完成独立 HTDY 15m 代码面和 production migration，但真实 WeCom canary 与 Alert Runtime activation 仍是独立 Gate。

本设计不得修改 Data Foundation 的 DatasetKey、八表 Catalog、Canonical 语义、月分区模型、contract rank1-day coverage 语义或 Historical Gateway。

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

Factor 是从指标和单一 timeframe confirmed K 线派生出来、用于描述市场状态的连续或离散研究特征。

V1 单周期 Factor 仅保留：

```text
price_vs_ema21
ema21_slope_5_bps
ema21_slope_10_bps
macd_cross
macd_zero_distance_abs
macd_zero_distance_bps
volume_ratio_prev
```

Factor 先保留原始值，不提前压成 `true/false`。例如 slope、zero distance 和 volume ratio 必须保留原值，以支持后续 Calibration 和复盘重算。

`timeframe_alignment` **不属于单周期 Factor**。它是两个 `SubingFactorSnapshot` 之间的关系，只在 Signal Evaluation 阶段按 primary/companion 的方向事实计算。

### 3.3 Signal

Signal 是经过人工批准的 `SubingSignalPolicy + accepted SubingCalibration` 对 Factor 和 multi-timeframe relationship 的确定性判断。

`SubingSignalEvaluation` 必须分离两个维度：

```text
status:
  MATCHED
  NOT_MATCHED
  RESEARCH_PENDING
  INSUFFICIENT_DATA

direction:
  LONG
  SHORT
  NONE
```

禁止把 `LONG/SHORT/NONE` 与 `RESEARCH_PENDING/INSUFFICIENT_DATA` 混成一个枚举。

只有：

```text
status == MATCHED
AND direction in (LONG, SHORT)
```

才构成可供 Future Alert V2 消费的正式入场方向 Signal。

在 `RESEARCH_PENDING` 状态下，如果已知事实足以判断候选方向，可以保留 `direction=LONG|SHORT` 供 Web 研究展示，但它仍不是正式 Signal，任何 Alert consumer 都必须以 `status == MATCHED` 为硬 Gate。

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
                       subing_research.py
                       zero I/O pure core
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
          SubingFactorSnapshot   SubingSignalEvaluation
                    ▲                     ▲
                    │                     │
                    └──────────┬──────────┘
                               │
                       SubingReadService
                       thin application seam
                         │              │
              ┌──────────┘              └──────────┐
              ▼                                    ▼
      MarketDataService                    MarketReadService
  dominant / segment / history          Historical + Live seam
              │                                    │
              └──────────────┬─────────────────────┘
                             ▼
                     Product Workspace
                             │
                    Calibration Research
                             │
                   accepted calibration
                             │
                             ▼
                         Signal
                             │
                      Future Alert V2
```

### 4.1 `SubingReadService`

V1 允许新增一个**薄的、无持久化的 `SubingReadService`**，因为苏冰需要 current-rank1、segment boundary、primary/companion 与 Historical/Live orchestration，而这些职责既不属于 pure Factor core，也不应污染现有 Historical-only `MarketResearchService`。

`SubingReadService` 只允许：

```text
复用 MarketDataService 解析 current dominant / historical rank1 segment
复用 MarketReadService 获取 contract Historical + completed Live seam
准备 primary / companion confirmed bar windows
调用 subing_research.py
组装 SuBing read snapshot
```

它不得：

```text
直接读 Parquet
直接读 Redis
直接调 RQData
写 DB
写 Canonical
新增缓存
新增 worker/scheduler/websocket
修改 MarketResearchService 的 P0 Historical-only 合同
```

这是为保持 SRP 而增加的窄应用 seam，不是新平台。

### 4.2 Functional Core + Imperative Shell

```text
SubingReadService
    ↓ I/O orchestration
subing_research.py
    ↓ zero I/O pure calculation
Factor / relationship / Signal
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

## 5. Current Dominant Contract and Rank1 Segment Identity

### 5.1 User-facing identity

用户在苏冰模式只选择品种，例如：

```text
JM 焦煤
当前主力 JM2609
```

用户不选择 `series_kind`，也不选择具体 contract。

### 5.2 Calculation identity

苏冰 V1 的 Kline、EMA21、MACD、Slope 和 Live 全部使用**当前 rank1 真实合约在当前 rank1 segment 内已经存在的 Canonical + completed Live bars**：

```text
symbol JM
↓
MainContractMap latest rank1
↓
JM2609
↓
current rank1 segment start
↓
SeriesKind.CONTRACT / JM2609
↓
segment-local Canonical + JM2609 completed Live
```

禁止直接对拼接后的 `actual_dominant` 序列递推 EMA/MACD。

也禁止假设 Canonical 中存在 JM2609 成为 rank1 **之前**的完整合约历史。当前 Data Foundation 的 contract Dataset 只覆盖该 contract 被映射为 rank1 的交易日，因此苏冰不得为了 warm-up 绕过 `MarketDataService` 调 RQData，也不得修改 Data Foundation 去补一套完整生命周期 contract 数据。

### 5.3 Rank1-segment-local warm-up

换月后新主力 segment 从自己的第一根 rank1 Canonical bar 开始重新 warm-up：

```text
old rank1 segment
    X 不继承 EMA/MACD state
new rank1 segment
    ↓
只使用 new segment 内 confirmed bars
    ↓
warm-up 不足 -> INSUFFICIENT_DATA
    ↓
warm-up 完成 -> Factor / Signal 可用
```

warm-up 所需 bars 不在 SuBing 里硬编码一个随意常量，而应由 Indicator Kernel 的 `calculation_basis.warmup_bars`、Slope 5/10 窗口以及 MACD cross 需要前一 ready point 的依赖共同推导。

换月后出现一段短暂无 Signal 的窗口是正确的 fail-closed 行为，不允许使用：

```text
上一主力 indicator state
continuous 序列
另一个 contract
pre-rank1 provider 临时数据
```

来填补。

### 5.4 Historical Calibration identity

历史 Calibration 仍研究“当时的主力品种”，但指标计算必须 **rank1-segment-local**：

```text
actual_dominant query
↓
resolved_contract_segments
↓
每个 segment 识别真实 contract 与 rank1 日期边界
↓
读取该 contract 在该 segment 内已有 Canonical
↓
segment-local EMA/MACD/Slope warm-up
↓
只保留 warm-up 完成后、且仍位于该 rank1 segment 内的样本
```

`actual_dominant` bars / `resolved_contract_segments` 只用于解析 rank1 segment identity；不得把跨 segment 的 bars 用于 EMA/MACD/Slope 递推。

segment 开头因 warm-up 不足产生的历史样本直接 unavailable，不向 segment 之前读取补齐。

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

5m/15m 是第一优先业务轨；1d calibration 与 Signal research 不阻塞 intraday Signal 的成熟和验收。

---

## 7. Factor Contract

### 7.1 `SubingFactorSnapshot`

建议内部概念字段：

```text
timeframe
bar_end
trading_day
contract
segment_start_trading_day
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

Factor Snapshot 不输出 `qualified / entry / buy / sell / flat / timeframe_alignment`。

### 7.2 Slope definition

对最近 N 个 ready EMA21：

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

### 8.3 Accepted Calibration is a Git fact

Calibration 从 candidate 晋升为可执行 Signal 输入必须经过以下硬 Gate：

```text
Calibration Research
→ candidate
→ 人工批准
→ 写入仓库内 Git-tracked、versioned、human-reviewable calibration artifact
→ commit
→ Signal 才允许从 RESEARCH_PENDING 晋升为 MATCHED
```

聊天确认、临时脚本参数、浏览器 localStorage、未提交文件或运行时内存值都不能成为正式 Calibration 事实源。

Accepted Calibration 必须有稳定 `calibration_id/version`。同一版本不得原地修改语义；阈值变化形成新版本。具体文件路径由 implementation plan 在现有仓库布局中选择，不因此建设 Calibration Registry、DB 或后台管理面。

### 8.4 Calibration scope — simplest first

Slope 第一轮研究 timeframe-wide threshold：

```text
5m 一个候选
15m 一个候选
1d 一个候选
```

只有真实 Validation 证据表明少量品种长期不适用时，才允许 product override。

MACD zero-band 第一轮也从**最少参数**开始：

```text
5m timeframe-wide normalized zero_distance_bps threshold
15m timeframe-wide normalized zero_distance_bps threshold
1d timeframe-wide normalized zero_distance_bps threshold
```

同时保留 `zero_distance_abs` 作为诊断/解释维度，验证 normalized distance 是否真的能够降低品种尺度差异。

只有 timeframe-wide normalized threshold 在 Discovery/Validation 中对明确品种持续失效时，才允许为少量品种增加 product override。V1 不预设 `60 products × 3 timeframes = 180` 个 zero-band 参数。

### 8.5 MACD capability Gate

当前 MACD 仍属于已有兼容/展示口径，不得因为苏冰开始使用它，就隐式宣布其已经获得正式 Signal/Live/Alert 资格。

V1 可以先用明确记录的 MACD policy/version 做 Historical/Live **Factor observation**，但在 `SubingSignalEvaluation.status` 可以晋升为 `MATCHED` 之前，必须完成一个独立的 Lane 3 语义审查：

```text
确认 Python MACD policy/version
确认 confirmed 1d/5m/15m 计算口径
补充 golden / edge tests
确认 Historical 与 completed Live 同口径
同步 Indicator deep canonical / registry capability（如实现合同需要）
```

该 Gate 未完成时，即使 Accepted Calibration 已存在，也只能保持 research-only，不得接 Alert V2。

---

## 9. Signal Semantics

### 9.1 Condition and evaluation state

内部条件统一：

```text
PASS
FAIL
RESEARCH_PENDING
UNAVAILABLE
NOT_APPLICABLE
```

`SubingSignalEvaluation`：

```text
status:
  MATCHED
  NOT_MATCHED
  RESEARCH_PENDING
  INSUFFICIENT_DATA

direction:
  LONG
  SHORT
  NONE
```

判断优先级：

```text
必需数据缺失 / segment warm-up 不足
→ status = INSUFFICIENT_DATA
→ direction = NONE

任一已知 hard condition FAIL
→ status = NOT_MATCHED
→ direction = NONE

所有已知条件通过，但 Calibration / capability Gate 未冻结
→ status = RESEARCH_PENDING
→ direction = LONG | SHORT（若候选方向已可确定，否则 NONE）

所有必需条件通过
→ status = MATCHED
→ direction = LONG | SHORT
```

正式 Signal 的唯一判定：

```text
status == MATCHED
AND direction != NONE
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
companion timeframe direction relationship
```

Companion timeframe 只承担：

```text
price / EMA21 direction
slope direction
```

不要求 companion 同时 MACD cross 或 3x volume。

`direction_alignment` 在这里由 primary/companion 两个 `SubingFactorSnapshot` 推导，是 Signal condition，不写回任何单周期 Factor Snapshot。

### 9.4 5m/15m behavior

5m 可独立触发，只要求 15m 方向/斜率一致。

15m 也可以独立触发，只要求最新 confirmed 5m 方向/斜率一致；5m 不必同时有完整 trigger。

方向冲突：

```text
status = NOT_MATCHED
direction = NONE
```

### 9.5 Same-boundary resolver

若同一 `bar_end`：

```text
5m  = MATCHED LONG
15m = MATCHED LONG
```

只输出一个 resolved Signal：

```text
status = MATCHED
direction = LONG
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

primary 与 companion 都必须在各自当前 rank1 segment 内独立 warm-up；不得从上一个主力 segment 借 indicator state。

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
→ SubingReadService
```

`SubingReadService` 不直接读取 Redis；`subing_research.py` 只接受 bars，不知道 Redis。

现有 P0 `MarketResearchService` 继续保持 Historical-only，不因苏冰修改其职责。

### 11.2 Current contract and segment only

盘中只观察当前 rank1 真实合约的当前 rank1 segment。

如果 Historical current dominant 与 Live subscription contract 不一致：

```text
Historical 可显示
Live Signal fail-closed
reason = contract mismatch
```

绝不能把两个 contract 拼在一起计算指标。

如果 current segment 自换月以来的 bars 尚不足以完成 EMA/MACD/Slope warm-up：

```text
status = INSUFFICIENT_DATA
```

不从 segment 前补数据。

### 11.3 Refresh

Web 不新增第二条 WebSocket。

沿用现有 completed Live bar event 作为 refresh trigger：

```text
new completed primary bar
→ refresh SuBing snapshot
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
current rank1 segment Kline + EMA21
```

副图继续固定：

```text
Volume
MACD
```

换月后苏冰模式的可见历史可能从新 rank1 segment 起较短，这是现有 Canonical 合同下的正常行为；不得为了补长图表而切回 actual_dominant 或另取 pre-rank1 contract 数据。

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

换月后 warm-up 不足时明确显示：

```text
苏冰 · 当前主力已切换
指标 warm-up 中 · 暂无正式判断
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

苏冰详情显示 Factor value、condition result、primary/companion confirmed time、current contract 与 segment start，但不把内部枚举直接暴露给用户。

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

对每个 rank1 segment 中 warm-up 完成后的历史样本计算：

```text
directional return 3K / 5K / 8K
MFE 3K / 5K / 8K
MAE 3K / 5K / 8K
EMA21 failure within 3K / 5K / 8K
```

这些 future labels 只用于离线研究，永不进入实时 Factor。

### 13.2 Intraday horizon

5m / 15m 的 3/5/8K outcome 严格不跨 `trading_day`，也不跨 rank1 segment。

当日或当前 segment 剩余 K 不够：

```text
对应 horizon = unavailable
```

不能拿下一交易日或下一主力 segment 补齐。

### 13.3 Slope calibration first

顺序固定：

```text
Slope Calibration
→ candidate
→ 人工批准并形成 accepted Git fact
→ MACD Zero-Band Calibration
```

禁止同时优化 slope + zero-band。

Slope report 输出 bucket/distribution、样本数、后续结果和候选阈值，不输出“最佳参数”并自动采用。

5m/15m intraday calibration 优先；1d calibration 可以独立后续完成，不阻塞 intraday Signal。

### 13.4 MACD zero-band research

至少比较：

```text
Cohort A = all confirmed MACD crosses
Cohort B = 除 zero-band 外其他 SuBing 条件已经成立的 crosses
```

第一轮优先按 timeframe-wide `zero_distance_bps` bucket 比较 3/5/8K outcome；`zero_distance_abs` 用于诊断不同品种是否仍存在系统性尺度偏差。

只有 Validation 证明 timeframe-wide normalized threshold 对少量品种持续不适用，才增加 product override；不预建 product × timeframe 全矩阵。

### 13.5 Discovery / Validation

参数研究必须时间分离：

```text
Discovery
→ candidate frozen
→ later-period Validation
```

同一时间段不得既选 threshold 又宣称 threshold 有效。

候选一旦因为验证结果再次调整，必须形成新的 candidate version 再验证。

所有样本都遵守 rank1-segment-local 计算；segment 前 warm-up 不足的样本不进入 Discovery/Validation。

### 13.6 Storage and accepted artifact

不建研究 DB，不长期保存 raw factor samples。

批量研究采用有界 chunk + streaming aggregate，完成后释放 raw rows。

Candidate report 可以是临时研究输出，但不能直接驱动 Signal。

唯一需要长期版本化的是：

```text
人工批准后的最小 SubingCalibration artifact
```

它必须 Git-tracked、versioned、human-reviewable，并通过 commit 成为仓库事实。Signal 不读取聊天记忆、临时报告、localStorage 或运行时动态阈值。

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

只有 Accepted Calibration 已形成 Git fact、MACD capability Gate 完成、Signal 稳定且完成一段 Live 人工观察后，才新立项：

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

未来 Signal rule 应采用版本化、不可原地改变语义的 rule identity，保证 Event 能定位当时的 policy/calibration identity；具体表结构留给 Alert V2 独立设计。

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

### 14.5 Event fact vs post-hoc reconstruction

Future Alert V2 中，Alert/Event 需要证明的是：

> **当时系统确实在给定 rule/policy/calibration identity 下产生并通知过这条 Signal。**

由于 Live 是 transient observation、不会提升为 Canonical，后续使用 Canonical 对当时 Factor/Signal 做重算只能称为：

```text
post-hoc reconstruction
```

不能承诺与当时 transient Live 输入 bit-for-bit 相同。

V1 不因此长期保存完整 Factor Snapshot；如果以后复盘确实证明“必须精确保留当时 Live 输入/Factor”有长期价值，再作为独立设计增加最小 snapshot。当前不做。

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
rank1-segment warm-up insufficient
companion unavailable
calibration pending
accepted calibration artifact absent
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

当前单用户、单品种页面，读取 current rank1 segment 内最多约：

```text
primary <= 300 bars
companion <= 300 bars
```

segment 本身不足 300 时只使用已有 segment bars；不得向 segment 之前补取数据。

执行 EMA21/MACD/Slope/Volume/relationship/Signal，5m 最多约每 5 分钟刷新一次。

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
→ segment-local calculation
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
Signal status / direction separation
Signal condition priority
multi-timeframe relationship is not persisted as Factor
5m / 15m companion alignment
same-boundary 15m wins
no future companion
partial-bar poison
rank1 rollover poison
rank1-segment-local warm-up
no pre-rank1 warm-up fallback
Historical/Live contract mismatch
Canonical + completed Live seam
3/5/8 intraday labels do not cross trading_day or rank1 segment
Discovery / Validation time separation
accepted calibration Git gate
Web overlay single-select
unsupported frequency state
HTDY repaint warning regression
Alert V1 untouched regression
```

两个关键 poison tests：

1. **Rollover poison**：用明显价差的两个主力 segment 证明换月后 EMA/MACD 从新 segment 自身重新 warm-up，绝不延续旧 contract 状态，也不向新 contract 的 pre-rank1 日期读取补齐；
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

S1  SubingReadService + Current-rank1 Factor Snapshot
    复用 MarketDataService + MarketReadService
    rank1-segment-local Historical + completed Live + multi-TF
    不修改现有 MarketResearchService Historical-only 合同

S2  Product Workspace Factor Observation
    无/苏冰/火天大有单选 + EMA21 + Factor details
    Signal 仍可保持 RESEARCH_PENDING

S3  Intraday Factor Calibration — Slope
    先 5m/15m
    3/5/8 labels + discovery/validation + candidate only

Gate
    人工批准 slope candidate
    写入 tracked/versioned calibration artifact 并 commit

S4  Intraday Factor Calibration — MACD Zero-Band
    timeframe-wide normalized first
    abs distance diagnostic
    只有 Validation 证据支持时才增加少量 product override

Gate
    人工批准 zero-band candidate
    更新 tracked/versioned calibration artifact 为新 accepted version
    + MACD formal Signal capability Gate

S5  SuBing Entry Signal
    status + direction + 5m/15m resolver
    Web 展示，但仍不接 Alert V1

Observation period
    人工盘中使用和复盘

Parallel/non-blocking Daily track
    1d Slope / Zero-Band Calibration + Signal Research
    不阻塞 5m/15m Intraday Signal

Future independent task
    Alert V2 — SuBing Entry Signal Integration
```

如果实现过程中发现 Slope / Zero-Band 或 MACD capability 尚无法冻结，则 Signal 保持 `RESEARCH_PENDING`，不得为了“功能完整”自行选择阈值或放宽 capability。

### 18.1 Canonical alignment prerequisite

当前 `docs/INDICATOR_KERNEL.md` 中仍存在“Market 图表尚未挂载指标”的旧描述，而当前代码/STATUS 已经存在 EMA/MACD/HTDY Product Workspace 行为。

本轮只修改 SuBing Spec，不修改其他 canonical；但 implementation plan 必须在第一批受影响任务中安排**最小 deep-canonical 对齐**，避免 Codex 在实现时面对互相冲突的 active 文档。该对齐只修正文档事实，不借机扩张 Indicator Kernel 边界。

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

1. 当前品种自动解析当前 rank1 真实合约与 current rank1 segment；
2. Kline/EMA/MACD/Slope 只使用当前 rank1 segment，不跨换月递推，也不读取 pre-rank1 contract 数据补 warm-up；
3. 换月后 warm-up 不足明确 `INSUFFICIENT_DATA`；
4. 1d/5m/15m Factor 由 Python authoritative core 计算；
5. 5m/15m 盘中只消费 completed Live bars；
6. multi-timeframe 不使用未来 companion，且 alignment 只属于 Signal relationship；
7. raw Factor value 与 Signal gate 分离；
8. Signal evaluation 分离 `status` 与 `direction`；
9. Calibration / capability 未批准时明确 `RESEARCH_PENDING`；
10. Accepted Calibration 必须是 Git-tracked/versioned 仓库事实；
11. Signal 仅输出入场方向，不承担持仓/退出；
12. 5m/15m 同刻 full signal 只保留 15m 一条；
13. Web 为 `无 / 苏冰 / 火天大有` 单选；
14. `SubingReadService` 是唯一新增薄应用 seam，现有 `MarketResearchService` Historical-only 合同保持不变；
15. 不新增研究 DB/Redis/worker/scheduler/WebSocket/Factor platform；
16. 不修改 Data Foundation；
17. 当前 Alert V1 保持原样；
18. Future Alert V2 的 Canonical 重算只定义为 post-hoc reconstruction，不冒充 exact Live snapshot；
19. 未来企微接入必须作为独立 Alert V2，且只接 5m/15m entry signal；
20. `auto_order=false` 始终成立。

本设计不证明盈利、参数长期稳定、Strategy Ready、Backtest Ready、Alert Ready、Runtime Ready 或 release Ready。

---

## 21. Final Design Statement

苏冰 V1 的最终定位：

> **一个基于当前 rank1 真实合约、严格按 rank1 segment 使用 confirmed Historical/Live Bar 的轻量 Factor → Signal 研究能力。换月后不跨 contract 继承指标状态，也不读取 pre-rank1 数据补 warm-up；可重算的 Factor 不长期存储；Calibration 从最少参数开始，经 Discovery/Validation 与人工批准后必须成为 Git-tracked/versioned 仓库事实；盘中只执行通过 capability Gate 和 accepted calibration 的确定性入场方向规则。第一阶段不建设 Strategy，不建设通用 Factor 平台，也不接现有 Alert V1。未来若验证成熟，再以独立 Alert V2 复用现有 Scope/Event/WeCom/Runtime 基础设施发送 5m/15m 入场方向信号；后续 Canonical 重算仅用于 post-hoc reconstruction，不冒充当时 transient Live 的 exact snapshot。**