# GPT Review Package: JM V1B OOS Full Window

生成时间：2026-07-12

任务 ID：`JM-V1B-OOS-FULL-WINDOW-VALIDATION`

## 1. 冻结配置

```json
{
  "strategy": "jm_v1b_daily_direction_fast_entry / v1b.0 / 15m",
  "data_policy": "local_parquet / primary / passed",
  "execution_timing": "next_bar_open",
  "costs": {"rate": 0.0001, "slippage": 1.0, "size": 60, "pricetick": 0.5, "capital": 100000},
  "persist_to_db": false
}
```

配置文件：`configs/oos/jm_v1b_report14_frozen.json`

## 2. 执行命令（已运行）

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py --list-windows

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py \
  --format markdown --output-dir data/reports/oos_validation_full_window_20260712/plan_only

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/oos_validation_run.py \
  --run --format markdown --output-dir data/reports/oos_validation_full_window_20260712/run
```

## 3. 测试结果

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_oos_validation_run.py
uv run --project services/quant-api ruff check scripts/oos_validation_run.py services/quant-api/tests/test_oos_validation_run.py
```

结果：6 passed；ruff All checks passed。

## 4. 基线 trust audit

- `report_id=14`：`audit_status=passed`（10/10）
- 总收益约 -19.29%
- 未回写 report

## 5. 全窗口 OOS 总判定

- `overall_status`: **passed**
- `persist_to_db`: false
- `would_write_db`: false
- `would_run_rqdata`: false
- `would_send_notifications`: false

## 6. 窗口结果（如实保留）

| window_id | trades | return_pct | mdd_pct | win_rate | profit_factor | trust |
|---|---:|---:|---:|---:|---:|---|
| in_sample_baseline | 125 | -8.56 | 14.19 | 40.8% | 0.86 | passed |
| oos_fixed | 32 | -9.06 | 7.61 | 37.5% | 0.29 | passed |
| walk_forward_a_test | 5 | -1.92 | 1.54 | 0.0% | 0.00 | passed |
| walk_forward_b_test | 14 | +0.55 | 2.72 | 35.7% | 1.08 | passed |
| walk_forward_c_test | 32 | -9.06 | 7.61 | 37.5% | 0.29 | passed |

原始 JSON：`data/reports/oos_validation_full_window_20260712/run/oos_validation.json`

## 7. 与 report_id=14 差异（摘要）

详见：`data/reports/oos_validation_full_window_20260712/BASELINE_VS_OOS.md`

要点：

1. 窗口切分导致 trade_count 与收益不可直接与全窗口基线数值对比。
2. OOS 使用当前 active `data_version=v1b_jm_20200102_20260710`，基线为 `v1b_jm_20230103_20260706`。
3. 2026H1 样本外仍亏损；2025Q1 walk-forward 仅 5 笔且全亏。
4. 未调参、未改策略、未包装收益。

## 8. 风险与禁止项确认

- [x] 未写正式 `backtest_tasks` / `backtest_reports`
- [x] 未回写 `report_id=14`
- [x] 未进入模拟/实盘
- [x] 未发送通知
- [x] 亏损窗口保留
- [x] 低交易数窗口保留（walk_forward_a_test=5）
- [x] 审查包无 `.env`/token/webhook/license

## 9. 外部 GPT 审查问题

1. 非 DB OOS 的内存 trust checks 是否足够支撑研究结论？
2. 数据版本漂移是否应阻断“复现 report 14”表述？
3. 在冻结参数下，2026H1 亏损是否构成继续研究的硬阻断？
4. walk-forward 极低样本窗口应如何写入验收口径？

## 10. 建议上传文件

- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
- `services/quant-api/tests/test_oos_validation_run.py`
- `data/reports/oos_validation_full_window_20260712/run/oos_validation.json`
- `data/reports/oos_validation_full_window_20260712/BASELINE_VS_OOS.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
