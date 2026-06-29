# STRATEGY_SPEC_REVIEW

## 1. 总体结论

- review_target: `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md`
- target_strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- target_strategy_version: `v0.2.0-daily`
- review_date: `2026-06-29`
- review_basis:
  - `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_TARGET.md`
  - `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md`
  - `.agents/skills/su-bing-strategy/SKILL.md`
  - `.agents/skills/su-bing-strategy/references/STRATEGY_GENERATION_PROTOCOL.md`
- 是否允许进入代码实现：Yes

结论：

- 该规格是一个独立 daily-only Strategy Spec，不是旧 `su_bing_jm_v1b_short_hold` 的修复版，也不是旧 `su_bing_ema21` 的续写版。
- 规格明确只使用 `1d` daily bar，没有把 `15m` / `5m` 写入新规则。
- 规格明确排除旧短持有、旧固定止损、旧固定止盈、`1.5R`、`time_exit_bar_8`、intraday stop loss 和同日直接反手。
- 做多、做空、MACD 0 轴附近、金叉、死叉、成交量确认、成交时点、离场和持仓规则均达到可实现级别。
- 未发现 P0 级未来函数、数据泄露或实盘越界问题。
- 允许进入代码实现，但实现任务仍必须另行授权修改范围，并严格按本 review 的实现边界执行。

审查清单：

| Check | Result | Note |
|---|---|---|
| 是否真的只使用日线 | Pass | `interval = 1d only`，`data_frequency = 1d`，指标、入场、离场均写为 daily bar。 |
| 是否仍误用 15m / 5m | Pass | `15m` / `5m` 只出现在明确排除列表。 |
| 是否仍保留旧止损、止盈、8 bar 时间退出 | Pass | 固定止损、固定止盈、`1.5R`、`time_exit_bar_8` 均明确排除。 |
| 做空规则是否清楚 | Pass | `close < EMA21` + MACD 0轴附近死叉 + `volume > previous_volume`。 |
| 做多对称规则是否清楚 | Pass | `close > EMA21` + MACD 0轴附近金叉 + `volume > previous_volume`。 |
| MACD 0轴附近金叉 / 死叉是否定义明确 | Pass | DIF/DEA、near-zero、golden/dead cross 都有公式。 |
| `jm_macd_zero_band = 25` 是否明确 | Pass | 参数表和 near-zero 公式均引用。 |
| `volume > previous_volume` 是否定义明确 | Pass | current/previous 都定义为已收盘 daily bar。 |
| 离场和持仓规则是否明确 | Pass | EMA21 收盘失效，下一根 daily open 平仓；否则继续持有。 |
| 是否存在未来函数 | Pass | 明确禁止使用未来 K线和下一根 high / low / close 生成当前信号。 |
| 是否存在数据泄露 | Pass | Review Tags、复盘 note、MFE/MAE、报告结论不得回写信号。 |
| 是否存在同日反手歧义 | Pass | 明确不允许同一根 daily signal bar 同时 exit 和 reverse entry。 |
| 是否明确不接实盘 | Pass | `live_trading_enabled = false`，`auto_order_enabled = false`，明确排除 CTP / TqSdk 交易接口。 |

## 2. P0 问题

无。

未发现以下 P0 问题：

- 未发现用未来 high / low / close 生成当前信号。
- 未发现当前 daily close 信号在当前 close 成交。
- 未发现 `15m` / `5m` 小周期被误写入信号链路。
- 未发现旧短持有规则、旧 `1.5R` 止盈、旧 `time_exit_bar_8` 被保留为有效规则。
- 未发现 Review Tags、人工复盘结论或报告结论参与同一时点 `on_bar` 信号。
- 未发现自动下单、实盘接口或未经风控的交易路径。

## 3. P1 问题

无必须先修改 Strategy Spec 才能进入代码实现的 P1。

实现期必须重点守住以下 P1 约束：

- 不得把“无固定止损”误实现为“无风险统计”。本策略的风险应通过 EMA21 失效退出后的实际亏损分布、最大回撤、最大连续亏损、隔夜跳空和保证金占用体现。
- 不得把下一根 daily open 的成交可用性扩展为读取下一根 high / low / close。下一根 daily open 只能用于成交价格，不能用于信号判断。
- 不得允许同一根信号日直接反手。若持仓中出现反向入场条件，只能先触发原持仓的 EMA21 离场逻辑；平仓成交完成后，下一根日线重新判断开仓。
- 不得在缺少 `price_tick`、手续费、合约乘数、保证金或合约映射时继续正式回测。

## 4. P2 问题

- MACD warm-up 数量没有写成固定整数。规格已经要求“足够日线 bar”且 warm-up 不生成信号；实现时建议固定为可测试的最小历史长度，并在测试里覆盖 warm-up 边界。
- `jm_macd_zero_band = 25` 已明确，但其单位隐含为 DIF / DEA 的价格差值单位。实现和报告中建议记录该阈值单位，避免后续和归一化 MACD 或不同价格尺度混用。
- 本版本没有固定止盈和固定止损，策略可能出现长持仓和较大隔夜风险。该设计符合当前 Spec，但报告应额外展示持仓天数分布、最大单笔亏损、最大不利浮动和跳空影响。
- 当前规格允许多空双向，但未定义交易所涨跌停或停牌/无下一根 open 的异常处理。后续实现可在 backtest adapter 层作为撮合异常处理，不需要修改本 Spec。

## 5. 必须修复项

无必须修复项。

进入代码实现前，开发任务必须把以下内容作为验收检查，而不是回头修改本 Spec：

- 只读 daily bar，不生成或读取任何 `15m` / `5m` 信号。
- 只在 daily close 后生成信号，下一根 daily open 成交。
- MACD near-zero、golden cross、dead cross 和 volume expansion 必须逐项可测试。
- 旧短持有规则、旧 `su_bing_ema21` 规则、Review Tags、复盘 note 不得进入信号函数。
- 成本、滑点、合约乘数、保证金、最大回撤、最大连续亏损必须进入结果和报告。

## 6. 实现边界

本 review 只允许后续另开“代码实现任务”时参考，不直接授权当前任务修改代码。

当前任务禁止修改：

- `STRATEGY_TARGET.md`
- `STRATEGY_SPEC.md`
- `packages/quant-core/`
- `services/quant-api/`
- `apps/quant-web/`
- database migrations
- vn.py source code
- CTP / TqSdk trading interfaces
- `.env`
- 账号、密码、API keys、tokens、licenses

后续代码实现若获用户授权，建议只允许最小范围：

- 新增独立策略实现目录或模块，策略代码必须使用 `strategy_code = su_bing_jm_daily_ema21_macd_volume`。
- 新增该策略对应参数 schema / 默认参数文件。
- 新增该策略的单元测试，覆盖日线-only、MACD 交叉、volume 确认、下一日 open 成交、EMA21 失效退出、禁止同日反手、成本和缺字段 fail fast。

实现仍不得：

- 修改 vn.py 源码。
- 接入实盘交易。
- 自动下单。
- 修改 Web、API 或数据库，除非用户在后续任务中单独授权。
- 把旧 `su_bing_jm_v1b_short_hold` 或旧 `su_bing_ema21` 作为父类、规则来源或参数来源。

## 7. 建议下一步

1. 进入独立代码实现任务，先实现最小 daily-only 策略核心和参数校验，不改 Web / API / DB。
2. 先写测试，再写实现，重点覆盖：
   - daily-only 数据约束。
   - `close > EMA21` 多头入场与 `close < EMA21` 空头入场。
   - MACD near-zero + 金叉 / 死叉。
   - `current_volume > previous_volume`。
   - signal daily close 与 fill next daily open 分离。
   - EMA21 失效退出。
   - 禁止同日直接反手。
   - Review Tags 不进入信号。
   - 缺成本、合约乘数、保证金或 `price_tick` fail fast。
3. 第一轮回测报告必须标记为 research / backtest only，不得进入实盘或自动下单链路。
4. 回测后再做一次安全审查，重点看最大回撤、最大连续亏损、跳空亏损、长持仓风险和结果是否被少数极端交易主导。
