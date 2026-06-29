# Su Bing JM Daily EMA21 MACD Volume Strategy Spec

> 本文是基于 `su-bing-strategy` Skill、`STRATEGY_GENERATION_PROTOCOL.md` 和 `STRATEGY_TARGET.md` 生成的独立 Strategy Spec。
> 本文不是旧 `su_bing_jm_v1b_short_hold` 的修复版，不是旧 `su_bing_ema21` 的续写版，也不授权写策略代码或直接下单。

## 1. Strategy Identity

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.2.0-daily`
- target_code: `su_bing_jm_daily_ema21_macd_volume`
- project_stage: `V1-B`
- strategy_stage: `strategy_spec`
- status: `draft_for_review`
- generated_on: `2026-06-29`
- product: `JM`
- product_name: 焦煤
- interval: `1d only`
- trade_direction: `long_short`
- live_trading_enabled: `false`
- auto_order_enabled: `false`

Research goal:

- 在 JM 焦煤最近 3 年 primary / passed 日线数据上，验证 EMA21 趋势位置、MACD 0 轴附近金叉/死叉、成交量放大确认组成的 daily-only 策略是否具备可回测、可复盘的行为特征。

Version reason:

- 新增独立 daily-only 规格，替代继续修补旧短持有策略的路径。
- 固化用户本轮给定参数和成交假设，不从旧 `su_bing_jm_v1b_short_hold` 或旧 `su_bing_ema21` 继承规则。

## 2. Source Separation

Skill sources:

- skill: `.agents/skills/su-bing-strategy/SKILL.md`
- generation_protocol: `.agents/skills/su-bing-strategy/references/STRATEGY_GENERATION_PROTOCOL.md`
- rulebook: `.agents/skills/su-bing-strategy/references/SU_BING_RULEBOOK.md`
- review_tags: `.agents/skills/su-bing-strategy/references/SU_BING_REVIEW_TAGS.md`
- strategy_target: `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_TARGET.md`

Rule source categories:

- Course-derived rule candidates: `RULE-002` 交易系统、`RULE-004` EMA21、`RULE-005` MACD、`RULE-008` 开仓过滤、`RULE-009` 平仓规则、`RULE-012` 资金管理、`RULE-014` 量能观察点。
- Current-spec decisions: JM、`1d only`、EMA21 21、MACD 12/26/9、0 轴附近阈值 25、成交量大于上一根日线、下一根日线 open 成交、EMA21 收盘失效退出。
- Manual-review-only content: `RULE-015` through `RULE-018` 不进入信号，只进入复盘说明或拒绝信号解释。
- Post-trade review tags: `TAG-001` through `TAG-014` 只用于交易后诊断和复盘 note。
- Historical baseline: 旧 `su_bing_jm_v1b_short_hold` 只作为历史失败基线和工程接口参考，不作为规则来源。
- Legacy reference: 旧 `su_bing_ema21` 只作为历史参考，不作为规则来源、参数默认来源、周期默认来源或成交假设来源。

Forbidden inheritance:

- 不从旧短持有策略继承小周期、回调、距离、止损、止盈、持有 bar 数或 time exit。
- 不从旧 `su_bing_ema21` 继承入场、出场、过滤、参数或实现路径。
- 不从旧策略代码、旧测试或旧报告反推课程规则。

## 3. Data Scope

- data_source: `RQData / local standard parquet`
- data_role: `primary`
- quality_status: `passed`
- data_frequency: `1d`
- date_range:
  - spec_window_start: `2023-06-28`
  - spec_window_end: `2026-06-28`
  - final_backtest_window: 按本地数据湖中可用且质量通过的 JM 交易日裁剪，并写入报告。

Required bar fields:

- datetime
- trading_day
- symbol
- open
- high
- low
- close
- volume
- open_interest
- price_tick
- contract_multiplier
- commission_rule
- margin_rate
- data_role
- quality_status

Excluded data:

- `data_role != primary`
- `quality_status != passed`
- 天勤旧数据，除非后续单独标记为 validation source 做交叉校验。
- 交易练习者数据，只能作为 legacy_reference 页面测试或对照。
- 缺少手续费、滑点、合约乘数、保证金或 `price_tick` 的正式回测输入。

Contract handling:

- 回测不得直接交易抽象连续合约。
- 如使用主力连续映射，只能用于确定每个交易时点对应的可交易具体合约。
- 主力切换、换月、复权和合约参数必须时间戳可追溯。

## 4. Parameters

Frozen `v0.2.0-daily` parameters:

| Field | Value | Source type |
|---|---|---|
| ema_period | `21` | current_spec_decision |
| macd_fast | `12` | current_spec_decision |
| macd_slow | `26` | current_spec_decision |
| macd_signal | `9` | current_spec_decision |
| jm_macd_zero_band | `25` | current_spec_decision |
| volume_confirm_enabled | `true` | current_spec_decision |
| volume_rule | `current_volume > previous_volume` | current_spec_decision |
| maximum_position | `1` | current_spec_decision |
| allow_long | `true` | current_spec_decision |
| allow_short | `true` | current_spec_decision |
| slippage_ticks | `1` | current_spec_decision |

Parameter rules:

- 参数在 `v0.2.0-daily` 内冻结。
- 任何参数变更必须创建新的 strategy_version 或 parameter_version。
- 不允许先全样本优化后把最优参数静默写回本版本。
- 不允许缺少交易成本时以 0 手续费或 0 滑点继续正式回测。

## 5. Indicator Definitions

All indicators use completed daily bars only.

EMA21:

- `EMA21 = EMA(close, ema_period = 21)`
- 当前信号日记为 daily bar `t`。
- `current_close`、`current_volume`、`current_DIF`、`current_DEA` 均来自已收盘的 bar `t`。
- `previous_volume`、`previous_DIF`、`previous_DEA` 均来自已收盘的 bar `t-1`。

MACD:

- `DIF = EMA(close, macd_fast) - EMA(close, macd_slow)`
- `DEA = EMA(DIF, macd_signal)`
- `MACD histogram` 可记录为复盘字段，但本版本不使用柱体阈值生成信号。

MACD 0 轴附近:

```text
abs(DIF) <= jm_macd_zero_band
and abs(DEA) <= jm_macd_zero_band
```

MACD 死叉:

```text
previous_DIF >= previous_DEA
and current_DIF < current_DEA
```

MACD 金叉:

```text
previous_DIF <= previous_DEA
and current_DIF > current_DEA
```

Volume confirmation:

```text
current_volume > previous_volume
```

Warm-up:

- 至少需要足够日线 bar 计算 EMA21、MACD 12/26/9、上一根 MACD 和上一根成交量。
- warm-up 区间不得生成正式入场信号。

## 6. Entry Rules

Signal timing:

- 信号只能在 daily bar `t` 收盘后确认。
- bar `t` 的信号只能使用 bar `t` 及更早已完成日线数据。
- 不允许使用 bar `t+1` 的 high / low / close 生成 bar `t` 信号。

Short entry:

日线收盘后同时满足：

1. `close < EMA21`
2. MACD 在 0 轴附近
3. MACD 死叉
4. `volume > previous_volume`
5. `allow_short = true`
6. 当前无持仓，且不存在未执行的平仓指令

Short entry reason:

```text
daily_close_below_ema21
+ macd_near_zero_dead_cross
+ volume_expansion
```

Long entry:

日线收盘后同时满足：

1. `close > EMA21`
2. MACD 在 0 轴附近
3. MACD 金叉
4. `volume > previous_volume`
5. `allow_long = true`
6. 当前无持仓，且不存在未执行的平仓指令

Long entry reason:

```text
daily_close_above_ema21
+ macd_near_zero_golden_cross
+ volume_expansion
```

Rejected entry:

- 数据不是 `primary / passed`。
- warm-up 不足。
- 缺少 `previous_volume`、`previous_DIF` 或 `previous_DEA`。
- 缺少 `price_tick`、手续费、合约乘数或保证金字段。
- 当前已有持仓。
- 当前有待执行的平仓指令。
- 当前信号需要未来 K 线或下一根 K 线 high / low / close。
- 信号来自 Review Tags、复盘 note、人工结论、旧策略代码或旧规格默认值。

## 7. Execution Assumptions

Backtest engine target:

- engine: `vn.py / VeighNa CTA BacktestingEngine`
- adapter_boundary: 归一量化自定义 Adapter / Runner / ResultConverter；本文不授权实现。

Entry execution:

- 信号日 daily bar close 确认。
- 下一根 daily bar open 成交。
- 做多：`entry_price = next_open + slippage`
- 做空：`entry_price = next_open - slippage`
- `slippage = slippage_ticks * price_tick`
- 所有成交价按 `price_tick` 做不利方向取整。

Unfavorable rounding:

- 多头开仓价向上取整到合法 tick。
- 空头开仓价向下取整到合法 tick。
- 多头平仓价向下取整到合法 tick。
- 空头平仓价向上取整到合法 tick。

Forbidden:

- 不允许当前收盘信号在当前收盘价成交。
- 不允许使用下一根 daily bar 的 high / low / close 生成当前信号。
- 不允许用成交后的走势修正原始入场。

## 8. Exit Rules

This version does not use fixed stop loss, fixed take profit, short holding-period exit, or intraday exit.

Short exit:

1. 持有空单期间，只要 daily close > EMA21。
2. 下一根 daily open 平空。
3. 如果 daily close <= EMA21，则继续持有。

Short exit reason:

```text
short_close_above_ema21_exit_next_daily_open
```

Long exit:

1. 持有多单期间，只要 daily close < EMA21。
2. 下一根 daily open 平多。
3. 如果 daily close >= EMA21，则继续持有。

Long exit reason:

```text
long_close_below_ema21_exit_next_daily_open
```

Exit execution:

- 出场信号在 daily bar `t` 收盘后确认。
- 下一根 daily bar `t+1` open 平仓。
- 多单平仓：`exit_price = next_open - slippage`
- 空单平仓：`exit_price = next_open + slippage`
- 成交价同样按 `price_tick` 做不利方向取整。

No fixed stop / take profit:

- 本版本没有固定止损价。
- 本版本没有固定止盈价。
- 本版本没有 `R` 倍数止盈。
- 本版本没有盘中 high / low 触发退出。
- 不利行情处理仅通过日线收盘重新站上或跌破 EMA21 后，下一根日线 open 退出。

## 9. Reverse Rules

- 第一版不允许同一根信号日直接反手。
- 若持有多单期间出现做空入场条件，先按多单离场规则处理。
- 若持有空单期间出现做多入场条件，先按空单离场规则处理。
- 平仓成交完成后，下一根日线重新判断是否开新仓。
- 不允许在同一根 daily signal bar 内同时记录 exit 和 reverse entry。

## 10. Risk And Cost Requirements

Required cost and risk fields:

- price_tick
- contract_multiplier
- commission_rule
- commission
- slippage
- margin_rate
- margin_required
- maximum_position
- gross_pnl
- net_pnl
- max_drawdown
- max_consecutive_losses
- trade_count
- win_rate
- profit_factor
- average_trade
- strategy_version

Position rules:

- `maximum_position = 1`
- 不加仓。
- 不补仓。
- 不亏损加仓。
- 不 pyramiding。
- 不允许仓位脱离保证金和资金约束。

Cost rules:

- 手续费必须逐笔计入。
- 滑点必须逐笔计入。
- 合约乘数必须用于盈亏计算。
- 保证金占用必须统计。
- 缺少手续费、滑点、合约乘数、保证金或 `price_tick` 时，正式回测必须 fail fast。

Risk review:

- 单笔风险需在报告中体现为从入场到 EMA21 失效退出的实际亏损分布，而不是固定初始止损。
- 最大回撤必须统计。
- 最大连续亏损必须统计。
- 回测结果不等于实盘结果。
- 实盘前必须另行经过模拟和小资金人工确认流程；V1 不进入该阶段。

## 11. Review Tags And Trade Notes

Review tags are post-trade only.

Fixed tag semantics:

- `is_post_trade_only = true`
- `can_affect_same_trade_signal = false`
- `can_affect_future_version = review_required`

Suggested mapping:

- `TAG-001` 趋势判断：复盘价格与日线 EMA21 的趋势关系。
- `TAG-002` EMA21 位置：复盘入场、持仓、出场时 close 与 EMA21 的关系。
- `TAG-003` MACD 共振：复盘 MACD 0 轴附近交叉质量。
- `TAG-005` 突破质量：仅用于后验观察，不进入本版本入场触发。
- `TAG-008` 是否震荡误入：复盘 MACD 近 0 轴信号是否处于震荡噪声。
- `TAG-010` 是否止损合理：记录本版本无固定止损下的最大不利波动和实际退出。
- `TAG-011` 是否止盈过早：记录 EMA21 持仓退出是否过早或过晚，仅用于复盘。
- `TAG-013` 是否符合资金管理：复盘保证金、手续费、滑点和最大回撤。
- `TAG-014` 是否规则外交易：检查交易是否可追溯到 `v0.2.0-daily`。

Forbidden:

- Review Tags 不得反向影响当时交易决策。
- `TAG-*` 不得进入同一时点 `on_bar` 的入场、出场、过滤、加仓、减仓或反手。
- 复盘 note、人工结论、MFE、MAE、最终 PnL、报告结论不得回写为同一笔交易的信号条件。

## 12. Explicitly Excluded From This Version

The following are excluded by design:

- `15m`
- `5m`
- 短持有 `5-8 bar`
- `1.5R` take profit
- intraday stop loss
- `time_exit_bar_8`
- 旧 `su_bing_jm_v1b_short_hold` 入场规则
- 旧 `su_bing_ema21` 规则
- 回调入场规则
- 旧 pullback / distance guard / signal-bar extreme stop
- 固定止损
- 固定止盈
- 盘中 high / low 触发止损或止盈
- 同一根信号日直接反手
- 全自动实盘
- AI 自动下单
- CTP / TqSdk 交易接口
- Web 策略代码编辑器
- 数据库 migration
- API / Web / strategy code implementation

## 13. Future Function Guardrails

Hard rules:

- 只允许使用当前及过去已完成 daily bar。
- 当前 daily close 确认信号。
- 下一根 daily open 成交。
- 不允许使用未来 K 线。
- 不允许使用下一根 daily bar 的 high / low / close 生成当前信号。
- MACD、EMA21、volume 均必须以 left-closed historical sequence 计算。
- 合约映射、交易参数和数据质量状态必须按交易时点读取。

Required checks before implementation:

- Assert signal bar index < fill bar index。
- Assert signal generation does not read `t+1.high`、`t+1.low`、`t+1.close`。
- Assert entry and exit fills use next daily open only after signal is confirmed。
- Assert all warm-up bars cannot create entry signals。

## 14. Data Leakage Guardrails

Hard rules:

- `data_role = primary` and `quality_status = passed` are mandatory filters.
- Review Tags、manual review、trade notes、report conclusions must not feed back into signal logic.
- Full-sample statistics must not decide entry thresholds for the same sample.
- Trade result, MFE, MAE, final PnL, drawdown, or future EMA state must not decide original entry or exit.
- Contract rollover mapping must be timestamp-aware.

Required checks before implementation:

- Verify features are computed using only current and previous daily bars.
- Verify tags are written after trade close or in review workflows.
- Verify excluded sources cannot enter formal backtests.

## 15. Overfitting Guardrails

- No all-sample parameter optimization may be used as final acceptance.
- `v0.2.0-daily` parameters must stay frozen for this spec.
- Any parameter change must create a new strategy version or parameter version.
- Reports must include net PnL, drawdown, win rate, profit factor, average trade, max consecutive losses, trade count, fee, slippage, and symbol contribution.
- Validation should use chronological split and holdout review before any implementation is considered stable.
- Results dominated by one or two extreme trades must be marked `risk_review_required` rather than accepted as robust.

## 16. Output Fields

Each generated trade should be traceable to:

- strategy_code
- strategy_version
- product
- symbol
- contract
- interval
- direction
- signal_datetime
- fill_datetime
- entry_price
- exit_price
- entry_reason
- exit_reason
- ema21
- current_DIF
- current_DEA
- previous_DIF
- previous_DEA
- current_volume
- previous_volume
- price_tick
- contract_multiplier
- commission
- slippage
- margin_required
- gross_pnl
- net_pnl
- review_note_id
- review_tags

K-line markers:

- Entry marker at actual fill datetime and entry price.
- Exit marker at actual fill datetime and exit price.
- Signal metadata should retain signal daily bar datetime separately from fill datetime.

## 17. Test Plan

Document checks:

- Confirm `STRATEGY_TARGET.md` and `STRATEGY_SPEC.md` exist under `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`。
- Confirm strategy_code, strategy_version, product, interval, data_role, quality_status, parameters, and exclusions are present.
- Confirm old short-hold and old EMA21 are marked historical only, not rule sources.

Signal checks for future implementation:

- Verify short entry requires close below EMA21, MACD near zero, dead cross, and volume expansion.
- Verify long entry requires close above EMA21, MACD near zero, golden cross, and volume expansion.
- Verify no entry signal uses next daily high / low / close.
- Verify fills occur at next daily open with adverse slippage and tick rounding.

Risk checks:

- Verify commission, slippage, contract multiplier, margin, and price_tick are mandatory.
- Verify missing cost or contract metadata fails fast.
- Verify maximum position never exceeds 1.
- Verify reports include max drawdown and max consecutive losses.

Review checks:

- Verify Review Tags are post-trade only.
- Verify review notes cannot change original signals.
- Verify each trade can be linked to K-line markers and strategy version.

## 18. Implementation Boundary

This spec does not authorize code changes.

Files not authorized by this spec-generation task:

- `packages/quant-core/`
- `services/quant-api/`
- `apps/quant-web/`
- database migrations
- vn.py source code
- CTP / TqSdk trading interfaces
- `.env`
- accounts, passwords, API keys, tokens, licenses

Allowed files for this task were only:

- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_TARGET.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/STRATEGY_SPEC.md`
