# Vue quant-web

归一量化前端。技术栈：Vue 3 / Vite / TypeScript / Naive UI / Lightweight Charts。

## Current surface

- 路由只保留 Market（`/` → `/market`、`/market/chart`）。
- 展示60个 active 历史研究品种的当前 rank1 映射，并读取 Canonical K 线。
- active 60 的当日 rank1 completed 1m 可通过 Historical/Live seam 增量观察；continuous、非 rank1
  contract、日线和周线保持 Historical-only。
- 图表已挂载 K 线、成交量、OI、EMA/MACD、HTDY 观察、SuBing Factor/Signal 观察与
  Alert V2 Scope/Event 上下文；`图表设置`保留可选 EMA、SuBing internal-process 与合约控制。
- 无通用 signal/strategy、Execution Review、RQAlpha、dashboard/settings 入口。

## B1 决策漏斗

日常路径固定为：Market 首页先看苏冰正式事件与每日观察，再进入品种详情；详情检查栏保持
`当前观察 → 市场背景 → 数据详情` 三段。正式 Event、研究观察与 Research-only 事实保持分层；该流程不产生综合分、推荐、winner 或交易指令。

## 不做

- 自动交易、登录多用户、直接连库。
- 恢复已卸 Web 模块或 backtest 页面。

## 本地

```bash
pnpm --dir apps/quant-web install
pnpm --dir apps/quant-web dev
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

稳定产品边界看仓库根 `PROJECT_SOURCE.md`，当前 release/Runtime/Gate 看 `STATUS.md`，模块依赖看
`docs/ARCHITECTURE.md`。
