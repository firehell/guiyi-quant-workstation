# TASK-2026-07-12-026：数据层 Phase 3 最终验收

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-026-data-layer-phase3-final-acceptance |
| Branch | `feature/data-layer-phase2` |
| Status | DELIVERY_READY_DATA_LAYER_PARTIAL |
| Phase | Phase 3 final acceptance |
| Depends on | TASK-2026-07-12-025 |

## 1. 目标

Phase 2 补齐完成后：

1. 重跑 data layer final audit
2. 上层读取一致性回归
3. 增量维护回归
4. 全量测试与 lint
5. 产出 `DATA-LAYER-FINAL-ACCEPTANCE.md` 并写入 READY 或 PARTIAL

## 2. 允许修改范围

- `services/quant-api/tests/test_data_layer_consumer_consistency.py`
- `data/reports/data_layer_final_audit_phase3_20260712/**`
- `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`
- `docs/tasks/TASK-2026-07-12-026-data-layer-phase3-final-acceptance.md`
- `.ai/results/TASK-2026-07-12-026/**`
- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`

## 3. 禁止修改范围

- 不回滚 Phase 2 已 apply 的 supersede / 登记 / backfill
- 不把 warning 升级为 passed
- 不做大型架构重构

## 4. 1m 验收口径

架构口径：主力 1m 自 `2023-01-03` 起（非字面 2020+）。

## 5. required_tests

见 `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md` §测试清单。

## 6. 最终状态标记

- 全部 Gate 通过 → `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`
- 否则 → `DATA_LAYER_PARTIAL` + 剩余问题清单
