---
name: quant-frontend
description: 当任务涉及归一量化前端、Vue 3、Vite、TypeScript、Naive UI、K线图、深色量化工作台时使用。
---

# 归一量化前端开发 Skill

## 技术栈

- Vue 3
- Vite
- TypeScript
- Naive UI
- Pinia
- Vue Router
- Axios
- Lightweight Charts

## Current surface

仅 Market 工作台：`/` → `/market` 与 `/market/chart`。展示 Canonical 历史行情与 EMA/HTDY/MACD。

已卸（勿当现行页面）：Dashboard、数据中心、策略中心、回测任务/报告、信号扫描、复盘中心、系统设置、Live 模式。

## 规则

- 不使用 Next.js。
- 不做登录和多用户权限。
- 前端不直接连接数据库；数据经 FastAPI。
- 核心策略计算不写在前端；展示计算须标注非 StrategySignal。
- DataGap fail-closed，不暗示可回退 legacy。
- 页面风格是深色本地量化工作台，优先清晰、可扫描。
- 产品面以 `STATUS.md` / `apps/quant-web/README.md` 为准。
- 每次修改后给出运行命令和测试方法。
