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
- `signal_events`：后续企业微信只读提醒和 Web 事件时间线可读取的事件账本基础。

Stage 8.5 审查结论：

```text
signal_events 已完成 Stage 8.5-3 schema 最小实现，但仍不能直接承接 Stage 9 企业微信。
```

进入 Stage 9 前，还需要通过后续阶段确认真实主力映射和真实合约 trigger price 来源。

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
- `product`：品种，例如 `jm`、`rb`。
- `continuous_contract`：研究主连 / 连续合约，例如 `jm.MAIN`。
- `actual_contract`：真实主力或真实交易合约；没有映射证据时保持 `NULL`。
- `dominant_mapping_date`：主力映射日期，当前可空，后续由映射阶段补齐。
- `bar_start` / `bar_end`：信号对应确认 bar 的边界。
- `trigger_price`：触发价，当前来自显式 `trigger_price`、`signal_price` 或 `current_price`。
- `provider` / `source`：数据提供方和数据来源层。
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
- `product`
- `continuous_contract`
- `actual_contract`
- `event_type`
- `source_mode`
- `provider`
- `source`
- `data_role`
- `limit`

## 5. 验证

已覆盖：

- 扫描生成信号后写入 `signal_created`。
- 重复扫描不重复写 `signal_created`。
- `ack` / `status` 状态变化写入 `signal_status_changed`。
- 相同状态重复提交不写重复事件。
- `live-evaluator/preview` 不写 `StrategySignal`、`SignalNotification`、`SignalEvent`。
- 事件查询 API 可按信号和过滤条件读取事件。
- `.MAIN` 主连不会被写入 `actual_contract`；没有真实主力映射证据时保持 `NULL`。

## 6. Stage 8.5 前置缺口

Stage 8.5-3 已补齐 `strategy_signals` 与 `signal_events` 的显式字段和 API 输出，但当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`actual_contract` 在没有真实主力映射证据时保持 `NULL`。

当前 `trigger_price` 在 historical scan 中仍来自主连 bar close / `current_price`，不足以作为真实主力合约提醒价格。

Stage 9 企业微信只读提醒应在 Stage 8.5 Gate 通过后再设计。提醒必须基于显式真实合约绑定和触发价来源，只发观察提醒，不表达自动交易指令。
