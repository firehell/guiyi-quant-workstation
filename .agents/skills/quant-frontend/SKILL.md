---
name: quant-frontend
description: 当任务涉及归一量化前端、Vue 3、Vite、TypeScript、Naive UI、K线图或 Market 工作台时使用。
---

# 归一量化前端开发 Skill

## 技术栈

- Vue 3
- Vite
- TypeScript
- Naive UI
- Vue Router
- Axios
- Lightweight Charts

## Current surface

当前 Web 包含 Market 工作台（`/` → `/market` 与 `/market/chart`）和独立 Execution Review
（`/trade-records`）。Market 展示 Canonical 历史行情、EMA/HTDY/MACD、SuBing
current-rank1-segment-local Factor/Signal observation、server-side Alert Scope 与 persistent Event 铃铛，
并在允许的 series/phase 上叠加 Redis Live observation；Execution Review 只记录人工事实与复盘。

已卸（勿当现行页面）：Dashboard、数据中心、策略中心、回测任务/报告、旧信号扫描、旧 Review Center、系统设置。

## 规则

- 不使用 Next.js。
- 不做登录和多用户权限。
- 前端不直接连接数据库；数据经 FastAPI。
- 核心策略计算不写在前端；展示计算须标注非 StrategySignal。
- Alert Scope 只认 server API，不能以 localStorage 自选替代；persistent Event marker 与会重绘的当前
  HTDY marker 必须独立、按 bar time 稳定排序。
- SuBing 页面状态放入专用 composable，但行情 identity、Historical/Live seam 和 segment 裁剪仍只复用
  既有 Market contracts，不另建前端行情 resolver。
- DataGap fail-closed，不暗示可回退 legacy。
- 页面使用深蓝品牌 Shell + 浅色研究工作区，优先清晰、可扫描。
- 产品面以 `STATUS.md` / `apps/quant-web/README.md` 为准。
- 每次修改后给出运行命令和测试方法。
