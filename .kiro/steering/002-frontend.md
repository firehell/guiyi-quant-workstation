---
inclusion: fileMatch
fileMatchPattern: ['apps/**/*.{ts,tsx,vue,css}', 'apps/**/*.json']
---

# 前端开发规范
---
description: 前端开发规则
globs:
  - "apps/quant-web/**/*"
alwaysApply: false
---

前端规则：
- 使用 Vue 3 + Vite + TypeScript。
- UI 优先使用 Naive UI。
- 图表使用 Lightweight Charts 和 ECharts。
- 页面风格为深色本地量化工作台。
- 不要使用 Next.js。
- 前端不要直接读取数据库和数据源。
- 前端只通过 REST API / WebSocket 与后端通信。
