# FULL-HISTORY-AUDIT-V2-PREFLIGHT-000

状态：`COMPLETED / FULL_HISTORY_AUDIT_ENV_READY`

B2-00 只读固定审计环境：代码 worktree、实际数据 worktree、外置盘挂载、canonical bars、manifest、processed summary、direct PostgreSQL、Alembic、DuckDB、Profile/binding 数量和 runtime 开关。正式证据写入：

```text
data/reports/full_history_audit_v2_20260710/preflight/environment_evidence.json
data/reports/full_history_audit_v2_20260710/preflight/PREFLIGHT.md
```

脚本不打印环境变量值或连接串，不写 DB、Parquet、manifest，不调用 RQData。
