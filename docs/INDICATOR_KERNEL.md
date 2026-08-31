# Indicator Kernel

## 定位

`packages/quant-core/guiyi_quant/indicators/` 只保留可复算、无副作用的 EMA/MACD/ATR/Range/HTDY 指标核。指标核不读数据库、Redis、文件或网络，不写状态，不发送通知，也不形成订单。

## 使用边界

- EMA、MACD、ATR 的输入是已确认、按时间单调的 Bar 序列；warm-up 或身份不完整时由调用方明确 unavailable/fail-closed。
- `range_detector_lux_v1` 使用固定 `range20 × ATR500 × 1.0`、Wilder SMA seed 与 completed Bar；其 batch/incremental 计算因果且 append-only。`visual_start_at` 仅为 Web 回画起点，`confirmed_at` 才是策略首次可见时点；Historical `RangeDetectorVisualRange` 单独派生 active-level 结束时间。
- Range policy 只允许 `range_detector_readonly_display` 和 `subing_daily_trend_research`；formal backtest、generic strategy/live、Alert 与 notification 均 fail-closed。它不改变现有 SuBing 或 HTDY 公式、Rule、Runtime 或通知能力。
- SuBing 的 Factor、Signal、Calibration、FormalPolicy 与 Lifecycle 由现有权威服务组合，Web 只投影结果，不复制公式。
- HTDY 为 observation-only/repainting 指标，支持 `1m/5m/15m/30m/60m/1d/1w` 七个正式周期；日内 completed Live 与 D1/W1 Canonical seam 的时序边界由 Alert/Market 层执行。
- original 与 strict 不互换：original 仅 `observation_only`，strict 仅 `strategy_candidate`；formal consumer 必须经 `require_formal_policy` 明确命名，缺失、错误频率、非 actual-dominant confirmed current-last-bar 或 generic consumer 一律 fail-closed。
- SuBing scoped MACD 只由现有 SuBing Factor/Signal 服务在限定品种/周期上下文读取，不能作为通用 MACD signal 或 Alert 替代公式。
- original 的 future dependency 为 24 bars；Web 必须把最后 27 bars 标为 repaint/unstable zone。original XMA 的未解析语义保持 unavailable/fail-closed，不以 strict 或浏览器近似替代。
- 指标、Historical replay 和 reference fill 不构成策略晋升、回测结论、Alert retry 或订单能力。

## 验证

使用 `services/quant-api/tests/test_indicator_registry_v1.py`、对应 SuBing/HTDY contract tests 与 `TESTING.md` 的 backend 命令验证；不得从计算通过推导自然事件、通知送达或 Runtime 状态。
