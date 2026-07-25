# HTDY Original Repainting Realtime Alert

状态：`CODE_COMPLETE_EXTERNAL_GATE_PENDING`

## 范围

- JM 当前实际主力。
- confirmed/passed 15m bar。
- 通达信原版 XMA 子集：ZK1/ZD1/ZD2、黄K/白K与新出现的三连买多/卖空观察。
- 独立 `htdy_observation_alerts`、只读 API/Web、可选专用企业微信观察提醒。
- 未来函数与重绘是显式接受的观察语义；首次预警后不撤回、不更正，同一 bar 后续 revision 不重复。

## 禁止

- 不写 `strategy_signals` / `signal_events`。
- 不进入回测、订单或交易。
- 不改变阶段 5 HTDY rejected 结论。
- 不复用 S6-08/T5 或 T6 的 packet/hash。
- 不在 `LIVE_SIGNAL_EVENT_GATE_PASSED` 前部署、启用或真实发送。

## 运行 Gate

```text
GUIYI_HTDY_REALTIME_ALERTS_ENABLED
GUIYI_HTDY_WECOM_AUTOSEND_ENABLED
GUIYI_HTDY_REALTIME_ALERTS_APPROVAL_PACKET
GUIYI_HTDY_REALTIME_ALERTS_APPROVAL_HASH
```

生成器：

```bash
services/quant-api/.venv/bin/python scripts/engineering/htdy-realtime-alert-gate.py generate \
  --s6-08-receipt <LIVE_SIGNAL_EVENT_GATE_PASSED receipt> \
  --output <create-only packet path> \
  --enable-wechat
```

packet 绑定 Runtime commit、indicator source SHA、S6-08 receipt SHA、JM/15m/confirmed-only、未来函数/重绘确认以及企业微信开关范围，不含 webhook 或 secret。

## 外部验收

1. S6-08 已发布 `LIVE_SIGNAL_EVENT_GATE_PASSED` receipt。
2. 生成 packet 并取得其精确 hash 批准。
3. 仅启用两个 HTDY 专用开关并重启 live scheduler/notification worker。
   `GUIYI_LIVE_SIGNAL_EVENTS_ENABLED` 与 `GUIYI_WECHAT_AUTOSEND_ENABLED` 必须保持关闭，禁止把正式 T5/T6 与重绘观察链路混跑。
4. 自然出现一条真实 HTDY observation alert，Web/API 可回读。
5. 同 bar 后续周期/revision 不新增、不重发。
6. 若启用企微，仅发送该独立观察提醒；内容明确未来函数、可能重绘、不是交易指令、不自动下单。
7. SignalEvent、订单、交易及其他禁写表零漂移，日志敏感模式命中 0。
8. 关闭专用开关、清空授权并保存 fresh health。
