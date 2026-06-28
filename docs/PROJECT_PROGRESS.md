# PROJECT_PROGRESS.md — 当前项目进度

> 用途：给新的 Codex 线程、Cursor 人工检查和外部审查快速确认当前真实进度。  
> 当前阶段：V1-B：焦煤 JM 3 年真实数据短持有策略闭环已跑通，进入验收收尾。
> 边界：V1 不做实盘、不自动下单、不接 CTP / TqSdk 交易接口。

> 2026-06-28 V1-Final 验收复核：**未通过最终验收**。JM 真实交易约束链路已能严格暴露数据缺口，但新的 15m / 5m V1-Final 报告尚未生成。最新生成尝试为 `task_id=10`（15m）和 `task_id=11`（5m），均失败于 `TradingParameterMissingError: trading parameters incomplete for contract=JM2305 on 2023-03-01: price_tick`。当前 `futures_trading_parameters` 与 `fee_margin_rules` 的 JM 记录均为 38522 行，`price_tick` 非空数量均为 0。详见 `docs/V1_FINAL_ACCEPTANCE.md`。

---

## 1. 当前阶段

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环已完成工程闭环
```

V1-B 已把项目从旧的 V1-A “焦煤 1 年验收样板”推进到 3 年真实数据闭环：

```text
焦煤 JM 最近 3 年真实数据
→ 1d / 15m / 5m 标准 K线
→ 日线定方向
→ 15m 独立入场
→ 5m 独立入场
→ 持有 5-8 根本周期 K线
→ 止损退出
→ 正式回测报告
→ PostgreSQL 入库
→ Vue Web 资金曲线 / 回撤曲线 / 交易明细
→ K线买卖点 marker
→ 单笔交易复盘 note
→ 信号扫描提醒
```

阶段详情见：

```text
docs/V1B_JM_3Y_FAST_ENTRY.md
docs/V1B_JM_3Y_SHORT_HOLD.md
```

---

## 2. V1-B 真实完成状态

数据资产：

| 周期 | 时间范围 | 行数 | 状态 |
|---|---|---:|---|
| 1d | 2023-01-03 15:00:00 UTC 至 2025-12-31 15:00:00 UTC | 727 | `primary` / `passed` |
| 15m | 2023-01-03 09:15:00 UTC 至 2025-12-31 15:00:00 UTC | 16569 | `primary` / `passed` |
| 5m | 2023-01-03 09:05:00 UTC 至 2025-12-31 15:00:00 UTC | 49707 | `primary` / `passed` |

正式回测报告：

| report_id | 入场周期 | trades | equity points | drawdown points | total_return | max_drawdown | win_rate | profit_loss_ratio | max_consecutive_losses |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 15m | 127 | 727 | 727 | 0.5135000700 | 452714.6910 | 0.4330708661 | 1.0070937937 | 8 |
| 4 | 5m | 323 | 727 | 727 | 2.6282351100 | 1257709.1220 | 0.4829721362 | 1.3476551196 | 6 |

退出分布：

- 15m：`max_hold_bars_exit` 71 笔，`stop_loss_atr_or_structure` 56 笔。
- 5m：`max_hold_bars_exit` 213 笔，`stop_loss_atr_or_structure` 110 笔。
- 持仓 `hold_bars` 最大值均为 8；小于 5 的交易均来自止损提前退出。

复盘 note 示例：

- `review_id=1`
- `report_id=3`
- `trade_id=5`
- `symbol=jm`
- `entry_interval=15m`
- `direction=long`
- `entry_time=2023-03-01 09:30:00 UTC`
- `exit_time=2023-03-01 13:45:00 UTC`
- `hold_bars=8`
- `entry_reason=daily_long_ema21_pullback_macd_confirmed`
- `exit_reason=max_hold_bars_exit`

信号扫描结果：

- 最近任务：`SIG-JM-V1B-20260627164705-de1e8889`
- 状态：`completed`
- 周期：`15m`、`5m`
- 当前记录均为 `no_signal`
- 原因：`daily_direction_blocked|daily_close_near_ema21_neutral`
- 信号扫描只提醒和记录状态，不自动下单。

Web 查看路径：

- 回测报告：`http://127.0.0.1:5173/backtest?report_id=3`、`http://127.0.0.1:5173/backtest?report_id=4`
- K线买卖点：`http://127.0.0.1:5173/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3`
- 单笔复盘：`http://127.0.0.1:5173/review?review_id=1`
- 信号扫描：`http://127.0.0.1:5173/signal`

已通过验证：

```bash
uv run --project services/quant-api pytest -q
# 153 passed

uv run --project services/quant-api ruff check .
# All checks passed!

cd apps/quant-web && pnpm build
# build passed; BaseChart chunk 501.85 kB warning remains
```

---

## 3. 已具备能力

- V1 主路线已统一为 RQData + standard Parquet + DuckDB + PostgreSQL + vn.py + FastAPI + Redis/RQ + Vue Web。
- 数据源抽象、`data_role` 隔离、MarketDataReader / LocalParquetProvider 已存在。
- JM V1-B 1d / 15m / 5m RQData / local standard parquet 已注册为正式 `primary` 数据资产。
- vn.py adapter、strategy loader、symbol mapper、result converter 已存在。
- `jm_v1b_daily_direction_fast_entry` 已支持日线方向过滤、15m/5m 独立入场、5-8 根 K线短持有、止损退出和信号提醒。
- JM V1-B 15m / 5m 两份正式回测报告已入库。
- 回测报告、交易明细、资金曲线、回撤曲线、K线 marker、复盘 note、信号扫描页面已打通。
- 自动实盘、自动下单、CTP / TqSdk 交易接口不属于 V1。

---

## 4. 未解决问题

- 本轮未做浏览器截图级 UI 验收，只验证了前端 build 和 API / DB 事实。
- `pnpm build` 仍有 `BaseChart` 501.85 kB chunk warning，暂不阻塞 V1-B。
- 两份报告中的 `annual_return` 当前为 0.0，后续需要统一年化收益口径。
- 两份报告中的 `total_commission` / `total_slippage` 当前为 0.0，需要继续审查 vn.py 成本字段是否已完整计入。
- `max_drawdown` 当前按金额字段展示，后续需要补齐金额 / 百分比口径说明，避免 Web 误读。
- 信号扫描结果当前是 `no_signal` 状态，闭环已打通，但尚未验证真实触发信号时的提醒展示。
- 后续进入模拟观察前，仍需样本外、参数稳定性和风控审查。

---

## 5. 当前不做

V1-B 明确不做：

- 多品种批量扩展。
- 参数优化、网格搜索、AI 自动生成策略。
- tick 级高频回测。
- 复杂盘口队列撮合。
- Web 策略代码编辑器。
- Web 大屏扩展。
- 自动实盘。
- 自动下单。
- CTP / TqSdk 交易接口接入。
- 修改 vn.py 源码。
- 写入账号、密码、API Key、license、米筐账号、天勤账号、CTP 信息。

---

## 6. 下一阶段建议

1. 打 V1-B checkpoint commit / tag 前，先做一次浏览器级 Web smoke。
2. 修正或明确年化收益、手续费、滑点、最大回撤百分比的报告口径。
3. 固化 JM V1-B 的定期信号扫描任务，但仍然只提醒、不自动下单。
4. 做 V1-B 外部审查：未来函数、成交时点、成本、保证金、回撤和连亏。
5. 决定下一阶段是 V1-B.1 报告口径加固，还是 V1-C 单品种样本外验证。

---

## 7. 建议检查命令

```bash
rg -n "V1-B|焦煤 JM|3 年|日线.*方向|15m|5m|5-8|止损|自动下单|自动实盘" README.md AGENTS.md CLAUDE.md docs
```

```bash
git diff --name-only
```

后续实现任务回归：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```
