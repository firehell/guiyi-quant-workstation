# Stage 9 企业微信只读提醒发送链路

生成时间：2026-07-08

## 1. 定位

Stage 9 是归一量化工作站的信号提醒发送链路。核心目标：让通过准入 Gate 的 `signal_events` 事件能以企业微信 robot markdown 格式发送只读观察提醒，不自动下单，不生成交易指令。

当前状态：

```text
Stage 9-A：企业微信只读 preview / dry-run adapter — done
Stage 9-B1：受控发送 / 通知记录 / 失败重试框架 — done
Stage 9-B2：单条历史回放 eligible event 生成 + observation-only 真实 smoke — done（HTTP 200, sent）
```

## 2. 发送流程

```text
eligible SignalEvent (signal_created / signal_changed, entry_signal)
-> evaluate_stage9_signal_event_gate()
-> Gate 通过：生成企业微信 robot markdown payload
-> 读取 QYWX_WEBHOOK_URL（仅 CLI 显式授权时）
-> HTTP POST 发送
-> 记录 SignalNotification (sent / failed / retry_pending / skipped)
-> 失败最多重试 3 次
```

Gate 阻断时不发送，写入 `SignalNotification.status=skipped`。

## 3. Stage 9 Gate 准入规则

`evaluate_stage9_signal_event_gate()` 位于 `services/quant-api/app/signal/stage9_gate.py`，纯只读判断。

准入条件：

| 条件 | 要求 |
|---|---|
| `event_type` | `signal_created` 或 `signal_changed` |
| `signal_status` | `entry_signal` |
| `product` | 非空 |
| `continuous_contract` | 非空 |
| `actual_contract` | 非空，不能是 `*.MAIN` |
| `dominant_mapping_date` | 非空 |
| `bar_end` | 非空 |
| `trigger_price` | 大于 0，来自真实合约 confirmed bar |
| `provider` | `rqdata` 或 `local_parquet` |
| `data_role` | `primary` |
| `quality_status.status` | `passed` |
| payload basis | 包含 `observation_only`、`not_trading_instruction`、`auto_order=false` |
| 敏感字段 | 过滤 webhook / token / password / cookie / secret |

当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`actual_contract` 缺少真实映射证据时保持 `NULL`，这类事件会被 Gate 阻断。

## 4. API 端点

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/signals/events/{event_id}/stage9-wechat/preview` | GET | 只读返回 Gate 结果和 markdown payload preview，不发送 |
| `/api/signals/events/{event_id}/stage9-wechat/notification` | GET | 只读查询通知发送状态 |

preview response 固定返回：

- `would_send=false`
- `channel=enterprise_wechat`
- `notification_recorded=false`
- Gate 通过时附带脱敏 `wechat_payload`
- Gate 阻断时附带 `blocked_reasons`

## 5. CLI 工具

### 5.1 受控发送

```bash
# dry-run（默认，不读 webhook、不写 DB、不发送）
uv run --project services/quant-api python scripts/stage9_wechat_send_once.py --event-id <id>

# 真实发送（需显式授权）
uv run --project services/quant-api python scripts/stage9_wechat_send_once.py \
  --run-send --confirm-observation-only --event-id <id>
```

### 5.2 历史回放 event 生成

```bash
# dry-run（默认，不写库、不读 webhook、不发送）
uv run --project services/quant-api python scripts/stage9_jm_v1b_replay_event_once.py

# 写入一条历史回放 event
uv run --project services/quant-api python scripts/stage9_jm_v1b_replay_event_once.py \
  --run-write --confirm-historical-replay --confirm-observation-only
```

## 6. signal_notifications 表扩展

Stage 9-B1 migration `20260708_0018` 扩展了 `signal_notifications`：

| 字段 | 用途 |
|---|---|
| `event_id` | 关联 `signal_events.id` |
| `attempt_count` | 发送尝试次数 |
| `max_attempts` | 最大重试次数（默认 3） |
| `last_attempt_at` | 上次尝试时间 |
| `next_retry_at` | 下次重试时间 |
| `last_error_type` | 失败类型（如 `missing_webhook`） |
| `response_status_code` | 企业微信 HTTP 响应状态码 |

通知状态流转：

```text
sent          — 发送成功
failed        — 发送失败且达到最大重试次数
retry_pending — 发送失败但未达最大重试次数
skipped       — Gate 阻断，不发送
```

幂等键：`enterprise_wechat:signal_event:{event.id}`，避免同一事件重复发送。

## 7. 企业微信 payload 结构

payload 固定表达：

- `notice_scope=observation_only`
- `trading_instruction=not_trading_instruction`
- `auto_order=false`

payload 必须显示：

- 真实合约（`actual_contract`）
- 研究主连（`continuous_contract`）
- `bar_end`
- `trigger_price`
- `quality_status`
- 数据源（`provider` / `source`）

payload 和日志继续过滤 `webhook`、`token`、`password`、`cookie`、`secret` 等敏感键或值。

## 8. Stage 9-B2 smoke 结果

本轮已完成单条历史回放 eligible event 生成和 observation-only 真实 smoke：

- replay dry-run 找到 `JM2609 / 15m / 2026-07-03T14:30:00 / short / trigger_price=1279.5`
- 写入 `event_id=1`、`signal_id=3`
- Gate 返回 `allowed=true`、`blocked_reasons=[]`
- 真实 smoke 结果：`signal_notifications.id=1` 记录为 `sent / HTTP 200 / attempt_count=1`
- `sent_at=2026-07-08T15:25:01.328589+00:00`

该事件仅用于验证 Stage 9 企业微信发送链路，不代表当前实时 / 前向提醒绩效。

## 9. 安全边界

- 不自动下单，不生成订单草稿。
- webhook 只从环境变量 `QYWX_WEBHOOK_URL` 读取，不进文档、DB、日志或 payload。
- 真实发送只通过 CLI 显式执行，默认 dry-run。
- preview / dry-run 不读取 webhook、不写 `SignalNotification`。
- 不批量发送历史事件，不运行 retry-pending（后续 worker / scheduler 任务）。
- 历史回放 event 固定标记 `historical_replay=true`、`observation_only=true`。

## 10. 关键代码

| 文件 | 用途 |
|---|---|
| `services/quant-api/app/signal/stage9_gate.py` | 只读准入 Gate |
| `services/quant-api/app/signal/stage9_wechat.py` | preview / dry-run adapter |
| `services/quant-api/app/signal/stage9_wechat_delivery.py` | 受控发送 / 通知记录 / 重试 |
| `services/quant-api/app/signal/stage9_jm_v1b_replay.py` | 历史回放 event 生成 |
| `scripts/stage9_wechat_send_once.py` | 受控发送 CLI |
| `scripts/stage9_jm_v1b_replay_event_once.py` | 历史回放 CLI |
| `services/quant-api/alembic/versions/20260708_0018_stage9_wechat_notifications.py` | DB migration |
| `services/quant-api/tests/test_stage9_signal_event_gate.py` | Gate 测试 |
| `services/quant-api/tests/test_stage9_wechat_adapter.py` | preview adapter 测试 |
| `services/quant-api/tests/test_stage9_wechat_delivery.py` | 发送 / 重试测试 |
| `services/quant-api/tests/test_stage9_jm_v1b_replay.py` | 历史回放测试 |

## 11. 未完成

- 企业微信真实发送 worker / scheduler / 批量重试。
- 前向实时 eligible event 生成（当前只有历史回放）。
- retry-pending 自动重试 worker。
- 通知发送频率限制和静默时段。
