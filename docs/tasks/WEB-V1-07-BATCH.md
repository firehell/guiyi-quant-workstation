# WEB-V1-07：批量回测裁定

```text
BATCH_BACKTEST_RESEARCH_ONLY
```

## 裁定（代码证据）

- `services/quant-api/app/services/batch_backtest.py` 使用 `run_su_bing_backtest` + suitability 标签 + 参数模板网格
- 虽有 Profile binding（`passed_only`，见 `test_batch_task_freezes_all_assets...`），但入口目标是品种适配研究，不是 JM V1-B formal validation 闭环
- **不满足** `BATCH_BACKTEST_FORMAL_READY`

## 前端收口

- 默认 `canStartBatch=false`；显示缺失 Gate 与 `BATCH_BACKTEST_RESEARCH_ONLY`
- 保留历史任务/报告查询 UI
- 主回测页入口标 Legacy

## 修改

- `apps/quant-web/src/pages/backtest/batch.vue`
- `apps/quant-web/src/pages/backtest/index.vue`（Legacy 入口）
