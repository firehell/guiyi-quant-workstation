---
name: project-governor
description: 当任务涉及归一量化功能取舍、阶段归属、优先级、是否过度设计、是否偏离 V0/V1 研究闭环时使用。
---

# Project Governor Skill

## 判断原则

当前 v1.0.0 只封板可信 Canonical 60 品种、Market Web/API、data/runtime CLI 和有界 Market
Runtime。任何功能先判断是否加强这条行情研究底座；策略、回测、Signal/Review 都是未来新任务，
不得因历史文件或旧阶段名称恢复为当前兼容面。

## 阶段口径

- v1.0.0：RQData → Canonical/Catalog → MarketDataService → Market Web/API；60 品种 Live observation
  与 17:00 盘后增量更新保持有界、可恢复、无订单。
- 下一阶段：Market Radar / Product Workspace，只读复用现有行情与指标入口。
- 未来研究阶段：按新合同重建策略、回测、OOS/Walk-forward、Signal/Review 与 AI 辅助研究。
- 长期不做：自动交易、实盘下单、多用户 SaaS、tick 级高频和 AI 自动晋升正式策略。

## 输出

- 功能定位。
- 阶段归属。
- 第一版最小实现。
- 后期扩展。
- 不建议第一版做的部分。
- 优先级和风险点。

## 否决信号

- 第一版做全自动实盘、复杂 SaaS、多用户权限、手机 App、tick 级高频。
- 页面炫酷但数据链路不可靠。
- 功能无法本地验证或一次改多个大模块。
