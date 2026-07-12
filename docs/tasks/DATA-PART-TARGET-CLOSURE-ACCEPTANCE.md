# DATA-PART-TARGET-CLOSURE 总验收报告

生成时间：2026-07-12

状态：`DELIVERY_READY_DATA_PART_TARGET_CLOSURE`

## 1. 里程碑定义

数据部分目标完成需同时满足 5 个条件：

| # | 条件 | 状态 |
|---|---|---|
| 1 | Stage 5-B reference metadata gap 已关闭 | 通过 |
| 2 | 105 条 quality_warning 有明确消费边界 | 通过（TASK-010 Plan + TASK-011 代码） |
| 3 | Stage 8.6 八个 pending 有最终分流 | 通过（TASK-012） |
| 4 | 数据消费者统一遵守 active 入口 | 通过 |
| 5 | 文档 / 报告 / 测试形成最终事实源 | 本文件 |

## 2. JM 六周期 passed 证据

产品 `jm` / 合约 `jm.MAIN` / 窗口 `2023-01-03..2026-07-10`

| period | quality | derivation |
|---|---|---|
| 1m | passed | RQData direct |
| 5m | passed | aggregated from 1m |
| 15m | passed | aggregated from 1m |
| 30m | passed | aggregated from 1m |
| 60m | passed | aggregated from 1m |
| 1d | passed | trading_day aggregation from 1m |

证据路径：

- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `docs/DATA_CENTER.md` §3

## 3. Target coverage final

```text
covered_passed=17203
covered_warning=105
metadata_gap=0
not_applicable=273
issue_register_rows=105
quality_warning=105
```

证据：`data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`

## 4. Reference metadata gap closed

TASK-009 结果：

```text
needs_contract_universe_sync=0
needs_continuous_contract_sync=0
```

- `contract_universe`：285 success
- derived `continuous_contract_map`：546 success（`calls_rqdata=False`）

证据：`data/reports/reference_metadata_gap_reconcile_after_reference_metadata_apply_full_20260712/`

## 5. quality_warning=105 消费边界

任务：`TASK-2026-07-12-010` / `TASK-2026-07-12-011`

| 模块 | 规则 |
|---|---|
| Market | 允许展示 warning，API 返回质量字段 + message，前端 warning 提示 |
| Backtest | 默认 passed-only；warning 需 `allow_warning_quality=true` |
| Signal | 默认阻断 warning（Stage 9 前） |
| Review | extra 记录 `data_quality_status`；warning 带 caveat |

105 条 warning **不升级为 passed**。

文档：`docs/DATA_CENTER.md` §2.1

## 6. Stage 8.6 pending 分流

任务：`TASK-2026-07-12-012`

| disposition | count |
|---|---:|
| accepted_warning | 5 |
| registration_not_needed | 3 |
| requires_apply_gate | 0 |

- `bb/rs/wh/wr/zc`：accepted_warning（abnormal price，不升级 passed）
- `L2609F/PP2609F/V2609F`：registration_not_needed（LPV snapshot 产品名误报）

证据：`data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`

JM 六周期 6/6 passed **不受影响**。

## 7. Active 入口（消费者统一）

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究默认：`quality_status=passed`（`MarketDataReader.passed_only=True`）

## 8. 不授权事项

- Stage 9 信号事件 / 企业微信发送
- live runtime / scheduler 自动执行
- 自动交易 / 实盘下单
- 105 条 warning 升级为 passed
- derived continuous map 写成 RQData SDK 直接接口验收

## 9. 最终测试

```bash
rg -n "metadata_gap=546|missing_continuous_contract_map=546|PARTIAL_DELIVERY|CONTINUOUS_BLOCKED" \
  tasks/current.md docs/DATA_CENTER.md docs/gpt/CURRENT_STATE.md docs/tasks

uv run --project services/quant-api pytest -q services/quant-api/tests/test_target_coverage_audit.py
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_reference_metadata_gap_apply.py \
  services/quant-api/tests/test_reference_metadata_gap_reconcile.py
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_market_data_reader.py \
  services/quant-api/tests/test_stage8_6_pending_reconcile.py \
  services/quant-api/tests/test_review_center.py
git diff --check
```

## 10. GPT 同步清单

- `tasks/current.md`
- `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`
- `docs/tasks/TASK-2026-07-12-010-quality-warning-consumption-boundary.md`
- `docs/tasks/TASK-2026-07-12-012-stage8-6-pending-reconcile.md`
- `docs/DATA_CENTER.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`
