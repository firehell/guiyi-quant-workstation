# 火天大有 HTDY Strict V1 方案

生成时间：2026-07-12

## 1. 定位

`huotian_dayou_strict_v1` 是 `huotian_dayou_original_v0` 的独立向后看研究候选，不覆盖原始通达信公式，不替换 Web observation-only 图层。

当前状态：

- `status=strict_research_candidate`
- `source_version=huotian_dayou_original_v0`
- `xma_replacement_policy=double_trailing_ema`
- `closed_bar_only=true`
- `backtest_capable=false`
- `live_capable=false`
- `alert_capable=false`

本版本只验证“移除 XMA 后是否不重绘”。即使通过 future-tail 和逐 bar 测试，也不能直接写入正式策略、可信回测报告、`strategy_signals`、`signal_events`、live evaluator 或企业微信。

## 2. 改写原则

原始公式的 P0 风险来自 `XMA(XMA(...))`。strict v1 采用 trailing EMA 替代：

```text
XMA(XMA(H,25),25) -> EMA_TRAILING_SMA_SEED(EMA_TRAILING_SMA_SEED(H,25),25)
XMA(XMA(L,25),25) -> EMA_TRAILING_SMA_SEED(EMA_TRAILING_SMA_SEED(L,25),25)
XMA(XMA(C-REF(C,1),6),6) -> EMA_TRAILING_SMA_SEED(EMA_TRAILING_SMA_SEED(C-REF(C,1),6),6)
XMA(XMA(ABS(C-REF(C,1)),6),6) -> EMA_TRAILING_SMA_SEED(EMA_TRAILING_SMA_SEED(ABS(C-REF(C,1)),6),6)
```

`EMA_TRAILING_SMA_SEED` 只使用当前和过去 bar。窗口不足或存在无效值时输出 `NaN`，不使用未来值补齐 warm-up。

## 3. 输出字段

| 输出 | 类型 | strict v1 语义 | 当前能力 |
|---|---|---|---|
| `zk1` | 数值 | trailing double EMA 高点通道上轨 | research candidate |
| `zd1` | 数值 | trailing double EMA 低点通道下轨 | research candidate |
| `zd2` | 数值 | `EMA_TRAILING_SMA_SEED(zd1,25)` | research candidate |
| `yellow_candle` | 布尔 | 原黄K条件，依赖 strict `zd1` | observation candidate |
| `white_candle` | 布尔 | 原白K条件，依赖 strict `zk1` | observation candidate |
| `buy_observation` | 布尔 | 三连黄K刚成立 | observation candidate |
| `sell_observation` | 布尔 | 三连白K刚成立 | observation candidate |
| `var23` | 数值 | trailing double EMA 改写后的 VAR23 | research candidate |
| `callback_buy` | 布尔 | strict `var23` 派生回调买观察 | observation candidate |
| `xg_observation` | 布尔 | strict `zd1 + callback_buy` 派生观察字段 | observation candidate |

这些字段不得命名为 `entry_signal`、`exit_signal`、`buy_signal`、`sell_signal` 或任何可行动交易信号。

## 4. 明确排除

strict v1 不实现以下原始字段：

- `DDX`
- `V2/V5/V10/V20`
- `DY/DY2`
- `XG2`
- `XG2_DRAWTEXT`

原因：

- `FROMOPEN` 在期货多周期、夜盘和非日内周期中的定义未锁定。
- `CURRBARSCOUNT` 是图表末端语义，不等同历史回测或 live evaluator 的稳定字段。
- `XG2` 仍需要单独定义数据字段、bar 语义和 confirmed-bar 规则。

## 5. 与 original v0 的差异

| 项目 | original v0 | strict v1 |
|---|---|---|
| 通道核心 | `XMA(XMA(H/L,25),25)` | trailing double EMA |
| `VAR23` 核心 | 双层 `XMA` | trailing double EMA |
| 是否读取未来 bar | 是 | 否 |
| 是否会重绘 | 是 | future-tail 测试应不重绘 |
| Web 展示 | 已有 observation-only 层 | 本步不接 Web |
| 策略/扫描/live | 禁止 | 仍禁止 |
| Golden Sample | 后续第 4 步 | 后续第 4 步 |

strict v1 的数值不追求与 original v0 完全一致；它是安全替代方案候选，不是“无风险复刻原指标”。

## 6. 验证要求

本步通过标准：

- `future_tail_invariance`：修改未来尾部 bar 不改变更早位置的 strict 输出。
- `append_consistency`：逐 bar prefix 计算的最新值与一次性批量计算相同。
- warm-up 保持 `NaN`，不使用未来值或 0 填充。
- 输出字段仅包含 strict v1 白名单字段。
- metadata 固定标记 `backtest_capable=false`、`live_capable=false`、`alert_capable=false`。
- 禁止链路无 diff：正式策略、API 业务、scanner、live evaluator、DB、data、`.env` 均不被修改。

## 7. 后续 Gate

第 3 步完成后，只能说明：

```text
huotian_dayou_strict_v1 research candidate created and future-tail checked
```

不能把本阶段表述为已进入可信回测、预警链路、正式策略链路或可信指标定级。

第 4 步自动数值验收已通过，用户提供的 `JM8 焦煤主连 15分钟` 通达信截图已关闭外部视觉 oracle Gate，当前状态为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。未提供通达信数值导出，因此不能声明逐点数值 oracle pass。

第 5 步离线候选评估见 Git history（原 `OFFLINE_CANDIDATE_EVAL.md`）。它只允许输出 candidate events 和安全边界证据，不授权正式策略、可信回测报告、scanner、live evaluator、数据库或企业微信接入。
