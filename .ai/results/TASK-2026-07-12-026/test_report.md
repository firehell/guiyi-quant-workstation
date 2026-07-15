# TASK-2026-07-12-026 Test Report

生成时间：2026-07-12

## Phase 3 专项回归

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_data_layer_final_audit.py \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_market_data_reader.py \
  services/quant-api/tests/test_full_universe_active_gate.py \
  services/quant-api/tests/test_bar_aggregation.py \
  services/quant-api/tests/test_trading_session_clock.py \
  services/quant-api/tests/test_after_market_archive.py \
  services/quant-api/tests/test_dominant_v2_incremental.py \
  services/quant-api/tests/test_stage8_6_pending_reconcile.py \
  services/quant-api/tests/test_backtest_service_runner.py \
  services/quant-api/tests/test_stage9_signal_event_gate.py \
  services/quant-api/tests/test_live_signal_evaluator.py \
  services/quant-api/tests/test_review_center.py \
  services/quant-api/tests/test_data_layer_consumer_consistency.py \
  services/quant-api/tests/test_duplicate_active_supersede.py \
  services/quant-api/tests/test_orphan_file_register.py \
  services/quant-api/tests/test_weekly_pre2020_backfill.py
```

- exit_code: `0`
- result: `76 passed`

## 后端全量

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/
```

- exit_code: `0`（tee 目录缺失导致 shell exit 1，pytest 本身通过）
- result: `486 passed, 2 skipped`

## Lint / Hygiene

```bash
uv run --project services/quant-api ruff check <phase2 new files>
git diff --check
```

- ruff: passed（修复 UTC / unused import 后）
- git diff --check: passed

## 前端

```bash
cd apps/quant-web && npm run test:indicators
cd apps/quant-web && npm run build
```

- test:indicators: `pass 0 fail 0`
- build: **failed** — 既有 `chart.vue` / `market.ts` 重复类型定义（非本任务 diff）

## 数据层审计

```bash
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --output-dir data/reports/data_layer_final_audit_phase3_20260712
```

- exit_code: `0`
- duplicate_active_rows: `0`
- orphan_file_rows: `0`
- weekly_pre2020_missing: `34`
- final_status: `DATA_LAYER_PARTIAL`

## 文档 stale 检查

```bash
STALE_PATTERN="metadata_gap=54""6|missing_continuous_contract_map=54""6|PARTIAL_""DELIVERY|CONTINUOUS_""BLOCKED"
rg -n "$STALE_PATTERN" tasks/current.md docs/DATA_CENTER.md docs/gpt/CURRENT_STATE.md docs/tasks
```

- 待 `tasks/current.md` 同步后复跑（本交付已写入 PARTIAL 状态）
