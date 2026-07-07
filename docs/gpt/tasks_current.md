# 当前任务同步：LIVE-1M-6B-LIVE-EVALUATOR-READONLY

生成时间：2026-07-07

## 最新状态

`LIVE-1M-6B-LIVE-EVALUATOR-READONLY` 已完成最小代码闭环。

本轮新增后端 live evaluator preview API：显式调用 `/api/signals/live-evaluator/preview` 时，读取 live `15m/5m` entry bars，并结合 active primary historical `1d` 日线数据返回 JM V1-B 临时 evaluation result。

默认 `/api/signals/scan` 不读取 live DB，Market / Backtest / Signal 默认 historical active 链路不变。

## 关键输出

新增：

- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`

更新：

- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_signal_scanner_api.py`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 实现结论

新增 API：

```text
POST /api/signals/live-evaluator/preview
```

关键规则：

- entry interval 第一版仅支持 `15m` / `5m`。
- entry bars 来自 `live_aggregated_bars`。
- daily direction 来自 active primary historical `1d` standard parquet。
- 结果只返回 preview DTO，不写 `StrategySignal` / `SignalNotification` / `SignalScanTask`。
- warning / partial live bars 默认阻断可行动入场结论。
- 不推送 WebSocket，不接企业微信，不下单。

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

## 本轮没有做

- 没有新增 migration。
- 没有改 `MarketDataReader` active filter。
- 没有改默认 `SignalScanner` historical scan。
- 没有做 historical/live 拼接。
- 没有写正式信号或通知。
- 没有接企业微信。
- 没有前端页面。
- 没有下单或订单草稿。

## 下一步建议

建议先把本轮 diff 和测试结果交给浏览器 GPT 做边界审查。继续实现时不要跳过 Stage 8 `signal_events`，也不要直接进入企业微信推送。

## 建议 GPT 上传文件

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
