---
name: ui-bugfix
description: 前端 Bug 快速修复技能 — 高优先级 UI/UX 问题定位与修复。
agent_created: false
tags: [bugfix, frontend, react, urgent]
---

# ui-bugfix 技能

## 适用场景
- P0/P1 前端 Bug 紧急修复
- 图表渲染异常
- 数据展示错误
- WebSocket 连接问题
- 样式/布局异常

## 修复流程
1. **复现**：确认 Bug 能稳定复现
2. **定位**：通过 Console / React DevTools 找到根因
3. **修复**：最小变更原则，不引入新问题
4. **验证**：确认修复有效 + 无回归
5. **记录**：更新任务文件

## 常见 Bug 类型

### 图表不渲染
- 检查数据格式是否符合 ECharts/TradingView 要求
- 检查容器尺寸是否为 0

### WebSocket 断连
- 检查重连逻辑是否有 exponential backoff
- 检查组件卸载时是否清理了 WebSocket

### 数值显示异常
- 检查是否有精度丢失（浮点数）
- 检查涨跌颜色逻辑（红涨绿跌）

### 接口请求失败
- 检查 VITE_API_BASE_URL 环境变量
- 检查 CORS 配置
- 检查 JWT Token 是否过期

## Bug 报告模板
参考 `prompts/workbuddy-bugfix.md`
