# V1-Final Acceptance Review

生成时间：2026-06-28

阶段目标：

```text
V1-Final：焦煤 JM 真实交易约束回测闭环
```

结论：**通过 V1-Final 闭环验收**。

本轮已修复 JM `price_tick` 数据缺口，新的 V1-Final 15m / 5m 固定回测任务已成功生成报告，trade 级真实合约、成本和保证金字段已入库，report 汇总与 trade 明细汇总一致，Web 报告页和 K线 marker 页面均已 smoke 通过。

注意：本结论只代表 V1-Final 研究闭环验收通过，不代表策略可实盘。新报告显示回撤很高，后续仍必须做策略效果复核、样本外验证、模拟观察和人工风控确认。

## 1. 最终报告 ID

| 报告 | 结果 |
|---|---|
| JM V1-Final 15m entry report_id | 5 |
| JM V1-Final 5m entry report_id | 6 |

最新生成记录：

| task_id | 周期 | 状态 | report_id | 交易数 | total_commission | total_slippage | max_margin_required |
|---:|---|---|---:|---:|---:|---:|---:|
| 12 | 15m | success | 5 | 127 | 3254.2618200642255 | 7620.0 | 24996.0 |
| 13 | 5m | success | 6 | 323 | 9287.670933088062 | 19380.0 | 24846.0 |

历史失败记录：

| task_id | 周期 | 状态 | 失败类型 | 失败原因 |
|---:|---|---|---|---|
| 10 | 15m | failed | `TradingParameterMissingError` | `trading parameters incomplete for contract=JM2305 on 2023-03-01: price_tick` |
| 11 | 5m | failed | `TradingParameterMissingError` | `trading parameters incomplete for contract=JM2305 on 2023-03-01: price_tick` |

前置失败记录：

| task_id | 周期 | 状态 | 失败类型 | 处理结果 |
|---:|---|---|---|---|
| 8 | 15m | failed | `DeliveryCalendarMissingError` | 已修正 resolver：DCE 日历缺失时使用数据库已有 `CNFE` 全国期货交易日历兜底 |
| 9 | 5m | failed | `DeliveryCalendarMissingError` | 同上 |

## 2. 数据范围

正式 JM 数据资产仍然可用，均为 `rqdata` / `primary` / `passed`：

| 周期 | 时间范围 | 行数 | data_version |
|---|---|---:|---|
| 1d | 2023-01-03 15:00:00 UTC 至 2025-12-31 15:00:00 UTC | 727 | `rqdata_jm_standard_1d_20230103_20251231_v1` |
| 15m | 2023-01-03 09:15:00 UTC 至 2025-12-31 15:00:00 UTC | 16569 | `rqdata_jm_standard_15m_20230103_20251231_v1` |
| 5m | 2023-01-03 09:05:00 UTC 至 2025-12-31 15:00:00 UTC | 49707 | `rqdata_jm_standard_5m_20230103_20251231_v1` |

## 3. 策略版本

| 项目 | 值 |
|---|---|
| strategy_code | `jm_v1b_daily_direction_fast_entry` |
| strategy_version | `v1b.0` |
| research_symbol | `jm.MAIN` |
| actual contract mapping | 由 `main_contract_map` 按交易日解析 |
| signal timing | K线收盘处理信号，下一根 K线开盘成交 |

## 4. 成本口径

V1-Final 的目标成本口径为：

- 每笔 trade 使用 resolver 解析 `entry_contract` / `exit_contract`。
- `futures_trading_parameters` 优先提供 `contract_multiplier`、`price_tick`、手续费、保证金。
- `fee_margin_rules` 作为兜底。
- 如果两张表都无法补齐字段，任务必须 fail clearly，不允许静默回退到 `jm.MAIN` 或硬编码参数。

已修复：

- 根因：本地 RQData raw `trading_parameters` 和 `catalog` 留底中没有 `price_tick` 字段，`rqdatac.futures.get_trading_parameters` 的本机字段文档也不包含 `price_tick`。
- 修复方式：新增受控脚本 `scripts/backfill_jm_price_tick.py`，仅补 `product=jm`、`provider=rqdata`、`2023-01-01` 至 `2025-12-31` 内 `price_tick is null` 的行，不覆盖已有非空值，不修改策略或 resolver。
- 修复来源：`dce_notice_2015_95`，用于 V1-Final 覆盖区间内 JM 最小变动价位 `0.5`。
- 修复前：`futures_trading_parameters` V1-Final 窗口 JM `price_tick` 非空 0 / 8724；`fee_margin_rules` 非空 0 / 8724。
- 修复后：`futures_trading_parameters` V1-Final 窗口 JM `price_tick` 非空 8724 / 8724；`fee_margin_rules` 非空 8724 / 8724。
- `JM2305` / `2023-03-01` 已可解析：`price_tick=0.5`，`parameter_source=futures_trading_parameters`。

## 5. 换月 / 交割规则

已实现口径：

- 从实际合约代码解析合约月份，例如 `JM2405` -> `2024-05`。
- 最后允许持仓日为交割月前最后一个交易日。
- 优先查询合约交易所日历；若当前数据库只有 `CNFE` 全国期货交易日历，则使用 `CNFE` 兜底。
- 禁持窗口内不允许新开仓。
- 交割风险退出记录 `delivery_risk_exit`。
- 主力切换退出记录 `main_contract_roll_exit`。
- V1 不做自动移仓续持，新合约重新等信号。

## 6. Web 查看路径

旧 V1-B 报告仍可查看：

- 15m 旧报告：`http://127.0.0.1:5173/backtest?report_id=3`
- 5m 旧报告：`http://127.0.0.1:5173/backtest?report_id=4`
- 旧报告 K线 marker：`http://127.0.0.1:5173/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3`

新 V1-Final 报告路径：

- 15m 新报告：`http://127.0.0.1:5173/backtest?report_id=5`
- 5m 新报告：`http://127.0.0.1:5173/backtest?report_id=6`
- 15m 新报告 K线 marker：`http://127.0.0.1:5173/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=5`
- 5m 新报告 K线 marker：`http://127.0.0.1:5173/market?symbol=jm&contract=jm.MAIN&period=5m&report_id=6`

## 7. 已通过测试

```bash
uv run --project services/quant-api pytest -q
# 169 passed

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_backtest_contract_resolver.py \
  services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py \
  services/quant-api/tests/test_backtest_task_api.py

uv run --project services/quant-api ruff check .
# All checks passed!

cd apps/quant-web && pnpm build
# build passed; BaseChart 501.85 kB chunk warning remains

cd services/quant-api && uv run alembic current
# 20260628_0011 (head)
```

浏览器 smoke：

- 后端 `http://127.0.0.1:8000/health` 正常返回。
- 前端 `http://127.0.0.1:5173` 可启动。
- `/backtest?report_id=3` 可打开旧 15m 报告，资金、回撤、交易区域可见。
- `/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=3` 可打开 K线页面，canvas 非空，旧报告 marker 和复盘入口区域可见。
- `/backtest?report_id=5` 可打开新 15m V1-Final 报告，报告列表显示 `#5` 为 `V1-Final`。
- `/backtest?report_id=6` 可打开新 5m V1-Final 报告，报告列表显示 `#6` 为 `V1-Final`。
- `/market?symbol=jm&contract=jm.MAIN&period=15m&report_id=5` 可打开新报告 K线页面，显示 `回测复盘 #5`、交易数 127，并出现 trade marker 文本。
- `/market?symbol=jm&contract=jm.MAIN&period=5m&report_id=6` 可打开新报告 K线页面，显示 `回测复盘 #6`、交易数 323，并出现 trade marker 文本。
- 控制台未发现应用错误。

## 8. 通过项

- JM 三年正式数据可用。
- 固定策略可加载。
- vn.py 回测链路可执行。
- 旧 V1-B report 3/4 可读取。
- Web 回测报告页可显示旧报告，并能区分 `Smoke` / `Old V1-B`。
- Web K线页可显示旧报告 marker。
- resolver 对缺失日历和缺失交易参数均能 fail clearly。
- DCE 日历缺失时，resolver 已支持使用数据库已有 `CNFE` 全国期货交易日历。
- JM `price_tick` 数据缺口已补齐。
- 新 V1-Final report_id=5/6 已生成。
- 新报告 trade 级 `entry_contract`、`exit_contract`、`price_tick`、`commission`、`slippage`、`margin_required` 均为非空。
- 新报告 `total_commission`、`total_slippage`、`max_margin_required` 与 trade 级汇总一致。
- Web 新报告和新 K线 marker smoke 已通过。

## 9. 未通过项 / 风险项

- 未发现阻塞 V1-Final 闭环验收的剩余 P0。
- 新报告策略收益为负且最大回撤很高，只能作为研究闭环验收结果，不能作为实盘依据。
- vn.py 底层统计阶段输出过资金小于等于 0 的提示；归一化报告已入库并通过汇总核验，但后续策略效果审查需要单独复核资金曲线、风险敞口和仓位参数。
- Dashboard / Strategy / Settings 仍不属于 V1-Final 验收范围。

## 10. 当前不做

- 不扩多品种。
- 不做参数优化。
- 不接实盘。
- 不自动下单。
- 不修改 vn.py 源码。
- 不修改真实行情数据文件。
- 不写入账号、密码、API Key、米筐账号、天勤账号、CTP 信息。

## 11. 下一阶段建议

P0：无剩余 V1-Final 闭环阻塞。

P1：

1. 对 report_id=5/6 做策略效果审查，重点复核资金曲线、回撤、爆仓提示、固定手数和风险占用。
2. 给报告列表增加更明确的“数据质量阻塞 / 生成失败”提示。
3. 为最终报告生成命令固化一个只跑 JM 15m / 5m 的维护脚本。

P2：

1. 后续再做样本外验证和参数稳定性检查。
2. 后续再评估模拟观察，不进入自动实盘。
