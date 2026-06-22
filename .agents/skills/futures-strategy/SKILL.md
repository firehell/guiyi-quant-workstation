---
name: futures-strategy
description: 期货策略开发技能 — 基于 BaseStrategy 框架开发期货量化交易策略。
agent_created: false
tags: [strategy, futures, signal, python]
---

# futures-strategy 技能

## 适用场景
- 开发新交易策略
- 调试信号生成逻辑
- 策略参数优化
- 策略代码评审

## 策略目录结构
```
strategies/<strategy_name>/
├── strategy.py      核心策略逻辑（继承 BaseStrategy）
├── config.yaml      参数配置
├── signals.py       信号模块（可选）
├── backtest.py      回测入口
└── README.md        策略说明
```

## 现有策略
- `su_bing_ema21`：EMA21 均线趋势跟踪
- `ma_breakout`：均线突破系统
- `n_structure`：价格结构识别

## BaseStrategy 接口
```python
class MyStrategy(BaseStrategy):
    def on_bar(self, bar: Bar) -> Optional[Signal]: ...
    def on_signal(self, signal: Signal) -> Optional[Order]: ...
    def on_order(self, order: Order) -> None: ...
```

## 重要约束
- 严禁使用未来数据（前视偏差）
- 资金计算必须用 Decimal
- 下单前必须经过风控校验
- 回测通过后才能考虑实盘
