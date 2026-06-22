---
name: backtest-engine
description: 当任务涉及期货回测、策略信号、成交撮合、手续费、滑点、保证金、最大回撤、交易明细时使用。
---

# 回测引擎 Skill

## 第一版目标

实现 bar 级别事件驱动回测。

## 必须包含

1. Strategy
2. Signal
3. Order
4. Trade
5. Position
6. Portfolio
7. BrokerSimulator
8. RiskManager
9. BacktestEngine
10. ReportBuilder

## 严禁

1. 使用未来 K 线生成当前信号。
2. 用当前收盘价生成信号后又假设当前收盘成交，除非明确标注。
3. 忽略手续费和滑点。
4. 忽略合约乘数。
5. 忽略保证金占用。
6. 只输出收益曲线，不输出交易明细。

## 输出报告必须包含

- 总收益
- 年化收益
- 最大回撤
- 胜率
- 盈亏比
- 平均盈亏
- 连续亏损
- 交易明细
- 资金曲线
- 回撤曲线
