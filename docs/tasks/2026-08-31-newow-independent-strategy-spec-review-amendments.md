# Newow 独立策略 Spec 自审修正

状态：`NORMATIVE_REVIEW_AMENDMENT`

日期：2026-08-31

任务：Issue #262

基线文档：`docs/tasks/2026-08-31-newow-independent-strategy-spec.md`

> 本文是主 Spec 的规范性组成部分。发生冲突时，以本文为准。本文只关闭自审发现的歧义，不改变已确认产品方向：Newow 与 SuBing 完全隔离；趋势 V1 只绑定 D1；震荡 V1 只绑定 15m；当前不接 Alert、Runtime、订单或真实通知。

---

## 1. Kernel Bundle 与版本身份

主 Spec 的 `strategy_instance_id` 增加以下必填项：

```text
kernel_bundle_id
kernel_bundle_digest
```

`NewowKernelBundleIdentity` 固定记录：

```text
schema_version
bundle_id
phase_kernel_version
swing_kernel_version
structure_kernel_version
range_kernel_version
pattern_kernel_version
target_risk_kernel_version
evidence_kernel_version
execution_kernel_version
indicator_policy_digest
source_policy_id
bundle_digest
```

最终身份：

```text
strategy_instance_id = sha256(
  strategy_code
  + formula_version
  + profile_id
  + profile_hash
  + series_kind
  + source_policy_id
  + indicator_policy_digest
  + kernel_bundle_digest
)
```

约束：

- 任一被消费 Kernel 的语义、阈值、处理顺序或序列化合同改变，必须创建新 Kernel version；
- 新 Kernel version 被策略消费时，必须创建新的 strategy formula version / instance identity；
- 禁止只改变 `engine_identity_sha256` 而保持相同 strategy instance；
- Candidate Manifest 必须 pin `kernel_bundle_digest`；same-ID byte drift 继续 fail-closed。

Pattern Kernel 自身必须有独立研究 authority：

```text
data/research_candidates/newow_pattern_<profile>_candidate_v1.json
data/research_protocols/newow_pattern_<profile>_validation_v1.json
```

策略 Manifest 只能引用已经冻结的 Pattern Candidate digest，不能把形态阈值藏在策略报告中。

---

## 2. 数值确定性

V1 固定：

```text
numeric_dtype             = float64
numeric_epsilon           = 1e-12
published_round_digits    = 8
price_storage             = Decimal
```

处理规则：

- Canonical OHLC 使用原始 `Decimal` 身份；
- EMA / ATR / MACD 服从各自已冻结 formal policy 的 seed 与 rounding；
- moments、回归、标准化特征使用 NumPy float64；
- 对外发布值统一 round 到 8 位，但策略判定使用同一步内未发布前的 float64 值；
- price level 由 `Decimal(str(rounded_value))` 构造，不用二进制浮点直接构造 Decimal；
- event / action ID 不包含未 round 的浮点文本，只包含 bar identity、version、direction、setup identity 和 confirmed time。

边界：

```text
ATR <= epsilon                       -> ATR_NORMALIZATION_UNAVAILABLE
m2 <= epsilon                        -> MOMENTS_UNAVAILABLE
ER denominator <= epsilon            -> ER20 = 0
RV40 <= epsilon and RV10 <= epsilon  -> VolatilityRatio = 0
RV40 <= epsilon and RV10 > epsilon   -> VOLATILITY_RATIO_UNAVAILABLE
previous volume median <= 0          -> VOLUME_RATIO_UNAVAILABLE
previous OI missing or <= 0          -> OI_DELTA_UNAVAILABLE
```

`sample_std` 固定使用 `ddof=1`。不得由 pandas / SciPy 默认参数决定生产结果。

---

## 3. Shared Range Primitive

主 Spec 第 15 节引用的 Range 必须由独立、通用、clean-room 的：

```text
range_detector_lux_v1
```

提供；它不属于 SuBing，也不复制第三方 Pine Script。

### 3.1 Profile 参数

`NewowTimeframeProfile` 增加：

```text
range_min_length
range_atr_period
range_width_atr_multiplier
```

固定：

```text
newow_tf_1d_v1:
  range_min_length             = 20
  range_atr_period             = 100
  range_width_atr_multiplier   = 1.0

newow_tf_15m_v1:
  range_min_length             = 20
  range_atr_period             = 500
  range_width_atr_multiplier   = 1.0
```

D1 不采用 ATR500，因为单个期货物理合约通常无法稳定提供 500 根完成日线 warm-up；D1 的 100 是 Newow 期货 Profile 参数，不声称等于第三方默认值。

### 3.2 单 Bar 公式

对 completed Bar `t`：

```text
L = range_min_length
N = range_atr_period
M = range_width_atr_multiplier

center_t = SMA(close[t-L+1 ... t])
width_t  = ATR_N[t] * M
upper_t  = center_t + width_t
lower_t  = center_t - width_t

candidate_valid_t =
  对 i=0...L-1，均满足
  abs(close[t-i] - center_t) <= width_t
```

只有 SMA / ATR warm-up 完整、值有限、同一 physical contract 时才 ready。

### 3.3 时间与 revision

```text
confirmed_at    = bar_end[t]
visual_start_at = bar_end[t-L]
```

`visual_start_at` 仅用于绘图。Candidate 使用的实际窗口仍是 `t-L+1 ... t`。

- 新 candidate 与前一 detection 区间重叠时，保留 `range_id` 并创建新 revision；
- 新 revision 的边界只从本次 `confirmed_at` 向后生效；
- 不重叠时创建新 `range_id`；
- `intact -> broken_up | broken_down`，直到新 confirmation / revision 才可恢复 intact；
- 单个 `range_id + revision` 最多产生一次突破机会。

严格因果：

```text
策略 Bar t 只能读取 confirmed_at < bar_end[t] 的 Range；
Bar t 新确认或 revision 的 Range 不能被 t 自身用于入场。
```

主 Spec 中所有 RangeBias、Range edge、突破和 revision 行为均以本节为权威。

---

## 4. Pattern Candidate 的确定性枚举

形态识别不得任意挑选“最漂亮”的 Pivot 组合。

### 4.1 通道类

每次新 confirmed Swing 到来时，对 minor / major 分别枚举：

```text
连续 suffix，长度 4...12 个交替 Pivot
必须以最新 confirmed Swing 结束
不得跳过 suffix 内的 confirmed Swing
每侧至少2个触点
时间长度满足 Profile
```

对每个合法 suffix 分别拟合边界并分类为矩形、三角、楔形或旗形。

### 4.2 固定骨架类

```text
双顶 / 双底：最近连续3个 major Swing
头肩顶 / 头肩底：最近连续5个 major Swing
旗形：最近1条 major impulse edge + 随后的4...10个 minor Swing
杯柄：D1 最近连续 major/minor structure window，必须以当前 confirmed handle swing 结束
```

固定骨架不得跳过中间的 major Swing 来提高拟合质量。

### 4.3 Pattern identity 与 strict-before

```text
pattern.confirmed_at = max(contributing_swing.confirmed_at)
pattern.visual_start_at = first contributing pivot_at
```

每次新 contributing Swing 或边界变化都创建新的：

```text
pattern_id + revision
```

旧 revision immutable。

策略 Bar `t` 只能消费：

```text
pattern.confirmed_at < bar_end[t]
```

因此当前 Bar 不能既确认完整形态，又使用该形态在同一 Bar 形成 A 点。

### 4.4 多候选与 primary

全部合法候选保留。分别选择两个 primary：

```text
primary_visual_pattern
primary_action_pattern
```

`primary_visual_pattern` 排序：

```text
hard_valid desc
quality_score desc
specificity_rank desc
confirmed_at asc
pattern_id asc
revision asc
```

`primary_action_pattern` 先过滤 `action_eligible=true`，再使用相同排序。

`specificity_rank` 固定：

```text
head_shoulders       = 60
double_top_bottom    = 50
flag                  = 40
triangle              = 30
wedge                 = 20
rectangle             = 10
cup_handle            = 70  # 只可能成为 visual primary，V1 action_eligible=false
```

`NewowStrategySnapshot.current_pattern_id` 只引用 `primary_action_pattern`；Web 主图可显示 `primary_visual_pattern`，但不得误导为正式 Setup。

---

## 5. B 点不是第二次执行开仓

主 Spec 第 13.1 节的执行状态由以下内容覆盖：

```text
FLAT
→ PENDING_OPEN
→ ACTIVE_A
→ ACTIVE_CONFIRMED
→ PENDING_CLOSE
→ CLOSED
```

删除执行层的：

```text
PENDING_CONFIRMATION_ENTRY
```

趋势策略中的 `CONFIRM_B_PENDING` 改名为：

```text
RETEST_CONFIRMING
```

B 点只产生：

```text
B_RETEST_CONFIRMED milestone
entry_reference_b
b_invalidation_reference
```

它不得产生第二个 OPEN Action、第二个 reference fill、真实加仓手数或平均成本。一个 Episode 始终只有一个 entry Action。未来若要模拟 3:2:1 金字塔加仓，必须增加账户/头寸模型并发布独立策略版本。

---

## 6. 换月行政关闭不是可成交 CLOSE Action

主 Spec 的段末处理修改为：

```text
NewowAdministrativeClosure
├── closure_id
├── episode_id
├── reason = CONTRACT_SEGMENT_END
├── recognized_at
├── terminal_bar_end
├── terminal_reference_price
├── reference_basis = segment_terminal_close_non_executable
├── old_contract
├── incoming_contract
└── source_mapping_digest
```

约束：

- 行政关闭不创建 `NewowStrategyAction(action_type=CLOSE)`；
- `Episode.exit_action = null`；
- `Episode.administrative_closure` 指向上述记录；
- `recognized_at` 是权威 MainContractMap 已确认 rollover 的时间；
- terminal close 只是历史投影边界，不冒充当时可成交价格；
- 行政关闭 Episode 不进入完整策略质量、胜率、median R 或 OOS 主指标；
- Web 使用“主力切换，历史段结束”而不是“卖出/平仓信号”。

普通策略 CLOSE 仍必须由完成 Bar 上的策略退出条件确认，并使用下一同物理合约 Bar open reference。

---

## 7. Source Tail 的 pending 语义

当 Historical / Current 尾部出现：

```text
已确认 OPEN，但下一同合约 Bar 尚未出现
```

只返回 `pending_action`，不创建 Episode，不填 signal close 为 reference price。

当已有 Episode 的 CLOSE 已确认、但下一同合约 Bar 尚未出现：

- Episode 保持 active；
- 返回 pending CLOSE；
- 不提前填 exit reference；
- 下一次 append 时优先应用 pending；
- 若 append 后发现 physical segment 已结束，则取消普通 pending CLOSE，并使用第 6 节行政关闭记录。

---

## 8. Open-only Reference 与最小 Marketability

### 8.1 信号确认时可知的 Gate

在 completed signal Bar 上，只允许使用：

```text
signal bar volume > 0
previous volume median > 0
signal bar 非 ONE_PRICE_BAR
signal bar OHLC 有限且合法
```

不满足时输出：

```text
MARKETABILITY_UNAVAILABLE
```

Range 策略即使不把高 VolumeRatio 设为硬条件，也必须通过上述最小 Gate。

### 8.2 下一 Bar open 应用 pending

`engine.step(current_completed_bar)` 的第一步可以读取当前 Bar 的：

```text
contract
segment_id
frequency
trading_day
bar_start / bar_end identity
open
```

只用这些字段应用上一 Bar 的 pending Action。此时严禁读取当前 Bar 最终的：

```text
high
low
close
volume
open_interest
ONE_PRICE_BAR 判断
```

因为这些值在 open 时尚不可知。

下一 reference open 只要求：

```text
同 physical contract
同 frequency / profile
属于权威下一 Session Bar
open 有限且 > 0
gap / stop / target / RR 的 open-only 复核通过
```

Reference Action 必须标记：

```text
marketability = REFERENCE_OPEN_ONLY_UNVERIFIED
```

该标记明确表示 OHLC Bar open 只是研究参考，不证明真实委托在该价格可成交。

### 8.3 Bar 完成后的 ex-post diagnostics

当前 Bar 完成后可以记录：

```text
BAR_COMPLETED_ZERO_VOLUME
BAR_COMPLETED_ONE_PRICE
```

但这些 ex-post diagnostics：

- 不得反向取消已在 open 应用的 Action；
- 不得改写 entry reference；
- 不得单独把 Episode 从主 OOS 中删除；
- 必须作为 marketability stratum 单独报告。

必须增加因果 fixture：保持当前 Bar identity/open 不变，只修改其 high/low/close/volume/OI，pending Action 的应用结果必须完全一致。

---

## 9. Completed-Bar 执行语义

V1 没有盘中止损或盘中成交：

- stop / boundary / band / BOS 退出均在 completed close 上确认；
- 退出在下一同物理合约 Bar open 形成 reference；
- source 文档中的“盘中亏3点”“云端止损”等内容不进入 V1；
- high / low 只用于 Swing、形态、MFE / MAE 和 Target milestone；
- high / low 触及 stop 不构成正式 CLOSE；
- 同一 Bar 内 target 与 stop 都被 high/low 触及时，不猜测先后顺序。

Target milestone：

```text
多头 high >= target
空头 low <= target
```

只在该 Bar 完成后确认；由 Target1 触发的 profit floor 从下一根 Bar 才可用于退出判断，不能反向作用于触达 Target1 的当前 Bar。

---

## 10. Intraday 主力映射 Authority

项目现有 `actual_dominant` 由 `MainContractMap` 按 `trading_day` 选择物理合约。Newow 不自行改写映射算法，但 15m 的因果报告必须区分“Bar 因果”与“合约 owner 因果”。

每个 `NewowSourceSegment` 增加：

```text
mapping_policy_id
mapping_trade_date
mapping_source_identity
mapping_observed_at
mapping_availability_status
```

V1 固定：

- Historical 只能消费项目 accepted MainContractMap；
- 不根据当日 Newow 信号、成交量或持仓量重新选择合约；
- 每个交易日 owner 与 MarketDataService 返回结果 golden parity；
- retrospective 报告必须显示 `mapping_availability_status`；
- 若 source metadata 无法证明该 15m trading_day owner 在相应 Bar 前已经可知，则状态为：

```text
HISTORICAL_MAPPING_AVAILABILITY_UNPROVEN
```

此状态不阻止 Historical 图表和公式研究，但：

- 不得将该段计为 prospective OOS；
- 不得作为未来 completed-Live parity 证据；
- 不得支持 Alert / Runtime promotion。

Prospective OOS 和未来 Stage 2 必须在首根 session Bar 前冻结当天 physical contract authority；冻结后当日内不可因后续 volume/OI 变化改 owner。若冻结 authority 与后续 Canonical MainContractMap 不一致，整日进入：

```text
MAPPING_AUTHORITY_CONFLICT
```

并从 prospective strategy outcome 中 fail-closed，不回填另一合约结果。

本节不改变项目全局 `actual_dominant`，只给 Newow 15m 的证据强度增加显式边界。

---

## 11. Outcome 公式与成本边界

方向符号：

```text
LONG  direction_sign = +1
SHORT direction_sign = -1
```

普通完整 Episode：

```text
reference_change_percent =
  direction_sign * (exit_reference - entry_reference)
  / entry_reference * 100

initial_risk = abs(entry_reference - initial_stop)

reference_r_multiple =
  direction_sign * (exit_reference - entry_reference)
  / initial_risk
```

MFE / MAE：

```text
LONG:
  MFE = max(high_since_entry - entry_reference)
  MAE = min(low_since_entry - entry_reference)

SHORT:
  MFE = max(entry_reference - low_since_entry)
  MAE = min(entry_reference - high_since_entry)

MFE_R = MFE / initial_risk
MAE_R = MAE / initial_risk
```

Entry reference Bar 从 effective open 起计入 MFE / MAE；Exit reference Bar 不计入，因为退出参考发生在其 open。若 `initial_risk <= 0`，Episode 无效。

所有结果均是：

```text
gross / pre-cost / reference-only
```

在缺少 tick size、涨跌停价、手续费、滑点、平今规则、保证金和真实可成交性合同前：

- 不输出净收益或“盈利策略”；
- 不用 gross OOS 直接批准 Alert / Runtime；
- 将来进入可执行性研究前，必须新增 product-specific execution-cost Spec；
- 当前 `RESEARCH_SUPPORT_OBSERVED` 只表示公式值得继续研究。

---

## 12. Spec 自审结论

经本修正覆盖后：

- 没有第二次真实开仓语义；
- 没有把主力换月 terminal close 冒充策略成交；
- Range、Pattern 枚举和 primary 选择具备单一确定性规则；
- 数值边界、零方差、零成交量和尾部 pending 行为明确；
- pending Action 只使用 open 时可知字段，不读取当前 Bar future tail；
- Intraday contract owner 的可知性与 Bar 公式因果分开审计；
- completed-Bar 与 intrabar diagnostic 不再混淆；
- OOS 明确为税费前 reference outcome；
- 新周期和 Kernel 变化不会污染旧策略身份。

主 Spec 与本文仍处于 `DESIGN_REVIEW_PENDING`，未进入实现。