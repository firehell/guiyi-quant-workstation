# V1-Final Acceptance Review

生成时间：2026-06-28

阶段目标：

```text
V1-Final：焦煤 JM 真实交易约束回测闭环
```

结论：**未通过最终验收**。

本轮已验证后端、前端、数据库迁移、Web 旧报告展示和 K线 marker 页面均可运行；但新的 V1-Final 15m / 5m 正式报告未能生成，因此不能宣布 V1-Final 完成。

## 1. 最终报告 ID

| 报告 | 结果 |
|---|---|
| JM V1-Final 15m entry report_id | 未生成 |
| JM V1-Final 5m entry report_id | 未生成 |

生成尝试记录：

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

当前阻塞：

- `futures_trading_parameters` 中 JM 记录数：38522，`price_tick` 非空数量：0。
- `fee_margin_rules` 中 JM 记录数：38522，`price_tick` 非空数量：0。
- 因此 V1-Final 报告生成在 `JM2305` / `2023-03-01` 明确失败。

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

最终 V1-Final 报告路径暂未形成，因为最终 report_id 尚未生成。

## 7. 已通过测试

```bash
uv run --project services/quant-api pytest -q
# 167 passed

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

## 9. 未通过项

- 新 JM V1-Final 15m report 未生成。
- 新 JM V1-Final 5m report 未生成。
- 新 report_id 尚不存在。
- 当前数据库 JM 交易参数缺 `price_tick`，无法满足“交易参数必须来自数据库”的验收要求。
- 因最终报告未生成，不能验收最终报告中的 `entry_contract` / `exit_contract`、逐笔手续费、逐笔滑点、保证金、换月退出和交割风险退出展示。
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

P0：

1. 补齐 JM `price_tick` 的数据库来源，建议优先修复 RQData structured ingest 或增加显式数据修复迁移/导入脚本。
2. 补齐后重跑 JM V1-Final 15m / 5m 正式报告，确认生成新的 report_id。
3. 验证新报告 trade 级字段：`entry_contract`、`exit_contract`、`contract_multiplier`、`price_tick`、`commission`、`slippage`、`margin_required`。
4. 验证 report totals 等于 trade-level 汇总。
5. 再次做浏览器 smoke，打开新的最终 report_id。

P1：

1. 给报告列表增加更明确的“数据质量阻塞 / 生成失败”提示。
2. 为最终报告生成命令固化一个只跑 JM 15m / 5m 的维护脚本。

P2：

1. 后续再做样本外验证和参数稳定性检查。
2. 后续再评估模拟观察，不进入自动实盘。
