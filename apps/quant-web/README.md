# Vue quant-web

归一量化前端。技术栈：Vue 3 / Vite / TypeScript / Naive UI / Lightweight Charts。

## Current surface

- 路由仅 Market：`/` → `/market`（列表）与 `/market/chart`（K 线）。
- 展示60个 active 历史研究品种的当前 rank1 映射，并读取 Canonical K 线。
- `j/jm/ap/ag` 的当日 rank1 completed 1m 可通过 Historical/Live seam 增量观察；continuous、非 rank1
  contract、日线和周线保持 Historical-only。
- 当前图表只渲染 K 线与成交量。EMA/HTDY/MACD 仍是测试通过的 Web 观察镜像，尚未挂载到页面。
- 无「浏览 / 严格研究」切换，也没有 signal/strategy/review/dashboard/settings 入口。

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
