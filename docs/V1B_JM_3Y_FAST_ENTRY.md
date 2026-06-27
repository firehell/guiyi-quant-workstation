# V1-B - JM 3 年真实数据短持有策略闭环完成记录

> 本文记录 V1-B 的真实完成状态。V1-B 仍属于 V1 Web 研究闭环，不属于 V1.5 / V2 实盘阶段。

## 1. 阶段结论

V1-B 已跑通以下闭环：

```text
JM 近 3 年真实数据
→ 1d / 15m / 5m 标准 K线
→ 日线方向过滤
→ 15m / 5m 独立入场
→ 5-8 根本周期 K线短持有
→ 止损退出
→ vn.py 回测
→ PostgreSQL 报告入库
→ Vue Web 报告
→ K线买卖点 marker
→ 单笔交易复盘 note
→ 信号扫描提醒
```

本阶段没有接实盘账户，没有自动下单，没有写入账号、密码、API Key、米筐账号、天勤账号或 CTP 信息。

## 2. 数据资产

V1-B 正式样板数据为焦煤 JM 主力连续样本 `jm.MAIN`，来源口径为 RQData / local standard parquet，数据库记录为 `data_role=primary`、`quality_status=passed`。

| 周期 | 时间范围 | 行数 | 质量 |
|---|---|---:|---|
| 1d | 2023-01-03 15:00:00 UTC 至 2025-12-31 15:00:00 UTC | 727 | missing=0, duplicate=0 |
| 15m | 2023-01-03 09:15:00 UTC 至 2025-12-31 15:00:00 UTC | 16569 | missing=0, duplicate=0 |
| 5m | 2023-01-03 09:05:00 UTC 至 2025-12-31 15:00:00 UTC | 49707 | missing=0, duplicate=0 |

## 3. 策略与任务

策略名称：

```text
jm_v1b_daily_direction_fast_entry
```

策略口径：

- 日线只做方向过滤，使用已完成日线。
- 15m 与 5m 是两条独立入场链路。
- 入场信号生成后按下一根 K线成交口径处理。
- `max_hold_bars_min=5`，`max_hold_bars_max=8`。
- 止损可早于 5 根 K线退出；未触发止损时最晚第 8 根 K线退出。
- 信号扫描只提醒，不自动下单。

固定任务入口：

```text
POST /api/backtests/v1b/jm/15m/tasks
POST /api/backtests/v1b/jm/5m/tasks
```

## 4. 正式回测报告

### 4.1 15m entry

- `report_id=3`
- 入场周期：15m
- 状态：success
- 交易数：127
- 资金曲线点数：727
- 回撤曲线点数：727
- 总收益：0.5135000700
- 年化收益：0.0
- 最大回撤：452714.6910
- 胜率：0.4330708661
- 盈亏比：1.0070937937
- 最大连续亏损：8
- 持仓 K线范围：1 至 8

退出原因：

- `max_hold_bars_exit`：71 笔
- `stop_loss_atr_or_structure`：56 笔

### 4.2 5m entry

- `report_id=4`
- 入场周期：5m
- 状态：success
- 交易数：323
- 资金曲线点数：727
- 回撤曲线点数：727
- 总收益：2.6282351100
- 年化收益：0.0
- 最大回撤：1257709.1220
- 胜率：0.4829721362
- 盈亏比：1.3476551196
- 最大连续亏损：6
- 持仓 K线范围：1 至 8

退出原因：

- `max_hold_bars_exit`：213 笔
- `stop_loss_atr_or_structure`：110 笔

## 5. Web 查看路径

本地开发环境默认地址：

```text
http://127.0.0.1:5173
```

页面路径：

- 15m 报告：`/backtest?report_id=3`
- 5m 报告：`/backtest?report_id=4`
- K线买卖点：`/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3`
- 单笔复盘：`/review?review_id=1`
- 信号扫描：`/signal`

Web 报告页应能查看：

- 总收益、最大回撤、胜率、盈亏比、交易次数、最大连续亏损。
- 资金曲线、回撤曲线。
- 交易明细中的 `entry_interval`、`hold_bars`、`entry_reason`、`exit_reason`。
- K线买卖点 marker。
- 创建或查看单笔复盘入口。

## 6. 复盘 note 示例

当前已有一条 V1-B 复盘 note：

| 字段 | 值 |
|---|---|
| review_id | 1 |
| report_id | 3 |
| trade_id | 5 |
| symbol | jm |
| entry_interval | 15m |
| direction | long |
| entry_time | 2023-03-01 09:30:00 UTC |
| exit_time | 2023-03-01 13:45:00 UTC |
| hold_bars | 8 |
| entry_reason | daily_long_ema21_pullback_macd_confirmed |
| exit_reason | max_hold_bars_exit |

## 7. 信号扫描

固定扫描入口：

```text
POST /api/signals/v1b/jm/scan?run_inline=true
```

最近扫描任务：

- `task_no=SIG-JM-V1B-20260627164705-de1e8889`
- 状态：completed
- 周期：15m、5m
- completed：2
- failed：0

当前扫描结果：

| 周期 | status | direction | signal_time | daily_direction | no_signal_reason |
|---|---|---|---|---|---|
| 15m | no_signal | neutral | 2025-12-31 15:00:00 UTC | neutral | daily_direction_blocked\|daily_close_near_ema21_neutral |
| 5m | no_signal | neutral | 2025-12-31 15:00:00 UTC | neutral | daily_direction_blocked\|daily_close_near_ema21_neutral |

说明：无信号状态也是有效扫描结果；本阶段只提醒和记录状态，不自动下单。

## 8. 已通过测试命令

```bash
uv run --project services/quant-api pytest -q
# 153 passed

uv run --project services/quant-api ruff check .
# All checks passed!

cd apps/quant-web && pnpm build
# build passed
```

前端 build 仍有既有 chunk 警告：

```text
BaseChart-Z2_qqnFf.js 501.85 kB
```

该警告不阻塞 V1-B 验收，后续可单独做前端拆包优化。

## 9. 未解决问题

- 本轮未完成浏览器截图级 UI 验收。
- 年化收益当前为 0.0，需要统一年化收益计算口径。
- `total_commission` / `total_slippage` 当前为 0.0，需要继续审查 vn.py 成本字段是否完整落库。
- 最大回撤当前记录为金额字段，Web 后续应明确金额 / 百分比口径。
- 当前信号扫描结果为 `no_signal`，尚未用真实触发信号验证提醒展示。
- V1-B 回测结论只代表研究闭环可运行，不代表策略可进入模拟盘或实盘。

## 10. 下一阶段建议

优先建议进入 V1-B.1 报告口径加固：

1. 浏览器级 Web smoke：报告页、K线 marker、复盘页、信号页。
2. 统一年化收益、手续费、滑点、最大回撤百分比口径。
3. 固化 JM V1-B 定期扫描任务，仍只提醒、不自动下单。
4. 外部审查未来函数、成交时点、手续费、滑点、合约乘数、保证金、最大回撤和连续亏损。
5. 再决定是否进入 V1-C 样本外验证或单品种扩展。
