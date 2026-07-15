# Baseline vs OOS：report_id=14 差异解释

生成时间：2026-07-12

任务：`JM-V1B-OOS-FULL-WINDOW-VALIDATION`

## 固定边界确认

- 策略：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- 执行：`next_bar_open`
- 成本：`rate=0.0001`、`slippage=1.0`、`size=60`、`pricetick=0.5`、`capital=100000`
- 数据：`local_parquet / primary / passed`
- `persist_to_db=false`；未回写 `report_id=14`

## 基线（report_id=14）

| 字段 | 值 |
|---|---|
| trust audit | passed（10/10） |
| 时间窗口 | 2023-01-03 .. 2026-07-06 |
| trade_count | 155 |
| total_return | -19.29% |
| max_drawdown | 24.69% |
| win_rate | 40.0% |
| profit_loss_ratio | 1.11 |
| total_commission | 3633.20 |
| total_slippage | 9300.00 |
| data_version | `v1b_jm_20230103_20260706` |

说明：基线可信通过只代表链路可追溯，不代表策略有效或可实盘。

## 全窗口 OOS 结果摘要

| 窗口 | trades | return | MDD | win_rate | profit_factor | trust |
|---|---:|---:|---:|---:|---:|---|
| in_sample_baseline | 125 | -8.56% | 14.19% | 40.8% | 0.86 | passed |
| oos_fixed | 32 | -9.06% | 7.61% | 37.5% | 0.29 | passed |
| walk_forward_a_test | 5 | -1.92% | 1.54% | 0.0% | 0.00 | passed |
| walk_forward_b_test | 14 | +0.55% | 2.72% | 35.7% | 1.08 | passed |
| walk_forward_c_test | 32 | -9.06% | 7.61% | 37.5% | 0.29 | passed |

证据目录：`data/reports/oos_validation_full_window_20260712/run/`

## 与 report_id=14 的关键差异

### 1. 时间窗口不同

- `report_id=14` 覆盖约 3.5 年全窗口（至 2026-07-06）。
- `in_sample_baseline` 仅覆盖 2023-01-03 .. 2025-12-31，因此 trade_count 从 155 降到 125 是窗口切分结果，不是策略改写。
- `oos_fixed` / `walk_forward_c_test` 聚焦 2026H1，trade_count=32，亏损 -9.06%，必须如实保留。

### 2. 数据版本不同（实现漂移风险）

- 基线：`v1b_jm_20230103_20260706`
- OOS 运行：`v1b_jm_20200102_20260710`

这会导致同策略、同参数下交易次数和收益与 report 14 不完全可比。差异解释必须同时考虑：

1. 窗口切分；
2. 当前 active 数据版本与 report 14 生成时数据版本不一致。

因此 **不得** 把 `in_sample_baseline` 的 -8.56% 直接等同于“样本内复现成功”；它与 report 14 的 -19.29% 不是同一数据快照。

### 3. 收益与回撤

- 多数 OOS 窗口仍亏损或微利，未出现“调参后显著改善”。
- `walk_forward_b_test`（2025Q3）唯一小幅盈利 +0.55%，但仅 14 笔交易，样本过短，不能推导稳定性。
- `walk_forward_a_test`（2025Q1）5 笔全亏，win_rate=0，必须保留为低样本恶化证据。

### 4. 成本与乘数

- 所有窗口 `contract_multiplier_check` / `price_tick_check` 均为 passed（expected 60 / 0.5）。
- fee/slippage 随交易次数缩放；短窗口费用总额低于基线是正常现象。

### 5. trade/order/equity 一致性

- 每个窗口内存级 trust checks：`trade_count_consistency`、`equity_consistency`、`fee_slippage`、`execution_policy`、`lineage_mapping`、`contract_multiplier` 全部 passed。
- 全窗口 lineage：mapped_trades = trade_count，mapped_orders = order_count。

## 结论（研究层，非准入）

1. **未调参、未改策略、未写正式 DB**：符合 OOS Gate。
2. **亏损与低交易数窗口已保留**：包括 `oos_fixed`、`walk_forward_a_test`、`walk_forward_c_test`。
3. **不能宣称策略样本外稳定**：2026H1 仍亏损，2025Q1 极低样本全亏。
4. **不能宣称复现 report 14**：数据版本与窗口边界不同，in_sample 与 baseline 数值差异需视为“冻结参数下的新快照结果”，不是旧报告重放。
5. **report_id=14 trust passed 仍有效**：只读审计未回写；OOS 是并行验证，不替代 Stage 13-G。

## 建议外部 GPT 审查重点

1. 是否接受“数据版本漂移 + 窗口切分”作为 report 14 与 in_sample 差异的主因？
2. 2026H1 连续亏损是否足以阻止进入模拟盘讨论？
3. walk-forward 低样本窗口（5 笔）应如何标注统计可信度上限？
