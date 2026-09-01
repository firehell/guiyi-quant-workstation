# Indicator Kernel

指标内核只提供确定性、可复算的通用计算，不拥有策略、仓位、下单、Alert 或 Runtime 授权。

- EMA 采用固定 seed 与递推公式；输入不足或非有限值时 fail-closed。
- `ema21_slope_10_bps_per_bar` 只接受恰好 10 个 EMA21 值，公式为 `(ema[-1] - ema[0]) / 9 / ema[-1] * 10000`，结果四舍五入到 6 位；当前 EMA21 为零或输入非法时返回 `None`。
- MACD 采用 12/26/9；ATR 与 Range Detector 使用各自 causal kernel。
- Range policy 仅允许 `range_detector_readonly_display`，formal backtest、generic strategy/live、Alert 与 notification 均 fail-closed。
- HTDY 为 observation-only/repainting 指标，支持 `1m/5m/15m/30m/60m/1d/1w`；时序边界由 Alert/Market 层执行。
- 不存在 Daily Watch 方向过滤、5m/15m 正式因子或策略专用 MACD/EMA 公式。

使用 `services/quant-api/tests/test_indicator_kernel.py`、`services/quant-api/tests/test_indicator_registry_v1.py`、HTDY contract tests 与 `TESTING.md` 的 backend 命令验证。指标测试通过不能推导自然事件、通知送达或 Runtime 状态。
