# BACKTEST_ENGINE.md

生成时间：2026-07-09

## 1. 回测定位

V1 回测底座使用 vn.py / VeighNa CTA BacktestingEngine。归一量化负责数据选择、任务编排、参数校验、结果转换、报告入库和 Web 展示。

回测不等于实盘结果，不生成自动交易指令。

## 2. 回测数据入口

正式回测默认只读取：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

禁止默认读取 validation、legacy_reference、candidate、failed、旧 TqSdk / 天勤或交易练习者数据。

## 3. 当前 JM v2 数据基础

JM v2 六周期数据已完成 parquet、manifest、quality 和 DB 登记：

```text
1m / 5m / 15m / 30m / 60m / 1d
20230103_20260707_v2
provider = rqdata
data_role = primary
quality_status = passed
```

回测相关工作必须继续遵守 Stage 3A active 过滤约束；Stage 13 已完成当前可信回测主线复核收口，但不等于所有历史报告或所有策略完全可信。

### Stage 8.5 actual-contract bars 数据基础

Stage 8.5-6B 已完成 JM 当前真实主力合约 historical bars 写入试点：

- `product=jm`、`continuous_contract=jm.MAIN`、`actual_contract=JM2609`
- 六周期 canonical parquet 均为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`
- 真实合约 bars 路径使用 `actual_contract`，不混入 `jm.MAIN` 文件
- 后续回测可基于 actual-contract bars 进行真实合约成本核算

## 4. 当前回测能力

- 创建回测任务。
- RQ worker 执行 vn.py 回测。
- JM V1-B 15m / 5m 固定任务。
- 报告、资金曲线、回撤曲线、交易明细入库。
- ResultConverter 标准化 vn.py 输出。
- Web Backtest 页面展示报告和交易明细。
- K 线 marker 联动回测成交。
- 真实合约成本增强（手续费、保证金、强平退出）。
- Stage 13 只读可信审计器：按 report_id / task_no 复核数据 lineage、execution policy、trade/order/equity、手续费滑点、合约乘数、trusted metrics 和脱敏输出。
- Stage 13-D 报告可信 lineage：`BacktestTrade` 显式记录 `entry_signal_source`、`entry_order_no`、`exit_order_no`、`lineage_status`，`BacktestOrder` 显式记录 `trade_no`、`leg`、`lineage_source`、`mapping_status`，并在 report summary 中保存 `lineage_summary`。
- Stage 13-G report 14 lineage 修复：vn.py order row 按提交时间、方向和 offset 映射到 strategy trade；直接止损退出不伪造 close order，只记录 `strategy_trade_direct_exit`。
- 当前 `report_id=14` trust audit 已通过，所有 checks passed，可作为 JM V1-B fast-entry 15m 的当前可信样本继续用于 Web 展示和复盘链路检查。

核心代码：

- `services/quant-api/app/api/backtests.py`
- `services/quant-api/app/backtest/service.py`
- `services/quant-api/app/backtest/runner.py`
- `services/quant-api/app/backtest/trust_audit.py`
- `services/quant-api/app/backtest/v1b_jm_tasks.py`
- `services/quant-api/app/vnpy_integration/*`
- `packages/quant-core/guiyi_quant/strategies/*`

## 5. 当前策略

| 策略 | 状态 |
|---|---|
| `jm_v1b_daily_direction_fast_entry` | JM V1-B 15m / 5m 固定任务历史主线 |
| `su_bing_jm_v1b_short_hold` | 日线方向 + 15m/5m 短持有研究 spec |
| `su_bing_jm_daily_ema21_macd_volume` | 日线 EMA21 / MACD / 量能研究基线 |
| `su_bing_jm_daily_score2of4` | 独立研究版本 |

## 6. 回测安全检查

回测、策略或报告任务默认检查：

- 未来函数。
- 数据泄露。
- 过拟合。
- 信号时点和成交撮合错位。
- 手续费、滑点、合约乘数。
- 保证金占用。
- 最大回撤。
- 最大连续亏损。
- 单笔交易可复盘。
- 报告指标能追溯到底层 trade / order / equity。

## 7. Stage 13 可信审计入口

只读 CLI：

```bash
uv run --project services/quant-api python scripts/backtest_trust_audit.py --report-id <report_id> --format json
uv run --project services/quant-api python scripts/backtest_trust_audit.py --task-no <task_no> --format markdown
```

该入口默认不写 DB、不运行 RQData、不触发回测、不发送企业微信，只审计已入库报告。

当前审计规则覆盖：

- `data_lineage`：只允许 `rqdata` / `local_parquet`、`primary`、`quality_status != failed`，严格研究优先 `passed`。
- `execution_policy`：确认 `next_bar_open`，有 `entry_signal_time` 的 trade 必须在信号时间之后成交。
- `lineage_mapping`：检查 trade signal source、trade/order 映射状态、order `trade_no` / `leg`。
- `trade_order_consistency`：核对 report trade_count 与 trade rows、方向、价格、时间、数量和合约字段。
- `equity_consistency`：从 trades 复算 equity / drawdown，并与 summary 指标对齐。
- `fee_slippage`：检查 rate / slippage、逐笔 commission / slippage 和 summary totals。
- `contract_multiplier`：检查 size / pricetick、逐笔 contract multiplier / price tick 和 JM V1-B 真实合约成本 lineage。
- `trusted_metrics`：要求 `consistency_hash` 和 `metric_units`，区分从 trade/equity 派生的 trusted metrics 与外部 raw metrics。
- `reproducibility`：检查 task、策略、数据版本、start/end 等复现字段，并脱敏 request payload。
- `sensitive_output`：阻断 webhook、token、password、license、secret 和本机路径泄露。

Stage 13-G 受控 lineage repair：

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/stage13g_repair_report14_lineage.py --report-id 14 --dry-run
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api python scripts/stage13g_repair_report14_lineage.py --report-id 14 --apply --confirm-stage13g-report14-lineage-repair
```

该 repair 仅面向 `report_id=14` 的历史 lineage mapping warning。当前 report 14 已修复后，再运行 dry-run 会因 pre-repair guard 不满足而退出；这不是 trust audit 失败。

详见：

- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`

## 8. 未完成

- Stage 13 审计器不重跑回测，不能单独证明策略无未来函数；它主要审计已入库 report/trade/order/equity/metrics 层面的可信性。
- `report_id=14` 通过审计只代表当前 JM V1-B fast-entry 15m 样本，不代表所有历史报告或所有策略完全可信。
- 旧报告不自动回填 Stage 13-D/G lineage 字段；如需修复旧报告，应另开受控 backfill 阶段。
- 其他 JM 合约仍可能存在 `price_tick` metadata 缺口；后续如需批量修复必须另设 Gate。
- rollover-safe / trusted metrics 复核。
- 策略消融和样本外验证。
- Stage 14 Web 复盘闭环增强。
