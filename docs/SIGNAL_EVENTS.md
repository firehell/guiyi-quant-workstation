# Signal Events

生成时间：2026-07-07

## 1. 定位

`signal_events` 是信号事件账本，用来 append-only 记录正式信号快照的关键变化：

- 扫描首次生成信号：`signal_created`
- 扫描发现同一信号发生变化：`signal_changed`
- 人工查看、观察、忽略等生命周期变化：`signal_status_changed`

`signal_events` 不替代 `strategy_signals`。当前边界是：

- `strategy_signals`：最新可展示的信号快照。
- `signal_notifications`：WebSocket 等通知发送记录。
- `signal_events`：后续企业微信只读提醒和 Web 事件时间线可读取的可信事件源。

## 2. 数据边界

Stage 8 只记录观察 / 提醒事件：

- 不自动下单。
- 不生成订单草稿。
- 不接企业微信。
- 不读取或打印 `QYWX_WEBHOOK_URL`。
- 不把 live evaluator preview 自动持久化为正式信号事件。
- 不把原始 XMA PoC 或 XMA 派生信号写入 `signal_events`。

历史扫描仍读取 active primary 数据：

```text
provider/source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

## 3. 表结构

新增表：

```text
signal_events
```

关键字段：

- `event_key`：唯一去重键。
- `event_type`：`signal_created` / `signal_changed` / `signal_status_changed`。
- `signal_id`：关联 `strategy_signals.id`。
- `task_no`：扫描任务编号，人工状态事件沿用信号当前 `task_no`。
- `source_mode`：`historical_scan` / `jm_v1b_scan` / `manual_api`。
- `signal_status`：策略状态，例如 `entry_signal` / `no_signal`。
- `lifecycle_status`：人工生命周期状态，例如 `new` / `viewed` / `watching` / `ignored`。
- `data_role`、`quality_status`：保留数据边界和质量信息。
- `payload`：事件快照，已过滤 `webhook`、`token`、`password`、`secret`、`cookie` 等敏感键。

去重口径：

- `signal_created:{signal.dedupe_key}`
- `signal_changed:{signal.dedupe_key}:{task_no}`
- `signal_status_changed:{signal_id}:{old_status}:{new_status}:{timestamp}`

## 4. API

新增只读 API：

```text
GET /api/signals/events
GET /api/signals/{signal_id}/events
```

`GET /api/signals/events` 支持过滤：

- `signal_id`
- `task_no`
- `symbol`
- `event_type`
- `source_mode`
- `limit`

## 5. 验证

已覆盖：

- 扫描生成信号后写入 `signal_created`。
- 重复扫描不重复写 `signal_created`。
- `ack` / `status` 状态变化写入 `signal_status_changed`。
- 相同状态重复提交不写重复事件。
- `live-evaluator/preview` 不写 `StrategySignal`、`SignalNotification`、`SignalEvent`。
- 事件查询 API 可按信号和过滤条件读取事件。

Stage 9 企业微信只读提醒应基于 `signal_events` 继续设计提醒过滤和发送记录，不应在 Stage 8 中提前发送消息。
