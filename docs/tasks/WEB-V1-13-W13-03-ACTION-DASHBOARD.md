# WEB-V1-13 W13-03 行动型今日工作台验收

日期：2026-07-22

状态：`WEB_ACTION_DASHBOARD_READY`

## 只读 API 补差

`GET /api/dashboard/summary` 保持原字段兼容，并增加：

- `latest_data_time`：active 候选 provider、primary、非 failed 资产的最大 end_time。
- `latest_confirmed_bar_time`：live ingest/aggregation checkpoint 的最大 confirmed/aggregated bar 时间。
- `latest_live_signal_event`：仅返回 `source_mode=live_confirmed` 的最近事件。
- `latest_review`：最近 ReviewNote 摘要。
- `unfinished_review_count`：lesson 尚未填写的 ReviewNote 数量。

未新增 migration、模型字段、写请求或业务写入。

## 行动规则

`dashboardAction.ts` 按以下顺序生成动作：

1. Runtime/EOD 明确 `failed/blocked`；
2. 数据明确 `failed/blocked`；
3. `source_mode=live_confirmed && lifecycle_status=new`；
4. 待复盘，否则最近报告；
5. JM 15m 固定快捷入口。

`unknown` 不升级为失败；historical replay 不参与 live 优先级。JM 入口固定为 `symbol=jm&period=15m&contract_view=actual&data_mode=historical`，仍由 Market 的 Profile/quality 规则 fail-closed。

## 验收证据

- Dashboard API 定向 pytest：2 passed。
- Dashboard action unit：3 passed。
- Web unit：111 passed / 1 skipped / 0 failed。
- Web build：passed。
- mock E2E：11 passed；JM 15m query 已核对。

Gate：

```text
WEB_ACTION_DASHBOARD_READY
WEB_PRIMARY_WORKFLOW_READY
WEB_JM_QUICK_ENTRY_READY
```
