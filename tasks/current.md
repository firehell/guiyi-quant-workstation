# 当前任务：STAGE-8-SIGNAL-EVENTS

生成时间：2026-07-07
任务性质：`signal_events` 信号事件化

## 当前结论

`STAGE-8-SIGNAL-EVENTS` 已完成代码 / 文档级闭环。

本轮新增 append-only 的 `signal_events` 事件账本，用来记录正式信号从扫描生成、扫描变化到人工生命周期状态流转的关键事件。Stage 8 只做后端事件源和只读查询 API，不接企业微信，不生成订单，不自动下单。

## 本轮变更

### 1. 数据库与 ORM

新增：

- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/tests/test_signal_events.py`
- `docs/SIGNAL_EVENTS.md`

更新：

- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/schemas/signal.py`

核心行为：

- 新增 `SignalEvent` / `signal_events` 表。
- `event_key` 唯一，事件 append-only，不覆盖旧事件。
- 支持 `signal_created`、`signal_changed`、`signal_status_changed`。
- 区分策略状态 `signal_status` 和人工生命周期 `lifecycle_status`。
- `payload` 过滤 `webhook`、`token`、`password`、`secret`、`cookie` 等敏感键。

### 2. 信号扫描事件写入

更新：

- `services/quant-api/app/services/signal_scanner.py`

核心行为：

- 扫描首次创建 `StrategySignal` 时写入 `signal_created`。
- 扫描发现同一信号变化时写入 `signal_changed`。
- 普通 historical scan 使用 `source_mode=historical_scan`。
- JM V1-B 专用扫描使用 `source_mode=jm_v1b_scan`。
- 重复扫描同一未变化信号不会重复写 `signal_created`。

### 3. 人工生命周期事件写入

更新：

- `services/quant-api/app/signal/scanner.py`
- `services/quant-api/app/api/signals.py`

核心行为：

- `POST /api/signals/{signal_id}/ack` 和 `PATCH /api/signals/{signal_id}/status` 在状态真实变化时写入 `signal_status_changed`。
- 同一状态重复提交不追加事件。
- 人工事件使用 `source_mode=manual_api`。

### 4. 只读查询 API

新增：

- `GET /api/signals/events`
- `GET /api/signals/{signal_id}/events`

`GET /api/signals/events` 支持：

- `signal_id`
- `task_no`
- `symbol`
- `event_type`
- `source_mode`
- `limit`

## 本轮没有做

- 没有接企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有把 live evaluator preview 自动持久化为正式事件。
- 没有把原始 XMA PoC 或 XMA 派生信号接入 `signal_events`。
- 没有修改策略核心逻辑。
- 没有修改回测口径。
- 没有修改 JM v2 parquet、manifest 或 active 数据登记。
- 没有做 Web 页面大改。

## 验证结果

TDD 红灯：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
```

结果：

- 首次运行因缺少 `SignalEvent` 导入失败，确认测试覆盖缺失功能。
- 初始实现后暴露测试夹具未满足 `/canonical/bars/` active 读取路径，以及 `unread` 需要映射为 lifecycle `new`。

最终验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
```

结果：

- `test_signal_events.py`：`3 passed`。
- `test_signal_scanner_api.py`：`7 passed`。
- `test_live_signal_evaluator.py`：`4 passed`。

收尾验证：

```bash
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api ruff check services/quant-api/app/models/signal.py services/quant-api/app/signal/events.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
git diff --check
```

结果：

- Alembic：已升级 `20260707_0014 -> 20260707_0015`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 风险与未完成项

- `signal_events` 已具备 Stage 9 企业微信只读提醒的事件源，但 Stage 9 仍需单独设计提醒过滤、发送去重和失败重试。
- 当前事件 payload 是信号快照，不保存 K 线大体量数据。
- `live_signal_evaluator` 仍是 preview-only，不写事件；后续如需 live 事件化，应另开阶段明确 source_mode、质量门槛和确认 bar 边界。

## 下一步

建议进入：

```text
Stage 9：企业微信只读提醒
```

Stage 9 应基于 `signal_events` 做提醒过滤和发送记录，只发观察提醒，不表达自动交易指令，不读取或打印 webhook 明文。

## GPT 同步文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/SIGNAL_EVENTS.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/tests/test_signal_events.py`
