# Stage 13 Backtest Trust Audit

更新时间：2026-07-10

## 1. 阶段定位

Stage 13 定义为“可信回测主线复核”，不是策略优化阶段。

本阶段目标是审计当前回测主线是否可信、可追溯、可复现：

```text
Backtest API
-> BacktestService
-> vn.py runner / result_converter
-> BacktestReport / BacktestTrade / BacktestOrder
-> derived equity / drawdown / trusted metrics
```

本阶段不新增策略、不调参、不优化收益、不修改 RQData / parquet / manifest / quality report、不接企业微信、不接实盘、不自动下单。

## 2. 当前回测调用链

当前回测主线：

1. `services/quant-api/app/api/backtests.py` 创建或查询回测任务和报告。
2. `services/quant-api/app/backtest/service.py` 生成 vn.py setting、持久化任务和结果。
3. `services/quant-api/app/backtest/runner.py` 调用 vn.py adapter。
4. `services/quant-api/app/vnpy_integration/result_converter.py` 标准化 vn.py 输出。
5. `BacktestService.persist_result()` 只允许 `primary` 且 `quality_status != failed` 的结果持久化为成功报告。
6. `generate_equity_curve()` 与 `generate_drawdown_curve()` 从 closed trades 派生资金曲线和回撤曲线。
7. `compute_report_metrics()` 从 summary、trades、equity、drawdown 计算 trusted metrics。
8. `BacktestReportModel`、`BacktestTradeModel`、`BacktestOrderModel` 入库，Web Backtest 只读消费。

当前 `persist_result()` 会忽略输入结果中的 `equity_curve` / `drawdown_curve` / `balance_curve` / `daily_results`，改用 trades 派生曲线，降低外部结果字段污染报告指标的风险。

## 2.1 Stage 13-D lineage 修复

Stage 13-D 已将 report / trade / order 的信号与成交来源显式化，目标是让每笔成交能追溯到明确的策略事件或 order row，而不是从 K 线周期倒推。

新增字段：

- `backtest_trades.entry_signal_source`
- `backtest_trades.exit_signal_source`
- `backtest_trades.entry_order_no`
- `backtest_trades.exit_order_no`
- `backtest_trades.lineage_status`
- `backtest_orders.trade_no`
- `backtest_orders.leg`
- `backtest_orders.lineage_source`
- `backtest_orders.mapping_status`

映射原则：

- 优先使用 trade 显式字段。
- 其次使用 `strategy_execution_events` 中精确匹配的 `signal_datetime` / `fill_datetime`。
- 再使用 vn.py order row 的精确时间、方向、offset 映射。
- 不从 `open_time - interval` 反推 `entry_signal_time`。
- 找不到唯一来源时保留 `warning`，不伪装为可信 passed。

`lineage_summary` 会写入 report summary 和 task result payload，记录 `mapped / partial / missing / ambiguous` trade 与 order 数量。

## 2.2 Stage 13-E 新报告生成尝试

Stage 13-E 按计划尝试重新生成一份 `JM V1-B fast-entry 15m` 新报告：

- task_id: `21`
- task_no: `BTV-20260709131810-c9905541`
- strategy: `jm_v1b_daily_direction_fast_entry / v1b.0`
- period: `15m`

本次没有生成新的 `BacktestReport`，因此没有可用于 `trust audit` CLI smoke 的新 `report_id`。

阻断原因：

```text
TradingParameterMissingError:
trading parameters incomplete for contract=JM2609 on 2026-04-24: price_tick
```

含义：Stage 13-D 的 lineage 修复已经开始严格要求真实合约成本字段可追溯；当 `jm_v1b_result_enricher` 为成交补齐真实合约成本 lineage 时，发现 `FuturesTradingParameter.price_tick` 缺失，因此拒绝把该报告持久化为可信成功报告。

本次没有修改策略、没有调参、没有修改 RQData / parquet / manifest / quality report，没有回填旧报告，没有接企业微信、实盘或自动下单。

## 2.3 Stage 13-F metadata repair 与 Stage 13-E 重跑

Stage 13-F 已完成 `JM2609 / 2026-04-01..2026-07-07` trading parameters 只读审计、受控修复和 Stage 13-E 重跑。

只读审计结论：

- `JM2609` 在 `2026-04-01..2026-07-07` 共 57 个 trading parameter 日期。
- `futures_trading_parameters` 与 `fee_margin_rules` 各有 56 行缺 `price_tick`，唯一非空值为 `2026-07-07 = 0.5`。
- `2026-04-24` 附近只缺 `price_tick`；`contract_multiplier=60`、保证金、开平仓手续费和 `commission_type=by_money` 已存在。
- `market_data_files` 中 `JM2609` 的 `1m/5m/15m/30m/60m/1d` primary passed bars 已覆盖 `2026-04-24`。
- 其他 JM 合约仍有 `price_tick` 缺口，本轮没有扩大修复范围。

受控修复范围：

- 扩展 `scripts/backfill_jm_price_tick.py`，新增 `--contract` 与 `--expected-eligible-null`，写入前强制精确匹配待修行数。
- 已执行 `--contract JM2609 --expected-eligible-null 56 --apply`。
- 仅写入 `futures_trading_parameters.price_tick` 与 `fee_margin_rules.price_tick` 的空值行；不覆盖非空值。
- `FuturesTradingParameter.raw_payload.price_tick_backfill` 已记录 `stage=13-F`、`contract=JM2609`、日期范围、`price_tick=0.5` 和 source。
- 未修改 RQData / parquet / manifest / quality report，未修改策略、回测口径、旧失败 task/report、企业微信、实盘或自动下单。

修复后验证：

- `JM2609` 在 `2026-04-01..2026-07-07` 的 `FuturesTradingParameter.price_tick` 空值数为 0。
- `JM2609` 在同区间的 `FeeMarginRule.price_tick` 空值数为 0。
- 非 `JM2609` 的 JM 合约 `price_tick` 空值仍为 585，确认本轮没有 product-wide 批量修复。
- `resolve_jm_contract(trading_day=2026-04-24)` 可解析 `actual_contract=JM2609`、`price_tick=0.5`、`contract_multiplier=60`、`margin_ratio=0.12`、`parameter_source=futures_trading_parameters`。

Stage 13-E 重跑结果：

- 新 task：`task_id=22`、`task_no=BTV-20260709134008-0a42eca8`。
- 新 report：`report_id=14`、`report_no=BTV-20260709134008-0a42eca8-RPT-649c9c1d`。
- 策略：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`。
- 结果：`BacktestTaskRunner` inline 执行成功，生成 155 笔 trade。
- trust audit：`audit_status=warning`；`data_lineage`、`execution_policy`、`trade_order_consistency`、`equity_consistency`、`fee_slippage`、`contract_multiplier`、`trusted_metrics`、`reproducibility`、`sensitive_output` 均为 `passed`。
- 当前 warning 集中在 `lineage_mapping`：155 笔 trade 为 partial lineage，239 条 order row 未映射到 trade；这是 Stage 13-D 后续 lineage 映射质量问题，不再是 trading parameter 缺口。

## 2.4 Stage 13-G lineage mapping 收口

Stage 13-G 已完成 `report_id=14` 的显式映射收口：

- 155 笔 `backtest_trades` 全部为 `lineage_status=mapped`。
- 239 条 `backtest_orders` 全部为 `mapping_status=mapped`。
- report `lineage_summary` 为 `mapped_trades=155 / partial=0 / missing=0 / ambiguous=0 / mapped_orders=239 / unmapped=0 / ambiguous=0`。
- `scripts/backtest_trust_audit.py --report-id 14 --format markdown` 当前返回 `audit_status=passed`。
- `data_lineage`、`execution_policy`、`lineage_mapping`、`trade_order_consistency`、`equity_consistency`、`fee_slippage`、`contract_multiplier`、`trusted_metrics`、`reproducibility`、`sensitive_output` 十项全部通过。

该报告 `total_return=-0.1928553100985149`；可信通过不等于策略盈利、样本外稳定或可实盘。

## 3. 数据读取边界

正式回测 active 数据入口继续沿用：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

禁止把 `validation`、`legacy_reference`、`candidate`、`failed`、live DB、旧 TqSdk / 天勤或交易练习者数据混入正式回测。

## 4. Stage 13 最小审计器

新增只读审计器：

```text
services/quant-api/app/backtest/trust_audit.py
scripts/backtest_trust_audit.py
services/quant-api/tests/test_backtest_trust_audit.py
```

CLI 示例：

```bash
uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id <report_id> --format json
uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id <report_id> --format markdown
uv run --project services/quant-api python scripts/backtest_trust_audit.py --task-no <task_no> --format markdown
```

CLI 默认只读：

```text
readonly=true
would_write_db=false
would_run_rqdata=false
would_run_backtest=false
would_send_notifications=false
```

## 5. 审计规则

审计输出 `audit_status`：

- `passed`：关键检查均通过。
- `warning`：存在无法确认或需人工复核的字段。
- `failed`：数据边界、质量状态、核心一致性或敏感输出检查失败。

当前检查项：

- `data_lineage`：检查 `data_source`、`data_role`、`quality_status`、`data_version`。
- `execution_policy`：检查 `execution_timing=next_bar_open`，并要求有 `entry_signal_time` 的 trade 必须在信号时间之后成交。
- `lineage_mapping`：检查 `entry_signal_source`、`lineage_status`、order `mapping_status`；无 order rows 但 strategy execution event 完整时不视为缺失。
- `trade_order_consistency`：检查 report trade_count 与 trade 行数、trade 方向、价格、时间、数量、合约字段；有 trade 但无 order 时给 warning。
- `equity_consistency`：从 trades 复算 equity / drawdown，并与 summary 中 final equity、最大回撤金额、最大回撤比例对齐。
- `fee_slippage`：检查 rate / slippage、逐笔 commission / slippage、summary totals。
- `contract_multiplier`：检查 size / pricetick、逐笔 contract multiplier / price tick；JM V1-B 有成交但缺真实合约成本 lineage 时给 warning。
- `trusted_metrics`：检查 `consistency_hash` 和 `metric_units`。
- `reproducibility`：检查 task、策略、数据版本、start/end 等复现字段，并脱敏 request payload。
- `sensitive_output`：阻断 webhook、token、password、license、secret 和本机路径泄露。

## 6. 已知风险

- 第一版审计器不重跑回测，只审计已入库报告，因此不能单独证明策略无未来函数；它只能发现 report/trade/order/equity/metrics 层面的可信性问题。
- Stage 13-D 只补齐新报告 lineage，不回填旧报告；旧报告缺字段仍会 warning。
- Stage 13-F 已修复 `JM2609` 在 `2026-04-01..2026-07-07` 的 `price_tick` 缺口，但其他 JM 合约仍有 `price_tick` 缺口；后续如需批量修复必须另设 Gate。
- Stage 13-G 已使 `report_id=14` trust audit 通过；后续任何 converter、strategy execution event 或持久化改动都必须保持该报告审计不退化。
- `strategy_execution_events` 是策略层事件证据，不等同真实交易委托或实盘订单。
- `order_rows` 与 `trades` 已有最小显式映射，但 vn.py order row 缺少唯一 trade id 时仍可能 warning。
- 旧报告如果缺少 `entry_signal_time`，审计会返回 warning，而不是伪装 passed。
- JM V1-B 旧报告如果缺少真实合约、费用规则或主力映射来源，审计会返回 warning，需后续结合 actual-contract 回测主线继续修复。
- 当前未新增 API 或 Web 展示；如需在 Web Backtest 页面显示审计结果，应另开只读 API / 前端任务。

## 7. 验收命令

本阶段最小验证命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_backtest_trust_audit.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_backtest_service_runner.py services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py services/quant-api/tests/test_backtest_vnpy_schema.py services/quant-api/tests/test_backtest_task_api.py services/quant-api/tests/test_vnpy_integration.py services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py services/quant-api/tests/test_su_bing_jm_v1b_short_hold.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
PYTHONPATH=services/quant-api uv run --project services/quant-api pytest -q services/quant-api/tests/test_backfill_jm_price_tick.py
uv run --project services/quant-api ruff check services/quant-api/app/backtest/trust_audit.py scripts/backtest_trust_audit.py services/quant-api/tests/test_backtest_trust_audit.py
PYTHONPATH=services/quant-api uv run --project services/quant-api ruff check scripts/backfill_jm_price_tick.py services/quant-api/tests/test_backfill_jm_price_tick.py
cd services/quant-api && uv run python -m alembic upgrade head
git diff --check
```

## 8. 后续建议

Stage 13-G 已收口。下一阶段只允许独立设计样本外 / walk-forward 验证，不调参改善 `report_id=14` 收益，不扩大 metadata repair 到其他 JM 合约，不把审计通过解释为实盘准入。
