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
signal_events 已完成 Stage 8.5-3 schema 最小实现，并在 Stage 8.5-9 新增 Stage 9 前只读准入 Gate。
```

进入 Stage 9 guarded adapter 前，候选事件必须先通过 `evaluate_stage9_signal_event_gate()`；真实发送仍需后续 Stage 9 单独授权。

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
- Stage 9 Gate 可判断 eligible event、缺真实合约、`.MAIN` 误用、缺 bar / trigger price、quality 非 passed 和敏感字段脱敏。

## 6. Stage 9 前置 Gate

Stage 8.5-9 新增 `services/quant-api/app/signal/stage9_gate.py`，以只读 helper 判断事件能否作为企业微信只读提醒候选。

准入条件：

- `event_type` 只能是 `signal_created` 或 `signal_changed`。
- `signal_status` 必须是 `entry_signal`。
- `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_end` 和 `trigger_price` 必须齐全。
- `actual_contract` 不能是 `*.MAIN`。
- `trigger_price` 必须大于 0，并来自真实合约 confirmed bar。
- `provider` 只能是 `rqdata` 或 `local_parquet`。
- `data_role` 必须是 `primary`。
- `quality_status.status` 必须是 `passed`。
- payload basis 必须表达 `observation_only` 和 `not_trading_instruction`，并过滤 webhook / token / password / cookie / secret。

当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`actual_contract` 在没有真实主力映射证据时保持 `NULL`。这类事件会被 Stage 9 Gate 阻断，不能直接进入企业微信提醒。
