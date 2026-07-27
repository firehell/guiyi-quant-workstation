# WEB-V1-13 W13-05 研究上下文往返 Receipt

更新时间：2026-07-22

## 结论

`REPORT_TRADE_CHART_REVIEW_ROUNDTRIP_READY`

`SIGNAL_EVENT_CHART_REVIEW_ROUNDTRIP_READY`

`WEB_RESEARCH_CONTEXT_RETURN_READY`

以上结论限于候选代码、定向 API 测试和 mock browser 只读验收；真实数据库关联样本仍由 W13-07 单独验收。

## 实现边界

- 新增 `GET /api/signals/events/{event_id}`，按主键只读恢复 SignalEvent；不存在返回 404。
- Review 列表新增兼容式 `source_id` 精确过滤，并可与 `source_type` 联合使用；无 migration、无模型变化。
- `researchNavigation.ts` 统一 report、trade、signal、event、chart、review 的 query 构建与解析，并拒绝外站 `return_route`。
- Market 在 URL 状态同步时保留 `signal_id`、`signal_event_id`、`return_route`，并拒绝把 historical event 混入 live 或反向混用。
- Signal/Backtest 来源页将选中上下文写入 URL，将滚动位置放入 `history.state`。
- Review 页按来源 ID 只读查询：没有 ReviewNote 时展示真实 SignalEvent 与“尚无复盘”；仅点击“创建复盘”才调用既有 POST。
- 已存在的回测 Review 只读打开，不再为了查看而重复 POST。

## 测试证据

```text
npm test
117 passed / 0 failed / 1 skipped

npm run build
passed

npm run test:e2e
13 passed / 0 failed

PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_signal_events.py::test_signal_scan_writes_created_event_once_and_exposes_event_api \
  services/quant-api/tests/test_review_center_api.py::test_list_reviews_filters_exact_source_type_and_source_id
2 passed

PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api ruff check \
  services/quant-api/app/api/signals.py services/quant-api/app/api/reviews.py \
  services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_review_center_api.py
passed

git diff --check
passed
```

浏览器覆盖 report→trade→chart→review→report 与 event→chart→review→event；event 链覆盖刷新、back、forward、缺失 ReviewNote 降级，并对 POST/PUT/PATCH/DELETE 做零请求断言。

## 未扩大范围

- 未修改 SignalEvent 生成、通知发送、策略、回测口径、Profile binding、行情资产或 Runtime Gate。
- 未执行真实数据写入、migration、worker、scheduler、push、merge 或 deploy。
