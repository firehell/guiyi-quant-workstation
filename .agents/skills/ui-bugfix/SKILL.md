---
name: ui-bugfix
description: 当任务涉及归一量化 Vue/Naive UI 页面截图可见问题、布局错位、图表不渲染、控制台报错、WebSocket 前端异常时使用。
---

# UI Bugfix Skill

## 适用场景

- P0/P1 前端 Bug 紧急修复。
- 图表渲染异常。
- 数据展示错误。
- WebSocket 连接问题。
- 样式/布局异常。

## 修复流程

1. 复现：确认 Bug 能稳定复现。
2. 定位：通过浏览器 Console、Vue 组件状态、网络请求找到根因。
3. 修复：最小变更原则，不引入新问题。
4. 验证：确认修复有效 + 无回归。
5. 记录：说明改了哪些文件和刷新后效果。

## 常见问题

- 图表不渲染：检查数据格式、容器尺寸、初始化时机。
- WebSocket 断连：检查重连、清理、重复连接。
- 数值显示异常：检查精度、涨跌颜色、单位。
- 接口失败：检查 `VITE_API_BASE_URL`、CORS、错误态展示。

## 边界

- 只修截图或复现路径可见问题。
- 不重构业务逻辑。
- 不改策略、回测、风控核心。
- 修复后至少按 `TESTING.md` 跑 `pnpm --dir apps/quant-web test` 与 `pnpm --dir apps/quant-web build`，
  必要时浏览器验证。
