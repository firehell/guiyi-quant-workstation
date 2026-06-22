---
name: quant-frontend
description: 当任务涉及归一量化前端、Vue 3、Vite、TypeScript、Naive UI、K线图、回测报告、深色量化工作台时使用。
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
- ECharts

## 页面模块

V1 优先：Dashboard、数据中心、合约/品种池、K线工作台、策略中心、回测任务、回测报告、信号扫描、复盘中心、系统设置。

## 规则

- 不使用 Next.js。
- 不做登录和多用户权限。
- 先使用 mock 数据。
- 前端不直接连接数据库。
- 所有数据通过 FastAPI。
- 核心回测、风控、策略计算不写在前端。
- 页面风格是深色本地量化工作台，优先清晰、密集、可扫描。
- 每次修改后给出运行命令和测试方法。

## 页面要求

- K 线页使用 Lightweight Charts，回测统计使用 ECharts。
- 数据表、任务状态、空状态、错误状态要完整。
- 任务进度和信号推送预留 WebSocket。
- 页面先服务研究闭环，不做炫酷大屏。

## 验证

- `pnpm build`
- 本地打开 `http://127.0.0.1:5173`
- 浏览器 console 无相关 error/warn。
