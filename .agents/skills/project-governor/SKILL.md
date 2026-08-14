---
name: project-governor
description: 当任务涉及归一量化功能取舍、阶段归属、优先级、是否过度设计、是否偏离 V0/V1 研究闭环时使用。
---

# Project Governor Skill

## 判断原则

当前 release 基线为 v1.1.0：可信 Canonical 60 品种之上已完成 Market Radar / Product Workspace、
HTDY Alert V1 与 SuBing Factor/Signal 人工观察。任何功能先判断是否加强这条研究闭环；旧
Signal/Review/Strategy 子系统与回测仍已退役，不得因历史文件或名称恢复为兼容面。Alert V1 与
SuBing observation 是两个独立、限域的应用能力，不代表通用策略平台。

## 阶段口径

- v1.0.0：RQData → Canonical/Catalog → MarketDataService → Market Web/API 的历史基线。
- v1.1.0：60 品种有界 Market Runtime、Radar / Product Workspace 与只读研究面。
- 当前 develop：Alert V1 自然事件闭环；SuBing current-rank1-segment-local Factor/Signal 人工观察。
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
