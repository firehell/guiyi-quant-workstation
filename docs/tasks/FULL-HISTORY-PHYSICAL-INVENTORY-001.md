# FULL-HISTORY-PHYSICAL-INVENTORY-001

生成时间：2026-07-17

状态：`FULL_HISTORY_PHYSICAL_INVENTORY_READY`

## 1. 目标与边界

本任务建立独立于旧 2020/2023 target matrix 的物理事实 inventory，只回答：

> 当前本地物理 canonical Parquet、全部 manifest、processed summary 与 direct PostgreSQL 中实际有哪些资产？

执行边界：

- 不写 DB。
- 不写或修改 Parquet。
- 不调用 RQData。
- 不修改 `data_role`、`quality_status`、Profile binding、ORM 或 migration。
- 不生成 expected matrix、missing target 或下载建议。
- 正式审计终点固定为 `2026-07-10`；超出终点只标记，不过滤事实。
- 正式运行要求 direct PostgreSQL；连接不可用时返回 `ENV_BLOCKED_DB`，不允许 manifest/API fallback。

## 2. Git 与执行环境

```text
branch=codex/full-history-physical-inventory-001
worktree=/private/tmp/guiyi-full-history-physical-inventory-001
implementation_base=origin/main@a3719f06
data_project_root=/Volumes/扩展盘/guiyi-quant-workstation
data_environment_git_commit=613f52fcbbd681a6ddbbd2cf5c4dba9f85fc6368
db_snapshot_source=direct_postgresql
```

真实运行仅加载本机 runtime `project.env`，未打印连接串、密码或其他敏感值。

## 3. 实现

新增：

- `services/quant-api/app/services/rqdata_ingest/full_history_physical_inventory.py`
- `scripts/rqdata_full_history_physical_inventory.py`
- `services/quant-api/tests/test_full_history_physical_inventory.py`

核心行为：

- 扫描 `data/parquet/canonical/bars/**/*.parquet`。
- 字段驱动扫描 `data/manifests/**/*.csv`，只要求行包含 `standard_path` 与 `period`，不依赖窗口文件名。
- 扫描 `data/processed/v1b/**/*.json` 的 `periods.*.standard`。
- direct 查询全部 `data_type='bars'` 的 `MarketDataFile` 与 `DataQualityReport`，quality report 仅按 `file_id` 关联。
- 相对路径以 project root 规范化；绝对路径保留原事实，不自动重写旧根路径。
- 同 version identity、同路径聚合证据；同 identity 不同路径保持独立行；同路径多 identity 标记冲突。
- 每个 worker 复用自己的 DuckDB connection；单文件异常进入 inventory，不丢弃记录。
- `quick` 不计算 SHA-256；`full` 流式计算并比较声明 checksum。
- 输出目录存在即拒绝，不提供覆盖开关。

## 4. 正式 quick 结果

输出：

- `data/reports/full_history_audit_v2_20260710/physical_inventory.csv`
- `data/reports/full_history_audit_v2_20260710/manifest_aggregation.csv`
- `data/reports/full_history_audit_v2_20260710/db_inventory.csv`
- `data/reports/full_history_audit_v2_20260710/inventory_summary.json`

事实计数：

```text
physical_file_count=24763
physical_inventory_rows=27234
manifest_files=5537
manifest_rows_seen=38092
manifest_asset_rows=16298
processed_summary_files=756
processed_period_records=1437
market_data_file_rows=25134
quality_report_rows=25134
unlinked_quality_report_rows=0
unresolved_identity_count=0
parquet_read_failed_rows=0
schema_mismatch_rows=0
schema_inconsistent_rows=0
checksum_status=not_computed  # quick mode
```

代表品种实际物理起止时间：

| product | inventory rows | physical exists | DB records | physical min | physical max |
|---|---:|---:|---:|---|---|
| a | 325 | 325 | 300 | 2002-03-15 00:00:00 | 2026-07-10 15:00:00 |
| al | 821 | 821 | 796 | 2000-01-05 00:00:00 | 2026-07-10 15:00:00 |
| ag | 270 | 270 | 247 | 2012-05-10 00:00:00 | 2026-07-10 15:00:00 |
| jm | 265 | 261 | 230 | 2013-03-22 00:00:00 | 2026-07-10 15:00:00 |

## 5. Inventory 异常事实

- 4 条 DB 记录指向已不存在的 `experiments/rqdata_sample_acceptance/output/...` 文件；均为 jm 样本路径，当前 canonical 根外但仍在 project root 内。
- `identity_conflict_rows=4934`：同一路径存在多个 version identity 的历史证据；本任务不判断应保留哪个版本，也不修改 active binding。
- `duplicate_identity_rows=0`：按 version identity 统计，没有发现同 identity 的多物理路径行。
- `extends_beyond_audit_end_rows=0`。
- 以上事实不自动转化为 expected coverage、下载任务或数据修复授权。

## 6. 验证

```text
unit inventory tests: 10 passed
inventory + related audit regression: 49 passed
representative smoke: FULL_HISTORY_PHYSICAL_INVENTORY_SMOKE_READY
formal quick: FULL_HISTORY_PHYSICAL_INVENTORY_READY
db_snapshot_source=direct_postgresql
writes_database=false
writes_parquet=false
calls_rqdata=false
expected_matrix_generated=false
```

完整 SHA-256 模式未作为本轮 Gate 执行；需要时必须指定新的独立输出目录。

## 7. 状态语义

```text
FULL_HISTORY_PHYSICAL_INVENTORY_READY
DATA_LAYER_REAUDIT_REQUIRED
```

Inventory ready 仅表示物理、manifest、processed 与 direct DB 的当前事实已成功盘点，不表示 expected coverage、active binding 或消费者数据层已经封板。
