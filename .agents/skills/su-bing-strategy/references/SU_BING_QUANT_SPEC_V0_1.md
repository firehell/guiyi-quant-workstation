# SU_BING_QUANT_SPEC_V0_1

## 0. 文档定位

本文档是苏冰 EMA21 趋势系统的 v0.1 可回测量化规格，用于指导后续 vn.py `CtaTemplate` 策略实现、回测任务配置、交易明细归档、K 线 marker 和复盘 note 设计。

本文档不包含课程原文、私有 Notion 内容、主观案例硬编码、买卖点建议、实盘下单逻辑或经纪商接口调用。

来源依据：

- `SU_BING_RULEBOOK.md`：RULE-001 至 RULE-014、RULE-017、RULE-018。
- `SU_BING_REVIEW_TAGS.md`：TAG-001 至 TAG-014。
- 仓库当前苏冰 EMA21 草稿与 `docs/BACKTEST_ENGINE.md` 中已有参数口径。

重要边界：

- `v0.1` 是最小可回测规则规格，不是实盘策略。
- Rulebook 未给出的阈值统一标注为 v0.1 工程默认 / 待样本外验证，不包装为苏冰原始规则。
- 回测结果不等于实盘结果。

## 1. 策略名称

- strategy_code: `su_bing_ema21`
- strategy_name: 苏冰 EMA21 趋势系统
- strategy_family: `su_bing`

## 2. 策略版本

- strategy_version: `v0.1`
- version_status: `quant_spec`
- version_scope: 国内期货 bar 级回测规格
- version_boundary: 只用于研究、回测、复盘和信号提醒，不做实盘自动下单。

## 3. 策略目标

将苏冰体系中可规则化的趋势、EMA21、MACD、ATR 止损、R 倍止盈、资金管理和复盘要求，整理为可以直接指导 vn.py CTA 策略实现的量化规格。

v0.1 的目标是：

- 用 EMA21 定义趋势背景和价格位置。
- 用 MACD 作为辅助确认，不让 MACD 单独触发交易。
- 用 ATR 定义初始风险、止损距离和价格偏离过滤。
- 用固定 R 倍定义初始止盈目标。
- 明确信号确认时点和成交假设，避免未来函数。
- 明确手续费、滑点、合约乘数和保证金必须进入逐笔回测结果。
- 让每笔交易可以追溯到策略版本、参数、信号理由、止损价、止盈价、成交假设和复盘标签。

## 4. 适用市场

- market: 国内期货
- data_source: RQData / local standard parquet
- backtest_engine: vn.py / VeighNa CTA BacktestingEngine
- product_scope: V1 优先用于国内期货趋势或波段研究品种，具体品种池由回测任务配置决定。

禁止：

- 不用于股票、期权、外盘或加密资产，除非后续新版本重新定义市场口径。
- 不接 CTP、TqSdk 或任何实盘交易接口。
- 不做无人值守自动实盘。

## 5. 适用周期

支持周期：

| 周期 | v0.1 职责 | 是否可入场 | 说明 |
|---|---|---:|---|
| `15m` | 入场、持仓、出场周期 | yes | 适合较短波段回测，信号更频繁。 |
| `30m` | 入场、持仓、出场周期 | yes | 作为 15m 与 60m 之间的中间候选周期。 |
| `60m` | 入场、持仓、出场周期 | yes | 信号更慢，过滤部分小周期噪音。 |
| `1d` | 方向过滤周期 | conditional | 默认只做方向过滤，不作为 v0.1 高频入场周期。 |

多周期规则：

- `1d` 方向过滤只能使用已经完成并且在当前入场 bar 之前可见的日线。
- 日内周期不能提前读取当天尚未收盘的日线结果。
- 当日线方向过滤启用时，日内多头信号只能使用前一交易日或更早已确认的日线方向；空头同理。
- 每个回测任务必须明确 `entry_timeframe`，不得在同一笔交易中混用多个入场周期。

## 6. 趋势过滤规则

趋势过滤来自 RULE-001、RULE-002、RULE-003、RULE-008、RULE-013。

### 6.1 基础方向

对当前入场周期的已完成 bar 计算 EMA21：

- 多头环境：当前已完成 bar 的 `close > EMA21`。
- 空头环境：当前已完成 bar 的 `close < EMA21`。
- 中性环境：`close == EMA21` 或指标不可用。

基础方向只定义环境，不单独触发入场。

### 6.2 EMA21 斜率

v0.1 建议记录 EMA21 斜率字段：

- `ema21_slope = EMA21[current_completed_bar] - EMA21[previous_completed_bar]`
- 多头过滤候选：`ema21_slope > 0`
- 空头过滤候选：`ema21_slope < 0`

斜率阈值未由 Rulebook 给出。v0.1 只使用正负方向作为工程默认，后续如需最小斜率阈值必须生成新版本并做样本外验证。

### 6.3 日线方向过滤

当 `daily_direction.enabled = true` 时：

- 日线多头方向：最近一个已确认日线 `close > daily EMA21`。
- 日线空头方向：最近一个已确认日线 `close < daily EMA21`。
- 日线中性：日线 close 等于 EMA21、日线不足预热窗口、ATR 无效或日线数据缺失。

日线方向过滤生效规则：

- 当前日内 bar 只能使用 `daily.trading_day < intraday.trading_day` 的日线。
- 不允许用当天未收盘日线过滤当天日内信号。
- 日线方向与日内信号方向冲突时，禁止入场。

### 6.4 震荡与趋势不明

v0.1 不实现复杂震荡识别模型。以下情况直接视为禁止交易或观察：

- EMA21 方向冲突。
- 日线方向过滤启用但方向为 `neutral` 或 `unavailable`。
- ATR 无效或小于等于 0。
- 价格距离 EMA21 过远，导致追高追空风险。
- MACD 与趋势方向冲突。

## 7. EMA21 规则

EMA21 来自 RULE-004，并作为趋势背景、位置关系和风险过滤字段。

### 7.1 计算

- 参数：`ema_period = 21`
- 输入：当前交易周期已完成 bar 的 close 序列。
- 输出字段：`ema21`、`ema21_slope`、`close_vs_ema21`、`ema_distance_atr`

### 7.2 价格位置

- 多头候选必须满足：当前已完成 bar `close > EMA21`。
- 空头候选必须满足：当前已完成 bar `close < EMA21`。
- `close == EMA21` 时不交易。

### 7.3 偏离约束

用 ATR 衡量价格相对 EMA21 的偏离：

```text
ema_distance_atr = abs(close - EMA21) / ATR
```

v0.1 工程默认：

- `max_ema_deviation_atr = 1.5`
- 当 `ema_distance_atr > max_ema_deviation_atr` 时，禁止新开仓。

该阈值为工程默认 / 待样本外验证，不是 Rulebook 原文阈值。

### 7.4 EMA21 不得单独触发

EMA21 只能作为趋势、位置和过滤条件。任何入场必须同时满足趋势过滤、MACD 辅助、ATR 风险、成交量确认、方向开关和禁止交易检查。

## 8. MACD 辅助规则

MACD 来自 RULE-005 和 TAG-003。MACD 只做辅助确认，不单独生成交易。

### 8.1 计算

v0.1 工程默认：

- `macd_fast = 12`
- `macd_slow = 26`
- `macd_signal = 9`

输出字段：

- `dif`
- `dea`
- `macd_hist`
- `macd_cross_type`
- `macd_near_zero_axis`

### 8.2 多头辅助

多头候选至少需要满足：

- 当前已完成 bar 的 `DIF > DEA`，或当前 bar 形成 MACD 金叉。
- MACD 不与 EMA21 多头环境冲突。
- v0.1 可记录 `golden_cross` 作为入场理由的一部分。

### 8.3 空头辅助

空头候选至少需要满足：

- 当前已完成 bar 的 `DIF < DEA`，或当前 bar 形成 MACD 死叉。
- MACD 不与 EMA21 空头环境冲突。
- v0.1 可记录 `death_cross` 作为入场理由的一部分。

### 8.4 零轴附近过滤

当前仓库草稿使用 `abs(DIF) <= ATR` 作为零轴附近工程口径。v0.1 规格允许保留该工程默认，但必须标注为待验证：

- `macd_zero_axis_guard = abs(DIF) <= ATR`
- 该规则不是苏冰原文阈值，后续可改为更稳定的归一化阈值并生成新版本。

### 8.5 暂不实现背离

MACD 背离、失败、二次确认等结构需要确认 bar 和更明确的结构定义。v0.1 不实现背离，避免使用未来高低点或事后走势。

## 9. ATR 止损

ATR 止损来自 RULE-010 和 TAG-010。

### 9.1 计算

v0.1 工程默认：

- `atr_period = 14`
- `stop_atr_multiple = 2.0`

ATR 只能使用当前及历史已完成 bar。

### 9.2 初始风险距离

```text
risk_distance = ATR * stop_atr_multiple
```

ATR 无效、为 0 或缺失时，禁止开仓。

### 9.3 多头止损

多头信号确认时：

```text
initial_stop_price = signal_close - risk_distance
```

实际成交发生在下一根 K 线。后续实现必须在成交后重新校验：

- 若下一根成交价已经穿越或不合理接近止损价，必须跳过入场或按实现规格明确处理。
- 不允许用未来最低价决定是否开仓。

### 9.4 空头止损

空头信号确认时：

```text
initial_stop_price = signal_close + risk_distance
```

实际成交发生在下一根 K 线。后续实现必须在成交后重新校验止损距离和单笔风险。

### 9.5 止损不可后移

v0.1 不允许因为亏损厌恶、人工判断或复盘标签后移初始止损。若后续实现移动止损，必须单独生成新版本。

## 10. R 倍止盈

R 倍止盈来自 RULE-011 和 TAG-011。

### 10.1 R 定义

```text
R = abs(entry_price - initial_stop_price)
```

R 必须在入场成交后根据实际成交价与初始止损价计算，不得使用事后最高浮盈或未来价格。

### 10.2 固定 R 倍目标

v0.1 工程默认：

- `take_profit_r_multiple = 2.5`

多头：

```text
take_profit_price = entry_price + R * take_profit_r_multiple
```

空头：

```text
take_profit_price = entry_price - R * take_profit_r_multiple
```

### 10.3 盈利保护边界

v0.1 只实现固定 R 倍止盈，不实现分批止盈、移动止盈或主观提前止盈。

## 11. 入场条件

入场来自 RULE-002、RULE-003、RULE-004、RULE-005、RULE-008、RULE-013，并参考 TAG-001 至 TAG-009。

### 11.1 多头入场

当前入场周期 bar 收盘后，同时满足以下条件，生成多头 pending signal：

1. `allow_long = true`
2. 指标预热完成。
3. 当前已完成 bar `close > EMA21`。
4. EMA21 斜率为正，或后续实现明确允许不使用斜率过滤。
5. 若日线方向过滤启用，已确认日线方向为 `long`。
6. MACD 辅助多头：`DIF > DEA` 或形成已确认金叉。
7. `ema_distance_atr <= max_ema_deviation_atr`。
8. ATR 有效且 `risk_distance > 0`。
9. 成交量确认满足 `volume_ratio >= volume_multiplier`，或后续实现明确关闭成交量过滤并生成新版本。
10. 不触发任何禁止交易条件。

### 11.2 空头入场

当前入场周期 bar 收盘后，同时满足以下条件，生成空头 pending signal：

1. `allow_short = true`
2. 指标预热完成。
3. 当前已完成 bar `close < EMA21`。
4. EMA21 斜率为负，或后续实现明确允许不使用斜率过滤。
5. 若日线方向过滤启用，已确认日线方向为 `short`。
6. MACD 辅助空头：`DIF < DEA` 或形成已确认死叉。
7. `ema_distance_atr <= max_ema_deviation_atr`。
8. ATR 有效且 `risk_distance > 0`。
9. 成交量确认满足 `volume_ratio >= volume_multiplier`，或后续实现明确关闭成交量过滤并生成新版本。
10. 不触发任何禁止交易条件。

### 11.3 信号输出字段

后续实现建议每个 pending signal 至少输出：

- `strategy_code`
- `strategy_version`
- `entry_timeframe`
- `signal_bar_time`
- `signal_direction`
- `signal_reason`
- `ema21`
- `ema21_slope`
- `dif`
- `dea`
- `atr`
- `ema_distance_atr`
- `volume_ratio`
- `initial_stop_price`
- `planned_take_profit_price`
- `execution_timing`
- `review_tag_candidates`

## 12. 出场条件

出场来自 RULE-009、RULE-010、RULE-011、RULE-017，并参考 TAG-010 至 TAG-014。

### 12.1 止损出场

持仓后，如价格触发初始 ATR 止损，生成止损退出。

实现要求：

- 不得用未来 bar 的 high/low 提前判断当前 bar 是否触发。
- bar 级回测必须明确 stop 触发价和成交价假设。
- 若使用下一根 K 线成交，必须记录 `exit_signal_time` 与 `exit_fill_time`。

### 12.2 固定 R 倍止盈出场

持仓后，如价格触发固定 R 倍止盈，生成止盈退出。

实现要求：

- 止盈目标在入场成交后确定。
- 不得用最高浮盈倒推止盈。
- 必须记录 `take_profit_price` 和 `exit_reason`。

### 12.3 EMA21 失效出场

v0.1 允许以下出场候选：

- 多头持仓后，已完成 bar `close < EMA21`，视为 EMA21 多头环境失效。
- 空头持仓后，已完成 bar `close > EMA21`，视为 EMA21 空头环境失效。

失效信号在当前 K 线收盘确认，下一根 K 线成交。

### 12.4 MACD 反向辅助出场

v0.1 允许以下出场候选：

- 多头持仓后，已完成 bar 出现 MACD 死叉或 `DIF < DEA`。
- 空头持仓后，已完成 bar 出现 MACD 金叉或 `DIF > DEA`。

MACD 反向只作为辅助出场候选；若后续实现要作为强制出场，必须在参数中明确。

### 12.5 时间止损

v0.1 文档只保留时间止损扩展位，不默认启用。若后续实现 `max_hold_bars`，必须作为参数写入并生成新版本或明确 v0.1 子版本。

## 13. 禁止交易条件

任一条件满足时，禁止新开仓：

- 指标预热不足。
- 当前 K 线尚未收盘。
- ATR 无效、为 0 或缺失。
- EMA21 缺失或计算窗口不足。
- MACD 缺失或计算窗口不足。
- 日线方向过滤启用但日线方向为 `neutral`、`unavailable` 或与入场方向冲突。
- 当前价格偏离 EMA21 过远：`ema_distance_atr > max_ema_deviation_atr`。
- 趋势方向、EMA21 位置、MACD 辅助之间互相冲突。
- 合约乘数、最小变动价位、手续费、滑点或保证金参数缺失，导致成本或风险不可计算。
- 数据质量为 failed，或数据角色不是正式回测允许的 `primary` / `rqdata` / `local_parquet` 口径。
- 当前回测任务试图使用未来主力映射、未来复权因子、未来交易参数或事后复盘标签。
- 策略试图接实盘接口、自动下单或生成经纪商指令。

## 14. 资金管理规则

资金管理来自 RULE-010、RULE-012 和 TAG-013。

### 14.1 单笔风险

v0.1 要求实现层具备单笔风险上限字段：

```text
position_risk = abs(entry_price - initial_stop_price) * contract_multiplier * volume
position_risk_pct = position_risk / account_equity
```

Rulebook 未给出固定比例。v0.1 建议后续实现将 `risk_per_trade_pct` 作为外部任务参数，默认不高于 1%，并标注为工程默认 / 待验证。

### 14.2 手数计算

后续实现建议：

```text
max_volume_by_risk = floor(account_equity * risk_per_trade_pct / (R * contract_multiplier))
max_volume_by_margin = floor(account_available_cash / margin_required_per_contract)
volume = min(max_volume_by_risk, max_volume_by_margin, task_volume_limit)
```

若计算结果小于 1 手，禁止开仓。

### 14.3 保证金约束

每笔交易必须计算：

- `margin_ratio`
- `margin_required`
- `max_margin_required`
- `max_margin_usage_pct`

保证金参数必须来自对应历史时点的交易参数表或已审查的 fallback 规则，不得使用未来参数。

### 14.4 回撤和连亏

回测报告必须统计：

- 最大回撤金额。
- 最大回撤比例。
- 最大连续亏损。
- 胜率。
- 盈亏比。
- 期望值。
- 总手续费。
- 总滑点。

## 15. 参数表

以下参数为 v0.1 工程默认 / 待样本外验证，除 `ema_period=21` 外，不声明为苏冰原始阈值。

| 参数 | 默认值 | 类型 | 用途 | 状态 |
|---|---:|---|---|---|
| `entry_timeframe` | `15m` / `30m` / `60m` | enum | 入场和持仓周期 | 回测任务指定 |
| `ema_period` | `21` | int | EMA21 趋势线 | 规则核心 |
| `macd_fast` | `12` | int | MACD fast EMA | 工程默认 |
| `macd_slow` | `26` | int | MACD slow EMA | 工程默认 |
| `macd_signal` | `9` | int | MACD signal EMA | 工程默认 |
| `atr_period` | `14` | int | ATR 计算窗口 | 工程默认 |
| `stop_atr_multiple` | `2.0` | float | ATR 止损倍数 | 工程默认 / 待验证 |
| `take_profit_r_multiple` | `2.5` | float | R 倍止盈倍数 | 工程默认 / 待验证 |
| `max_ema_deviation_atr` | `1.5` | float | 价格偏离 EMA21 上限 | 工程默认 / 待验证 |
| `volume_window` | `20` | int | 成交量均值窗口 | 工程默认 / 待验证 |
| `volume_multiplier` | `1.2` | float | 成交量确认倍数 | 工程默认 / 待验证 |
| `allow_long` | `true` | bool | 是否允许做多 | 回测任务指定 |
| `allow_short` | `true` | bool | 是否允许做空 | 回测任务指定 |
| `daily_direction.enabled` | `false` | bool | 是否启用日线方向过滤 | 工程默认 |
| `daily_direction.interval` | `1d` | enum | 日线方向周期 | 固定为 `1d` |
| `daily_direction.ema_period` | `21` | int | 日线 EMA 周期 | 工程默认 |
| `risk_per_trade_pct` | `<= 0.01` | float | 单笔账户风险上限 | 后续实现建议 |

参数版本要求：

- 任一参数默认值改变，必须形成新策略版本或新参数版本。
- 回测报告必须保存实际使用参数。
- 参数调优不得全样本优化后再全样本验收。

## 16. 信号确认时点

信号确认规则：

- 所有指标只在当前 K 线完成后计算。
- 当前 K 线收盘前，不允许确认入场、出场、止损、止盈或过滤信号。
- 当前 K 线收盘生成的信号，最早只能在下一根 K 线成交。
- 多周期过滤只能使用当前时点已经完成并可见的大周期 bar。

推荐字段：

- `signal_bar_time`
- `signal_confirmed_at`
- `signal_bar_close`
- `signal_status = pending_next_bar`
- `execution_timing = next_bar_open`

## 17. 成交假设

成交假设固定为：

```text
当前 K 线收盘确认，下一根 K 线成交
```

实现建议：

- 入场：当前 K 线收盘确认 pending entry，下一根 K 线开盘成交。
- 出场：当前 K 线收盘确认 pending exit，下一根 K 线开盘成交。
- stop / take profit 若由 vn.py 引擎以 bar 级方式撮合，必须在报告中明确撮合假设。
- 禁止当前 bar 信号当前 bar 开盘成交。
- 禁止使用当前 bar 尚未完成时的 high/low/close 生成信号。

推荐值：

```text
execution_timing = next_bar_open
fill_policy = signal_on_close_fill_next_bar_open
```

## 18. 手续费、滑点、合约乘数、保证金要求

每笔交易必须逐笔计入：

- `contract_multiplier`
- `price_tick`
- `commission`
- `slippage`
- `margin_ratio`
- `margin_required`
- `parameter_source`
- `fee_rule_source`

要求：

- 合约乘数、最小变动价位、手续费和保证金必须使用对应历史交易日可获得的数据。
- 允许从 `futures_trading_parameters` 或经审查的 `fee_margin_rules` fallback 获取。
- 不得使用未来交易参数修正历史成交。
- `net_pnl = gross_pnl - commission - slippage`。
- 报告级 `total_commission`、`total_slippage` 必须等于 trade 级汇总。
- 报告级 `max_margin_required` 必须能从 trade 或持仓过程追溯。

## 19. 回测限制

必须限制：

- 不允许未来函数。
- 不允许数据泄露。
- 不允许当前 K 线尚未收盘就确认信号。
- 不允许把主观案例直接硬编码为入场或出场触发。
- 不允许实盘下单。
- 不允许 tick 级高频回测或盘口队列撮合。
- 不允许用回测结束后才知道的主力映射、复权因子、交易参数或复盘标签。
- 不允许只看收益，不看回撤、连亏、手续费、滑点、保证金和单笔风险。

样本要求：

- 参数研究、验证和最终验收数据必须分离。
- 若用同一品种多周期对比，必须记录每次参数生效时间、数据范围和版本号。
- 回测报告必须能追溯到交易明细、K 线买卖点 marker 和复盘 note。

## 20. 暂不实现项

v0.1 暂不实现：

- MACD 背离。
- N 字结构 / 分型。
- 图片案例规则化。
- 交易开平仓口诀自动拆解。
- 抄底摸顶或极端位置交易。
- 支撑压力人工画线。
- 外盘联动。
- 品种熟悉度评分。
- 盘口、tick、高频队列撮合。
- 分批止盈。
- 移动止损。
- 自动反手。
- 自动实盘下单。
- AI 自动生成策略并直接运行。

这些内容可以进入人工复核、复盘标签或后续策略版本，但不得在 v0.1 中作为交易触发。

## 21. 后续实现文件建议

后续实现建议只在新的代码任务中处理，本轮规格不修改代码。

建议文件：

- `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/vnpy_strategy.py`
- `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/config_schema.py`
- `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/default_params.json`
- `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/review_tags.json`
- `services/quant-api/tests/test_su_bing_ema21_vnpy_draft.py`
- `services/quant-api/tests/test_vnpy_integration.py`
- `services/quant-api/tests/test_backtest_vnpy_schema.py`
- `services/quant-api/tests/test_signal_scanner_api.py`

后续实现必须写入或验证：

- `strategy_code = su_bing_ema21`
- `strategy_version = v0.1`
- `signal_reason`
- `entry_reason`
- `exit_reason`
- `stop_loss_price`
- `take_profit_price`
- `execution_timing = next_bar_open`
- `contract_multiplier`
- `price_tick`
- `commission`
- `slippage`
- `margin_ratio`
- `margin_required`
- `review_tag_candidates`

## 22. 复盘标签映射

v0.1 建议交易明细和复盘 note 可映射以下标签：

| 规则主题 | Review Tag |
|---|---|
| 趋势方向与周期职责 | TAG-001 |
| EMA21 位置、斜率、偏离 | TAG-002 / TAG-009 |
| MACD 辅助确认 | TAG-003 |
| 回调质量 | TAG-004 |
| 突破质量 | TAG-005 |
| 追高追空 | TAG-006 |
| 逆势交易 | TAG-007 |
| 震荡误入 | TAG-008 |
| 止损合理性 | TAG-010 |
| 止盈执行 | TAG-011 |
| 执行纪律 | TAG-012 |
| 资金管理 | TAG-013 |
| 规则外交易 | TAG-014 |

复盘标签只用于交易后解释和后续规则迭代，不得回写到当时信号生成中。

## 23. 安全审查清单

P0 必须满足：

- 不使用未来高低点、未来收盘价、center rolling 或未来主力映射。
- 当前 bar 收盘信号不允许当前 bar 开盘成交。
- 手续费、滑点、合约乘数、保证金逐笔计入。
- 回测报告保留最大回撤、最大连续亏损和单笔风险。
- 不存在自动实盘下单路径。

P1 建议满足：

- 日线方向过滤启用时，严格使用前一交易日或更早的已确认日线。
- 参数版本、策略版本、数据范围和生效时间入库。
- K 线 marker、交易明细和复盘 note 可追溯同一笔交易。

P2 后续优化：

- 为震荡识别、EMA21 斜率阈值、MACD 零轴过滤和成交量确认建立样本外验证。
- 将背离、N 字结构和分批止盈作为独立版本研究，不并入 v0.1。
