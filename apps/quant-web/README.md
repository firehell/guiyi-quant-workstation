# Vue quant-web

归一量化前端。技术栈：Vue 3 / Vite / TypeScript / Naive UI / Lightweight Charts。

## Current surface

- 路由仅 Market：`/` → `/market`（列表）与 `/market/chart`（K 线）。
- 展示 60 活动品种的 Canonical 历史行情；主图 EMA10/21/60、火天大有、副图 MACD。
- 行情页无「浏览 / 严格研究」切换 UI；无 Live 模式；无 signal/strategy/review/dashboard/settings 入口。

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

产品与数据边界以仓库根 `STATUS.md`、`docs/ARCHITECTURE.md` 为准。
