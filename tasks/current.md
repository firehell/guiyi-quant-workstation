# 当前任务：LIVE-1M-6B-LIVE-EVALUATOR-READONLY

生成时间：2026-07-07
任务性质：策略中心 live evaluator 显式只读预览入口

## 当前结论

`LIVE-1M-6B-LIVE-EVALUATOR-READONLY` 已完成最小代码闭环。

本轮新增后端 live evaluator preview API。只有显式调用 `/api/signals/live-evaluator/preview` 时，才读取 `live_aggregated_bars` 中的 JM `15m/5m` live bars，并结合 active primary historical `1d` 日线数据做 JM V1-B 策略预览计算。结果只作为临时 evaluation result 返回，不写 `StrategySignal`、不写 `SignalNotification`、不创建 `SignalScanTask`、不推送 WebSocket / 企业微信、不生成订单。

默认 `/api/signals/scan`、Market / Backtest / Signal active historical 读取路径保持不变。

## 本轮变更

### 1. 后端只读 evaluator service

新增：

- `services/quant-api/app/services/live_signal_evaluator.py`

实现：

- `LiveSignalEvaluator.preview()` 只读计算 live evaluation result。
- entry interval 第一版仅支持 `15m` / `5m`。
- entry bars 从 `LiveMarketReader.get_bars()` 读取 live DB。
- 日线方向仍从 `MarketDataReader.load_latest_bars(..., period="1d", data_role="primary")` 读取 active standard parquet。
- 复用 JM V1-B 策略纯计算函数：`validate_params()`、`confirmed_daily_direction_snapshot()`、`calculate_indicators()`、`decide_entry()`。
- warning / partial / failed / rejected live rows 会进入 quality summary 和 warnings。
- 默认 `allow_warning_quality=false` 时，live warning / partial 会阻断可行动入场结论，返回 `no_signal`。

### 2. 后端 API / schema

更新：

- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/schemas/signal.py`

新增 API：

```text
POST /api/signals/live-evaluator/preview
```

请求约束：

- `symbol` 第一版只允许 `jm`。
- `entry_intervals` 第一版只允许 `15m` / `5m`。
- schema `extra="forbid"`，`auto_order` 等未知字段会被拒绝。
- `provider` / `source_mode` 为显式 live 过滤参数。

返回字段包括：

- `strategy_code`
- `strategy_version`
- `symbol`
- `contract`
- `entry_interval`
- `evaluated_at`
- `bar_time`
- `direction`
- `status`
- `daily_direction`
- `entry_reason`
- `no_signal_reason`
- `stop_loss_price`
- `quality`
- `warnings`
- `source`

### 3. 测试

新增：

- `services/quant-api/tests/test_live_signal_evaluator.py`

更新：

- `services/quant-api/tests/test_signal_scanner_api.py`

覆盖：

- 显式 live preview 能读取 live `15m/5m` bars 并返回 result。
- evaluator 调用后 `StrategySignal` / `SignalNotification` / `SignalScanTask` 均不新增。
- warning / partial live bars 默认返回 warning 并阻断可行动入场结论。
- live entry bars 不足时返回 `entry_bars_insufficient`。
- historical daily active 数据缺失时返回 `daily_data_missing`。
- 默认 `/api/signals/scan` 仍只读 active primary parquet，不读取 live rows。
- live preview endpoint 拒绝 unsupported interval 和 `auto_order` 等未知字段。

## 本轮没有做

- 没有新增 Alembic migration。
- 没有改 `MarketDataReader` active filter。
- 没有改 `SignalScanner` 默认 reader。
- 没有把 live DB 登记为 trusted standard parquet。
- 没有做 historical/live 拼接。
- 没有写 `StrategySignal`。
- 没有写 `SignalNotification`。
- 没有创建 `SignalScanTask`。
- 没有入队 RQ。
- 没有推送 WebSocket。
- 没有接企业微信或读取 `QYWX_WEBHOOK_URL`。
- 没有自动下单或生成订单草稿。
- 没有做前端页面。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_market_reader.py services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/services/live_signal_evaluator.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_signal_scanner_api.py
git diff --check
```

结果：

- `test_live_signal_evaluator.py`：`4 passed`。
- `test_signal_scanner_api.py`：`7 passed`。
- live reader + historical reader 回归：通过。
- `ruff check`：通过。
- `git diff --check`：通过。

## 风险与未完成项

- 当前仍未执行真实 live 非 dry-run 数据验证；本轮以构造 DB rows 验证 reader/API/策略预览边界。
- evaluator 只做后端 preview，不做 Web 页面；Web 展示增强留到 Stage 10。
- 日线方向仍使用 active historical `1d`，因为当前 live 聚合只到 `60m`。
- preview result 是观察辅助，不是可信回测结论，也不是正式信号记录。

## 下一步

建议先做一次外部 GPT 审查或小范围 API smoke，再进入：

```text
Stage 7：通达信指标本地化，标注未来函数 / 重绘风险
```

如继续 live 信号链路，也应按路线进入 Stage 8 `signal_events`，不要直接跳到企业微信推送。

## GPT 同步文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/tests/test_signal_scanner_api.py`
