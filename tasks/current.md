# 当前任务：WEB-VISUAL-REFACTOR-V1B

生成时间：2026-07-10

任务单：`docs/tasks/TASK-2026-07-10-004-web-visual-refactor-v1b.md`

分支：`codex/web-visual-refactor-v1b`

代码基线：`a7df3aaca38d7f66445102538c1ae3ddfc0e4a17`

状态：`DELIVERY_READY`

## 目标

在不修改 API、数据链路、策略、回测口径或写入边界的前提下，将 V1-B Web 升级为“克制科技感的桌面量化研究工作站”。

## 已完成

- [x] 建立 Primitive / Semantic / Component / Compatibility tokens。
- [x] 重构 Naive UI 暗色主题、图表主题桥接和全局可访问性样式。
- [x] 侧栏四分组、本地 SVG 图标、Header 边界徽章、快捷入口和本地时钟。
- [x] `PageShell` / `StatusTag` / `EmptyState` 增强，新增 `BoundaryBadge` / `DirectionTag` / `MetricCard` / `UiIcon`。
- [x] Dashboard、Signal、Market Chart 信息架构与 1440/1280/1024 响应式升级。
- [x] Backtest、Review、Market、Data、Runtime、Strategy、Settings、Batch Backtest 视觉语义迁移。
- [x] 三份 mockup 标记为“视觉参考 / 示例数据”，不作为生产源码。
- [x] 11 个路由完成真实 API 只读浏览器 smoke。
- [x] Post-fix：K 线工作台主图与副图十字星竖线联动，主图 hover 时竖线贯穿主图和 MACD/ATR 副图区域。

## 硬边界

- 不修改 FastAPI、PostgreSQL、Alembic、Parquet、DuckDB 或 active 数据入口。
- 不修改策略信号、回测、成交、成本、风控计算。
- 不执行信号扫描、回测、复盘写入、企业微信发送或任何交易动作。
- `research_only` schema/API 历史语义不在本任务修改；Header 使用独立边界文案。

## 验收证据

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
```

- Node tests：27 passed。
- Vite production build：passed；仍有既有约 651 kB chunk warning。
- Playwright：11 路由、0 console error / 0 warning。
- K 线：1440×900、1280×800、1024×768 均无整页横向溢出，21 个 canvas 正常创建。
- K 线 post-fix：`/market/chart?symbol=jm&contract=JM2609&period=15m` 在 1440×900 下主图 hover 后 `.linked-crosshair` 覆盖主图 top 到 MACD bottom，console 0 error / 0 warning。
- 截图：`output/playwright/web-refactor-*.png`。
- Post-fix 截图：`output/playwright/kline-linked-crosshair-v1b.png`。

## 遗留项

1. 视觉风格仍需用户最终主观验收。
2. 约 651 kB 公共 chunk 拆包属独立性能任务，本轮未扩大依赖或调整构建策略。
3. 真实公网、macOS LaunchAgent 外接卷权限、全品种 8 个 pending 和样本外验证仍是独立 Gate。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-10-004-web-visual-refactor-v1b.md`
- `workstation/team/UX_VISUAL_SPEC.md`
- `apps/quant-web/src/layouts/MainLayout.vue`
- `apps/quant-web/src/styles/tokens.css`
- `apps/quant-web/src/styles/theme.ts`
- `output/playwright/web-refactor-*.png`
