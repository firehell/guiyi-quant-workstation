# WEB-V1-08：信号页 source_mode 与时间线

```text
WEB_SIGNAL_EVENT_TIMELINE_READY
NO_HISTORICAL_LIVE_CONFUSION
```

## 裁定

- 主层级：Latest / Event timeline / Notification Preview
- 扫描配置默认折叠（次级）
- 强分 `source_mode`：`historical_scan` / `jm_v1b_scan` / `jm_v1b_historical_replay` / `live_confirmed` / `manual_api`
- replay 标「测试/回放」；JM 扫描改「历史研究扫描」
- 无真实发送按钮；Stage9 仅 Preview（would_send=false）

## 修改

- `apps/quant-web/src/pages/signal/index.vue`
- `apps/quant-web/src/components/signal/SignalEventsPanel.vue`
- `apps/quant-web/src/utils/signalSourceMode.ts`
