# BACKTEST_ENGINE.md — 回测引擎设计

> 版本：v0.1 · 状态：草稿 · 更新日期：2026-06-22

---

## 1. 设计目标

- 支持日线、小时线、分钟线多频率回测
- 回测结果与实盘逻辑共用同一套策略代码
- 内置真实交易成本（手续费、滑点、保证金）
- 结果可视化（净值曲线、持仓图、回撤图）

---

## 2. 回测流程

```
1. 加载数据（Parquet → DataFrame）
2. 初始化策略（读取 config.yaml）
3. 风控参数校验
4. 逐 Bar 回放
   └── on_bar() → 生成信号
   └── on_signal() → 风控校验 → 生成订单
   └── 模拟撮合（下一 Bar 开盘成交）
   └── 更新持仓与资金曲线
5. 生成绩效报告
6. 输出到 backtests/results/<strategy>/<date>/
```

---

## 3. 绩效计算标准

```python
# 必须输出的指标
metrics = {
    "annual_return": ...,       # 年化收益率
    "sharpe_ratio": ...,        # 夏普比率（年化，无风险利率 3%）
    "max_drawdown": ...,        # 最大回撤
    "win_rate": ...,            # 胜率
    "profit_loss_ratio": ...,   # 盈亏比
    "total_trades": ...,        # 总交易次数
    "daily_returns": [...],     # 日度收益序列
    "equity_curve": [...],      # 净值曲线
}
```

---

## 4. 交易成本设置

| 品种 | 手续费率 | 滑点（Tick） | 保证金比例 |
|---|---|---|---|
| 股指期货（IF/IC/IH） | 万分之 0.23 | 1 Tick | 12% |
| 螺纹钢（rb） | 万分之 1 | 1 Tick | 10% |
| 铜（cu） | 万分之 0.5 | 1 Tick | 10% |
| 原油（sc） | 万分之 0.5 | 1 Tick | 15% |

---

## 5. 结果文件格式

```
backtests/results/<strategy_name>/<YYYY-MM-DD>/
├── summary.json        核心绩效指标（JSON）
├── trades.csv          逐笔交易记录
├── daily_returns.csv   日度收益序列
├── equity_curve.csv    净值曲线
└── report.md           人类可读报告
```
