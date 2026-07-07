# 当前任务同步：STAGE-8-SIGNAL-EVENTS

生成时间：2026-07-07

## 最新状态

`STAGE-8-SIGNAL-EVENTS` 已完成代码 / 文档级闭环。

本轮新增 append-only 的 `signal_events` 事件账本，用来记录正式信号扫描生成、扫描变化和人工生命周期状态流转。Stage 8 只提供后端事件源和只读查询 API，不接企业微信，不生成订单，不自动下单。

## 关键输出

新增：

- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/tests/test_signal_events.py`
- `docs/SIGNAL_EVENTS.md`

更新：

- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/signal/scanner.py`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 实现结论

新增 `SignalEvent` / `signal_events`：

- `signal_created`：扫描首次生成信号。
- `signal_changed`：扫描发现同一信号内容变化。
- `signal_status_changed`：人工查看、观察、忽略等生命周期变化。

事件边界：

- `strategy_signals` 仍是最新信号快照。
- `signal_notifications` 仍是 WebSocket 等通知记录。
- `signal_events` 是 Stage 9 企业微信只读提醒和后续 Web 时间线可读取的事件源。

新增只读 API：

- `GET /api/signals/events`
- `GET /api/signals/{signal_id}/events`

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
```

结果：

- `test_signal_events.py`：`3 passed`。
- `test_signal_scanner_api.py`：`7 passed`。
- `test_live_signal_evaluator.py`：`4 passed`。

收尾检查：

```bash
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api ruff check services/quant-api/app/models/signal.py services/quant-api/app/signal/events.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
git diff --check
```

结果：

- Alembic：已升级 `20260707_0014 -> 20260707_0015`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 本轮没有做

- 没有接企业微信。
- 没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有把 live evaluator preview 自动持久化为正式事件。
- 没有把原始 XMA PoC 或 XMA 派生信号接入 `signal_events`。
- 没有修改策略核心逻辑或回测口径。
- 没有修改 JM v2 parquet、manifest 或 active 数据登记。
- 没有做 Web 页面大改。

## 下一步建议

下一步进入 Stage 9：企业微信只读提醒。

Stage 9 应基于 `signal_events` 做提醒过滤、发送去重、失败记录和敏感信息保护；只发观察提醒，不表达自动交易指令。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/SIGNAL_EVENTS.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/tests/test_signal_events.py`
