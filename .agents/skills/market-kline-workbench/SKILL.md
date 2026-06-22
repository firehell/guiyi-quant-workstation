---
name: market-kline-workbench
description: 当任务涉及 K线工作台、Lightweight Charts、指标叠加、买卖点 marker、回测成交点、信号解释面板、多周期展示时使用。
---

# Market Kline Workbench Skill

## 页面定位

K 线工作台服务复盘和信号验证，不是普通行情页。核心问题是“这笔交易为什么该做或不该做”。

## V1 布局

- 左侧：品种池、合约列表、周期选择、策略过滤。
- 中间：K 线主图、EMA21/MA/ATR、信号 marker、成交点。
- 右侧：趋势状态、信号解释、风控计算、策略参数。
- 底部：交易明细、信号列表、指标值、复盘标签。

## 组件建议

- `KlineChart.vue`
- `IndicatorLayer.vue`
- `SignalMarkerLayer.vue`
- `TradeMarkerLayer.vue`
- `PositionLineLayer.vue`
- `KlineToolbar.vue`

## 禁止

- 不要第一版做完整 TradingView。
- 不要第一版做复杂画线系统。
- 不要前端直接连接数据库。
- 不要在前端计算核心回测结果。

## 验证

- K 线容器尺寸非 0。
- mock K 线、EMA、买卖点能渲染。
- 浏览器 console 无相关错误。
