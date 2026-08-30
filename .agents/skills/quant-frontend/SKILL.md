---
name: quant-frontend
description: Use when 任务涉及归一量化 Vue 3、Vite、TypeScript、Naive UI、Market K线、Lightweight Charts、WebSocket、布局、浏览器错误或前端测试。
---

# 归一量化前端与 K 线工作台

用于 Vue 3、Vite、TypeScript、Naive UI、Market 图表、WebSocket、布局或前端测试任务。

先读 `AGENTS.md`、`PROJECT_SOURCE.md`、`docs/ARCHITECTURE.md`、`STATUS.md` 和相关 Market API contract。
前端实现位于 `apps/quant-web/src/`；图表与浏览器问题先在真实路径留下 viewport、Console、Network/WS
证据，再定位责任边界。

验证命令以 `TESTING.md` 为准：先运行覆盖改动的 unit 或 Playwright 场景，再按风险扩展完整 Web unit、E2E
与 build。
