# Stage 13 Backtest Trust Audit

生成时间：2026-07-09

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
- `trade_order_consistency`：检查 report trade_count 与 trade 行数、trade 方向、价格、时间、数量、合约字段；有 trade 但无 order 时给 warning。
- `equity_consistency`：从 trades 复算 equity / drawdown，并与 summary 中 final equity、最大回撤金额、最大回撤比例对齐。
- `fee_slippage`：检查 rate / slippage、逐笔 commission / slippage、summary totals。
- `contract_multiplier`：检查 size / pricetick、逐笔 contract multiplier / price tick；JM V1-B 有成交但缺真实合约成本 lineage 时给 warning。
- `trusted_metrics`：检查 `consistency_hash` 和 `metric_units`。
- `reproducibility`：检查 task、策略、数据版本、start/end 等复现字段，并脱敏 request payload。
- `sensitive_output`：阻断 webhook、token、password、license、secret 和本机路径泄露。

## 6. 已知风险

- 第一版审计器不重跑回测，只审计已入库报告，因此不能单独证明策略无未来函数；它只能发现 report/trade/order/equity/metrics 层面的可信性问题。
- `order_rows` 与 `trades` 当前只做基础数量和字段检查，不做完整成交撮合映射。
- 旧报告如果缺少 `entry_signal_time`，审计会返回 warning，而不是伪装 passed。
- JM V1-B 旧报告如果缺少真实合约、费用规则或主力映射来源，审计会返回 warning，需后续结合 actual-contract 回测主线继续修复。
- 当前未新增 API 或 Web 展示；如需在 Web Backtest 页面显示审计结果，应另开只读 API / 前端任务。

## 7. 验收命令

本阶段最小验证命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_backtest_trust_audit.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_backtest_service_runner.py services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py services/quant-api/tests/test_backtest_vnpy_schema.py services/quant-api/tests/test_backtest_task_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/backtest/trust_audit.py scripts/backtest_trust_audit.py services/quant-api/tests/test_backtest_trust_audit.py
git diff --check
```

## 8. 后续建议

Stage 13 下一步应优先对真实 JM V1-B report 运行 CLI smoke。如果返回 warning，应先修 report/trade/equity/成本/真实合约 lineage，再进入 Stage 14 Web 复盘增强。
