# Newow 牛哇趋势策略 V1 Implementation Plan

日期：2026-09-01  
状态：`SUPERSEDED / DO_NOT_EXECUTE / REWRITE_REQUIRED`  

> 本文件原实施计划已被最新版 `docs/tasks/2026-09-01-newow-trend-v1-design.md` 完整取代。旧计划混入了 Phase Lite、Structure Lite、Lux Range、active60、Shadow、Alert 和非主图能力，不再符合当前 V1 范围，因此不得据此启动源码任务。

当前唯一有效范围是：

```text
牛哇版本 · 趋势策略 · completed D1 详情页
├── 牛哇黄蓝趋势带
├── 建仓 / 持有 / 清仓 / 空仓
├── D1 / D2 / D3 逃顶
├── 杯柄 Setup
├── 日K + 成交量主图
├── 指标解读与历史标记
└── 当前版本 / 牛哇版本切换
```

当前明确不实施：

```text
底部三个副图
目标价 / 吸筹价 / 点阵
综合决策和仓位建议
牛哇震荡策略
其他形态
active60 / Shadow / PushPlus / Runtime
账户、订单、仓位或真实盈亏
```

后续必须在用户批准最新版 Spec 后，重新编写新的 Implementation Plan。旧任务拆分仅从 Git history 追溯，不作为 active 执行依据。
