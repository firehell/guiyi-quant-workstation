# BACKTEST_ENGINE.md — 归一量化回测设计

> 版本：V1 重构版  
> 当前路线：vn.py CTA BacktestingEngine 作为 V1 回测底座  
> 阶段边界：V1 不自研完整撮合引擎，不做 tick 高频回测，不做实盘。

---

## 1. 回测定位

V1 回测中心的目标不是从零造完整交易框架，而是：

```text
用 vn.py 作为底层回测执行器
用归一量化负责任务编排、数据准备、策略版本、结果转换、报告入库和 Web 展示
```

因此：

```text
vn.py = 底层回测能力
归一量化 = 研究闭环和产品层
```

---

## 2. V1 回测总流

```text
Web 创建回测任务
    |
    v
FastAPI 参数校验
    |
    v
backtest_tasks 入库
    |
    v
RQ Worker 执行
    |
    v
读取 standard parquet
    |
    v
VnpyBacktestAdapter
    |
    v
vn.py BacktestingEngine
    |
    v
vn.py raw result
    |
    v
ResultConverter
    |
    v
backtest_reports / trades / orders / curves 入库
    |
    v
Web 报告展示 + K线买卖点复盘
```

---

## 3. V1 不做内容

V1 不做：

1. 自研完整事件驱动撮合引擎。
2. tick 级高频回测。
3. 盘口队列模拟。
4. 复杂组合保证金。
5. 高频策略。
6. 自动实盘。
7. 实盘账户接入。
8. AI 自动生成策略并直接运行。
9. 直接修改 vn.py 源码。

---

## 3.1 当前 V1-B 回测口径

当前阶段：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

V1-B 回测只围绕焦煤 JM 最近 3 年真实数据展开。旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

V1-B 策略执行口径：

1. 日线只用于确定方向，不能作为入场周期。
2. 15m 可以独立入场，形成独立回测报告。
3. 5m 可以独立入场，形成独立回测报告。
4. 15m 入场后只持有 5-8 根 15m K线。
5. 5m 入场后只持有 5-8 根 5m K线。
6. 行情不利时按止损方法退出。
7. 未触发止损时按短持有窗口退出。

严谨性要求：

- 日线方向只能使用已确认日线，不能读取未来日线或当前未完成日线。
- 当前 bar 产生的信号不能用当前 bar 自身价格直接成交，必须明确下一 bar 或可验证成交时点。
- 15m 和 5m 是两条独立入场链路，不得混用交易明细或报告结论。
- 报告必须统计手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
- 回测结果必须明确不等于实盘结果。
- 信号扫描只提醒，不自动下单。

---

## 4. vn.py 集成原则

必须遵守：

1. 不修改 vn.py 源码。
2. 不依赖 VeighNa Studio GUI。
3. 通过 adapter / runner 调用 vn.py。
4. 策略优先写为 vn.py `CtaTemplate`。
5. 数据读取走本地标准化数据。
6. 回测结果必须转换为归一量化统一格式。
7. 归一量化业务层不散落调用 vn.py 内部实现。
8. 未来如果替换回测底座，只替换 adapter 层。

---

## 5. 推荐目录

```text
services/quant-api/app/vnpy_integration/
  __init__.py
  settings.py
  symbol_mapper.py
  backtest_runner.py
  result_converter.py
  strategy_loader.py
  errors.py

services/quant-api/app/backtest/
  __init__.py
  service.py
  task_runner.py
  schemas.py

packages/quant-core/guiyi_quant/strategies/
  su_bing_ema21/
    vnpy_strategy.py
    config_schema.py
    default_params.json
    review_tags.json
    README.md
```

---

## 6. Adapter 抽象

### 6.1 BacktestEngineAdapter

```python
class BacktestEngineAdapter:
    def run_backtest(self, task_config):
        raise NotImplementedError

    def convert_result(self, raw_result):
        raise NotImplementedError
```

V1 实现：

```text
VnpyBacktestAdapter
```

后置备用：

```text
CustomBacktestAdapter
```

---

### 6.2 MarketDataProvider

```python
class MarketDataProvider:
    def get_bars(self, vt_symbol: str, interval: str, start, end):
        raise NotImplementedError

    def get_contracts(self):
        raise NotImplementedError
```

V1 实现：

```text
RQDataProvider
LocalParquetProvider
```

后置候选：

```text
TqSdkDataProvider
```

说明：当前 active 回测读取只允许 RQData / Local Standard Parquet primary 数据。旧 TqSdk / 天勤和交易练习者数据已从 active 链路移除；`TqSdkDataProvider` 只能作为 future backup 单独设计，不得默认恢复为 V1 回测入口。

---

## 7. 回测任务配置

统一 task config：

```json
{
  "task_name": "su_bing_ema21_rb_60m_2020_2026",
  "engine_type": "vnpy",
  "strategy_code": "su_bing_ema21",
  "strategy_version": "v0.1.0",
  "strategy_class_path": "guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy",
  "symbols": ["rb888.SHFE"],
  "interval": "60m",
  "start": "2020-01-01",
  "end": "2026-06-30",
  "initial_capital": 100000,
  "rate": 0.0001,
  "slippage": 1,
  "size": 10,
  "pricetick": 1,
  "margin_rate": 0.12,
  "data_source": "local_parquet",
  "data_role": "primary",
  "params": {
    "ema_period": 21,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 14,
    "stop_atr_multiple": 2.0
  },
  "risk": {
    "max_single_trade_risk_pct": 0.01,
    "max_margin_usage_pct": 0.4,
    "max_positions": 3
  }
}
```

---

## 8. 回测结果统一格式

vn.py 原始结果必须转换为：

```json
{
  "report": {
    "task_id": "xxx",
    "engine_type": "vnpy",
    "strategy_code": "su_bing_ema21",
    "strategy_version": "v0.1.0",
    "symbol": "rb888.SHFE",
    "interval": "60m",
    "start": "2020-01-01",
    "end": "2026-06-30",
    "initial_capital": 100000,
    "final_equity": 123000,
    "total_return": 0.23,
    "annual_return": 0.08,
    "max_drawdown": 0.12,
    "max_drawdown_amount": 12000,
    "sharpe": 1.1,
    "win_rate": 0.42,
    "profit_loss_ratio": 2.1,
    "trade_count": 138,
    "max_consecutive_losses": 6,
    "total_commission": 3200,
    "total_slippage": 1800,
    "data_source": "rqdata",
    "data_version": "20260626_v1"
  },
  "trades": [],
  "orders": [],
  "daily_results": [],
  "equity_curve": [],
  "drawdown_curve": []
}
```

---

## 9. 数据读取规则

回测禁止直接调用外部 SDK。

正确流程：

```text
backtest_task
→ MarketDataReader
→ standard parquet
→ pandas DataFrame
→ vn.py BarData
→ BacktestingEngine
```

正式回测默认只允许：

```text
data_role = primary
quality_status != failed
```

如使用 validation 或 legacy_reference，必须在任务中显式标记：

```text
is_research_only = true
```

---

## 10. 回测严谨性规则

必须检查：

1. 是否存在未来函数。
2. 是否存在数据泄露。
3. 当前 K线收盘生成信号后，是否错误假设当前收盘成交。
4. 信号生成和成交撮合是否错位合理。
5. 手续费是否计入。
6. 滑点是否计入。
7. 合约乘数是否正确。
8. 保证金占用是否估算。
9. 最大回撤是否统计。
10. 连续亏损是否统计。
11. 交易明细是否可复盘。
12. 策略参数是否过拟合。
13. 样本内 / 样本外是否区分。
14. 回测结果是否明确不等于实盘结果。

---

## 11. 初始策略

V1 第一批策略：

```text
1. 苏冰 EMA21 趋势系统
2. 均线突破 + 趋势过滤系统
3. N 字结构 / 分型系统
```

优先实现：

```text
packages/quant-core/guiyi_quant/strategies/su_bing_ema21/vnpy_strategy.py
```

---

## 12. 苏冰 EMA21 策略 V1

策略目标：

```text
把苏冰 EMA21 趋势系统从主观规则转成可配置、可回测、可复盘的 vn.py CTA 策略
```

核心条件：

```text
趋势环境：
- close > EMA21：多头环境
- close < EMA21：空头环境

辅助条件：
- MACD DIF / DEA 接近零轴
- MACD 金叉 / 死叉
- 成交量放大
- 避免快速拉升后追入
- ATR 控制止损距离

入场：
- 趋势方向确认
- 回调后重新转强
- MACD 共振
- 当前价格不过度偏离 EMA21

出场：
- 反向信号
- 跌破 / 突破 EMA21
- ATR 止损
- 固定 R 倍止盈
- 时间止损后置
```

默认参数：

```json
{
  "ema_period": 21,
  "macd_fast": 12,
  "macd_slow": 26,
  "macd_signal": 9,
  "volume_window": 20,
  "volume_multiplier": 1.2,
  "atr_period": 14,
  "stop_atr_multiple": 2.0,
  "take_profit_r_multiple": 2.5,
  "max_ema_deviation_atr": 1.5,
  "allow_long": true,
  "allow_short": true
}
```

---

## 13. 数据库表

V1 回测相关表：

```text
backtest_tasks
backtest_reports
backtest_trades
backtest_orders
backtest_daily_results
backtest_equity_curve
backtest_drawdown_curve
```

`backtest_tasks` 关键字段：

```text
engine_type
vnpy_strategy_class
vnpy_setting_json
data_source
data_role
data_version
raw_result_path
normalized_result_path
status
error_type
error_message
traceback
started_at
finished_at
```

`backtest_reports` 关键字段：

```text
engine_type
engine_version
strategy_code
strategy_version
symbol
interval
initial_capital
final_equity
total_return
annual_return
max_drawdown
win_rate
profit_loss_ratio
trade_count
max_consecutive_losses
total_commission
total_slippage
data_source
data_version
```

---

## 14. API 设计

```text
POST /api/backtests/tasks
GET  /api/backtests/tasks
GET  /api/backtests/tasks/{task_id}
GET  /api/backtests/reports
GET  /api/backtests/reports/{report_id}
GET  /api/backtests/reports/{report_id}/trades
GET  /api/backtests/reports/{report_id}/orders
GET  /api/backtests/reports/{report_id}/daily-results
GET  /api/backtests/reports/{report_id}/equity-curve
GET  /api/backtests/reports/{report_id}/drawdown-curve
```

后端端到端 demo：

```bash
uv run --project services/quant-api python experiments/vnpy_rqdata_demo/run_demo.py --backend-e2e
```

该 demo 使用第 4 步 standard Parquet fixture，创建回测任务，调用真实 vn.py runner，执行 `result_converter` 和 `persist_result`，再通过 FastAPI `TestClient` 查询 report / trades / equity_curve / drawdown_curve。输出文件：

```text
experiments/vnpy_rqdata_demo/output/backend_e2e_result.json
```

默认使用隔离临时 SQLite，不污染本地 PostgreSQL；如需本地开发库 smoke，可显式追加 `--use-app-db`。该 demo 是研究验收，不读取真实 RQData 账号，不接 CTP / TqSdk 实盘，不代表实盘结果。

---

## 15. 任务队列

使用：

```text
Redis + RQ
```

状态：

```text
pending
running
success
failed
cancelled
```

失败必须记录：

```text
error_type
error_message
traceback
failed_at
```

---

## 16. 验收标准

```text
[ ] 能创建回测任务
[ ] 能写入 backtest_tasks
[ ] 能进入 RQ 队列
[ ] Worker 能调用 VnpyBacktestAdapter
[ ] 能读取 standard parquet
[ ] 能运行 vn.py 回测
[ ] 能转换结果为统一 JSON
[ ] 能写入 backtest_reports
[ ] 能写入 backtest_trades
[ ] 能生成 equity_curve
[ ] 能生成 drawdown_curve
[ ] Web 能展示报告
[ ] K线能显示买卖点
```

安全验收：

```text
[ ] 没有未来函数
[ ] 没有数据泄露
[ ] 没有自动实盘
[ ] 没有账号密码入库
[ ] 回测包含手续费
[ ] 回测包含滑点
[ ] 回测包含最大回撤
[ ] 回测包含连续亏损
```
