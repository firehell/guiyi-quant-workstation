# WEB-V1-13 W13-04 Market 研究工作台验收

日期：2026-07-22

状态：`MARKET_RESEARCH_WORKSPACE_READY`

## 实现

- 从单体 chart 页面提取 `MarketContextBar.vue`、`MarketEvidenceStrip.vue`、`MarketRightRail.vue`。
- 删除旧 `MarketStrategySidebar.vue`，右栏收口为四个原生可访问 Tab：策略、信号、复盘、运行。
- 策略 Tab 保留指标/observation-only 边界；FuturesResearch 与固定参数计算器下沉到折叠实验工具，并明确“非正式风控”。
- 信号 Tab 集中 StrategySignal、SignalEvent 与通知只读状态。
- 复盘 Tab 集中 report/trade/Review 上下文；无 report/trade 时不伪造关联。
- 运行 Tab 集中 LiveTarget、Live 质量与 Runtime observation。
- 手动 Tab 偏好只写 `gy.market.rightRailTab`；signal/event deep-link 自动开信号，report/trade deep-link 自动开复盘。
- JM 快捷入口缺少 contract query 时，复用既有 dominant resolver 解析实际主力；不新建合约选择逻辑。

## 不变边界

未修改 Market API、`MAX_BARS_PER_REQUEST`、viewport、Profile fail-closed、lineage、HTDY/EMA 语义、marker 生成或 Live 20 秒刷新逻辑。

## 验收证据

- right-rail unit：3 passed。
- mock E2E：11 passed；四 Tab 可见；切换 Tab 不增加 bars/indicators 请求；signal/review 自动选择通过。
- Web build：passed。
- 视觉截图：`output/playwright/w13-04-market-workspace.png`。

Gate：

```text
MARKET_RESEARCH_WORKSPACE_READY
MARKET_CONTEXT_EVIDENCE_SEPARATED
MARKET_RIGHT_RAIL_TABBED_READY
NO_MARKET_SEMANTIC_REGRESSION
```
