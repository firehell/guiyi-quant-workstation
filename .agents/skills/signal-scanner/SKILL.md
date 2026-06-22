---
name: signal-scanner
description: 当任务涉及多品种多周期信号扫描、策略提醒、信号等级、企业微信推送、人工确认、误报复盘时使用。
---

# Signal Scanner Skill

## V1 流程

品种池 -> 周期池 -> 策略规则 -> 趋势过滤 -> 波动过滤 -> 风险过滤 -> 生成信号 -> 分级评分 -> Web 展示 -> 可选企业微信提醒 -> 人工确认。

## 信号等级

- A：强趋势、位置合理、盈亏比足够。
- B：条件基本满足但有轻微风险。
- C：仅观察。
- D：过滤，不推送。

## 信号字段

`strategy_id`、`strategy_version_id`、`symbol`、`timeframe`、`direction`、`signal_type`、`signal_level`、`trigger_price`、`stop_loss_price`、`risk_reward_ratio`、`reason`、`created_at`、`status`。

## 禁止

- 不要信号一出现就自动下单。
- 不要没有风险计算就提醒。
- 不要推送无法解释的黑箱信号。
- 不要一天推太多低质量信号。
