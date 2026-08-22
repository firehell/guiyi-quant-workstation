# Vue quant-web

归一量化前端。技术栈：Vue 3 / Vite / TypeScript / Naive UI / Lightweight Charts。

## Current surface

- 路由为 Market（`/` → `/market`、`/market/chart`）与 Execution Review（`/trade-records`）。
- 展示60个 active 历史研究品种的当前 rank1 映射，并读取 Canonical K 线。
- active 60 的当日 rank1 completed 1m 可通过 Historical/Live seam 增量观察；continuous、非 rank1
  contract、日线和周线保持 Historical-only。
- 图表已挂载 K 线、成交量、OI、EMA/MACD、HTDY 观察、SuBing Factor/Signal 观察与
  Alert V2 Scope/Event 上下文；Web 计算仍只是展示镜像。
- `/trade-records` 提供四状态人工处理、真实执行时间线、复盘重建、trusted-partial 人民币估算与轻量统计；缺失 multiplier 时明确显示人民币估算不可用。
- 无通用 signal/strategy、旧 review center、dashboard/settings 入口。

## B1 决策漏斗

日常路径固定为：Market 首页先看“需要处理”，再从 `0..3` 个“优先检查”进入品种详情；详情页按
“当前检查栏”的 `现在 → 市场背景 → 当前观察 → 位置/参与 → 提醒 → 更多研究` 顺序完成验证。
`degraded` Radar 不输出优先检查，正式 Event、研究观察与 Research-only 事实保持分层；该流程不产生
综合分、推荐、winner 或交易指令。

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
