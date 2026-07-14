# Signal And Notification

更新时间：2026-07-14

事实来源：`docs/SIGNAL_EVENTS.md`

当前状态：current，live-confirmed 和长期发送 Gate pending。

## 当前能力

- `strategy_signals` 保存最新信号快照。
- `signal_events` append-only 记录正式信号事件。
- Stage 9 Gate 校验真实合约、bar、trigger price、provider/data_role/quality_status、观察提醒语义和脱敏。
- Stage 9-A preview / dry-run 不读取 webhook、不发送、不写通知记录。
- Stage 9-B1 具备受控发送记录和重试框架。
- Stage 9-B2 historical replay single-send smoke 已通过。

## 边界

- Historical replay smoke 不是 live-confirmed smoke。
- 单次发送不是长期 worker/scheduler 运行能力。
- 企业微信只做观察提醒，不生成订单草稿，不自动下单。
- webhook 只允许从环境变量读取，不写入仓库、日志或文档。

## 未完成 Gate

- live-confirmed event single-send smoke。
- notification worker / scheduler 长期运行。
- 5 个交易日长稳和故障恢复。

