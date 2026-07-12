# 火天大有 HTDY Strict V1 离线候选评估

生成时间：2026-07-12

## 1. 定位

本文件定义第 5 步：

```text
HTDY-STEP5-OFFLINE-BACKTEST-CANDIDATE-EVAL
```

本阶段只评估 `huotian_dayou_strict_v1` 是否具备后续正式回测设计价值，不接入正式回测任务、报告入库、信号事件、live evaluator 或企业微信。

允许结论：

```text
huotian_dayou_strict_v1 offline backtest candidate evaluated
```

## 2. 版本与策略候选命名

| 字段 | 值 |
|---|---|
| indicator_version | `huotian_dayou_strict_v1` |
| strategy_code | `huotian_dayou_strict` |
| strategy_version | `v0.1.0-offline` |
| candidate_policy | `strict_v1_15m_offline_v0` |
| fill_policy | `signal_on_close_fill_next_bar_open` |
| execution_scope | `offline_comparison_only` |
| status | `offline_backtest_candidate_eval` |

能力边界保持：

- `backtest_candidate=true`
- `backtest_capable=false`
- `live_capable=false`
- `alert_capable=false`
- `trading_capable=false`

`v0.1.0-offline` 只用于离线候选评估，不覆盖 `huotian_dayou_original_v0`，也不替代 `huotian_dayou_strict_v1` 的指标版本。

## 3. 数据与读取约束

离线 runner 只读现有 JM `15m` parquet：

```text
provider/source = rqdata
data_role = primary
quality_status = passed
symbol/contract/period = jm / jm.MAIN / 15m
```

工具不下载数据、不覆盖 parquet、不登记 `market_data_files`、不写 PostgreSQL。

## 4. 候选事件解释

本阶段只输出 candidate events：

| strict 字段 | 离线解释 |
|---|---|
| `buy_observation` | long entry candidate |
| `xg_observation` | long entry candidate |
| `sell_observation` | short or exit candidate |

信号时点固定为当前 bar 收盘确认；若后续做收益对照，只能使用下一根 bar open 作为拟成交时点。本阶段默认不计算可信 PnL，不生成可信回测报告。

## 5. Runner

只读 JSON 输出：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/offline_candidate_eval.py
```

可选导出：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/offline_candidate_eval.py \
  --output-json /tmp/htdy_strict_offline_candidate.json \
  --output-markdown /tmp/htdy_strict_offline_candidate.md
```

可通过 `GUIYI_HTDY_OFFLINE_SOURCE` 指定 parquet 文件，或通过 `GUIYI_DATA_ROOT` 指定数据仓根目录。

## 6. 验收标准

- 输出包含版本、数据 lineage、checksum、事件时点、候选解释和能力边界。
- `strategy_version` 固定为 `v0.1.0-offline`。
- `event_interpretation.mode=candidate_events_only`。
- 不创建 backtest task，不写 `BacktestReport`。
- 不写 `strategy_signals`、`signal_events`、live evaluator 或企业微信链路。
- 禁止链路 diff 核对无输出。

## 7. 后续 Gate

若离线候选评估值得继续，下一步必须另开正式回测候选 Plan，至少补齐：

- 独立正式策略实现或 adapter；
- 参数 schema 与默认参数；
- 入场、出场、止损、反手和冲突处理；
- 成本、滑点、合约乘数、保证金；
- report / trade / order / equity / drawdown 对账；
- trust audit 与外部 GPT 安全复核。
