# TASK-2026-07-12-016：`report_id=14` 样本外验证设计

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-016-oos-validation-plan |
| 日期 | 2026-07-12 |
| 分支 | `main` |
| Base | Stage 13-G / DATA-PART-TARGET-CLOSURE |
| 状态 | `DELIVERY_READY_PLAN_NO_WRITE` |
| 类型 | strategy validation plan |

## 背景

Stage 13-G 已使 `report_id=14` 达到 trust audit `passed`：

- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- trades：155 mapped
- orders：239 mapped
- trust audit：10/10 passed
- total return：约 `-19.29%`

该结论只代表报告链路可信、可追溯、可复算，不代表策略有效、样本外稳定或可实盘。

## 冻结对象

后续样本外验证必须冻结：

- strategy id：`jm_v1b_daily_direction_fast_entry`
- strategy version：`v1b.0`
- entry interval：`15m`
- data source：`rqdata / local_parquet`
- data role：`primary`
- quality：默认 `passed-only`
- execution policy：`next_bar_open`
- fees / slippage / multiplier / price tick：沿用 report 14 可追溯口径
- old report：`report_id=14` 仅作基线，不回写、不覆盖

## 样本划分建议

以当前 JM V1-B 数据窗口 `2023-01-03..2026-07-10` 为约束，建议拆为：

| 分区 | 时间 | 用途 |
|---|---|---|
| 样本内基线 | 2023-01-03..2025-12-31 | 只复现 report 14 口径，不调参 |
| 样本外固定窗口 | 2026-01-01..2026-07-10 | 验证规则冻结后的表现 |
| walk-forward A | 2023-01-03..2024-12-31 train / 2025Q1 test | 稳定性观察 |
| walk-forward B | 2023-07-01..2025-06-30 train / 2025Q3 test | 稳定性观察 |
| walk-forward C | 2024-01-01..2025-12-31 train / 2026H1 test | 最新窗口观察 |

如果实际 runner 暂不支持 train/test 参数，应先新增只读/配置层执行计划，不得为了跑通而修改策略规则。

## 验证指标

每个窗口至少记录：

- trade count
- total return
- max drawdown
- max consecutive losses
- win rate
- profit factor
- avg R / expectancy
- fee and slippage totals
- largest loss trade
- signal count and no-trade reason
- data_version / quality_status
- trust audit status

## 失败结果记录规则

以下结果必须如实保留，不能调参掩盖：

- 样本外继续亏损
- trade count 过低
- 最大回撤扩大
- 连续亏损恶化
- 信号稀疏或集中在少数行情段
- trust audit warning / failed
- 数据质量非 passed

## 执行命令草案

只读审计：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

后续如需真实生成样本外报告，必须另开执行任务并显式声明：

- 是否写入 `backtest_tasks` / `backtest_reports`
- 是否只输出临时 JSON/Markdown
- 使用哪个 frozen config
- 目标窗口

## 通过 / 失败标准

通过样本外设计的标准：

- 能明确冻结策略和数据口径。
- 能区分样本内、样本外和 walk-forward。
- 不把 report 14 的 trust passed 写成策略准入。
- 不修改旧策略版本和旧报告。
- 能为后续 Codex 执行生成单独 Prompt。

样本外执行通过标准另行定义，不能只用收益为正作为唯一标准。

## 风险

- 过拟合：不得围绕 2026H1 调参。
- 数据泄露：日线方向只能使用当前交易日前已确认日线。
- 成交错位：继续要求 next bar open。
- 质量漂移：warning 默认不得进入正式 backtest。
- 成本漂移：手续费、滑点、乘数和 price tick 必须随报告记录。

## Cursor 执行 Prompt

BEGIN CURSOR PROMPT

你现在在 `/Volumes/扩展盘/guiyi-quant-workstation` 仓库中工作。

任务：设计 `report_id=14` 的样本外 / walk-forward 验证方案。只做设计和文档，不调参，不跑新的优化。

先阅读：

- `AGENTS.md`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/tasks/V1-TRUSTED-CLOSURE-ACCEPTANCE.md`
- `packages/quant-core/guiyi_quant/strategies/su_bing_jm_v1b_short_hold/README.md`

当前事实：

- `report_id=14`
- strategy：`jm_v1b_daily_direction_fast_entry / v1b.0 / 15m`
- trust audit：10/10 passed
- total return：约 -19.29%
- 审计 passed 只代表可追溯，不代表策略有效。

目标：

1. 冻结策略版本、参数、数据版本和 execution policy；
2. 定义样本内、样本外、walk-forward 区间；
3. 定义哪些指标用于验证稳定性；
4. 定义哪些失败结果必须如实记录；
5. 输出后续执行任务单草案。

禁止：

- 不调参改善收益；
- 不修改旧策略版本；
- 不把样本内结果包装成准入结论；
- 不写新回测结果入库；
- 不改数据源；
- 不引入自动交易。

输出文件建议：

- `docs/tasks/TASK-2026-07-12-xxx-oos-validation-plan.md`

文档必须包含：

1. 背景；
2. 冻结对象；
3. 样本划分；
4. 执行命令草案；
5. 通过 / 失败标准；
6. 风险；
7. 下一步是否需要 Codex 执行。

END CURSOR PROMPT

## 下一步

需要 Codex 执行时，另开新任务：

```bash
# 只读基线
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown

# 列出窗口
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py --list-windows

# 执行单窗口（不入库）
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py \
  --run --window oos_fixed --format markdown
```

实现文件：

- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`

2026-07-12 试跑：`oos_fixed` → 32 trades，临时报告 `data/reports/oos_validation_20260712_075323/`。

