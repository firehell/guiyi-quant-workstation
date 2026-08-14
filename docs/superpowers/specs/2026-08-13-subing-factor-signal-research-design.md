# 苏冰 Factor → Signal 研究与盘中观察 V1 Design

Final design：2026-08-14  
Current baseline：`develop` after Gate A + intraday Zero-Band OOS review

## 1. Purpose

本设计定义“苏冰”V1 的最终研究与入场方向 Signal 边界。

目标不是恢复旧 Strategy/Backtest，也不是建设通用 Factor 平台，而是在冻结的 Data Foundation、Market Research Workspace、Indicator Kernel 和 Market Runtime seam 之上，以最小新增面完成：

```text
Indicator
→ Factor
   ├─ Product Workspace observation
   └─ Calibration Research
          ↓
   accepted slope-only Calibration
          ↓
   scoped MACD capability Gate
          ↓
        Signal
          ↓
   Live human observation
          ↓
   Future Alert V2
```

V1 只做**入场方向信号**。不承担持仓、EMA21/8K 退出、止损止盈、加减仓、反手、资金、订单或自动交易。

长期原则：

```text
AI 可以辅助研究，但不能自动晋升规则。
研究负面结果可以删除规则，而不是强行寻找参数。
Signal/通知是人工观察，不是自动交易指令。
auto_order=false。
```

---

## 2. Repository / Data Boundary

- Historical 唯一事实链：`Canonical Parquet -> eight-table Catalog -> MarketDataService`。
- 物理 Dataset 只有 `continuous | contract`；`actual_dominant` 只按 `MainContractMap rank1` 查询拼接。
- contract Canonical 只覆盖该 contract 被映射为 rank1 的交易日，不假设完整上市生命周期。
- Redis Live Overlay 与 Historical Canonical 分离；Live 不提升为 Canonical。
- `MarketResearchService` 保持 Historical-only；Historical/Live seam 继续由 `MarketReadService` 承担。
- Indicator Kernel 是 EMA/MACD 的基础计算权威。
- 当前 Alert V1 仍是独立 HTDY 应用；本设计不得修改其 Rule/Scope/Event/Runtime/WeCom 语义。

不得修改 Data Foundation 的 DatasetKey、八表 Catalog、Canonical、月分区、contract rank1-day coverage 或 Historical Gateway。

---

## 3. Concept Model

### 3.1 Indicator

复用：

```text
EMA21
MACD
```

不注册 `subing` Indicator，不复制 EMA/MACD 算法。

### 3.2 Factor

单周期 `SubingFactorSnapshot` 保留原始事实：

```text
price_vs_ema21
ema21_slope_5_raw
ema21_slope_10_raw
ema21_slope_5_bps_per_bar
ema21_slope_10_bps_per_bar
macd_dif
macd_dea
macd_histogram
macd_cross
macd_cross_level
macd_zero_distance_abs
macd_zero_distance_bps
volume_ratio_prev
```

Factor 不提前压成 entry/buy/sell/qualified。

`timeframe_alignment` 不是单周期 Factor，而是 Signal Evaluation 中 primary/companion 的关系。

### 3.3 Signal

`SubingSignalEvaluation` 分离：

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

正式 Signal 唯一判定：

```text
status == MATCHED
AND direction in (LONG, SHORT)
```

V1 不做 score、星级或置信度。

### 3.4 Strategy

Strategy 不实现。只有未来确实需要系统管理持仓/退出/资金或完整交易级回测时，才新立项 `Signal -> Strategy`。

---

## 4. Architecture

```text
Indicator Kernel
EMA21 / MACD
      │
      ▼
subing_research.py
zero-I/O pure core
      ▲
      │
SubingReadService
thin application seam
   │          │
   ▼          ▼
MarketDataService   MarketReadService
history/segment     Historical+Live seam
   │          │
   └────┬─────┘
        ▼
Product Workspace
        │
Calibration Research
        │
accepted slope-only Calibration
        │
scoped MACD capability
        │
        ▼
      Signal
        │
Future Alert V2
```

### 4.1 `SubingReadService`

只允许：

```text
解析 current dominant / current rank1 segment
读取 primary / companion Historical+completed Live
准备 confirmed bar windows
调用 pure Subing core
组装 read snapshot
```

不得：直接读 Parquet/Redis/RQData、写 DB/Canonical、加缓存/worker/scheduler/WebSocket，或修改 `MarketResearchService` 的 Historical-only 合同。

不新增 `SubingRepository/SubingDB/SubingRedis/FactorStore/FactorRegistry/RuleEngine/StrategyEngine`。

---

## 5. Current Dominant / Rank1 Segment Identity

用户只选择品种；SuBing 自动解析当前 rank1 真实合约。

所有 Kline、EMA21、MACD、Slope、Factor 和 Live 必须使用：

```text
latest rank1 real contract
+
current rank1 segment only
```

禁止对拼接后的 `actual_dominant` 递推 EMA/MACD。

换月后：

```text
new segment starts
→ indicator state reset
→ only segment-local confirmed bars
→ warm-up insufficient => INSUFFICIENT_DATA
```

不得使用上一主力 state、continuous、其他 contract 或 pre-rank1 provider 数据补 warm-up。

Historical Calibration 只用 `actual_dominant/resolved_contract_segments` 解析 segment identity；每个 segment 单独计算指标，segment 前数据不进入递推。

---

## 6. Supported Frequencies

```text
1d
5m
15m
```

- `5m/15m`：当前 intraday 主线，Historical + completed Live Observation + future Signal/Alert。
- `1d`：独立、非阻塞 Research/Web 轨道；不得阻塞 intraday Signal。
- `1m/30m/60m/1w`：SuBing V1 unavailable，但普通 Market 行情和历史分页继续工作。

---

## 7. Factor Contract

`SubingFactorSnapshot` 至少包含：

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
slope_5_raw / slope_10_raw
slope_5_bps_per_bar / slope_10_bps_per_bar
macd_dif / macd_dea / macd_histogram
macd_cross
macd_cross_level
macd_zero_distance_abs
macd_zero_distance_bps
volume / previous_volume / volume_ratio_prev
```

### 7.1 Slope

对最近 N 个 ready EMA21 做 OLS：

```text
x = 0..N-1
EMA21 ≈ a + b*x
```

```text
slope_bps_per_bar = b / mean(EMA21 window) * 10000
```

V1 同时使用 5K 与 10K。`FLAT` 属于 Calibration 后的 Signal 判定，不属于 Factor。

### 7.2 MACD

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

交叉确认 K：

```text
cross_level = (DIF + DEA) / 2
zero_distance_abs = abs(cross_level)
zero_distance_bps = abs(cross_level) / close * 10000
```

不反推 K 内交叉时刻。

### 7.3 Volume

```text
volume_ratio_prev = current_volume / previous_volume
```

`previous_volume <= 0` => unavailable，不补零/无穷大。

---

## 8. Policy and Calibration

### 8.1 Frozen method rules

`SubingSignalPolicyV1` 保存方法规则，例如：

```text
EMA21
slope windows = 5/10
intraday volume ratio = 3.0
intraday timeframes = 5m/15m
same-boundary resolution = higher timeframe wins
```

EMA/MACD 算法引用 Indicator Kernel policy/version。

### 8.2 Gate A — approved slope Calibration

已人工批准：

```text
5m slope_flat_threshold_bps_per_bar
= 0.688190651160584793944957992

15m slope_flat_threshold_bps_per_bar
= 1.329531078893356968545882036
```

批准语义仅是 EMA21 flat / trend-persistence filter，不是 slope 单因子盈利证明。

### 8.3 Intraday Zero-Band research result — rejected as hard gate

Discovery 使用完整 companion-aware Cohort B；随后冻结最宽候选 C：

```text
5m C = 16.01901065112843434322837440 bps
15m C = 27.16954645407146036410753274 bps
```

在独立 Validation `2026-05-01..2026-08-11` 中与 NO-BAND baseline 对照：

- 5m C 的 3K/5K/8K EMA21 failure 均高于 NO-BAND；5K/8K median directional return 与正负分布也更弱；MFE/MAE 同时缩小，不是方向质量改善。
- 15m 仅 5K 有局部 terminal-return 改善，但 3K/8K 不一致、三个 horizon failure 均更高，且样本稀疏。
- 15m LONG/SHORT OOS 存在明显 asymmetry；本版本不得使用 Validation 现场创建方向特例。

因此：

```text
macd_cross                 => 保留 executable
macd_zero_distance_abs/bps => 保留 Factor/Web/research
macd_zero_band hard gate   => intraday V1 拒绝
```

不得回头在同一 Validation window 测 A/B 后重新选参数，不增加 product/sector/direction override。

该结论只覆盖 5m/15m；1d 是否需要 zero-band 必须独立研究。

### 8.4 Accepted intraday Calibration artifact

在 Gate B-R 通过后，artifact 只包含两个 slope Decimal：

```json
{
  "schema_version": 1,
  "calibration_id": "subing_intraday_v1",
  "accepted_timeframes": ["5m", "15m"],
  "slope_flat_threshold_bps_per_bar": {
    "5m": "0.688190651160584793944957992",
    "15m": "1.329531078893356968545882036"
  }
}
```

不得用 Infinity、超大值、nullable special-case 伪装 zero-band。

聊天、stdout、localStorage、env 或运行时内存值不能成为 accepted Calibration。Artifact 必须 Git-tracked/versioned；同 ID 不得原地改变语义。

### 8.5 Gate B-R

在创建 production artifact 前，必须人工确认：

```text
slope pair frozen
intraday zero-band hard gate rejected
accepted Calibration is slope-only
zero-distance remains observation/research-only
15m LONG asymmetry is observation risk only
```

当前设计收缩的批准不自动等于 Gate B-R promotion 批准。

### 8.6 MACD capability Gate C

Generic MACD 当前仍是 compatibility/display 口径。正式 Signal 在 `MATCHED` 前必须独立审查：

```text
fast12 / slow26 / signal9
sma_window
histogram_scale=2
confirmed-only
Historical/completed-Live parity
golden/dead edge tests
```

未来 scoped SuBing Signal policy 必须与 Factor observation policy 在 seed/histogram/lookback/confirmed-only 上数学等价。Gate C 不批准 generic MACD、Backtest 或 Alert capability。

---

## 9. Signal Semantics

### 9.1 State priority

```text
required data unavailable / warm-up insufficient
→ INSUFFICIENT_DATA / NONE

known hard condition fail
→ NOT_MATCHED / NONE

slope Calibration artifact absent or MACD Gate C pending
→ RESEARCH_PENDING / candidate direction or NONE

all required conditions pass
→ MATCHED / LONG|SHORT
```

### 9.2 Intraday 5m/15m Required conditions

LONG primary：

```text
price ABOVE EMA21
slope5 > threshold(primary)
slope10 > 0
MACD GOLDEN
volume_ratio_prev available and >= 3
latest confirmed companion READY
companion price ABOVE EMA21
companion slope5 > threshold(companion)
companion slope10 > 0
```

SHORT 镜像：BELOW、负 slope、MACD DEAD。

**没有 zero-distance hard condition。** `macd_zero_distance_abs/bps` 不能改变 `MATCHED/NOT_MATCHED`。

Companion 不要求 MACD cross 或 3x volume。

### 9.3 Multi-timeframe

```text
companion.bar_end <= primary.bar_end
```

5m primary 取最新 confirmed 15m；15m primary 取最新 confirmed 5m。方向冲突 => `NOT_MATCHED/NONE`。

同一 `bar_end` 5m/15m 同方向均 MATCHED 时只输出一条 15m：

```text
trigger_timeframe = 15m
lower_tf_confirmation = true
resolution = HIGHER_TIMEFRAME_WINS
```

反向冲突必须 fail-closed。

### 9.4 Daily

1d 当前只做 Research/Web，未进入 accepted intraday artifact，不接企微。Intraday zero-band rejection 不自动修改 1d research hypothesis。

---

## 10. Confirmed-bar / Lookahead Rules

所有正式 Factor/Signal 只消费 confirmed bars。partial Live bar 即使暂时出现 3x volume 或 MACD cross 也忽略。

primary/companion 均必须 segment-local warm-up；不得借上一个主力 state。

---

## 11. Live Observation

复用：

```text
LiveMarketService
→ completed 1m
→ 5m/15m aggregation
→ Redis Live Overlay
→ MarketReadService
→ SubingReadService
```

不新增 SuBing Runtime 数据链、Redis key、worker、scheduler、WebSocket。

Historical current dominant 与 Live contract 不一致时 Live Signal fail-closed；Historical 可继续读但不得拼两个 contract。

Web 沿用 completed bar event refresh；5m/15m 共同 boundary 只允许一次 bounded delayed refresh，不 polling/锁/事务。

---

## 12. Product Workspace

研究 Overlay 单选：

```text
无 / 苏冰 / 火天大有
```

SuBing：current rank1 segment Kline + EMA21；Volume/MACD 固定副图。有效 current-contract identity 不覆盖用户原 Market series preference。

`macd_zero_distance` 可以继续显示为解释事实，但 UI 不得把“接近零轴”标为 intraday Signal pass/fail 条件。

30m/60m 等 unsupported frequency 保持 Overlay 选择但显示 unavailable；普通 Market Kline/分页继续工作。

---

## 13. Calibration Research Discipline

### 13.1 Future labels

离线研究：

```text
directional return 3K/5K/8K
MFE 3K/5K/8K
MAE 3K/5K/8K
EMA21 failure within 3K/5K/8K
```

5m/15m 不跨 `trading_day`、contract 或 rank1 segment；不足 horizon => unavailable。

### 13.2 Discovery / Validation

```text
Discovery
→ candidate frozen
→ later non-overlapping Validation
```

Validation 不能变成新的 Discovery。Zero-Band C OOS 被拒绝后，不允许回测 A/B 来“救”规则。

### 13.3 Negative result handling

研究结论可以是：

```text
Factor 有解释信息
但没有足够条件增量价值进入 Signal
```

这是本次 zero-distance 的 intraday V1 结论。保留 Factor，不保留 hard gate。

### 13.4 Storage

不建 research DB，不长期保存 raw Factor samples。可重算的研究样本不持久化；长期事实只保存人工批准后的最小 Calibration artifact 和必要 canonical/status 决策。

---

## 14. Alert Boundary

当前 Alert V1 不变。

只有：

```text
Gate B-R passed
+ slope-only Calibration artifact committed
+ Gate C passed
+ deterministic Signal implemented/reviewed
+ Live human observation period
```

之后，才新立项 `Alert V2 — SuBing Entry Signal Integration`。

未来复用 existing Scope/Event/WeCom/Runtime，不创建第二套通知系统。第一版未来企微只接 5m/15m entry signal，系统不下单。

Live 是 transient；未来 Canonical 重算只称 `post-hoc reconstruction`，不声称 exact Live snapshot。

---

## 15. Fail-closed

- 非法 symbol / unsupported SuBing API frequency：422。
- Market data/mapping/partition conflict：复用稳定 409，不 fallback。
- warm-up/companion unavailable：`INSUFFICIENT_DATA`。
- slope artifact absent / MACD Gate C pending：`RESEARCH_PENDING`。
- malformed Calibration artifact：稳定配置错误，不用默认值继续。
- zero-distance 缺失本身**不得**让 intraday Signal insufficient；它不再是 executable required field。

---

## 16. Required Tests

必须覆盖：

```text
Factor deterministic calculation
Slope OLS 5K/10K + bps/bar
MACD golden/dead equality edges
MACD zero-distance Factor calculation
MACD Historical/completed-Live parity
Volume invalid denominator
rank1 rollover / no pre-rank1 warm-up poison
partial-bar poison
5m/15m no-future companion
same-boundary 15m wins
3/5/8 labels no cross trading_day/segment
Discovery/Validation separation
Gate A exact slope values
slope-only Calibration loader/schema fail-closed
zero-distance changes do not affect intraday Signal result
no zero-band executable condition
15m LONG OOS asymmetry does not create direction-specific rules
scoped MACD policy equivalence
Web overlay/unsupported-frequency regression
Alert V1 untouched regression
```

---

## 17. Current Development Sequence

```text
S0-S2  Factor Observation                    COMPLETE
S3     Slope Calibration                     COMPLETE
Gate A slope pair                            PASSED
S4     Zero-Band Discovery + frozen-C OOS    COMPLETE
Result intraday zero-band hard gate          REJECTED
Gate B-R slope-only Calibration promotion    PENDING
S5     Commit slope-only Calibration artifact
S6     Scoped MACD evidence
Gate C MACD Signal capability                PENDING
S7     Deterministic intraday Signal
S8     Product Workspace Signal observation
Observation period
Future Alert V2
```

1d 是独立、非阻塞 track。

---

## 18. Lane / Human Gates

Factor formula、Calibration/OOS、Signal semantics、MACD capability 均为 Lane 3：

```text
Sol
高推理
Plan-only before semantic changes
independent Review
```

代码进入 `develop` 不代表 Calibration/MACD/Signal/Alert/Runtime/release 自动获批。

Gate B-R、Gate C、Future Alert/Runtime/release 均是相互独立的人工 Gate。

---

## 19. Acceptance Definition

Intraday SuBing V1 完成时必须证明：

1. current rank1 real contract + current segment only；
2. no cross-roll indicator state / no pre-rank1 warm-up；
3. completed Live only；
4. Gate A exact slope pair 是唯一 accepted intraday Calibration 参数；
5. zero-distance Factor 保留，但 zero-band hard gate 被 OOS 拒绝且不进入 Signal；
6. accepted Calibration 是 Git-tracked/versioned slope-only artifact；
7. scoped MACD capability 经过独立 Gate C，generic MACD 未提升；
8. Signal 只做 LONG/SHORT entry observation，不做持仓/退出；
9. multi-TF 不未来引用，同 boundary 15m wins；
10. 15m LONG OOS asymmetry 仅作为风险记录，不产生 Validation-driven 方向特例；
11. 无 research DB/cache/worker/new Runtime；
12. Alert V1/Data Foundation 不变；
13. `auto_order=false`。

本设计不证明盈利、长期参数稳定、Backtest Ready、Alert Ready、Runtime Ready 或 release Ready。

---

## 20. Final Design Statement

> **苏冰 V1 是 current-rank1、rank1-segment-local、confirmed-bar-only 的轻量 Factor → Signal 研究能力。Slope 经独立 Discovery/Validation 后人工冻结；MACD zero-distance 虽保留为可解释 Factor，但在完整 SuBing 条件下未通过 OOS 增量价值检验，因此不进入 intraday hard gate。Accepted intraday Calibration 收缩为两个 slope Decimal；MACD cross 仍需独立 capability Gate。最终盘中只执行人工批准、确定性的入场方向规则，不建设 Strategy/Factor 平台，不自动下单，不接现有 Alert V1；未来 Alert V2 仍需独立设计与人工 Gate。**