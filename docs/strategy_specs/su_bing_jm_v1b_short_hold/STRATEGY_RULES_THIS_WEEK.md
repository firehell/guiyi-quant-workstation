# 苏冰 JM V1-B 短持有策略说明（本周整理版）

## 1. 当前策略一句话说明

当前修改后的苏冰策略是一个独立的 V1-B 研究策略：

```text
日线 EMA21 判断方向
→ 15m 或 5m 独立寻找 EMA21 回踩入场
→ 下一根同周期 K 线开盘成交
→ 固定 1 手上限
→ 止损 / 1.5R 止盈 / 信号失效 / 第 8 根 bar 时间退出
→ 回测和复盘，不自动下单
```

策略代码：

```text
su_bing_jm_v1b_short_hold
```

策略版本：

```text
v0.1.1-spec
```

当前版本不是旧 `su_bing_ema21` 的修补版，也不继承旧策略参数。旧策略只能作为历史或工程参考，不能作为本版本的规则来源。

---

## 2. 适用范围

| 项目 | 当前规则 |
|---|---|
| 项目阶段 | V1-B：焦煤 JM 3 年真实数据短持有策略闭环 |
| 品种 | 焦煤 JM |
| 数据源 | RQData / local standard parquet |
| 数据角色 | `primary` |
| 数据质量 | `passed` |
| 方向周期 | 1d |
| 入场周期 | 15m 和 5m 两条独立链路 |
| 回测底座 | vn.py CTA BacktestingEngine |
| 实盘边界 | 只做研究、回测、复盘、提醒，不自动下单 |

15m 和 5m 是两套独立回测链路：

- 15m 的信号、成交、交易明细和报告只评价 15m。
- 5m 的信号、成交、交易明细和报告只评价 5m。
- 两者不能混用交易结果，也不能把一个周期的表现当成另一个周期的结论。

---

## 3. 当前冻结参数

| 参数 | 当前值 | 说明 |
|---|---:|---|
| `ema_period` | 21 | 入场周期 EMA21 |
| `daily_ema_period` | 21 | 日线方向 EMA21 |
| `pullback_lookback_bars` | 3 | 最近 3 根已完成入场周期 K 线判断是否回踩 EMA21 |
| `pullback_interaction_ticks` | 1 | 距 EMA21 1 tick 内视为触碰 / 互动 |
| `max_entry_ema_distance_ticks` | 8 | 收盘价距离 EMA21 最多 8 tick |
| `stop_buffer_ticks` | 1 | 止损放在信号 K 线极值外 1 tick |
| `max_initial_stop_distance_ticks` | 30 | 初始止损距离最多 30 tick |
| `take_profit_enabled` | true | 启用止盈 |
| `take_profit_r_multiple` | 1.5 | 止盈为 1.5R |
| `planned_time_exit_bars` | 8 | 未触发其他退出时，第 8 根持仓 bar 后时间退出 |
| `slippage_ticks` | 1 | 每边 1 tick 滑点 |
| `initial_capital` | 1,000,000 | 固定回测初始资金 |
| `risk_per_trade_ratio` | 0.5% | 单笔风险预算 |
| `maximum_position` | 1 手 | 每次最多开 1 手 |
| `max_entries_per_trading_day_per_interval` | 2 | 每个交易日每个周期最多入场 2 次 |
| `allow_long` | true | 允许做多 |
| `allow_short` | true | 允许做空 |
| `macd_usage` | record only | MACD 只记录，不参与过滤 |
| `breakout_breakdown_enabled` | false | 突破 / 跌破入场禁用 |
| `volume_confirmation_enabled` | false | 量能确认禁用 |

---

## 4. 日线方向怎么判断

日线只用于判断方向，不直接入场。

对每一根 15m / 5m 小周期 K 线，策略只允许使用该交易日之前已经确认收盘的日线。也就是说：

```text
小周期交易日 = D
可用日线 = D-1 或更早的已完成日线
禁止使用 D 当天尚未收盘的日线
```

### 4.1 可以做多的日线条件

满足以下全部条件，日线方向才是多头：

```text
已确认日线 close > 已确认日线 EMA21
并且
当前已确认日线 EMA21 >= 上一根已确认日线 EMA21
```

对应状态：

```text
confirmed_daily_long_ema21
```

### 4.2 可以做空的日线条件

满足以下全部条件，日线方向才是空头：

```text
已确认日线 close < 已确认日线 EMA21
并且
当前已确认日线 EMA21 <= 上一根已确认日线 EMA21
```

对应状态：

```text
confirmed_daily_short_ema21
```

### 4.3 不允许入场的日线状态

如果日线不是明确多头或明确空头，则小周期信号全部拒绝：

```text
daily_direction_neutral
daily_direction_unavailable_confirmed_bars_insufficient
```

这类信号只记为 rejected signal，不开仓。

---

## 5. 什么时候入场

当前版本只做 EMA21 回踩入场：

```text
pullback_only
```

突破、跌破、量能确认、MACD 过滤都不参与当前版本入场。

### 5.1 入场信号和成交时点

策略使用同周期已经收盘的 K 线作为信号 K 线：

```text
信号 K 线 = bar t
成交 K 线 = bar t+1
成交价格 = bar t+1 open ± 1 tick 滑点
```

做多时：

```text
entry_price = 下一根 bar open + 1 tick
```

做空时：

```text
entry_price = 下一根 bar open - 1 tick
```

信号生成时禁止使用下一根 K 线的 high / low / close。

### 5.2 做多入场条件

做多必须同时满足：

```text
1. 日线方向 = long
2. 入场周期 close > 入场周期 EMA21
3. 入场周期 EMA21 >= 上一根入场周期 EMA21
4. 最近 3 根入场周期 K 线内，价格曾经回踩 / 触碰 EMA21 附近
5. 信号 K 线 close 重新站上 EMA21
6. 信号 K 线 close 距 EMA21 不超过 8 tick
7. 初始止损距离不超过 30 tick
8. 当天该周期入场次数未超过 2 次
9. 合约交易参数完整：price_tick、合约乘数、手续费规则、保证金率都存在
```

回踩 / 触碰 EMA21 的具体判断：

```text
最近 3 根 K 线中，任意一根 low <= 对应 EMA21 + 1 tick
```

做多信号原因：

```text
daily_long_ema21_pullback_distance_guard
```

### 5.3 做空入场条件

做空必须同时满足：

```text
1. 日线方向 = short
2. 入场周期 close < 入场周期 EMA21
3. 入场周期 EMA21 <= 上一根入场周期 EMA21
4. 最近 3 根入场周期 K 线内，价格曾经反抽 / 触碰 EMA21 附近
5. 信号 K 线 close 重新跌回 EMA21 下方
6. 信号 K 线 close 距 EMA21 不超过 8 tick
7. 初始止损距离不超过 30 tick
8. 当天该周期入场次数未超过 2 次
9. 合约交易参数完整：price_tick、合约乘数、手续费规则、保证金率都存在
```

反抽 / 触碰 EMA21 的具体判断：

```text
最近 3 根 K 线中，任意一根 high >= 对应 EMA21 - 1 tick
```

做空信号原因：

```text
daily_short_ema21_pullback_distance_guard
```

---

## 6. 什么时候不入场

下面任意一种情况出现，当前信号都不会开仓，只记录 rejected signal：

| 拒绝原因 | 含义 |
|---|---|
| `warming_up` | EMA21 或回踩窗口所需 K 线不足 |
| `daily_direction_blocks_entry` | 日线方向不是明确多头或空头 |
| `daily_entry_limit_reached` | 当天该周期已入场 2 次 |
| `missing_price_tick` | 缺少最小变动价位 |
| `missing_contract_multiplier` | 缺少合约乘数 |
| `missing_commission_rule` | 缺少手续费规则 |
| `missing_margin_rate` | 缺少保证金率 |
| `long_pullback_not_interacted_with_ema21` | 多头最近 3 根 K 线没有回踩 EMA21 |
| `long_close_not_back_above_ema21` | 多头信号 K 线没有重新站上 EMA21 |
| `long_entry_ema21_not_rising` | 多头入场周期 EMA21 没有走平或上升 |
| `long_entry_ema_distance_too_wide` | 多头收盘价离 EMA21 超过 8 tick |
| `short_pullback_not_interacted_with_ema21` | 空头最近 3 根 K 线没有反抽 EMA21 |
| `short_close_not_back_below_ema21` | 空头信号 K 线没有重新跌回 EMA21 下方 |
| `short_entry_ema21_not_falling` | 空头入场周期 EMA21 没有走平或下降 |
| `short_entry_ema_distance_too_wide` | 空头收盘价离 EMA21 超过 8 tick |
| `initial_stop_distance_too_wide` | 成交后初始止损距离超过 30 tick |
| `position_size_zero` | 按风险计算后手数为 0 |

---

## 7. 每次开仓几手

当前版本的结论很简单：

```text
每次最多 1 手。
实际回测中通过风控检查后也是 1 手。
```

手数计算仍按风险公式做一遍，但最后被 `maximum_position = 1` 限制住。

### 7.1 手数计算公式

```text
initial_risk_per_contract =
  abs(entry_price - initial_stop_price) * contract_multiplier
  + estimated_commission
  + estimated_slippage

raw_position_size =
  floor(initial_capital * risk_per_trade_ratio / initial_risk_per_contract)

position_size =
  min(raw_position_size, maximum_position)
```

当前固定值：

```text
initial_capital = 1,000,000
risk_per_trade_ratio = 0.005
single_trade_risk_budget = 5,000 CNY
maximum_position = 1 手
```

所以：

- 如果按风险公式算出来大于等于 1 手，最终开 1 手。
- 如果按风险公式算出来小于 1 手，拒绝开仓。
- 如果 1 手保证金超过初始资金假设，拒绝开仓。
- 手数不能脱离止损距离单独决定。

---

## 8. 初始止损怎么放

止损必须在入场前确定。

### 8.1 多单止损

```text
initial_stop_price = 信号 K 线 low - 1 tick
```

### 8.2 空单止损

```text
initial_stop_price = 信号 K 线 high + 1 tick
```

### 8.3 止损距离限制

成交后重新计算：

```text
abs(entry_price - initial_stop_price) <= 30 tick
```

如果超过 30 tick，则这笔交易被拒绝。

当前版本不启用 ATR 止损，不启用摆动高低点 lookback 止损。

---

## 9. 什么时候离场

当前离场优先级固定为：

```text
1. 止损
2. 止盈
3. 信号失效退出
4. 时间退出
```

如果同一根 bar 同时触及止损和止盈，按保守规则：

```text
止损优先
```

### 9.1 止损退出

多单：

```text
当前 bar low <= stop_loss_price
```

空单：

```text
当前 bar high >= stop_loss_price
```

止损成交价：

- 正常触及：按止损价再扣 / 加 1 tick 滑点。
- 跳空穿越：按当前 bar open 再扣 / 加 1 tick 滑点，并记录 `gap_execution = true`。

### 9.2 止盈退出

止盈为固定 1.5R。

多单：

```text
take_profit_price = entry_price + abs(entry_price - stop_loss_price) * 1.5
```

空单：

```text
take_profit_price = entry_price - abs(entry_price - stop_loss_price) * 1.5
```

多单触发：

```text
当前 bar high >= take_profit_price
```

空单触发：

```text
当前 bar low <= take_profit_price
```

### 9.3 信号失效退出

信号失效不是立刻在当前收盘价平仓，而是在当前 bar 收盘确认失效后，下一根同周期 bar 开盘退出。

多单信号失效：

```text
当前已完成 bar close < 入场周期 EMA21
或
下一次可确认的日线方向不再是 long
```

空单信号失效：

```text
当前已完成 bar close > 入场周期 EMA21
或
下一次可确认的日线方向不再是 short
```

退出成交：

```text
下一根 bar open ± 1 tick 滑点
```

退出原因：

```text
signal_failure_exit
```

### 9.4 时间退出

如果没有触发止损、止盈、信号失效，则执行时间退出。

15m 链路：

```text
最多持有 8 根 15m K 线
```

5m 链路：

```text
最多持有 8 根 5m K 线
```

V1-B 目标里保留了 5-8 根 bar 的短持有语义，但当前 v0.1.1 的实际规则是：

```text
第 5 根 bar 只作为观察下限，不主动退出。
第 8 根 completed holding bar 触发时间退出。
下一根同周期 bar open 成交。
```

退出原因：

```text
time_exit_bar_8
```

---

## 10. 成本和交易参数

每笔交易必须具备：

```text
price_tick
contract_multiplier
commission_rate 或 commission_per_contract
margin_rate
```

缺任何一个关键字段都不允许继续回测。

当前 JM V1-B 任务配置中的基础回测参数：

```text
rate = 0.0001
slippage = 1.0
size = 60
pricetick = 0.5
capital = 1,000,000
```

策略内部按交易参数记录：

- 手续费。
- 双边滑点。
- 合约乘数。
- 保证金占用。
- 毛盈亏。
- 净盈亏。
- 是否跳空成交。

---

## 11. 当前版本明确禁用什么

当前版本禁用：

```text
突破入场
跌破入场
量能确认
MACD 过滤
ATR 止损
同一版本内参数优化
Review Tags 反向影响入场
复盘 note 反向影响入场
回测结果反向影响同一笔交易
连续合约直接交易
实盘下单
自动下单
CTP / TqSdk 交易接口
```

MACD 当前只作为记录字段和后续复盘候选，不参与任何入场或出场判断。

---

## 12. 当前回测结果摘要

本周整理的上下文中，当前本地正式数据覆盖：

```text
2023-06-28T00:00:00 -> 2025-12-31T15:00:00
```

目标窗口到 2026-06-28，但本地 `primary / passed` JM 数据尚未覆盖 2026-01-01 至 2026-06-28，所以没有使用合成数据或替代数据补齐。

### 12.1 15m 结果

| 指标 | 数值 |
|---|---:|
| 初始资金 | 1,000,000.00 |
| 期末权益 | 881,975.90 |
| 总收益 | -11.80% |
| 年化收益 | -4.87% |
| 最大回撤 | 11.80% |
| 交易次数 | 763 |
| 胜率 | 29.75% |
| 盈亏比 | 0.992 |
| 单笔期望 | -154.68 |
| 最大连亏 | 11 |
| 毛盈亏 | -50,910.00 |
| 净盈亏 | -118,024.10 |
| 手续费 | 21,334.10 |
| 滑点 | 45,780.00 |
| rejected signals | 11,379 |

### 12.2 5m 结果

| 指标 | 数值 |
|---|---:|
| 初始资金 | 1,000,000.00 |
| 期末权益 | 815,706.22 |
| 总收益 | -18.43% |
| 年化收益 | -7.78% |
| 最大回撤 | 18.43% |
| 交易次数 | 1,186 |
| 胜率 | 25.72% |
| 盈亏比 | 0.788 |
| 单笔期望 | -155.39 |
| 最大连亏 | 19 |
| 毛盈亏 | -79,020.00 |
| 净盈亏 | -184,293.78 |
| 手续费 | 34,113.78 |
| 滑点 | 71,160.00 |
| rejected signals | 36,982 |

当前结论：

```text
不建议进入模拟盘或实盘验证。
建议进入 v0.2 研究设计阶段。
```

原因：

- 15m 和 5m 都是负收益。
- 两个周期最大回撤都超过 10% review threshold。
- 成本对短持有策略影响非常明显。
- 5m 交易频率更高，成本压制更重。
- 下一版应优先研究信号质量、过滤条件、出场机制和成本敏感性，不应直接做全样本参数优化。

---

## 13. 当前策略流程图

```text
读取 1d / 15m / 5m primary passed 数据
        |
        v
用 D-1 或更早日线计算 EMA21 方向
        |
        v
日线 long? -------------------- 日线 short?
   |                                |
   v                                v
15m / 5m 找多头回踩 EMA21       15m / 5m 找空头反抽 EMA21
   |                                |
   v                                v
close 重新站上 EMA21            close 重新跌回 EMA21
   |                                |
   v                                v
距离 EMA21 <= 8 tick             距离 EMA21 <= 8 tick
   |                                |
   v                                v
下一根 bar open 成交             下一根 bar open 成交
   |                                |
   v                                v
最多 1 手，预设止损和 1.5R 止盈
        |
        v
按优先级退出：
止损 -> 止盈 -> 信号失效 -> 第 8 根 bar 时间退出
        |
        v
生成交易明细、成本、回撤、K 线买卖点、复盘数据
```

---

## 14. 风控和审查要点

当前版本已经明确的安全边界：

- 信号只使用当前及过去已完成 K 线。
- 日线方向只使用 D-1 或更早已确认日线。
- 当前 bar 收盘出信号，下一 bar 开盘成交。
- 同 bar 同时触发止损和止盈时，止损优先。
- 手续费、滑点、合约乘数、保证金必须计入。
- 每笔交易必须能追踪到具体交易参数、入场原因、退出原因和策略版本。
- Review Tags 只能用于事后复盘，不能参与同一笔交易信号。
- V1-B 不接实盘，不自动下单。

下一版 v0.2 需要重点审查：

1. 亏损主要来自交易成本、入场质量，还是出场机制。
2. `pullback_only` 是否过宽，导致震荡行情中过多入场。
3. 5m 是否需要降低交易频率或提高信号门槛。
4. 日线 EMA21 方向过滤是否滞后。
5. 是否需要增加趋势强度、波动率、时段、距离、结构类过滤。
6. 不允许全样本调参后直接验收，必须做样本切分或样本外验证。

---

## 15. 相关文件

| 文件 | 作用 |
|---|---|
| `docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md` | 当前策略规格 |
| `docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC_REVIEW.md` | 规格审查 |
| `docs/strategy_specs/su_bing_jm_v1b_short_hold/BACKTEST_REVIEW_CONTEXT.md` | 本周回测审查上下文 |
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/config_schema.py` | 冻结参数和校验 |
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/default_params.json` | 默认参数快照 |
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/vnpy_strategy.py` | 当前策略实现 |
| `services/quant-api/app/backtest/v1b_jm_tasks.py` | JM V1-B 回测任务配置 |
| `services/quant-api/tests/test_su_bing_jm_v1b_short_hold.py` | 当前策略测试 |
