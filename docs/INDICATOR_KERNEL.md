# Indicator Kernel

指标内核只提供确定性、可复算的通用计算，不拥有策略、仓位、下单、Alert 或 Runtime 授权。

- EMA 采用固定 seed 与递推公式；输入不足或非有限值时 fail-closed。
- `ema21_slope_10_bps_per_bar` 只接受恰好 10 个 EMA21 值，公式为 `(ema[-1] - ema[0]) / 9 / ema[-1] * 10000`，结果四舍五入到 6 位；当前 EMA21 为零或输入非法时返回 `None`。
- MACD 采用 12/26/9；ATR 与 Range Detector 使用各自 causal kernel。
- Range policy 仅允许 `range_detector_readonly_display`，formal backtest、generic strategy/live、Alert 与 notification 均 fail-closed。
- HTDY 为 observation-only/repainting 指标，支持 `1m/5m/15m/30m/60m/1d/1w`；时序边界由 Alert/Market 层执行。
- 不存在 Daily Watch 方向过滤、5m/15m 正式因子或策略专用 MACD/EMA 公式。

使用 `services/quant-api/tests/test_indicator_kernel.py`、`services/quant-api/tests/test_indicator_registry_v1.py`、HTDY contract tests 与 `TESTING.md` 的 backend 命令验证。指标测试通过不能推导自然事件、通知送达或 Runtime 状态。

## MACD 人工观察副图（2026-10-25）

`ths_macd_ma21_display_v1` 按 owner 同花顺公式显示 DIFF=EMA(C,12)-EMA(C,26)、
DEA=EMA(DIFF,9)、MACD=2*(DIFF-DEA)，青色 DIFF、黄色 DEA、灰色零轴。
金叉为前一 DIFF<=DEA 且当前 DIFF>DEA 且 C>MA(C,21)；死叉方向相反且 C<MA(C,21)。
MA21 需要完整21根；偏移=max(最近最多60根 abs(DIFF)/abs(DEA) 最大值*0.12,0.01)，
红▲画于 DIFF-偏移，绿▼画于 DIFF+偏移。相等不触发价格过滤。

此版本只负责 KlineChart 观察副图，由 `thsMacdDisplay.ts` 实现，与通用内核和正式苏冰策略版本分开。
EMA 以加载窗口内每个物理合约/calculation segment 的首个 close 为 seed；不跨段计算，非法 close 重置。
加载更早数据可能改变重叠区的 EMA 数值，不宣称与同花顺完整历史逐值一致。
苏冰参考数据仍覆盖主图 EMA21，但不再覆盖独立 MACD 副图；苏冰正式 Event、历史信号、
参考交易和 Runtime 不受此显示版本影响。原公式 NOTICE 在此范围仅由图上金死叉标记表达，
不新增通知、回放、PushPlus 或正式 Alert 规则。此显示公式不是策略、收益或账户事实权威。
