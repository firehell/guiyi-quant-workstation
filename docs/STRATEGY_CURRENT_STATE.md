# STRATEGY_CURRENT_STATE.md

生成时间：2026-07-08

## 1. 策略边界

当前策略工作服务 V1 研究闭环：

```text
数据 -> 策略 -> 回测 -> 报告 -> 复盘 -> 信号提醒 -> 人工观察
```

策略信号只提醒，不自动下单。

## 2. 当前策略清单

| strategy_code | version | 状态 | 说明 |
|---|---|---|---|
| `jm_v1b_daily_direction_fast_entry` | `v1b.0` | 历史主线 | JM 15m / 5m 固定任务 |
| `su_bing_ema21_vnpy` | `v0.1.0` | 研究基线 | EMA21 趋势跟踪，ATR 止损/止盈 |
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | spec | 日线方向 + 15m/5m 短持有 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 冻结基线 | 日线 EMA21 / MACD / 量能 |
| `su_bing_jm_daily_score2of4` | `v0.3.0-daily-score2of4` | 研究版本 | trusted 结果为负 |
| `su_bing_jm_daily_trend_cross_score2` | `v0.3.1` | 研究版本 | 趋势交叉评分实验 |
| `tdx_xma_bands` | `poc-risk-review` | observation-only | 通达信 XMA PoC，存在未来函数 / 重绘风险，不进入正式信号 |

## 3. 当前数据前提

后续策略回测应优先使用 JM v2 数据：

```text
source = rqdata / local_parquet
data_role = primary
quality_status = passed
data_version = *_20230103_20260707_v2
```

旧结果可以作为历史参考，不作为当前策略结论。

## 4. 保留文档事实源

每个当前策略目录只保留核心事实源：

- `STRATEGY_TARGET.md`
- `STRATEGY_SPEC.md`
- `STRATEGY_SPEC_REVIEW.md`
- `BACKTEST_REVIEW_CONTEXT.md`

苏冰知识最小源：

- `docs/strategy_knowledge/su_bing/SOURCE_INDEX.md`
- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
- `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`
- `docs/strategy_knowledge/su_bing/SU_BING_SKILL.md`

## 5. 后续策略任务

- Stage 7 已完成通达信 XMA PoC 风险审查；原始 XMA / XMA 派生信号不得进入可信回测、正式 signal、live evaluator 或企业微信提醒。
- Stage 8 已完成 `signal_events` 信号事件化，支持 contract context 显式字段。
- Stage 8.5 已完成 schema 扩展：`strategy_signals` / `signal_events` 新增 product、continuous_contract、actual_contract、dominant_mapping_date、bar_start、bar_end、trigger_price、provider、source、data_role、quality_status 字段。
- Stage 9 Gate 准入要求：事件必须为 `signal_created` / `signal_changed`、`signal_status=entry_signal`、具备真实 `actual_contract`、正数 `trigger_price`、`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status.status=passed`；缺真实合约或 `.MAIN` 伪装合约的事件会被阻断。
- 后续可信回测主线复核必须显式记录 strategy_code、strategy_version、参数、数据版本、回测区间、手续费、滑点、合约乘数和报告指标。

## 6. 禁止事项

- 不静默修改旧策略版本。
- 不把实验结果包装成实盘建议。
- 不把实时观察表现当作可信回测结论。
- 不接 CTP / TqSdk 交易接口。
- 不自动下单。
