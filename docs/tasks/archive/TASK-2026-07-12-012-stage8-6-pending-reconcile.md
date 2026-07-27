# TASK-2026-07-12-012：Stage 8.6 八个 pending 独立复核

| 字段 | 内容 |
|---|---|
| Task ID | TASK-2026-07-12-012-stage8-6-pending-reconcile |
| 日期 | 2026-07-12 |
| 分支 | `codex/stage8-6-pending-reconcile` |
| Base | TASK-2026-07-12-010 / TASK-2026-07-12-011 |
| 状态 | `DELIVERY_READY_READONLY_RECONCILE` |

## 目标

对 Stage 8.6 snapshot 的 8 个 `audit_pending` 做最终分流，避免与 target coverage 缺口或 LPV 误报混淆。

## 执行方式

只读 reconcile，输入：

- `data/reports/stage8_6_active_gate_matrix.csv`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md`

## 分流结果

| product | contract | disposition | 说明 |
|---|---|---|---|
| bb | bb.MAIN | accepted_warning | 主连 1d abnormal price warning，不升级 passed |
| rs | rs.MAIN | accepted_warning | 同上 |
| wh | wh.MAIN | accepted_warning | 同上 |
| wr | wr.MAIN | accepted_warning | 同上 |
| zc | zc.MAIN | accepted_warning | 同上 |
| l | L2609F | registration_not_needed | snapshot product 误报；`l_f` 行已 active_passed |
| pp | PP2609F | registration_not_needed | snapshot product 误报；`pp_f` 行已 active_passed |
| v | V2609F | registration_not_needed | snapshot product 误报；`v_f` 行已 active_passed |

```text
accepted_warning=5
registration_not_needed=3
requires_apply_gate=0
```

## 产出

- `data/reports/stage8_6_pending_reconcile_20260712/stage8_6_pending_reconcile_ledger.csv`
- `data/reports/stage8_6_pending_reconcile_20260712/STAGE8_6_PENDING_RECONCILE.md`
- `services/quant-api/app/services/rqdata_ingest/stage8_6_pending_reconcile.py`
- `scripts/rqdata_stage8_6_pending_reconcile.py`
- `services/quant-api/tests/test_stage8_6_pending_reconcile.py`

## 安全边界

- `writes_database=False`
- `writes_parquet=False`
- `calls_rqdata=False`
- 未修改 quality_status
- JM 六周期 6/6 passed 结论不变

## 测试

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage8_6_pending_reconcile.py
python scripts/rqdata_stage8_6_pending_reconcile.py
```
