---
name: market-kline-workbench
description: 当任务涉及 Market K线工作台、Lightweight Charts、指标叠加、Historical/Live seam 或多周期展示时使用。
---

# Market Kline Workbench Skill

## 页面定位

当前 K 线工作台是 Market 行情研究页，核心任务是可信地查看 60 品种的历史 Canonical、真实主力/主连、
七周期和盘中 Live Overlay。它不包含回测成交、Signal/Review 或下单语义。

## V1 布局

- 首页：先看“需要处理”，再从 `0..3` 个“优先检查”进入品种详情；Radar `degraded` 时 fail-closed，
  不输出优先检查。
- 左侧：60 品种池、合约/真实主力/主连与周期选择。
- 中间：K 线主图、现有 Indicator Registry overlay、成交量与 MACD。
- 右侧“当前检查栏”：固定按 `现在 → 市场背景 → 当前观察 → 位置/参与 → 提醒 → 更多研究`
  验证，正式 Event、研究观察与 Research-only 事实不得互相替代。
- 底部：按当前 Workspace 设计承载只读指标值与研究信息，不恢复已退役交易/信号表面。

## 组件建议

- 现有图表权威组件：`apps/quant-web/src/components/kline/KlineChart.vue`。
- 新 Workspace 组件按当前 design/plan 分层；新增前先检索现有组件，不创建重复 toolbar、indicator layer
  或第二套行情状态管理。

## 禁止

- 不要第一版做完整 TradingView。
- 不要第一版做复杂画线系统。
- 不要前端直接连接数据库。
- 不要在前端自判主力、选择 Canonical 文件或复制后端核心指标算法。
- 不要把 Redis Live 写入或提升为 Historical Canonical。

## 验证

- K 线容器尺寸非 0。
- fixture K 线、EMA、Volume/MACD 能渲染。
- Historical/Live seam、generation token、重连与向左分页行为保持稳定。
- 浏览器 console 无相关错误。
