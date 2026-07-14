# Indicator And Strategy Kernel

更新时间：2026-07-14

事实来源：`packages/quant-core/README.md`、`docs/INDICATOR_KERNEL.md`、代码检索。

当前状态：current，策略结论仍需外部 Gate。

## 指标状态

- EMA：`guiyi_quant.indicators.ema.ema_series`，当前 validated，用于 Web EMA 口径对齐。
- MACD：`v1-draft`，用于口径对照，不应直接宣称全链路迁移完成。
- ATR：`v1-draft`，用于口径对照，不应直接宣称全链路迁移完成。
- 火天大有：`observation_only`，Web 层展示观察，不得进入回测、live evaluator、`signal_events` 或企业微信提醒链路。
- XMA 风险：存在重绘风险，不进入正式信号和回测。

## 策略状态

仓库中存在苏冰 EMA21、JM V1-B、短持有等 vn.py strategy drafts / candidates。当前 `report_id=14` 是可信回归基线，但不是盈利或实盘准入结论。

## 迁移边界

指标或策略输出若改变信号时点、交易记录或报告指标，必须升策略版本并重跑回归，不能静默覆盖旧策略版本。

