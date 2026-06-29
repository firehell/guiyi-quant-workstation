# Su Bing JM Daily EMA21 MACD Volume Strategy Target

> 本文只定义策略目标边界，不是完整 Strategy Spec，不是可执行策略，不授权写策略代码、回测代码、Web、数据库迁移或实盘接口。

## 1. 目标身份

- strategy_code: `su_bing_jm_daily_ema21_macd_volume`
- strategy_version: `v0.2.0-daily`
- strategy_stage: `strategy_target`
- project_stage: `V1-B`
- product: `JM`
- product_name: 焦煤
- interval: `1d only`
- data_role: `primary`
- quality_status: `passed`
- generated_on: `2026-06-29`

本目标用于新增一个独立的苏冰规则候选日线策略：在 JM 焦煤最近 3 年真实数据上，研究 EMA21 趋势位置、MACD 0 轴附近金叉/死叉、成交量放大确认是否能形成可回测、可复盘的日线交易规则。

## 2. 来源与边界

本目标基于以下材料和当前用户规则生成：

- `.agents/skills/su-bing-strategy/SKILL.md`
- `.agents/skills/su-bing-strategy/references/STRATEGY_GENERATION_PROTOCOL.md`
- `.agents/skills/su-bing-strategy/references/SU_BING_RULEBOOK.md`
- `.agents/skills/su-bing-strategy/references/SU_BING_REVIEW_TAGS.md`
- 用户本轮明确给定的 daily-only 策略规则、参数、成交假设和禁止事项。

来源分离：

- 课程候选：EMA21、MACD、成交量、持仓依据、退出管理、资金管理和复盘标签只作为规则候选或复盘候选。
- 本轮新增决策：JM、日线周期、MACD 0 轴附近阈值、金叉/死叉定义、成交量确认、下一日开盘成交、EMA21 收盘失效退出。
- 历史参考：旧 `su_bing_jm_v1b_short_hold` 只作为历史失败基线和工程接口参考，不作为规则来源。
- 历史参考：旧 `su_bing_ema21` 只作为 `history_draft` / `legacy_reference`，不作为规则来源、参数默认来源、周期默认来源或成交假设来源。
- 复盘标签：`TAG-*` 只能用于交易后诊断、K线复盘和复盘 note，不得影响同一时点 `on_bar` 信号。

本文不复制课程原文、长段摘录、截图、图片案例内容或私有 Notion 内容。

## 3. 当前策略目标

- 研究用途：研究、回测、报告归档和单笔复盘。
- 实盘边界：不做实盘，不自动下单，不接 CTP / TqSdk 交易接口。
- 数据来源：RQData / local standard parquet。
- 数据过滤：正式回测只允许 `data_role = primary` 且 `quality_status = passed` 的 JM 日线数据。
- 数据窗口：`2023-06-28` 至 `2026-06-28`；实际回测窗口可按本地数据湖可用且质量通过的交易日裁剪，并必须写入报告。
- 周期职责：只使用 `1d`，不使用任何小周期择时或盘中退出。
- 交易方向：允许做多和做空。
- 持仓方式：规则化持有，直到日线收盘跌破或突破 EMA21 后，下一根日线 open 平仓。

核心规则目标：

- 做多：日线 close > EMA21，MACD 在 0 轴附近金叉，且 volume > previous_volume。
- 做空：日线 close < EMA21，MACD 在 0 轴附近死叉，且 volume > previous_volume。
- 成交：信号日 daily bar close 确认，下一根 daily bar open 成交，并按 `price_tick` 和 `slippage_ticks = 1` 做不利方向处理。

## 4. 固定参数

| Field | Value |
|---|---|
| ema_period | `21` |
| macd_fast | `12` |
| macd_slow | `26` |
| macd_signal | `9` |
| jm_macd_zero_band | `25` |
| volume_confirm_enabled | `true` |
| volume_rule | `current_volume > previous_volume` |
| maximum_position | `1` |
| allow_long | `true` |
| allow_short | `true` |
| slippage_ticks | `1` |

以上参数为 `v0.2.0-daily` 冻结参数。任何参数变更都必须新建策略版本或参数版本，不允许通过旧策略、旧代码或全样本寻优静默覆盖。

## 5. 明确不使用

本策略明确不使用以下旧规则、旧周期或旧退出方式：

- `15m`
- `5m`
- 短持有 `5-8 bar`
- `1.5R` 止盈
- intraday stop loss
- `time_exit_bar_8`
- 旧 `su_bing_jm_v1b_short_hold` 的入场规则
- 旧 `su_bing_ema21` 的规则
- 回调入场、突破入场或旧短持有 pullback 规则
- 固定止损、固定止盈、盘中止损、盘中止盈
- 同一根信号日直接反手

## 6. 后续流程

1. 基于本文生成独立 `STRATEGY_SPEC.md`。
2. 审查未来函数、数据泄露、过拟合、成交假设、手续费、滑点、合约乘数、保证金、最大回撤、连续亏损和复盘标签边界。
3. 只有在独立规格通过审查后，才能另开代码实现任务。
4. 后续实现仍需用户明确允许修改代码范围；本文不授权修改 `packages/quant-core/`、`services/quant-api/`、`apps/quant-web/`、数据库 migration 或实盘接口。
