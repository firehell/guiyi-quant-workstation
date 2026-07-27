# TASK-2026-07-12-004：source_interval provenance repair dry-run

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-004-source-interval-provenance-repair-dry-run |
| Branch | main |
| Status | DELIVERY_READY_DRY_RUN |
| Source Issue Register | data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/issue_register.csv |
| Source Triage | data/reports/target_coverage_gap_triage_20260711/source_interval_unverified_triage.csv |
| Output Report | data/reports/source_interval_provenance_repair_dry_run_20260712/ |

## 1. 任务类型

数据 provenance 修复候选 dry-run / 不写 DB / 不写 Parquet / 不改 manifest / 不改 processed summary / 不调用 RQData。

## 2. 目标

为目标覆盖矩阵中的 `source_interval_unverified=1039` 生成逐文件候选清单，确认后续如要 apply，需要同步哪些 checksum 和元数据位置。

## 3. 本次变更

- 新增只读服务：`services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py`。
- 新增 CLI：`scripts/rqdata_source_interval_provenance_repair.py`。
- 新增测试：`services/quant-api/tests/test_source_interval_provenance_repair.py`。
- 新增报告目录：`data/reports/source_interval_provenance_repair_dry_run_20260712/`。

## 4. Dry-run 输出

| output | rows | 用途 |
|---|---:|---|
| `candidate_files.csv` | 276 | unique Parquet file 粒度候选 |
| `affected_coverage_rows.csv` | 1039 | target coverage row 到 candidate 的映射 |
| `SOURCE_INTERVAL_PROVENANCE_REPAIR_DRY_RUN.md` | 1 | 汇总、同步边界和下一步 Gate |

## 5. 核心结论

| 指标 | 结果 |
|---|---:|
| affected_coverage_rows | 1039 |
| unique_candidate_files | 276 |
| source_interval_status=source_interval_column_missing | 276 |
| apply_eligible=True | 276 |
| manifest_checksum_sync_required=True | 276 |
| db_checksum_sync_required=True | 276 |
| processed_summary_checksum_sync_required=True | 61 |
| processed_summary_checksum_sync_required=False | 215 |

周期分布：

| period | candidate files |
|---|---:|
| 1d | 80 |
| 5m | 49 |
| 15m | 49 |
| 30m | 49 |
| 60m | 49 |

## 6. 硬边界

- 本任务不写 PostgreSQL。
- 本任务不写 raw / processed / canonical Parquet。
- 本任务不改 manifest、processed summary、checksum、file_size、data_version、data_role、quality_status。
- 本任务不调用 RQData。
- 本任务不新增 Alembic migration 或 schema。
- 本任务不处理 `missing_db_registration`、`quality_failed` 或 reference metadata gaps。
- 本任务不修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行逻辑。

## 7. 测试与验证

- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：2 passed。
- `python -m py_compile services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py`
  - 结果：通过。
- `uv run --project services/quant-api python scripts/rqdata_source_interval_provenance_repair.py --output-dir data/reports/source_interval_provenance_repair_dry_run_20260712`
  - 结果：candidate_files=276，affected_coverage_rows=1039。
- `wc -l data/reports/source_interval_provenance_repair_dry_run_20260712/candidate_files.csv data/reports/source_interval_provenance_repair_dry_run_20260712/affected_coverage_rows.csv`
  - 结果：277 lines / 1040 lines，扣除 header 后为 276 / 1039。
- `uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/source_interval_provenance_repair.py scripts/rqdata_source_interval_provenance_repair.py services/quant-api/tests/test_source_interval_provenance_repair.py`
  - 结果：All checks passed。
- `git diff --check`
  - 结果：通过，无 whitespace error。

## 8. 后续 Gate

下一步如要执行写入，必须新开 `source_interval_provenance_repair_apply` 受控任务，并再次人工确认。apply 阶段必须以 unique Parquet file 为单位，且每个被重写文件必须同步：

- Parquet checksum / file size；
- manifest checksum；
- processed summary checksum（仅 61 个存在记录的文件）；
- DB `market_data_files.checksum` / `file_size_bytes`。

禁止在 apply 阶段顺手修改质量状态、补 DB registration、修 failed quality 或补 reference metadata。
