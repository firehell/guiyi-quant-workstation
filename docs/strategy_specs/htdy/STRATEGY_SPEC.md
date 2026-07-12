# 火天大有 HTDY 策略骨架

生成时间：2026-07-12

## 1. 策略身份

| 字段 | 值 |
|---|---|
| strategy_code | `huotian_dayou_original` |
| strategy_version | `v0-observation-only` |
| indicator_code | `huo_tian_da_you` |
| indicator_version | `original-v0` |
| status | `observation_only` |
| repainting_risk | `known` |
| backtest_capable | `false` |
| live_capable | `false` |
| alert_capable | `false` |
| trading_capable | `false` |

本骨架只用于后续研究和人工观察复盘，不是可执行策略规格。

## 2. 适用范围

- 当前仅用于 Web 主图人工观察。
- 可用于人工复盘时标注“黄K/白K/三连/XG/XG2 出现过”。
- 不替换 V1-B 苏冰 EMA21 主线。
- 不进入可信回测报告和模拟/实盘流程。

## 3. 观察条件

### 3.1 通道观察

- `ZK1`：双层 XMA 高点通道上轨。
- `ZD1`：双层 XMA 低点通道下轨/压制线。
- `ZD2`：`EMA(ZD1,25)` 色带辅助线。

解释：只用于观察价格和通道的相对位置，不作为交易条件。

### 3.2 黄K观察

黄K表示 `ZD1` 压制或覆盖当前 K 线：

```text
黄K = (ZD1 > LOW AND ZD1 < HIGH)
   OR (ZD1 > MIN(C,O) AND ZD1 < MAX(C,O))
   OR (ZD1 > HIGH)
```

连续 3 根黄K刚成立时，原公式显示 `买多`。归一量化中该字段只能命名为 `buy_observation`，不得命名为正式 `entry_signal`。

### 3.3 白K观察

白K表示实体超过 `ZK1`：

```text
BODYH = MAX(O,C)
BODYL = MIN(O,C)
OVERLOW = MAX(BODYL,ZK1)
白K = BODYH > ZK1 AND BODYH > OVERLOW
```

连续 3 根白K刚成立时，原公式显示 `卖空`。归一量化中该字段只能命名为 `sell_observation`，不得命名为正式 `entry_signal`。

### 3.4 XG 观察

原公式 `XG`：

```text
VAR23 = 100 * XMA(XMA(C-REF(C,1),6),6) / XMA(XMA(ABS(C-REF(C,1)),6),6)
回调买 = LLV(VAR23,2)=LLV(VAR23,7) AND COUNT(VAR23<0,2) AND CROSS(VAR23,MA(VAR23,2))
XG = ZD1 > HIGH AND 回调买 AND L <= ZD1
```

归一量化中只能作为 `callback_buy_observation`。

### 3.5 XG2 观察

原公式 `XG2`：

```text
XG2 = C>O AND DY2<0.02 AND MA(C,5)>MA(C,60) AND C/REF(C,1)>=1.02 AND H<ZK1
```

归一量化中只能作为 `momentum_observation`。由于依赖 `ZK1` 和 `CURRBARSCOUNT`，不能进入策略信号。

## 4. 禁止交易规则

本版本不定义：

- 入场规则。
- 出场规则。
- 止损规则。
- 止盈规则。
- 仓位规则。
- signal fingerprint。
- 企业微信 Gate。

如果后续要进入上述任何一项，必须另开 `huotian_dayou_strict_v1`，先移除未来函数并通过安全审查。

## 5. 数据与成交口径

当前版本无正式数据入口要求，因为不执行回测或信号扫描。

后续 PoC 若需要样本：

- 只能使用 synthetic bars 或本地已通过质量检查的 JM 样本。
- 不写 PostgreSQL。
- 不生成正式报告。
- 不登记 `strategy_signals` / `signal_events`。
- 不触发企业微信。

## 6. 复盘标签建议

可作为人工复盘标签，但不能作为交易结论：

- `htdy_yellow_candle`
- `htdy_white_candle`
- `htdy_three_yellow_observation`
- `htdy_three_white_observation`
- `htdy_xg_observation`
- `htdy_xg2_observation`
- `htdy_repainting_risk_known`

## 7. 升级条件

只有满足以下条件，才允许讨论 `validated` 候选：

1. 新建 strict 版本，不覆盖原始版。
2. 移除 `XMA` 或证明替代实现不读取未来 bar。
3. 通过 future-tail 不重绘测试。
4. 通过逐 bar / 批量一致性测试。
5. 固定 Golden Sample 和人工视觉验收。
6. 明确交易时点：当前 bar 收盘信号只能下一 bar 成交。
7. 另开回测和信号事件 Plan。

## 8. Strict V1 研究候选

第 3 步已新增独立 `huotian_dayou_strict_v1` 方案，见 `STRICT_V1_SPEC.md`。

当前结论：

- strict v1 使用 trailing double EMA 替代 `XMA`，不覆盖 original v0。
- strict v1 输出仍使用 `observation` / `candidate` 命名，不定义正式入场、出场、止损、止盈或仓位规则。
- `XG2`、`DY/DY2`、`DDX/V2/V5/V10/V20` 暂不进入 strict v1。
- 本骨架仍不允许写入正式策略代码、回测报告、`strategy_signals`、`signal_events`、live evaluator 或企业微信。
