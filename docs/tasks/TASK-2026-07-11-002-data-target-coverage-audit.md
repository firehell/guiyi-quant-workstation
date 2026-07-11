# TASK-2026-07-11-002：目标覆盖矩阵只读审计

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002-data-target-coverage-audit |
| Branch | codex/data-target-coverage-audit |
| Worktree | /Volumes/扩展盘/guiyi-parallel/data-audit |
| Status | DELIVERY_READY_WITH_CLI_ENV_NOTE |
| Baseline | main 含 TASK-2026-07-11-001 data-audit 结果 |

## 1. 任务类型

数据质量检查 / 目标覆盖矩阵 / 只读审计

## 2. 背景

上一阶段 `TASK-2026-07-11-001-data-asset-audit` 只证明了 Stage 8.6 当前发现到的 active 快照：

- 90 产品中 82 `active_passed` / 8 `active_partial`。
- 1326 manifest-level discovered active records `active_passed` / 8 `audit_pending`。
- JM 最新主连六周期 6/6 `active_passed`。

该快照不是完整目标覆盖率。本任务新增独立目标覆盖矩阵，固定粒度为：

```text
product x contract_role x symbol/contract x period x year x status
```

## 3. 目标

在不修复、不登记、不写 DB/Parquet/RQData 的前提下，产出目标资产目录、物理资产清单、目标覆盖矩阵、元数据一致性矩阵、问题登记表和摘要报告。

## 4. 允许修改范围

- `scripts/rqdata_target_coverage_audit.py`
- `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
- `services/quant-api/tests/test_target_coverage_audit.py`
- `data/reports/target_coverage_audit_20260711/`
- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-002-data-target-coverage-audit.md`
- `docs/DATA_CENTER.md`
- `docs/gpt/CURRENT_STATE.md`

## 5. 禁止修改范围

- 不写 PostgreSQL。
- 不写 raw / processed / canonical parquet。
- 不调用 RQData 下载。
- 不修复 `bb/rs/wh/wr/zc` warning。
- 不补登记 `L2609F/PP2609F/V2609F`。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信。
- 不读取或打印 `.env`、RQData、Webhook、DB 密码等凭据。
- 不改 Alembic migration，不新增数据库 schema。

## 6. 实现摘要

- 新增独立审计器 `target_coverage_audit.py`，不复用 Stage 8.6 active snapshot 的结论语义。
- 新增 CLI `scripts/rqdata_target_coverage_audit.py`。
- 支持 DB 只读查询；DB 缺认证时降级读取本机 API readonly snapshot：
  - `/api/v1/data/coverage`
  - `/api/v1/data/quality-reports`
- API 也不可用时仍可输出 manifest-only 审计，并将 DB / API 限制写入 summary。
- 输出状态固定为：`covered_passed`、`covered_warning`、`missing_db_registration`、`missing_physical_file`、`row_count_mismatch`、`metadata_gap`、`not_applicable`、`unknown_error` 等。
- 物理文件核对使用 manifest / DB `file_path` 指向的真实路径，不假定当前 worktree 有完整 `data/parquet`。

## 7. 本次运行结果

运行命令：

```bash
uv run --project services/quant-api python scripts/rqdata_target_coverage_audit.py --products-file data/universe/full_products_90.txt --output-dir data/reports/target_coverage_audit_20260711
```

DB direct CLI 状态：

- 本 worktree 无 `.env` / `DATABASE_URL`，默认 PostgreSQL 连接失败：`fe_sendauth: no password supplied`。
- 未读取 `.env`，未提取或打印 DB/RQData/Webhook 凭据。
- 已使用本机 API readonly snapshot fallback。

输出规模：

- `target_asset_catalog.csv`：17689 rows。
- `asset_physical_inventory.csv`：15159 rows。
- `target_coverage_matrix.csv`：17689 rows。
- `metadata_consistency_matrix.csv`：3780 rows。
- `issue_register.csv`：4528 rows。

覆盖矩阵状态：

| status | count |
|---|---:|
| covered_passed | 16164 |
| covered_warning | 1144 |
| missing_db_registration | 108 |
| not_applicable | 273 |

元数据矩阵状态：

| status | count |
|---|---:|
| metadata_gap | 3276 |
| not_applicable | 504 |

Issue 类型：

| issue_type | count |
|---|---:|
| db_unavailable | 3276 |
| source_interval_unverified | 1039 |
| missing_db_registration | 108 |
| quality_warning | 105 |

## 8. 输出产物

- `data/reports/target_coverage_audit_20260711/target_asset_catalog.csv`
- `data/reports/target_coverage_audit_20260711/asset_physical_inventory.csv`
- `data/reports/target_coverage_audit_20260711/target_coverage_matrix.csv`
- `data/reports/target_coverage_audit_20260711/metadata_consistency_matrix.csv`
- `data/reports/target_coverage_audit_20260711/issue_register.csv`
- `data/reports/target_coverage_audit_20260711/coverage_summary.md`

## 9. 测试与验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_target_coverage_audit.py -q
```

结果：5 passed。

```bash
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
```

结果：8 passed。

待最终交付前执行：

```bash
git diff --check
git status --short
```

## 10. 结论边界

- 本任务完成的是目标覆盖矩阵只读审计，不是数据修复。
- Stage 8.6 的 `1326 active_passed / 8 audit_pending` 仍是 discovered active snapshot，不代表完整目标覆盖率。
- 已知 8 pending 未被修复，也不能因本矩阵存在其他缺口而被当作唯一问题。
- JM V1-B 最新主连六周期可信基线仍需以 JM Stage 8.6 profile 验证；本任务不改变该结论。
- Stage 9 仍 blocked，本任务不授权企业微信发送。

## 11. 下一步建议

1. 若要得到完整元数据覆盖结论，需在只读 DB 环境可用后重跑本 CLI。
2. 对 `source_interval_unverified` 先做只读根因分类，区分实际缺列、历史 1d 直连资产和派生 1d 资产。
3. 对 `missing_db_registration` 另开受控登记 Plan，不在本任务修复。
4. 对 `quality_warning` 另开只读质量根因审查，不得为提高通过率覆盖 warning。
