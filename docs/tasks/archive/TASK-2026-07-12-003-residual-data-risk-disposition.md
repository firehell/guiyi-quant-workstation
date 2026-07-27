# TASK-2026-07-12-003：剩余数据风险受控处置分流

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-003-residual-data-risk-disposition |
| Branch | main |
| Status | DELIVERY_READY_RISK_DISPOSITION |
| Source Report | data/reports/target_coverage_audit_20260712_after_weekly_metadata_repair/ |
| Output Report | data/reports/residual_data_risk_disposition_20260712/ |

## 1. 任务类型

数据风险收口 / 剩余 issue 分流 / 不写 DB / 不写 Parquet / 不改质量状态。

## 2. 目标

在 `ad/ec/op` 周线 row_count mismatch 清零后，将剩余风险从“未处理项”收口为明确的受控 Gate：

1. `source_interval_unverified` 进入 provenance repair dry-run。
2. `missing_db_registration` 进入 `L/PP/V` actual-contract registration dry-run。
3. `quality_failed` 进入 readonly root-cause audit。
4. 参考元数据缺口进入 metadata sync/backfill dry-run。
5. 当前工作区中与数据修复无关的本地变更保持不触碰。

## 3. 本次结论

| issue_group | rows | unique_assets | disposition |
|---|---:|---:|---|
| source_interval_unverified | 1039 | 276 | 只做 provenance 修复，不改 failed/passed 语义 |
| missing_db_registration | 108 | 93 | 先 dry-run registration candidates，再人工确认写 DB |
| quality_failed | 105 | 15 | 只读根因审查，不为覆盖率升级状态 |
| metadata_reference_gaps | 831 | 0 | 参考元数据 sync/backfill，不让上层各自补逻辑 |
| workspace_external_changes | 0 | 0 | 当前 git status 未显示活动变更；若再出现则另行处理 |

## 4. 硬边界

- 本任务不写 PostgreSQL。
- 本任务不写 raw / processed / canonical Parquet。
- 本任务不改 manifest、checksum、data_version、data_role、quality_status。
- 本任务不调用 RQData。
- 本任务不新增 Alembic migration 或 schema。
- 本任务不修改策略、回测、信号、live runtime、scheduler、企业微信或任何交易执行逻辑。
- 本任务不回退或改写用户/其他任务已有的 `README.md`、`scripts/local-services-status.sh`、`scripts/post-reboot-verify.sh`；当前 `git status --short` 未显示这些路径为活动变更。

## 5. 下一步 Gate

1. `source_interval_provenance_repair_dry_run`
   - 输入：276 个唯一 Parquet 文件。
   - 输出：逐文件候选，包含 row_count、checksum_before、checksum_after 预估、manifest/processed summary/DB checksum 同步计划。
   - apply 前必须再次确认。

2. `lpv_actual_contract_registration_dry_run`
   - 输入：`l/pp/v` 108 rows / 93 files。
   - 输出：registration candidates。
   - apply 前必须验证 file exists、DuckDB row_count、manifest quality passed、checksum、唯一键。

3. `quality_failed_root_cause_audit`
   - 输入：15 个唯一 failed files。
   - 输出：根因 bucket：可重建、需重新下载、应归档、保留 failed。
   - 禁止直接改 `quality_status=passed`。

4. `reference_metadata_gap_dry_run`
   - 输入：831 rows。
   - 输出：contract universe 与 continuous contract map sync/backfill candidates。
   - 禁止由 Market/Backtest/Signal/Review 各自补 fallback 逻辑。

## 6. 验收标准

- 剩余 issue 不再以“未处理”散落在任务总结里，而是全部归入明确 Gate。
- 每个 Gate 都有输入数量、允许动作、禁止动作和下一步产物。
- 当前工作区外部变更被识别并保留，不与数据修复混做。
