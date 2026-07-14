# Backtest

更新时间：2026-07-14

事实来源：`docs/BACKTEST_ENGINE.md`

当前状态：current，样本外和 walk-forward 仍 pending。

## 链路

```text
Backtest API
-> BacktestService
-> vn.py runner
-> ResultConverter
-> BacktestReport / Trade / Order
-> derived equity / drawdown / trusted metrics
-> trust audit
```

## 当前基线

- report：`report_id=14`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- data：`local_parquet / primary / passed`
- trades：155
- orders：239
- trust audit：passed
- total return：约 -19.29%

## 边界

trust audit passed 只证明数据、执行、成本、trade/order/equity/metrics 和敏感输出一致，不证明策略盈利、稳定或可实盘。

## 后续

OOS / walk-forward 需独立任务，使用 frozen config，不调参改善收益。

