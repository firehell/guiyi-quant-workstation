# FULL-HISTORY-AUDIT-V2-RUN-003

## Result

```text
execution_status=FULL_HISTORY_AUDIT_V2_EXECUTED
gate_status=AUDIT_BLOCKED
data_layer_status=DATA_LAYER_REAUDIT_REQUIRED
audit_end=2026-07-10
git_commit=497178af2b1faa8197d6f6a75c53e1e0608743bd
db_snapshot_source=direct_postgresql
products=90
writes_database=false
writes_parquet=false
calls_rqdata=false
```

完整模式成功读取 24763 个 canonical Parquet；DuckDB read failure 为 0。硬 Gate 被 checksum 和 path drift 事实触发：382 行 `mismatch`、1384 行 `declared_conflict`，另有 4 条 DB-only 路径位于 canonical root 外且物理文件缺失，因此本次不能宣布 Audit ready 或数据层 final ready。

## Residual counts

| category | rows |
|---|---:|
| expected coverage matrix | 720 |
| physical expected coverage residual | 252 |
| physical file integrity residual | 1783 |
| registration residual | 2090 |
| quality residual | 127 |
| reference metadata root residual | 180 |
| reference downstream blocked | 270 |
| weekly semantics residual | 90 |
| actual rank=1 targets | 12726 |
| actual rank=1 covered | 11605 |
| actual roll residual | 1121 |
| profile blocked | 1345 |
| profile eligible warning | 5 |

## Legacy comparison

- 旧 `metadata_gap=1853`、weekly `34`、actual `45` 均未作为 V2 target 或 Gate 输入。
- 旧 weekly `partial_or_missing_pre2020=34` 在 V2 中全部具有 covered physical weekly evidence，确认 34 个 legacy weekly false positive；其 provider-authoritative start/calendar 语义仍需单独验证。
- `metadata_gap=1853` 与 V2 reference root residual 的计量单位不同，不能用差值冒充修复数量。
- 旧 actual `45` 由 V2 的 12726 个 rank=1 interval targets 重新计算；真实 residual 见 `actual_roll_residuals.csv`。

## B2-04A input

优先只读拆分：checksum mismatch/conflicting declarations、252 个 derived expected coverage partial、actual rank=1 interval residual、calendar/session evidence root、quality warning/failed 与 Profile blocked root cause。禁止直接生成下载或 DB 修复任务。

## Commands and exit codes

| command | exit code | result |
|---|---:|---|
| B2-02 targeted regression pytest | 0 | 73 passed |
| initial DB/Alembic check from wrong cwd | 1 | discarded and corrected |
| direct PostgreSQL read-only check + Alembic current/heads | 0 | PostgreSQL; current=head |
| representative DuckDB `read_parquet` | 0 | 5908 rows readable |
| `rqdata_full_history_audit_v2.py` quick | 0 | engine executed |
| `rqdata_full_history_physical_inventory.py --scan-mode full` | 0 | 24763 files scanned |
| `rqdata_full_history_audit_v2.py` against full inventory | 0 | engine executed |
| report helper syntax/root attempts | 1 / 1 | no retained output; corrected |
| final B2-03 report build | 0 | ten requested artifacts written |
| post-run direct PostgreSQL count check | 0 | bars files=25134; quality reports=25134 |

连接凭据、数据库 URL、RQData 凭据和通知地址均未打印或写入报告。
