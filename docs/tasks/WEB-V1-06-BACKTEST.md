# WEB-V1-06：回测中心研究边界（关键）

```text
WEB_BACKTEST_REPORT_CLOSED_LOOP_READY
WEB_BACKTEST_FORMAL_RESEARCH_BOUNDARY_READY
```

## 裁定

- 通用表单默认留空；去掉 `rb2405` 等 formal 暗示
- 任意通用提交为 research-only；JM 固定任务为 formal-research 历史回测
- Indicator Policy / trust / audit 字段仅审计展示，不作策略有效证明
- 批量入口弱化并标 Legacy（见 WEB-V1-07）

## 修改

- `apps/quant-web/src/pages/backtest/index.vue`
- `apps/quant-web/src/components/backtest/JmV1bQuickTasks.vue`
