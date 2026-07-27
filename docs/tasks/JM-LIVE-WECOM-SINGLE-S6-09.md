# HTDY 指定事件单条企业微信 Gate（S6-09）

更新时间：2026-07-28

## 状态

```text
LIVE_WECOM_SINGLE_SEND_PASSED
REAL_SEND_COMPLETED
GUIYI_WECHAT_AUTOSEND_ENABLED=false
```

## 目标

在 HTDY S6-08 schema-v3 receipt 通过后，只选择一个未通知的 exact HTDY
`signal_created` event，复用既有 `SignalNotification` 和 Stage 9 delivery 完成一次企业微信观察提醒。

## 硬前置

- S6-08 schema-v3 receipt/hash 验证通过；
- event 精确匹配 `htdy_original_realtime_first_seen/v1.0`、
  `live_realtime_repainting` 和 `htdy_original_xma_15m_first_seen_v1`；
- event 未存在 sent notification；
- SignalEvent flag=false、packet/hash 为空；
- autosend=false；
- Runtime/live/EOD health fresh/ok。

## 合同

- S6-09 packet 绑定一个 `event_id`、event hash、signal_id、S6-08 receipt/hash、
  Runtime/DB identity、notification baseline、dedupe key 和 forbidden counters。
- webhook 只记录 present，不记录值；日志、DB、receipt 不含 secret。
- 最大尝试次数 3；成功后重复执行为零发送。
- 不允许改用另一个 event 绕过去重或失败边界。
- Web、API、PostgreSQL `SignalNotification` 与企业微信送达结果必须四方一致。
- 消息必须显示方向、JM 实际合约、15m、观察桶、首次检测时间、首次检测价格、
  `observed_bar_close`、partial/confirmed，以及 XMA 未来函数、可能重绘、首次检测后不撤回、
  仅供观察、不是交易指令、不自动下单。
- 长期 worker autosend 始终保持关闭。

## 实现入口

```text
services/quant-api/app/services/htdy_s6_09_wecom_gate.py
scripts/jm_htdy_s6_09_wecom_gate.py
```

CLI 只允许以下三个互斥模式：

- `--prepare`：只读采集当前事实并 create-only 生成授权包；
- `--verify`：重新采集事实并验证包/hash，不发送、不写数据库；
- `--execute`：必须同时提供用户精确批准的 packet hash；只允许绑定
  `SignalEvent.id=4` 的一次性投递和 15 分钟内最多三次可重试错误尝试。

可重试错误仅限 timeout、HTTP 408/429 和 5xx；其他失败立即关闭该次投递。
成功后同一 dedupe key 不再调用 HTTP。每次真实尝试和 final receipt 均为 create-only
证据。默认 Stage 9、worker 和 `retry_pending_notifications()` 不携带 S6-09
authorization，因此 HTDY 仍 fail-closed。

S6-09 不修改 Runtime env、launchd、SignalEvent flag、autosend、StrategySignal、
SignalEvent、Review、EOD、Profile、订单或交易路径。

## Approval B

只有完成 fake HTTP、retry、幂等、敏感模式、old-source/historical-replay rejection、
S6-08 receipt drift 和 event substitution rejection 测试，且真实 packet 生成并验证后，
才请求一次：

```text
event_id + exact S6-09 packet hash + one real send
```

Approval B 之前，本文件不构成发送批准。

## 真实验收结果

用户于 `2026-07-27` 精确批准：

```text
event_id=4
packet=46d7c1317e1e83205cf1ef4b8516af9a2a30e354f69799cbf8ff6d18f913ee5b
one_real_send=true
```

Gate 在执行前重新验证 packet、event、Runtime、DB、S6-08 receipt、flags、
health、webhook 存在性和通知基线。真实结果：

```text
SignalEvent.id=4
StrategySignal.id=6
SignalNotification.id=2
status=sent
attempt_count=1
max_attempts=3
response_status_code=200
dedupe_key=enterprise_wechat:signal_event:4
```

同一 packet 的紧接幂等探测仍返回 `sent / attempt_count=1`，未发生第二次 HTTP
请求。最终 receipt：

```text
data/reports/jm_live_wecom_single_s6_09/
20260728-event4-47819f4f/final_receipt.json
receipt_hash=2d92fb7070496b8ff7c6246a394558fc0e6843e3ceb828ab74add991b329676c
```

本结果只证明指定 HTDY 观察事件完成一次有界企业微信接口投递。它不证明人工端已阅读、
策略有效或盈利，也不授权 autosend、其他事件、长期通知、交易或自动下单。
