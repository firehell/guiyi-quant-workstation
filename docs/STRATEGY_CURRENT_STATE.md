# STRATEGY_CURRENT_STATE.md

生成时间：2026-07-07

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
| `su_bing_jm_v1b_short_hold` | `v0.1.1-spec` | spec | 日线方向 + 15m/5m 短持有 |
| `su_bing_jm_daily_ema21_macd_volume` | `v0.2.0-daily` | 冻结基线 | 日线 EMA21 / MACD / 量能 |
| `su_bing_jm_daily_score2of4` | `v0.3.0-daily-score2of4` | 研究版本 | trusted 结果为负 |
| `su_bing_jm_daily_trend_cross_score2` | `v0.3.1` | 研究版本 | 趋势交叉评分实验 |

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

- Stage 3A 先确认 active 数据过滤。
- Stage 3B 确认 Web Data 页面能展示 JM v2 覆盖和质量状态。
- 后续可信回测主线复核必须显式记录 strategy_code、strategy_version、参数、数据版本、回测区间、手续费、滑点、合约乘数和报告指标。

## 6. 禁止事项

- 不静默修改旧策略版本。
- 不把实验结果包装成实盘建议。
- 不把实时观察表现当作可信回测结论。
- 不接 CTP / TqSdk 交易接口。
- 不自动下单。
