# HTDY 指定事件单条企业微信 Gate（S6-09）

更新时间：2026-07-26

## 状态

```text
CONTRACT_SKELETON_FROZEN
IMPLEMENTATION_NOT_STARTED
REAL_SEND_NOT_AUTHORIZED
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

## Approval B

只有完成 fake HTTP、retry、幂等、敏感模式、old-source/historical-replay rejection、
S6-08 receipt drift 和 event substitution rejection 测试，且真实 packet 生成并验证后，
才请求一次：

```text
event_id + exact S6-09 packet hash + one real send
```

本文件不构成发送批准，不发布 `LIVE_WECOM_SINGLE_SEND_PASSED`。
