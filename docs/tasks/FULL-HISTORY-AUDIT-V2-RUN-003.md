# FULL-HISTORY-AUDIT-V2-RUN-003

生成时间：2026-07-17

状态：`FULL_HISTORY_AUDIT_V2_EXECUTED / AUDIT_BLOCKED`

## 1. 范围和只读边界

本任务在 Mac mini 实际数据环境重跑全品种 Audit V2 quick/full。固定 audit end 为 `2026-07-10`，输入为 B2-02 engine、canonical physical Parquet、全部 manifest/processed summary、direct PostgreSQL metadata/quality/Profile。

- 未调用 RQData。
- 未写 DB。
- 未写或覆盖 canonical Parquet。
- 未修改 manifest、quality status、data role 或 Profile binding。
- 只新增本任务报告与本地 `.ai/results` 执行证据。
- 旧 `1853 / 34 / 45` 只作历史对照，不参与 V2 Gate。

full inventory 与运行后 read-only 复核的 bars `market_data_files` / `data_quality_reports` 数量均为 `25134 / 25134`。

## 2. Preflight

```text
FULL_HISTORY_AUDIT_ENV_READY
git_commit=497178af2b1faa8197d6f6a75c53e1e0608743bd
data_environment_git_commit=613f52fcbbd681a6ddbbd2cf5c4dba9f85fc6368
head=origin/main
data_root=/Volumes/扩展盘/guiyi-quant-workstation
canonical_parquet_count=24763
db_snapshot_source=direct_postgresql
alembic_current=head=20260712_0023
audit_end=2026-07-10
```

DuckDB 代表样本 `a.MAIN/1d` 成功读取 5908 行，范围 `2002-03-15..2026-07-10`。live runtime、live signal、after-market archive 和 WeChat autosend 均为 unset/default false。

## 3. 执行结果

Quick 与 full engine 均完成，覆盖 90 品种、720 个 continuous expected window、V1 derived periods、12726 个 rank=1 actual interval target、reference metadata 和 1350 个 Profile target。

完整 physical inventory：

```text
physical_file_count=24763
duckdb_read_failed_rows=0
checksum_matched_rows=25451
checksum_mismatch_rows=382
checksum_declared_conflict_rows=1384
checksum_no_declared_rows=17
outside_canonical_root_rows=4
missing_physical_rows=4
```

由于 B2-03 规定任何 checksum failure 或数据根漂移都令结果 blocked，本任务同时命中 checksum failure 与 4 条 DB-only path drift，最终状态为：

```text
execution_status=FULL_HISTORY_AUDIT_V2_EXECUTED
gate_status=AUDIT_BLOCKED
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
```

B2-02 engine 自身返回 `FULL_HISTORY_AUDIT_V2_READY` 只说明引擎执行完成；B2-03 full checksum Gate 优先，不得据此宣布审计或数据层 ready。

## 4. 新 residual

| 类别 | 数量 |
|---|---:|
| coverage matrix | 720 |
| expected physical partial | 252 |
| file integrity residual | 1783 |
| exact registration residual evidence | 2090 |
| quality residual evidence | 127 |
| reference root residual | 180 |
| reference downstream blocked | 270 |
| weekly semantics residual | 90 |
| actual rank=1 covered | 11605/12726 |
| actual roll residual | 1121 |
| Profile blocked | 1345/1350 |
| Profile eligible warning | 5/1350 |

Registration/file quality 数量包含物理 evidence/version 行，不能直接解释为应写 DB 或应下载资产。B2-04A 必须先按 applicability、active/version、声明来源和 root cause 去重分类。

## 5. Legacy comparison

- 旧 `metadata_gap=1853` 与 V2 reference root residual 计量单位不同，禁止相减冒充修复量。
- 旧 34 个 `partial_or_missing_pre2020` weekly 产品在 V2 均存在 covered physical weekly evidence，确认 34 个 legacy weekly false positive；provider authoritative start 与 calendar 语义仍未因此自动通过。
- 旧 actual `45` 不沿用；V2 按 12726 个 rank=1 interval target 重算，当前 residual 为 1121。

## 6. 输出

目录：`data/reports/full_history_audit_v2_run_20260710/`

- `full_history_coverage_matrix.csv`
- `physical_residuals.csv`
- `registration_residuals.csv`
- `quality_residuals.csv`
- `reference_metadata_residuals.csv`
- `weekly_semantics_residuals.csv`
- `actual_roll_residuals.csv`
- `profile_eligibility_matrix.csv`
- `AUDIT_V2_SUMMARY.md`
- `audit_evidence.json`

本地 preflight、quick/full 中间报告和生成器证据位于 `.ai/results/FULL-HISTORY-AUDIT-V2-RUN-003/`。

## 7. B2-04A 输入

下一任务只读优先级：

1. 将 382 mismatch 与 1384 declared conflict 按 path/version/manifest source 去重并判定声明漂移还是物理损坏。
2. 解释 252 个 derived expected partial 的共同 2020 seam，不自动生成下载任务。
3. 将 1121 actual interval residual 按缺物理、缺 exact registration、quality 与 checksum 拆分。
4. 先关闭 90 calendar boundary 和 90 session historical-scope root residual，再重算 270 downstream blocked。
5. 将 1345 Profile blocked 反向归因到上述五层，不写 binding。
