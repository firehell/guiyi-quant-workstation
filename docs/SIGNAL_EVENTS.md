# Signal Events

更新时间：2026-07-14

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

进入 Stage 9 guarded adapter 前，候选事件必须先通过 `evaluate_stage9_signal_event_gate()`；Stage 9-A preview / dry-run adapter、Stage 9-B1 受控发送 / 通知记录 / 失败重试框架和 Stage 9-B2 单条历史回放 smoke 均已完成。

当前状态边界：

- Stage 9-B2 是 historical replay single-send smoke，不是 live-confirmed smoke。
- notification worker / scheduler 具备代码和测试基础，但长期自动发送 Gate 未通过。
- live-confirmed event、真实企业微信 autosend、5 个交易日长稳和故障恢复均仍是外部 Gate。
- 本文不授权自动交易、订单草稿或无人值守发送。

## 2. 数据边界

Stage 8 只记录观察 / 提醒事件：

- 不自动下单。
- 不生成订单草稿。
- Stage 9-A preview 不真实发送企业微信，不写 `SignalNotification`。
- Stage 9-B1 受控发送框架已具备真实发送能力，但默认 dry-run 不读 webhook、不写 DB、不发送；真实发送需 CLI 显式执行。
- 不读取或打印 `QYWX_WEBHOOK_URL`（除 Stage 9-B 真实发送 CLI 显式授权时）。
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
- `source_mode`：`historical_scan` / `jm_v1b_scan` / `manual_api` / `jm_v1b_historical_replay` / `live_confirmed`。
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
- live created：`signal_created:{live_dedupe_key}:created`
- live changed：`signal_changed:{live_dedupe_key}:{state_hash}`

### `signal_notifications` 扩展字段（Stage 9-B1）

Stage 9-B1 migration `20260708_0018` 扩展了 `signal_notifications` 表：

| 字段 | 用途 |
|---|---|
| `event_id` | 关联 `signal_events.id` |
| `attempt_count` | 发送尝试次数 |
| `max_attempts` | 最大重试次数（默认 3） |
| `last_attempt_at` | 上次尝试时间 |
| `next_retry_at` | 下次重试时间 |
| `last_error_type` | 上次失败类型（如 `missing_webhook`） |
| `response_status_code` | 企业微信 HTTP 响应状态码 |

兼容旧 WebSocket 通知记录，旧记录的上述字段为 `NULL`。

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

## 7. Stage 9-A 企业微信 preview adapter

Stage 9-A 新增只读 preview / dry-run adapter：

- `services/quant-api/app/signal/stage9_wechat.py`
- `GET /api/signals/events/{event_id}/stage9-wechat/preview`
- `services/quant-api/tests/test_stage9_wechat_adapter.py`

行为：

- 先调用 `evaluate_stage9_signal_event_gate()`。
- Gate 通过时生成企业微信 robot markdown payload preview。
- Gate 阻断时返回 `blocked_reasons`，不生成可发送 payload。
- response 固定返回 `would_send=false`、`channel=enterprise_wechat`、`notification_recorded=false`。
- payload 必须显示真实合约、`bar_end`、`trigger_price`、`quality_status`、数据源和观察提醒 / 非交易指令语义。
- preview 和 payload 继续过滤 webhook / token / password / cookie / secret。

边界：

- 不读取或打印 `QYWX_WEBHOOK_URL`。
- 不真实发送企业微信。
- 不写 `SignalNotification`。
- 不新增 migration、worker、scheduler 或失败重试。
- 不自动下单，不生成订单草稿。

## 8. Stage 9-B 企业微信发送记录与重试框架

Stage 9-B1 已新增受控发送 / 记录 / 重试框架：

- `services/quant-api/app/signal/stage9_wechat_delivery.py`
- `scripts/stage9_wechat_send_once.py`
- `GET /api/signals/events/{event_id}/stage9-wechat/notification`
- `services/quant-api/tests/test_stage9_wechat_delivery.py`
- `services/quant-api/alembic/versions/20260708_0018_stage9_wechat_notifications.py`

行为：

- 每次发送前仍必须调用 `evaluate_stage9_signal_event_gate()`。
- Gate 阻断时不发送，写入 `SignalNotification.status=skipped`。
- Gate 通过后才允许读取环境变量 `QYWX_WEBHOOK_URL`。
- 缺少 webhook 时不发送，写入 `failed / missing_webhook`。
- 真实发送只通过 CLI 显式执行：`--run-send --confirm-observation-only --event-id <id>`。
- 失败后最多重试 3 次；未达上限写 `retry_pending` 和 `next_retry_at`，达到上限写 `failed`。
- 同一事件幂等键固定为 `enterprise_wechat:signal_event:{event.id}`，避免重复发送。
- 通知 payload 和输出只保存脱敏后的 `payload_basis`、企业微信 markdown payload、blocked reasons 和发送摘要。

边界：

- Stage 9-A preview API 仍保持只读，不写 `SignalNotification`。
- Stage 9-B1 没有执行真实 smoke，没有批量发送历史事件，没有 worker / scheduler。
- 不自动下单，不生成订单草稿，不把 webhook / token / password / cookie / secret 写入日志、DB、文档或测试输出。
- Stage 9-B2 真实 smoke 仍需单独指定一个 eligible `event_id` 并确认运行命令。

## 9. Stage 9-B2 单条历史回放 eligible event

Stage 9-B2 新增受控历史回放入口，用于在没有最新 eligible event 时生成一条可验证企业微信发送链路的真实历史 entry event：

- `services/quant-api/app/signal/stage9_jm_v1b_replay.py`
- `scripts/stage9_jm_v1b_replay_event_once.py`
- `services/quant-api/tests/test_stage9_jm_v1b_replay.py`

行为：

- 默认 dry-run，不写 `StrategySignal`、不写 `SignalEvent`、不写 `SignalNotification`。
- 候选只来自已登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed` 的 actual-contract historical bars。
- 使用 `LiveTargetContractResolver` 解析 `actual_contract`，不硬编码长期主力合约。
- 日线方向仍读取 `continuous_contract=jm.MAIN` 的 active historical 视图；trigger price 只来自真实合约 confirmed bar close。
- `--run-write --confirm-historical-replay --confirm-observation-only` 才允许写入一条 `StrategySignal -> SignalEvent`。
- 事件固定标记 `source_mode=jm_v1b_historical_replay`、`historical_replay=true`、`observation_only=true`、`not_trading_instruction=true`、`auto_order=false`。
- 固定 dedupe key，重复执行不会重复写 `SignalEvent`。

本轮实际结果：

- replay dry-run 找到 `JM2609 / 15m / 2026-07-03T14:30:00 / short / trigger_price=1279.5`。
- 写入后返回 `event_id=1`、`signal_id=3`。
- `evaluate_stage9_signal_event_gate()` 返回 `allowed=true`、`blocked_reasons=[]`。
- `scripts/stage9_wechat_send_once.py --event-id 1` dry-run 返回 `allowed=true`、不读取 webhook、不发送。
- 后续单条重试已临时注入 `QYWX_WEBHOOK_URL` 进程环境并执行一次真实 smoke；`signal_notifications.id=1` 更新为 `sent / HTTP 200 / attempt_count=1`，`sent_at=2026-07-08T15:25:01.328589+00:00`。

边界：

- 历史回放 event 只用于 Stage 9-B2 企业微信发送链路 smoke，不代表当前实时 / 前向提醒绩效。
- 不批量发送历史事件，不运行 retry-pending，不接 worker / scheduler。
- 不自动下单，不生成订单草稿，不输出或保存 webhook / token / password / cookie / secret。

## 10. V1 live-confirmed writer 与 notification worker

2026-07-10 新增代码级闭环：

- `LiveSignalEventService` 与 `NotificationDispatchService`。
- 独立 RQ queue：`guiyi-notifications`。
- worker task：`app.tasks.notifications.deliver_live_notification_task`。
- scheduler 只自动选择 `source_mode=live_confirmed` 的 `signal_created/signal_changed`；historical replay 永不自动入队。

formal writer 准入条件：

- `status=entry_signal` 且周期只能为 `5m/15m`。
- 聚合与日线综合质量必须为 `passed`，warnings 为空。
- `bar_end`、正数 `trigger_price`、long/short direction 齐全。
- `actual_contract` 必须存在且不能是 `*.MAIN`。
- entry source 必须是 `live_db_actual_contract / rqdata`。
- event 固定携带 `source_mode=live_confirmed`、`data_role=primary`、`observation_only=true`、`not_trading_instruction=true`、`auto_order=false`。

幂等与 revision：

- dedupe 包含 strategy/version/product/actual contract/period/bar_end/event type。
- 同一 confirmed bar 相同状态重跑不新增 signal/event。
- trigger/stop/reason/quality 状态摘要变化时只追加一个 state-hash `signal_changed` event。
- `/live-evaluator/preview` 保持原有零写行为，不因 formal writer 存在而改变。

notification 行为：

- `GUIYI_WECHAT_AUTOSEND_ENABLED=false` 为默认值。
- scheduler 只创建/入队通过 Stage 9 Gate 的 live event，不读取 webhook。
- 只有 notification worker 在 feature flag 开启后读取 `QYWX_WEBHOOK_URL`。
- `sent/skipped/max-attempt failed` 不再处理；due `retry_pending` 最多重试到 3 次。
- pending job 采用稳定 RQ job id，并能在 dispatcher 中恢复 stale pending。

当前状态边界：

- 代码与测试已完成。
- 本轮未写真实 `StrategySignal/SignalEvent/SignalNotification`，未发送企业微信，未加载 worker/scheduler。
- Stage 9-B2 历史真实 smoke 不等于 live-confirmed smoke 或长期运行能力。
